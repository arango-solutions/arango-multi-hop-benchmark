// Dashboard tab: KPIs, distribution bars, accepted rows, and exports.

import { api, downloadFile, errorText } from "../api.js";
import { banner, el, field, fmtNum, replace } from "../dom.js";

const ROW_LIMIT = 100;
const ROW_COLUMNS = ["cluster_id", "hop_count", "persona", "question", "answer"];

function distribution(title, data) {
  const entries = Object.entries(data ?? {});
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  const rows = entries
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) =>
      el(
        "div",
        { class: "dist-row" },
        el("span", { class: "key", title: key }, key),
        el(
          "span",
          { class: "dist-track" },
          el("span", { class: "fill", style: { width: `${Math.round((value / max) * 100)}%` } }),
        ),
        el("span", { class: "num" }, String(value)),
      ),
    );
  return el("div", {}, el("h3", {}, title), el("div", { class: "dist" }, rows));
}

function kpi(value, label) {
  return el("div", { class: "kpi" }, el("div", { class: "value" }, value), el("div", { class: "label" }, label));
}

function kpis(summary, source) {
  const cards = [kpi(String(summary.total_accepted), "Accepted")];
  if (source === "session") {
    cards.push(
      kpi(String(summary.total_rejected), "Rejected"),
      kpi(`${(summary.accept_rate * 100).toFixed(1)}%`, "Accept rate"),
    );
  }
  cards.push(kpi(fmtNum(summary.avg_hop_count), "Avg hops"));
  cards.push(kpi(fmtNum(summary.avg_weighted_rubric), "Avg rubric"));
  if (summary.duration_s !== null && summary.duration_s !== undefined) {
    cards.push(kpi(`${summary.duration_s.toFixed(1)}s`, "Duration"));
  }
  return el("div", { class: "kpi-grid" }, cards);
}

export function createDashboardTab(ctx) {
  const state = { source: "session", data: null, error: null, busy: false };
  const element = el("div", { class: "panel" });

  async function load(source) {
    state.busy = true;
    state.error = null;
    render();
    try {
      state.data = await api.dashboardSummary(source);
    } catch (err) {
      state.data = null;
      state.error = errorText(err);
    } finally {
      state.busy = false;
      render();
    }
  }

  async function exportAs(fmt) {
    state.error = null;
    try {
      const ext = fmt === "excel" ? "xlsx" : "json";
      await downloadFile(
        `/dashboard/export?source=${state.source}&fmt=${fmt}`,
        `multihop_eval_${state.source}.${ext}`,
      );
    } catch (err) {
      state.error = errorText(err);
      render();
    }
  }

  function rowsTable(rows) {
    const header = el("tr", {}, ROW_COLUMNS.map((c) => el("th", {}, c)));
    const body = rows
      .slice(0, ROW_LIMIT)
      .map((row) => el("tr", {}, ROW_COLUMNS.map((c) => el("td", {}, String(row[c] ?? "")))));
    return el(
      "div",
      { class: "table-scroll" },
      el(
        "table",
        { class: "data-table" },
        el("thead", {}, header),
        el("tbody", {}, body),
      ),
    );
  }

  function render() {
    const summary = state.data?.summary ?? null;
    const rows = state.data?.rows ?? [];
    const available = Boolean(state.data?.available);

    const sourceSelect = el(
      "select",
      {
        id: "dash-source",
        onChange: (e) => {
          state.source = e.target.value;
          void load(state.source);
        },
      },
      el("option", { value: "session", selected: state.source === "session" }, "Current session run"),
      el("option", { value: "arango", selected: state.source === "arango" }, "Persisted (Arango)"),
    );

    const children = [
      el("h2", {}, "Dashboard"),
      el(
        "div",
        { class: "btn-row", style: { marginBottom: "0.75rem" } },
        field("Data source", sourceSelect, { style: { marginBottom: 0, minWidth: "220px" } }),
        el(
          "button",
          { type: "button", disabled: state.busy, onClick: () => load(state.source) },
          "Refresh",
        ),
        el(
          "button",
          { type: "button", disabled: state.busy || !available, onClick: () => exportAs("json") },
          "Download JSON",
        ),
        state.source === "session" &&
          el(
            "button",
            { type: "button", disabled: state.busy || !available, onClick: () => exportAs("excel") },
            "Download Excel",
          ),
      ),
      state.source === "arango" &&
        !ctx.connected() &&
        banner(
          "warn",
          "Persisted data is read live from Arango. Connect on the Configure tab first.",
        ),
      state.error && banner("error", state.error),
      state.data &&
        !available &&
        !state.error &&
        banner(
          "info",
          state.source === "session"
            ? "No run has completed in this session yet. Start a run on the Run tab."
            : "No persisted QA rows found in the configured collection.",
        ),
    ];

    if (summary && available) {
      children.push(
        kpis(summary, state.source),
        el(
          "div",
          { class: "row" },
          distribution("Hop distribution", summary.hop_distribution),
          distribution("Persona distribution", summary.persona_distribution),
        ),
        el(
          "div",
          { class: "row" },
          distribution("Cluster coverage", summary.cluster_coverage),
          state.source === "session"
            ? distribution("Rejection breakdown", summary.rejection_breakdown)
            : el("div", {}),
        ),
        Object.keys(summary.rubric_means ?? {}).length > 0 &&
          distribution("Rubric means", summary.rubric_means),
        el(
          "h3",
          {},
          rows.length > ROW_LIMIT
            ? `Accepted rows (showing first ${ROW_LIMIT} of ${rows.length})`
            : `Accepted rows (${rows.length})`,
        ),
        rowsTable(rows),
      );
    }

    replace(element, children);
  }

  render();
  void load(state.source);

  return { element };
}
