// Arango connection panel, embedded at the top of the Configure tab.

import { api, errorText } from "../api.js";
import { banner, el, field, replace } from "../dom.js";

const DEFAULT_DB = "_system";

/**
 * @param {object} ctx application context
 * @param {(status: object) => void} onChange called with each new ConnectionStatus
 * @returns {HTMLElement}
 */
export function createConnectionPanel(ctx, onChange) {
  const form = { host: "https://", db: DEFAULT_DB, username: "root", password: "" };
  let databases = [];
  let busy = false;
  let localError = null;

  const panel = el("div", { class: "panel" });

  if (ctx.connection?.db) form.db = ctx.connection.db;

  function loadDatabases(connected) {
    if (!connected) {
      databases = [];
      return;
    }
    api
      .databases()
      .then((r) => {
        databases = r.databases;
        render();
      })
      .catch(() => {
        databases = [];
      });
  }

  async function run(fn) {
    busy = true;
    localError = null;
    render();
    try {
      const status = await fn();
      if (status.db) form.db = status.db;
      onChange(status);
    } catch (err) {
      localError = errorText(err);
    } finally {
      busy = false;
      render();
      loadDatabases(Boolean(ctx.connection?.status?.startsWith("connected")));
    }
  }

  const connectAmp = () => run(() => api.connect({ mode: "amp", db: form.db }));
  const connectManual = () => run(() => api.connect({ mode: "password", ...form }));
  const disconnect = () => run(() => api.disconnect());
  const test = () => run(() => api.testConnection());

  function switchDb(next) {
    form.db = next;
    const status = ctx.connection?.status;
    const useAmp = ctx.connection?.amp?.detected && status === "connected_amp";
    return run(() =>
      useAmp
        ? api.connect({ mode: "amp", db: next })
        : api.connect({ mode: "password", ...form, db: next }),
    );
  }

  function textInput(id, key, opts = {}) {
    return el("input", {
      id,
      type: opts.type ?? "text",
      value: form[key],
      placeholder: opts.placeholder,
      onInput: (e) => {
        form[key] = e.target.value;
      },
    });
  }

  function statusBanner(status, ampDetected) {
    if (status === "connected_amp") {
      const name = ctx.connection?.amp?.deployment_name;
      return banner(
        "ok",
        `Connected via AMP${name ? ` (deployment ${name})` : ""}. The token rotates automatically.`,
      );
    }
    if (status === "connected_manual") {
      return banner("info", "Connected with manual credentials.");
    }
    if (status === "error") {
      return banner("error", `Not connected — ${ctx.connection?.error ?? "unknown error"}`);
    }
    if (ampDetected) {
      return banner(
        "info",
        "AMP environment detected. Connect via AMP to use deployment credentials, or use the manual form.",
      );
    }
    return banner("warn", "Disconnected. Fill in the connection form below.");
  }

  function render() {
    const status = ctx.connection?.status ?? "disconnected";
    const connected = status.startsWith("connected");
    const ampDetected = Boolean(ctx.connection?.amp?.detected);

    const children = [
      el("h2", {}, "Arango connection"),
      statusBanner(status, ampDetected),
      localError && banner("error", localError),
    ];

    if (ampDetected && !connected) {
      children.push(
        el(
          "div",
          { class: "btn-row", style: { marginBottom: "0.75rem" } },
          el(
            "button",
            { class: "primary", type: "button", disabled: busy, onClick: connectAmp },
            "Connect via AMP",
          ),
        ),
      );
    }

    if (!connected) {
      children.push(
        el(
          "div",
          { class: "row" },
          field(
            "Host",
            textInput("conn-host", "host", {
              placeholder: "https://my-cluster.arangodb.cloud",
            }),
          ),
          field("Database", textInput("conn-db", "db")),
        ),
        el(
          "div",
          { class: "row" },
          field("Username", textInput("conn-user", "username")),
          field("Password", textInput("conn-pass", "password", { type: "password" })),
        ),
        el(
          "div",
          { class: "btn-row" },
          el(
            "button",
            { class: "primary", type: "button", disabled: busy, onClick: connectManual },
            "Connect",
          ),
        ),
      );
    } else {
      const options = (databases.length ? databases : [form.db]).map((name) =>
        el("option", { value: name, selected: name === form.db }, name),
      );
      children.push(
        field(
          "Database",
          el(
            "select",
            {
              id: "conn-db-switch",
              disabled: busy,
              onChange: (e) => switchDb(e.target.value),
            },
            options,
          ),
        ),
        el(
          "div",
          { class: "btn-row" },
          el("button", { type: "button", disabled: busy, onClick: test }, "Test connection"),
          el(
            "button",
            { class: "danger", type: "button", disabled: busy, onClick: disconnect },
            "Disconnect",
          ),
          ctx.connection?.last_tested &&
            el("span", { class: "muted" }, `Last verified ${ctx.connection.last_tested} UTC`),
        ),
      );
    }

    replace(panel, children);
  }

  render();
  loadDatabases(Boolean(ctx.connection?.status?.startsWith("connected")));
  return panel;
}
