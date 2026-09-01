// Configure tab: connection, Autograph project, collections, LLM provider,
// evaluation parameters, personas, and the scoring rubric.

import { api, errorText } from "../api.js";
import { banner, el, field, replace, splitLines, splitNums } from "../dom.js";
import { createConnectionPanel } from "./connection.js";

const COLLECTION_ROLES = [
  { key: "sources_collection", label: "Sources collection" },
  { key: "similarity_collection", label: "Similarity collection" },
  { key: "relations_collection", label: "Relations collection" },
  { key: "domains_collection", label: "Domains collection" },
  { key: "rags_collection", label: "RAGs collection" },
  { key: "qa_collection", label: "QA collection (output)" },
];

// Every Autograph collection name is derived from the project name. Kept in
// sync with COLLECTION_NAME_TEMPLATES in multihop_eval/config.py so the live
// preview here matches what the backend derives on save.
function deriveCollections(projectName) {
  const p = projectName.trim();
  return {
    similarity_collection: `${p}_similarities`,
    relations_collection: `${p}_corpus_relations`,
    rags_collection: `${p}_rags`,
    sources_collection: `${p}_sources`,
    domains_collection: `${p}_domains`,
    qa_collection: `qa_pairs_${p}_v1`,
  };
}

export function createConfigureTab(ctx) {
  const state = {
    projectName: "",
    collections: {},
    llm: null,
    evalParams: null,
    personas: [],
    rubric: [],
    discovered: [],
    saveMsg: null,
    busy: false,
  };

  initFromConfig();

  function initFromConfig() {
    const resp = ctx.configResp;
    if (!resp) return;
    const d = resp.defaults;
    const saved = resp.saved ?? null;

    state.projectName =
      typeof saved?.arango?.project_name === "string"
        ? saved.arango.project_name
        : (d.project_name ?? "");

    const coll = { ...d.collections };
    if (saved?.arango) {
      for (const { key } of COLLECTION_ROLES) {
        if (typeof saved.arango[key] === "string") coll[key] = saved.arango[key];
      }
    }
    state.collections = coll;

    const savedKey = saved?.llm?.api_key;
    state.llm = {
      ...d.llm,
      ...(saved?.llm ?? {}),
      api_key: savedKey && savedKey !== "***" ? savedKey : "",
    };

    const e = saved?.eval ?? {};
    state.evalParams = {
      target_clusters: (e.target_clusters ?? d.eval.target_clusters).join("\n"),
      n_questions: e.n_questions ?? d.eval.n_questions,
      hop_dist: (e.hop_dist ?? d.eval.hop_dist).join(","),
      hop_dist_weights: (e.hop_dist_weights ?? d.eval.hop_dist_weights).join(","),
      max_verify_rounds: e.max_verify_rounds ?? d.eval.max_verify_rounds,
      save_to_arango: e.save_to_arango ?? d.eval.save_to_arango,
      score_with_rubric: e.score_with_rubric ?? d.eval.score_with_rubric,
    };
    state.personas = e.personas ?? d.personas;
    state.rubric = e.rubric_fields ?? d.rubric_fields;
  }

  // -----------------------------------------------------------------------
  // Panels that re-render independently
  // -----------------------------------------------------------------------

  const collectionsPanel = el("div", { class: "panel" });
  const llmPanel = el("div", { class: "panel" });
  const evalPanel = el("div", { class: "panel" });
  const personaBody = el("tbody", {});
  const rubricBody = el("tbody", {});
  const actionsMsg = el("div", {});

  function loadCollections() {
    if (!ctx.connected()) {
      state.discovered = [];
      renderCollections();
      return;
    }
    api
      .collections()
      .then((r) => {
        state.discovered = r.collections;
        renderCollections();
      })
      .catch(() => {
        state.discovered = [];
        renderCollections();
      });
  }

  function onConnectionChange(status) {
    ctx.setConnection(status);
    loadCollections();
    renderEval();
  }

  // -- Collections ---------------------------------------------------------

  function renderCollections() {
    const connected = ctx.connected();
    const names = state.discovered.map((c) => c.name);

    const controls = COLLECTION_ROLES.map(({ key, label }) => {
      const current = state.collections[key] ?? "";
      // The QA collection is an output: it usually does not exist yet, so it
      // stays a free-text field even when a live collection list is available.
      const usePicker = connected && names.length > 0 && key !== "qa_collection";
      if (!usePicker) {
        return field(
          label,
          el("input", {
            id: `coll-${key}`,
            type: "text",
            value: current,
            onInput: (e) => {
              state.collections[key] = e.target.value;
            },
          }),
        );
      }
      const options = [];
      if (!names.includes(current)) {
        options.push(el("option", { value: current, selected: true }, current || "(pick)"));
      }
      for (const c of state.discovered) {
        options.push(
          el(
            "option",
            { value: c.name, selected: c.name === current },
            `${c.name} (${c.doc_count.toLocaleString()} docs, ${c.kind})`,
          ),
        );
      }
      return field(
        label,
        el(
          "select",
          {
            id: `coll-${key}`,
            onChange: (e) => {
              state.collections[key] = e.target.value;
            },
          },
          options,
        ),
      );
    });

    replace(
      collectionsPanel,
      el("h2", {}, "Collections"),
      !connected &&
        el(
          "p",
          { class: "muted" },
          "Not connected — collection names are typed manually. Connect above to pick from a live list.",
        ),
      el("div", { class: "row" }, controls),
    );
  }

  // -- LLM -----------------------------------------------------------------

  function llmInput(id, key, opts = {}) {
    return el("input", {
      id,
      type: opts.type ?? "text",
      step: opts.step,
      min: opts.min,
      max: opts.max,
      value: state.llm[key],
      placeholder: opts.placeholder,
      onInput: (e) => {
        state.llm[key] = opts.type === "number" ? Number(e.target.value) : e.target.value;
      },
    });
  }

  function renderLlm() {
    if (!state.llm) {
      replace(llmPanel);
      llmPanel.hidden = true;
      return;
    }
    llmPanel.hidden = false;
    replace(
      llmPanel,
      el("h2", {}, "LLM provider"),
      el(
        "div",
        { class: "row" },
        field("API URL", llmInput("llm-url", "api_url")),
        field("API key", llmInput("llm-key", "api_key", { type: "password", placeholder: "sk-…" })),
      ),
      el(
        "div",
        { class: "row-3" },
        field("Model", llmInput("llm-model", "model")),
        field(
          "Temperature",
          llmInput("llm-temp", "temperature", { type: "number", step: "0.05", min: "0", max: "2" }),
        ),
        field("Max tokens", llmInput("llm-max", "max_tokens", { type: "number" })),
      ),
      el(
        "div",
        { class: "row" },
        field("Timeout (s)", llmInput("llm-timeout", "timeout_s", { type: "number" })),
        field("Retries", llmInput("llm-retries", "retries", { type: "number" })),
      ),
    );
  }

  // -- Evaluation parameters ----------------------------------------------

  async function fetchClusters() {
    const domains = state.collections.domains_collection;
    if (!domains) return;
    try {
      const r = await api.clusters(domains);
      if (r.clusters.length && state.evalParams) {
        state.evalParams.target_clusters = r.clusters.join("\n");
        renderEval();
      }
    } catch {
      // ignore — leave the textarea as-is
    }
  }

  function evalInput(id, key, opts = {}) {
    return el("input", {
      id,
      type: opts.type ?? "text",
      value: state.evalParams[key],
      onInput: (e) => {
        state.evalParams[key] = opts.type === "number" ? Number(e.target.value) : e.target.value;
      },
    });
  }

  function evalCheckbox(key, label) {
    return el(
      "label",
      { class: "field checkbox" },
      el("input", {
        type: "checkbox",
        checked: state.evalParams[key],
        onChange: (e) => {
          state.evalParams[key] = e.target.checked;
        },
      }),
      label,
    );
  }

  function renderEval() {
    if (!state.evalParams) {
      replace(evalPanel);
      evalPanel.hidden = true;
      return;
    }
    evalPanel.hidden = false;
    const domains = state.collections.domains_collection;
    const clustersArea = el("textarea", {
      id: "eval-clusters",
      value: state.evalParams.target_clusters,
      onInput: (e) => {
        state.evalParams.target_clusters = e.target.value;
      },
    });

    replace(
      evalPanel,
      el("h2", {}, "Evaluation parameters"),
      el(
        "div",
        { class: "row" },
        field("Target clusters (one per line)", clustersArea, {
          hint:
            ctx.connected() && domains
              ? el(
                  "button",
                  { type: "button", disabled: state.busy, onClick: fetchClusters },
                  `Fetch cluster ids from ${domains}`,
                )
              : null,
        }),
        field("Questions per cluster", evalInput("eval-n", "n_questions", { type: "number" })),
      ),
      el(
        "div",
        { class: "row-3" },
        field("Hop sizes (comma, all ≥ 2)", evalInput("eval-hop", "hop_dist")),
        field("Weights (sum to 1.0)", evalInput("eval-weights", "hop_dist_weights")),
        field(
          "Max verify rounds",
          evalInput("eval-verify", "max_verify_rounds", { type: "number" }),
        ),
      ),
      el(
        "div",
        { class: "btn-row" },
        evalCheckbox("save_to_arango", "Save accepted rows to Arango"),
        evalCheckbox("score_with_rubric", "Score with rubric (judge LLM)"),
      ),
    );
  }

  // -- Persona / rubric editors -------------------------------------------

  function renderPersonas() {
    const rows = state.personas.map((p, i) =>
      el(
        "tr",
        {},
        el(
          "td",
          {},
          el("input", {
            "aria-label": `persona-label-${i}`,
            type: "text",
            value: p.label,
            onInput: (e) => {
              state.personas[i].label = e.target.value;
            },
          }),
        ),
        el(
          "td",
          {},
          el("textarea", {
            "aria-label": `persona-instruction-${i}`,
            value: p.instruction,
            onInput: (e) => {
              state.personas[i].instruction = e.target.value;
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
              onClick: () => {
                state.personas.splice(i, 1);
                renderPersonas();
              },
            },
            "✕",
          ),
        ),
      ),
    );
    replace(personaBody, rows);
  }

  function renderRubric() {
    const numberCell = (i, key, label, step) =>
      el(
        "td",
        {},
        el("input", {
          "aria-label": `rubric-${label}-${i}`,
          type: "number",
          step,
          value: state.rubric[i][key],
          onInput: (e) => {
            state.rubric[i][key] = Number(e.target.value);
          },
        }),
      );

    const rows = state.rubric.map((r, i) =>
      el(
        "tr",
        {},
        el(
          "td",
          {},
          el("input", {
            "aria-label": `rubric-name-${i}`,
            type: "text",
            value: r.name,
            onInput: (e) => {
              state.rubric[i].name = e.target.value;
            },
          }),
        ),
        el(
          "td",
          {},
          el("textarea", {
            "aria-label": `rubric-desc-${i}`,
            value: r.description,
            onInput: (e) => {
              state.rubric[i].description = e.target.value;
            },
          }),
        ),
        numberCell(i, "scale_min", "min"),
        numberCell(i, "scale_max", "max"),
        numberCell(i, "weight", "weight", "0.1"),
        el(
          "td",
          {},
          el(
            "button",
            {
              type: "button",
              onClick: () => {
                state.rubric.splice(i, 1);
                renderRubric();
              },
            },
            "✕",
          ),
        ),
      ),
    );
    replace(rubricBody, rows);
  }

  // -- Save / load ---------------------------------------------------------

  function showMsg(kind, text) {
    state.saveMsg = { kind, text };
    replace(actionsMsg, banner(kind, text));
  }

  async function loadFromEnv() {
    state.busy = true;
    replace(actionsMsg);
    try {
      await api.loadFromEnv();
      await ctx.refreshConfig();
      initFromConfig();
      renderCollections();
      renderLlm();
      renderEval();
      renderPersonas();
      renderRubric();
      projectInput.value = state.projectName;
      showMsg("ok", "Loaded configuration from environment.");
    } catch (err) {
      showMsg("error", errorText(err));
    } finally {
      state.busy = false;
    }
  }

  async function save() {
    if (!state.llm || !state.evalParams) return;
    state.busy = true;
    replace(actionsMsg);
    try {
      await api.saveConfig({
        project_name: state.projectName,
        collections: state.collections,
        llm: state.llm,
        eval: {
          target_clusters: splitLines(state.evalParams.target_clusters),
          n_questions: state.evalParams.n_questions,
          hop_dist: splitNums(state.evalParams.hop_dist).map((n) => Math.trunc(n)),
          hop_dist_weights: splitNums(state.evalParams.hop_dist_weights),
          max_verify_rounds: state.evalParams.max_verify_rounds,
          save_to_arango: state.evalParams.save_to_arango,
          score_with_rubric: state.evalParams.score_with_rubric,
          personas: state.personas.filter((p) => p.label.trim() && p.instruction.trim()),
          rubric_fields: state.rubric.filter((r) => r.name.trim() && r.description.trim()),
        },
      });
      await ctx.refreshConfig();
      showMsg("ok", "Configuration saved for this session.");
    } catch (err) {
      showMsg("error", errorText(err));
    } finally {
      state.busy = false;
    }
  }

  // -----------------------------------------------------------------------
  // Static structure
  // -----------------------------------------------------------------------

  const projectInput = el("input", {
    id: "project-name",
    type: "text",
    value: state.projectName,
    placeholder: "multihop_eval",
    onInput: (e) => {
      state.projectName = e.target.value;
      if (state.projectName.trim()) {
        state.collections = deriveCollections(state.projectName);
        renderCollections();
      }
    },
  });

  const projectHint = el("p", { class: "muted" });
  projectHint.append(
    "Every collection below is derived from this as ",
    el("code", {}, "<project>_<suffix>"),
    " (and ",
    el("code", {}, "qa_pairs_<project>_v1"),
    " for the QA output), so setting it once propagates the name everywhere. Edit an individual field below to override just that collection.",
  );

  const element = el(
    "div",
    {},
    createConnectionPanel(ctx, onConnectionChange),
    el(
      "div",
      { class: "panel" },
      el("h2", {}, "Autograph project"),
      field("Autograph project name", projectInput, { hint: projectHint }),
    ),
    collectionsPanel,
    llmPanel,
    evalPanel,
    el(
      "div",
      { class: "panel" },
      el("h2", {}, "Personas"),
      el(
        "table",
        { class: "editable-table" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", { style: { width: "25%" } }, "Label"),
            el("th", {}, "Instruction"),
            el("th", { style: { width: "1%" } }),
          ),
        ),
        personaBody,
      ),
      el(
        "button",
        {
          type: "button",
          style: { marginTop: "0.5rem" },
          onClick: () => {
            state.personas.push({ label: "", instruction: "" });
            renderPersonas();
          },
        },
        "+ Add persona",
      ),
    ),
    el(
      "div",
      { class: "panel" },
      el("h2", {}, "Evaluation rubric"),
      el(
        "table",
        { class: "editable-table" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", { style: { width: "18%" } }, "Name"),
            el("th", {}, "Description"),
            el("th", { style: { width: "8%" } }, "Min"),
            el("th", { style: { width: "8%" } }, "Max"),
            el("th", { style: { width: "10%" } }, "Weight"),
            el("th", { style: { width: "1%" } }),
          ),
        ),
        rubricBody,
      ),
      el(
        "button",
        {
          type: "button",
          style: { marginTop: "0.5rem" },
          onClick: () => {
            state.rubric.push({
              name: "",
              description: "",
              scale_min: 1,
              scale_max: 5,
              weight: 1.0,
            });
            renderRubric();
          },
        },
        "+ Add rubric field",
      ),
    ),
    el(
      "div",
      { class: "panel" },
      el(
        "div",
        { class: "btn-row" },
        el("button", { class: "primary", type: "button", onClick: save }, "Save configuration"),
        el("button", { type: "button", onClick: loadFromEnv }, "Load from env / .env"),
      ),
      el("div", { style: { marginTop: "0.75rem" } }, actionsMsg),
    ),
  );

  renderCollections();
  renderLlm();
  renderEval();
  renderPersonas();
  renderRubric();
  loadCollections();

  return { element };
}
