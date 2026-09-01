// Ad-hoc tab: validate a single QA pair against pasted source documents.

import { api, errorText } from "../api.js";
import { banner, el, field, replace } from "../dom.js";

const MIN_SOURCES = 2;

export function createAdhocTab(ctx) {
  const state = {
    question: "",
    answer: "",
    reasoning: "",
    proof: [{ point: "", source_id: "" }],
    sources: [
      { _id: "", content: "" },
      { _id: "", content: "" },
    ],
    scoreWithRubric: false,
    busy: false,
    error: null,
    result: null,
  };

  const element = el("div", { class: "panel" });
  const proofBody = el("tbody", {});
  const sourceBody = el("tbody", {});
  const statusArea = el("div", {});
  const resultArea = el("div", {});

  function textarea(id, key) {
    return el("textarea", {
      id,
      value: state[key],
      onInput: (e) => {
        state[key] = e.target.value;
        syncSubmit();
      },
    });
  }

  function canSubmit() {
    return (
      ctx.hasConfig() &&
      !state.busy &&
      state.question.trim().length > 0 &&
      state.answer.trim().length > 0 &&
      state.sources.filter((s) => s._id.trim()).length >= MIN_SOURCES
    );
  }

  function renderProof() {
    const rows = state.proof.map((p, i) =>
      el(
        "tr",
        {},
        el(
          "td",
          {},
          el("input", {
            "aria-label": `proof-point-${i}`,
            type: "text",
            value: p.point,
            onInput: (e) => {
              state.proof[i].point = e.target.value;
            },
          }),
        ),
        el(
          "td",
          {},
          el("input", {
            "aria-label": `proof-source-${i}`,
            type: "text",
            value: p.source_id,
            onInput: (e) => {
              state.proof[i].source_id = e.target.value;
            },
          }),
        ),
        el(
          "td",
          {},
          el(
            "button",
            {
              type: "button",
              disabled: state.proof.length <= 1,
              onClick: () => {
                state.proof.splice(i, 1);
                renderProof();
              },
            },
            "×",
          ),
        ),
      ),
    );
    replace(proofBody, rows);
  }

  function renderSources() {
    const rows = state.sources.map((s, i) =>
      el(
        "tr",
        {},
        el(
          "td",
          {},
          el("input", {
            "aria-label": `source-id-${i}`,
            type: "text",
            value: s._id,
            onInput: (e) => {
              state.sources[i]._id = e.target.value;
              syncSubmit();
            },
          }),
        ),
        el(
          "td",
          {},
          el("textarea", {
            "aria-label": `source-content-${i}`,
            value: s.content,
            onInput: (e) => {
              state.sources[i].content = e.target.value;
            },
          }),
        ),
        el(
          "td",
          {},
          el(
            "button",
            {
              type: "button",
              disabled: state.sources.length <= MIN_SOURCES,
              onClick: () => {
                state.sources.splice(i, 1);
                renderSources();
                syncSubmit();
              },
            },
            "×",
          ),
        ),
      ),
    );
    replace(sourceBody, rows);
  }

  async function evaluate() {
    state.busy = true;
    state.error = null;
    state.result = null;
    replace(resultArea);
    replace(statusArea, el("span", { class: "muted" }, "Evaluating…"));
    syncSubmit();
    try {
      state.result = await api.adhocEvaluate({
        question: state.question,
        answer: state.answer,
        reasoning_chain: state.reasoning,
        proof: state.proof.filter((p) => p.point.trim() || p.source_id.trim()),
        sources: state.sources
          .filter((s) => s._id.trim())
          .map((s) => ({ _id: s._id.trim(), content: s.content })),
        score_with_rubric: state.scoreWithRubric,
      });
    } catch (err) {
      state.error = errorText(err);
    } finally {
      state.busy = false;
      replace(statusArea);
      syncSubmit();
      renderResult();
    }
  }

  function renderResult() {
    const children = [];
    if (state.error) {
      children.push(
        el("div", { style: { marginTop: "0.75rem" } }, banner("error", state.error)),
      );
    }
    const r = state.result;
    if (r) {
      const badges = [
        el(
          "span",
          { class: `badge ${r.multi_hop_pass ? "pass" : "fail"}` },
          `Multi-hop ${r.multi_hop_pass ? "pass" : "fail"}`,
        ),
        el(
          "span",
          { class: `badge ${r.proof_verdict === "pass" ? "pass" : "fail"}` },
          `Proof ${r.proof_verdict}`,
        ),
        el("span", { class: "muted" }, `Genuine hops: ${r.genuine_hop_count}`),
      ];
      if (r.rubric_weighted_score !== null && r.rubric_weighted_score !== undefined) {
        badges.push(
          el("span", { class: "muted" }, `Weighted rubric: ${r.rubric_weighted_score.toFixed(3)}`),
        );
      }

      const block = [
        el("h3", {}, "Result"),
        el("div", { class: "btn-row", style: { marginBottom: "0.75rem" } }, badges),
        el(
          "div",
          { class: "field" },
          el("label", {}, "Multi-hop reasoning"),
          banner("info", r.multi_hop_reason || "—"),
        ),
      ];

      const rubricEntries = Object.entries(r.rubric_scores ?? {});
      if (rubricEntries.length > 0) {
        block.push(
          el("h3", {}, "Rubric scores"),
          el(
            "table",
            { class: "data-table" },
            el(
              "thead",
              {},
              el(
                "tr",
                {},
                el("th", {}, "Field"),
                el("th", { style: { width: "70px" } }, "Score"),
                el("th", {}, "Justification"),
              ),
            ),
            el(
              "tbody",
              {},
              rubricEntries.map(([name, s]) =>
                el(
                  "tr",
                  {},
                  el("td", {}, name),
                  el("td", {}, String(s.score)),
                  el("td", {}, s.justification),
                ),
              ),
            ),
          ),
        );
      }

      block.push(
        el("h3", {}, "Corrected proof"),
        el("div", { class: "log" }, JSON.stringify(r.corrected_proof, null, 2)),
      );
      children.push(el("div", { style: { marginTop: "1rem" } }, block));
    }
    replace(resultArea, children);
  }

  const evaluateButton = el(
    "button",
    { class: "primary", type: "button", onClick: evaluate },
    "Evaluate",
  );

  function syncSubmit() {
    evaluateButton.disabled = !canSubmit();
  }

  const rubricCheckbox = el("input", {
    id: "adhoc-rubric",
    type: "checkbox",
    checked: state.scoreWithRubric,
    onChange: (e) => {
      state.scoreWithRubric = e.target.checked;
    },
  });

  const addRowBar = (label, onClick) =>
    el(
      "div",
      { class: "btn-row", style: { margin: "0.5rem 0 1rem" } },
      el("button", { type: "button", onClick }, label),
    );

  replace(
    element,
    el("h2", {}, "Ad-hoc"),
    el(
      "p",
      { class: "muted" },
      "Validate a single QA pair against its source documents — the same multi-hop & proof checks the generation pipeline runs.",
    ),
    !ctx.hasConfig() &&
      banner(
        "warn",
        "Save a configuration on the Configure tab first (it supplies the LLM credentials and rubric).",
      ),
    field("Question", textarea("adhoc-q", "question")),
    field("Answer", textarea("adhoc-a", "answer")),
    field("Reasoning chain (optional)", textarea("adhoc-r", "reasoning")),
    el("h3", {}, "Proof points"),
    el(
      "table",
      { class: "editable-table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { style: { width: "60%" } }, "Point"),
          el("th", {}, "Source id"),
          el("th", { style: { width: "40px" } }),
        ),
      ),
      proofBody,
    ),
    addRowBar("+ Add proof point", () => {
      state.proof.push({ point: "", source_id: "" });
      renderProof();
    }),
    el("h3", {}, `Source documents (≥ ${MIN_SOURCES})`),
    el(
      "table",
      { class: "editable-table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { style: { width: "30%" } }, "_id"),
          el("th", {}, "Content"),
          el("th", { style: { width: "40px" } }),
        ),
      ),
      sourceBody,
    ),
    addRowBar("+ Add source", () => {
      state.sources.push({ _id: "", content: "" });
      renderSources();
      syncSubmit();
    }),
    el(
      "div",
      { class: "field checkbox" },
      rubricCheckbox,
      el("label", { htmlFor: "adhoc-rubric" }, "Score with rubric"),
    ),
    el("div", { class: "btn-row" }, evaluateButton, statusArea),
    resultArea,
  );

  renderProof();
  renderSources();
  syncSubmit();

  return { element };
}
