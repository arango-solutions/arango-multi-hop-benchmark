// Run tab: start/stop generation and follow progress over SSE.

import { api, errorText, runEventsUrl } from "../api.js";
import { banner, el, replace } from "../dom.js";

const ACTIVE = new Set(["running"]);
const LOG_TAIL = 200;

export function createRunTab(ctx) {
  const state = {
    status: "idle",
    log: [],
    accepted: 0,
    target: 0,
    summary: null,
    error: null,
    busy: false,
  };
  let source = null;

  const element = el("div", { class: "panel" });

  function closeStream() {
    source?.close();
    source = null;
  }

  function openStream() {
    closeStream();
    const es = new EventSource(runEventsUrl());
    source = es;
    es.onmessage = (msg) => {
      let ev;
      try {
        ev = JSON.parse(msg.data);
      } catch {
        return;
      }
      if (ev.kind === "status") {
        state.status = ev.status ?? "done";
        state.summary = ev.summary ?? null;
        state.error = ev.error ?? null;
        if (ev.summary) {
          state.accepted = ev.summary.accepted;
          state.target = Math.max(state.target, ev.summary.accepted);
        }
        closeStream();
        render();
        return;
      }
      if (ev.line) state.log.push(ev.line);
      const p = ev.payload ?? {};
      if (typeof p.accepted === "number") state.accepted = p.accepted;
      if (typeof p.target === "number") state.target = p.target;
      render();
    };
    es.onerror = () => {
      // The stream closes normally when the run ends; refetch status to settle.
      closeStream();
      api
        .runStatus()
        .then((s) => {
          state.status = s.status;
          state.summary = s.summary;
          state.error = s.error;
          render();
        })
        .catch(() => undefined);
    };
  }

  async function start() {
    state.busy = true;
    state.error = null;
    render();
    try {
      const s = await api.startRun();
      state.status = s.status;
      state.log = [];
      state.accepted = 0;
      state.target = s.target;
      state.summary = null;
      openStream();
    } catch (err) {
      state.error = errorText(err);
    } finally {
      state.busy = false;
      render();
    }
  }

  async function stop() {
    state.busy = true;
    render();
    try {
      await api.stopRun();
    } catch (err) {
      state.error = errorText(err);
    } finally {
      state.busy = false;
      render();
    }
  }

  function render() {
    const connected = ctx.connected();
    const hasConfig = ctx.hasConfig();
    const running = ACTIVE.has(state.status);
    const pct =
      state.target > 0 ? Math.min(100, Math.round((state.accepted / state.target) * 100)) : 0;
    const tail = state.log.slice(-LOG_TAIL).reverse();

    replace(
      element,
      el("h2", {}, "Run"),
      !connected &&
        banner("warn", "No live Arango connection. Connect on the Configure tab before running."),
      connected &&
        !hasConfig &&
        banner("warn", "Save a configuration on the Configure tab before running."),
      el(
        "div",
        { class: "btn-row", style: { marginBottom: "0.75rem" } },
        el(
          "button",
          {
            class: "primary",
            type: "button",
            disabled: state.busy || running || !connected || !hasConfig,
            onClick: start,
          },
          "Run",
        ),
        el(
          "button",
          { class: "danger", type: "button", disabled: state.busy || !running, onClick: stop },
          "Stop",
        ),
        el("span", { class: "muted" }, "Status: ", el("strong", {}, state.status)),
      ),
      el(
        "div",
        { class: "progress", style: { marginBottom: "0.75rem" } },
        el("div", {
          class: "bar",
          style: { width: `${running || state.summary ? pct : 0}%` },
        }),
        el(
          "div",
          { class: "label" },
          running ? `${state.accepted}/${state.target}` : state.status === "idle" ? "" : state.status,
        ),
      ),
      state.error && banner("error", `Run failed: ${state.error}`),
      state.summary &&
        banner(
          "ok",
          `${state.status === "stopped" ? "Run stopped. " : "Run complete. "}` +
            `${state.summary.accepted} accepted, ${state.summary.rejected} rejected ` +
            `(accept rate ${(state.summary.accept_rate * 100).toFixed(1)}%) ` +
            `in ${state.summary.duration_s.toFixed(1)}s.`,
        ),
      el("h3", {}, "Live log (most recent first)"),
      el("div", { class: "log" }, tail.length ? tail.join("\n") : "(no events yet)"),
    );
  }

  render();

  // Restore state on mount; resume streaming if a run is still active.
  api
    .runStatus()
    .then((s) => {
      state.status = s.status;
      state.log = s.log;
      state.accepted = s.accepted;
      state.target = s.target;
      state.summary = s.summary;
      state.error = s.error;
      render();
      if (ACTIVE.has(s.status)) openStream();
    })
    .catch(() => undefined);

  return { element, dispose: closeStream };
}
