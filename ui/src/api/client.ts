// HTTP client for the Multi-Hop Eval API.
//
// BYOC routing note: the SPA is served at …/frontend/ (AMP) or …/ui/ (local
// dev). API endpoints live one level up, so a root-relative fetch("/run/start")
// would hit the domain root (ArangoDB itself) instead of the service. We strip
// whichever prefix the SPA is mounted under to recover the service base path,
// exactly mirroring the arango-cypher reference.
//
// The ArangoDB platform proxy strips `Authorization: Bearer` for its own JWT,
// so the per-client session token rides in a custom `X-Arango-Session` header.

import type {
  AdhocRequest,
  AdhocResponse,
  AmpInfo,
  ClustersResponse,
  CollectionsResponse,
  ConfigResponse,
  ConfigSaveRequest,
  ConnectionStatus,
  ConnectRequest,
  DashboardResponse,
  DashboardSource,
  DatabasesResponse,
  RagEvalRequest,
  RagEvalResponse,
  RunStatus,
} from "./types";

const SESSION_HEADER = "X-Arango-Session";
const SESSION_STORAGE_KEY = "multihop_eval_session";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/**
 * Recover the API base path by stripping the SPA mount prefix from the current
 * pathname. Checks `/frontend` first because AMP is the production target.
 */
export function apiBase(pathname: string = window.location.pathname): string {
  for (const prefix of ["/frontend", "/ui"]) {
    const idx = pathname.indexOf(prefix);
    if (idx >= 0) return pathname.slice(0, idx);
  }
  return "";
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string): void {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, token);
  } catch {
    // localStorage unavailable (e.g. private mode) — token lives in memory only.
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const { headers: extraHeaders, ...rest } = options;
  const res = await fetch(apiBase() + path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { [SESSION_HEADER]: token } : {}),
      ...(extraHeaders as Record<string, string>),
    },
  });

  // The backend mints/echoes the session token on every response.
  const returnedToken = res.headers.get(SESSION_HEADER);
  if (returnedToken) setToken(returnedToken);

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, formatDetail(body.detail ?? body));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => formatDetail(d)).join("; ");
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.msg === "string") return obj.msg;
    if (typeof obj.detail === "string") return obj.detail;
    return JSON.stringify(detail);
  }
  return String(detail);
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  // Connection
  connectionStatus: () => request<ConnectionStatus>("/connection/status"),
  amp: () => request<AmpInfo>("/connection/amp"),
  connect: (body: ConnectRequest) =>
    request<ConnectionStatus>("/connection/connect", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  disconnect: () =>
    request<ConnectionStatus>("/connection/disconnect", { method: "POST" }),
  testConnection: () =>
    request<ConnectionStatus>("/connection/test", { method: "POST" }),
  databases: () => request<DatabasesResponse>("/connection/databases"),
  collections: () => request<CollectionsResponse>("/connection/collections"),
  clusters: (domainsCollection: string) =>
    request<ClustersResponse>(
      `/connection/clusters?domains_collection=${encodeURIComponent(domainsCollection)}`,
    ),

  // Config
  getConfig: () => request<ConfigResponse>("/config"),
  saveConfig: (body: ConfigSaveRequest) =>
    request<ConfigResponse>("/config", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  loadFromEnv: () => request<ConfigResponse>("/config/from-env"),

  // Run
  startRun: () => request<RunStatus>("/run/start", { method: "POST" }),
  stopRun: () => request<RunStatus>("/run/stop", { method: "POST" }),
  runStatus: () => request<RunStatus>("/run/status"),

  // Dashboard
  dashboardSummary: (source: DashboardSource) =>
    request<DashboardResponse>(`/dashboard/summary?source=${source}`),

  // Ad-hoc
  adhocEvaluate: (body: AdhocRequest) =>
    request<AdhocResponse>("/adhoc/evaluate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // RAG Eval
  ragEvalEvaluate: (body: RagEvalRequest) =>
    request<RagEvalResponse>("/rag_eval/evaluate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/**
 * Build the SSE URL for the active run. EventSource cannot set headers, so the
 * session token is passed as a query parameter (the backend accepts both).
 */
export function runEventsUrl(): string {
  const token = getToken();
  const q = token ? `?session=${encodeURIComponent(token)}` : "";
  return apiBase() + "/run/events" + q;
}

/**
 * Fetch a binary/export endpoint and trigger a browser download. Unlike a
 * plain `<a download>`, this sends the `X-Arango-Session` header so the
 * backend can resolve the caller's session (where the run/result lives).
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
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
