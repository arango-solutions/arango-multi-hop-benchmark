// RAG Eval tab: score one or more RAG systems against the golden QA set.

import { api, downloadFile, errorText } from "../api.js";
import { banner, el, field, replace, splitNums, splitStrings } from "../dom.js";

function metricTable(title, data) {
  const entries = Object.entries(data ?? {});
  if (entries.length === 0) return null;
  const rows = entries
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([metric, value]) =>
      el(
        "tr",
        {},
        el("td", {}, metric),
        el(
          "td",
          { class: "num-cell" },
          typeof value === "number" ? value.toFixed(4) : String(value),
        ),
      ),
    );
  return el(
    "div",
    {},
    el("h3", {}, title),
    el("table", { class: "data-table" }, el("tbody", {}, rows)),
  );
}

function systemCard(run) {
  return el(
    "div",
    { class: "panel" },
    el("h2", {}, run.system_name),
    el(
      "div",
      { class: "muted", style: { marginBottom: "0.5rem" } },
      `${run.n_responses} responses · ${run.n_matched_goldens} matched goldens`,
    ),
    el(
      "div",
      { class: "row" },
      metricTable("Retrieval metrics", run.metrics.retrieval),
      metricTable("Generation metrics", run.metrics.generation),
    ),
  );
}

export function createRagEvalTab(ctx) {
  const state = {
    relevanceMode: "binary",
    kValues: "1, 3, 5, 10",
    responseSource: "jsonl",
    arangoCollection: "rag_responses_v1",
    systemFilter: "",
    lengthZ: 2.0,
    fuzzThreshold: 75,
    emptyRetrievalMin: "",
    goldenLimit: "",
    jsonlText: null,
    jsonlName: null,
    busy: false,
    error: null,
    result: null,
  };

  const element = el("div", {});
  const formPanel = el("div", { class: "panel" });
  const sourcePanel = el("div", {});
  const statusArea = el("div", {});
  const resultArea = el("div", {});
  const cardsArea = el("div", {});

  function canSubmit() {
    return (
      ctx.connected() &&
      !state.busy &&
      (state.responseSource === "arango" ||
        (state.jsonlText !== null && state.jsonlText.length > 0))
    );
  }

  const evaluateButton = el(
    "button",
    { class: "primary", type: "button", onClick: () => void evaluate() },
    "Evaluate",
  );
  const exportJsonButton = el(
    "button",
    { type: "button", hidden: true, onClick: () => void exportAs("json") },
    "Download JSON",
  );
  const exportExcelButton = el(
    "button",
    { type: "button", hidden: true, onClick: () => void exportAs("excel") },
    "Download Excel",
  );

  function syncButtons() {
    evaluateButton.disabled = !canSubmit();
    const showExports = Boolean(state.result?.runs?.length);
    exportJsonButton.hidden = !showExports;
    exportExcelButton.hidden = !showExports;
    exportJsonButton.disabled = state.busy;
    exportExcelButton.disabled = state.busy;
  }

  function onFile(file) {
    if (!file) {
      state.jsonlText = null;
      state.jsonlName = null;
      renderSource();
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      state.jsonlText = String(reader.result ?? "");
      state.jsonlName = file.name;
      renderSource();
    };
    reader.readAsText(file);
  }

  function renderSource() {
    if (state.responseSource === "jsonl") {
      const lineCount = state.jsonlText?.split("\n").filter(Boolean).length ?? 0;
      replace(
        sourcePanel,
        field(
          "Responses JSONL",
          el("input", {
            id: "rag-file",
            type: "file",
            accept: ".jsonl,.json,application/json,text/plain",
            onChange: (e) => onFile(e.target.files?.[0]),
          }),
          {
            hint:
              state.jsonlName &&
              el("span", { class: "muted" }, `Loaded ${state.jsonlName} (${lineCount} lines)`),
          },
        ),
      );
    } else {
      replace(
        sourcePanel,
        field(
          "Response collection",
          el("input", {
            id: "rag-collection",
            type: "text",
            value: state.arangoCollection,
            onInput: (e) => {
              state.arangoCollection = e.target.value;
            },
          }),
        ),
      );
    }
    syncButtons();
  }

  async function evaluate() {
    state.busy = true;
    state.error = null;
    state.result = null;
    replace(resultArea);
    replace(cardsArea);
    replace(statusArea, el("span", { class: "muted" }, "Evaluating…"));
    syncButtons();
    try {
      state.result = await api.ragEvalEvaluate({
        relevance_mode: state.relevanceMode,
        k_values: splitNums(state.kValues).filter(Number.isFinite),
        response_source: state.responseSource,
        response_arango_collection: state.arangoCollection,
        system_filter: splitStrings(state.systemFilter),
        length_z_threshold: state.lengthZ,
        groundedness_fuzz_threshold: state.fuzzThreshold,
        empty_retrieval_min_score:
          state.emptyRetrievalMin.trim() === "" ? null : Number(state.emptyRetrievalMin),
        jsonl_text: state.responseSource === "jsonl" ? state.jsonlText : null,
        golden_limit: state.goldenLimit.trim() === "" ? null : Number(state.goldenLimit),
      });
    } catch (err) {
      state.error = errorText(err);
    } finally {
      state.busy = false;
      replace(statusArea);
      syncButtons();
      renderResult();
    }
  }

  async function exportAs(fmt) {
    state.error = null;
    try {
      const ext = fmt === "excel" ? "xlsx" : "json";
      await downloadFile(`/rag_eval/export?fmt=${fmt}`, `rag_eval.${ext}`);
    } catch (err) {
      state.error = errorText(err);
      renderResult();
    }
  }

  function renderResult() {
    const children = [];
    if (state.error) {
      children.push(el("div", { style: { marginTop: "0.75rem" } }, banner("error", state.error)));
    }
    const r = state.result;
    if (r) {
      const block = [
        banner(
          "ok",
          `${r.n_systems} system(s) · ${r.n_responses} responses · ${r.n_goldens} goldens.`,
        ),
      ];
      if (r.load_errors.length > 0) {
        block.push(
          banner(
            "warn",
            `${r.load_errors.length} response row(s) skipped:`,
            el("div", { class: "log", style: { marginTop: "0.4rem" } }, r.load_errors.join("\n")),
          ),
        );
      }
      if (r.runs.length === 0) {
        block.push(
          banner(
            "info",
            "No responses matched. Check the system filter and that the responses' qa_pair_key values match the goldens' _key.",
          ),
        );
      }
      children.push(el("div", { style: { marginTop: "0.75rem" } }, block));
    }
    replace(resultArea, children);
    replace(cardsArea, (r?.runs ?? []).map(systemCard));
  }

  function numberInput(id, key, opts = {}) {
    return el("input", {
      id,
      type: "number",
      step: opts.step,
      value: state[key],
      onInput: (e) => {
        state[key] = opts.raw ? e.target.value : Number(e.target.value);
      },
    });
  }

  replace(
    formPanel,
    el("h2", {}, "RAG Eval"),
    el(
      "p",
      { class: "muted" },
      "Score one or more RAG systems against the golden QA set: retrieval (P@K, R@K, MRR, NDCG@K, …) and rule-based generation metrics.",
    ),
    !ctx.connected() &&
      banner("warn", "Goldens are read from Arango. Connect on the Configure tab first."),
    el(
      "div",
      { class: "row-3" },
      field(
        "Relevance mode",
        el(
          "select",
          {
            id: "rag-relevance",
            onChange: (e) => {
              state.relevanceMode = e.target.value;
            },
          },
          el("option", { value: "binary", selected: true }, "binary"),
          el("option", { value: "graded" }, "graded"),
        ),
      ),
      field(
        "K values (comma-separated)",
        el("input", {
          id: "rag-k",
          type: "text",
          value: state.kValues,
          onInput: (e) => {
            state.kValues = e.target.value;
          },
        }),
      ),
      field(
        "Response source",
        el(
          "select",
          {
            id: "rag-source",
            onChange: (e) => {
              state.responseSource = e.target.value;
              renderSource();
            },
          },
          el("option", { value: "jsonl", selected: true }, "JSONL upload"),
          el("option", { value: "arango" }, "Arango collection"),
        ),
      ),
    ),
    sourcePanel,
    el(
      "div",
      { class: "row-3" },
      field(
        "System filter (comma-separated, optional)",
        el("input", {
          id: "rag-filter",
          type: "text",
          value: state.systemFilter,
          onInput: (e) => {
            state.systemFilter = e.target.value;
          },
        }),
      ),
      field("Length z-threshold", numberInput("rag-lenz", "lengthZ", { step: "0.1" })),
      field("Groundedness fuzz threshold", numberInput("rag-fuzz", "fuzzThreshold")),
    ),
    el(
      "div",
      { class: "row" },
      field(
        "Empty-retrieval min score (optional)",
        numberInput("rag-empty", "emptyRetrievalMin", { step: "0.1", raw: true }),
      ),
      field("Golden limit (optional)", numberInput("rag-golden", "goldenLimit", { raw: true })),
    ),
    el("div", { class: "btn-row" }, evaluateButton, statusArea, exportJsonButton, exportExcelButton),
    resultArea,
  );

  replace(element, formPanel, cardsArea);
  renderSource();
  syncButtons();

  return { element };
}
