// HTTP client for the Multi-Hop Eval API.
//
// BYOC routing note: the UI is served at the service root, at …/ui/ and at
// …/frontend/. API endpoints live at the service root, so a root-relative
// fetch("/run/start") would hit the domain root (Arango itself) instead of the
// service. `apiBase()` recovers the service base path from location.pathname.
//
// The Arango platform proxy strips `Authorization: Bearer` for its own JWT,
// so the per-client session token rides in a custom `X-Arango-Session` header.

const SESSION_HEADER = "X-Arango-Session";
const SESSION_STORAGE_KEY = "multihop_eval_session";
const SPA_PREFIXES = ["/frontend", "/ui"];

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/**
 * Recover the API base path from the current pathname.
 *
 * Resolves the directory the document was loaded from, then strips the SPA
 * mount prefix when there is one. The returned base never has a trailing
 * slash, so callers concatenate it with a leading-slash path.
 *
 * @param {string} [pathname]
 * @returns {string}
 */
export function apiBase(pathname = window.location.pathname) {
  let dir = pathname;
  const leaf = dir.slice(dir.lastIndexOf("/") + 1);
  if (leaf.includes(".")) dir = dir.slice(0, dir.lastIndexOf("/"));
  if (dir.endsWith("/") && dir.length > 1) dir = dir.slice(0, -1);
  if (dir === "/") dir = "";
  for (const prefix of SPA_PREFIXES) {
    if (dir.endsWith(prefix)) return dir.slice(0, -prefix.length);
  }
  return dir;
}

export function getToken() {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setToken(token) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, token);
  } catch {
    // localStorage unavailable (e.g. private mode) — the token lives in memory only.
  }
}

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(formatDetail).join("; ");
  if (detail && typeof detail === "object") {
    if (typeof detail.msg === "string") return detail.msg;
    if (typeof detail.detail === "string") return detail.detail;
    return JSON.stringify(detail);
  }
  return String(detail);
}

async function request(path, options = {}) {
  const token = getToken();
  const { headers: extraHeaders, ...rest } = options;
  const res = await fetch(apiBase() + path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { [SESSION_HEADER]: token } : {}),
      ...extraHeaders,
    },
  });

  // The backend mints/echoes the session token on every response.
  const returnedToken = res.headers.get(SESSION_HEADER);
  if (returnedToken) setToken(returnedToken);

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, formatDetail(body.detail ?? body));
  }
  if (res.status === 204) return undefined;
  return res.json();
}

const postJson = (path, body) =>
  request(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request("/health"),

  // Connection
  connectionStatus: () => request("/connection/status"),
  amp: () => request("/connection/amp"),
  connect: (body) => postJson("/connection/connect", body),
  disconnect: () => request("/connection/disconnect", { method: "POST" }),
  testConnection: () => request("/connection/test", { method: "POST" }),
  databases: () => request("/connection/databases"),
  collections: () => request("/connection/collections"),
  clusters: (domainsCollection) =>
    request(`/connection/clusters?domains_collection=${encodeURIComponent(domainsCollection)}`),

  // Config
  getConfig: () => request("/config"),
  saveConfig: (body) => postJson("/config", body),
  loadFromEnv: () => request("/config/from-env"),

  // Run
  startRun: () => request("/run/start", { method: "POST" }),
  stopRun: () => request("/run/stop", { method: "POST" }),
  runStatus: () => request("/run/status"),

  // Dashboard
  dashboardSummary: (source) => request(`/dashboard/summary?source=${source}`),

  // Ad-hoc
  adhocEvaluate: (body) => postJson("/adhoc/evaluate", body),

  // RAG Eval
  ragEvalEvaluate: (body) => postJson("/rag_eval/evaluate", body),
};

/**
 * Build the SSE URL for the active run. EventSource cannot set headers, so the
 * session token is passed as a query parameter (the backend accepts both).
 */
export function runEventsUrl() {
  const token = getToken();
  const q = token ? `?session=${encodeURIComponent(token)}` : "";
  return apiBase() + "/run/events" + q;
}

/**
 * Fetch an export endpoint and trigger a browser download. Unlike a plain
 * `<a download>`, this sends the `X-Arango-Session` header so the backend can
 * resolve the caller's session (where the run/result lives).
 */
export async function downloadFile(path, filename) {
  const token = getToken();
  const res = await fetch(apiBase() + path, {
    headers: token ? { [SESSION_HEADER]: token } : {},
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, formatDetail(body.detail ?? body));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Normalise a thrown value into a display string. */
export function errorText(err) {
  return err instanceof ApiError ? err.message : String(err);
}
