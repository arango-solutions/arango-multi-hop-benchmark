import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type {
  CollectionItem,
  ConfigResponse,
  ConnectionStatus,
  LLMConfig,
  Persona,
  RubricField,
} from "../api/types";
import { ConnectionPanel } from "./ConnectionPanel";

interface Props {
  connection: ConnectionStatus | null;
  configResp: ConfigResponse | null;
  onConnectionChange: (status: ConnectionStatus) => void;
  refreshConnection: () => Promise<ConnectionStatus>;
  refreshConfig: () => Promise<ConfigResponse>;
}

const COLLECTION_ROLES: { key: string; label: string }[] = [
  { key: "sources_collection", label: "Sources collection" },
  { key: "similarity_collection", label: "Similarity collection" },
  { key: "relations_collection", label: "Relations collection" },
  { key: "domains_collection", label: "Domains collection" },
  { key: "rags_collection", label: "RAGs collection" },
  { key: "qa_collection", label: "QA collection (output)" },
];

interface EvalParams {
  target_clusters: string; // one per line
  n_questions: number;
  hop_dist: string; // comma separated
  hop_dist_weights: string; // comma separated
  max_verify_rounds: number;
  save_to_arango: boolean;
  score_with_rubric: boolean;
}

export function ConfigureTab({
  connection,
  configResp,
  onConnectionChange,
  refreshConfig,
}: Props) {
  const [collections, setCollections] = useState<Record<string, string>>({});
  const [llm, setLlm] = useState<LLMConfig | null>(null);
  const [evalParams, setEvalParams] = useState<EvalParams | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [rubric, setRubric] = useState<RubricField[]>([]);

  const [discovered, setDiscovered] = useState<CollectionItem[]>([]);
  const [saveMsg, setSaveMsg] = useState<{ kind: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = connection?.status?.startsWith("connected") ?? false;

  // Initialise the form from defaults, overlaying any previously-saved config.
  useEffect(() => {
    if (!configResp || evalParams) return;
    const d = configResp.defaults;
    const saved = configResp.saved as
      | {
          arango?: Record<string, string>;
          llm?: Partial<LLMConfig>;
          eval?: Record<string, unknown>;
        }
      | null;

    const coll: Record<string, string> = { ...d.collections };
    if (saved?.arango) {
      for (const { key } of COLLECTION_ROLES) {
        if (typeof saved.arango[key] === "string") coll[key] = saved.arango[key];
      }
    }
    setCollections(coll);

    const savedKey = saved?.llm?.api_key;
    setLlm({
      ...d.llm,
      ...(saved?.llm ?? {}),
      api_key: savedKey && savedKey !== "***" ? savedKey : "",
    });

    const e = (saved?.eval ?? {}) as Record<string, unknown>;
    setEvalParams({
      target_clusters: ((e.target_clusters as string[]) ?? d.eval.target_clusters).join("\n"),
      n_questions: (e.n_questions as number) ?? d.eval.n_questions,
      hop_dist: ((e.hop_dist as number[]) ?? d.eval.hop_dist).join(","),
      hop_dist_weights: ((e.hop_dist_weights as number[]) ?? d.eval.hop_dist_weights).join(","),
      max_verify_rounds: (e.max_verify_rounds as number) ?? d.eval.max_verify_rounds,
      save_to_arango: (e.save_to_arango as boolean) ?? d.eval.save_to_arango,
      score_with_rubric: (e.score_with_rubric as boolean) ?? d.eval.score_with_rubric,
    });
    setPersonas((e.personas as Persona[]) ?? d.personas);
    setRubric((e.rubric_fields as RubricField[]) ?? d.rubric_fields);
  }, [configResp, evalParams]);

  // Discover collections when connected.
  useEffect(() => {
    if (!connected) {
      setDiscovered([]);
      return;
    }
    api
      .collections()
      .then((r) => setDiscovered(r.collections))
      .catch(() => setDiscovered([]));
  }, [connected, connection?.db]);

  const collectionNames = useMemo(() => discovered.map((c) => c.name), [discovered]);

  async function fetchClusters() {
    const domains = collections.domains_collection;
    if (!domains) return;
    try {
      const r = await api.clusters(domains);
      if (r.clusters.length && evalParams) {
        setEvalParams({ ...evalParams, target_clusters: r.clusters.join("\n") });
      }
    } catch {
      // ignore — leave the textarea as-is
    }
  }

  async function loadFromEnv() {
    setBusy(true);
    setSaveMsg(null);
    try {
      await api.loadFromEnv();
      setEvalParams(null); // force re-init from the refreshed config
      await refreshConfig();
      setSaveMsg({ kind: "ok", text: "Loaded configuration from environment." });
    } catch (err) {
      setSaveMsg({
        kind: "error",
        text: err instanceof ApiError ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!llm || !evalParams) return;
    setBusy(true);
    setSaveMsg(null);
    try {
      await api.saveConfig({
        collections,
        llm,
        eval: {
          target_clusters: splitLines(evalParams.target_clusters),
          n_questions: evalParams.n_questions,
          hop_dist: splitNums(evalParams.hop_dist).map((n) => Math.trunc(n)),
          hop_dist_weights: splitNums(evalParams.hop_dist_weights),
          max_verify_rounds: evalParams.max_verify_rounds,
          save_to_arango: evalParams.save_to_arango,
          score_with_rubric: evalParams.score_with_rubric,
          personas: personas.filter((p) => p.label.trim() && p.instruction.trim()),
          rubric_fields: rubric.filter((r) => r.name.trim() && r.description.trim()),
        },
      });
      await refreshConfig();
      setSaveMsg({ kind: "ok", text: "Configuration saved for this session." });
    } catch (err) {
      setSaveMsg({
        kind: "error",
        text: err instanceof ApiError ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <ConnectionPanel connection={connection} onChange={onConnectionChange} />

      <div className="panel">
        <h2>Collections</h2>
        {!connected && (
          <p className="muted">
            Not connected — collection names are typed manually. Connect above to pick
            from a live list.
          </p>
        )}
        <div className="row">
          {COLLECTION_ROLES.map(({ key, label }) => (
            <div className="field" key={key}>
              <label htmlFor={`coll-${key}`}>{label}</label>
              {connected && collectionNames.length && key !== "qa_collection" ? (
                <select
                  id={`coll-${key}`}
                  value={collections[key] ?? ""}
                  onChange={(e) =>
                    setCollections({ ...collections, [key]: e.target.value })
                  }
                >
                  {!collectionNames.includes(collections[key] ?? "") && (
                    <option value={collections[key] ?? ""}>
                      {collections[key] ?? "(pick)"}
                    </option>
                  )}
                  {discovered.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({c.doc_count.toLocaleString()} docs, {c.kind})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id={`coll-${key}`}
                  type="text"
                  value={collections[key] ?? ""}
                  onChange={(e) =>
                    setCollections({ ...collections, [key]: e.target.value })
                  }
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {llm && (
        <div className="panel">
          <h2>LLM provider</h2>
          <div className="row">
            <div className="field">
              <label htmlFor="llm-url">API URL</label>
              <input
                id="llm-url"
                type="text"
                value={llm.api_url}
                onChange={(e) => setLlm({ ...llm, api_url: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="llm-key">API key</label>
              <input
                id="llm-key"
                type="password"
                value={llm.api_key}
                placeholder="sk-…"
                onChange={(e) => setLlm({ ...llm, api_key: e.target.value })}
              />
            </div>
          </div>
          <div className="row-3">
            <div className="field">
              <label htmlFor="llm-model">Model</label>
              <input
                id="llm-model"
                type="text"
                value={llm.model}
                onChange={(e) => setLlm({ ...llm, model: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="llm-temp">Temperature</label>
              <input
                id="llm-temp"
                type="number"
                step="0.05"
                min="0"
                max="2"
                value={llm.temperature}
                onChange={(e) =>
                  setLlm({ ...llm, temperature: Number(e.target.value) })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="llm-max">Max tokens</label>
              <input
                id="llm-max"
                type="number"
                value={llm.max_tokens}
                onChange={(e) =>
                  setLlm({ ...llm, max_tokens: Number(e.target.value) })
                }
              />
            </div>
          </div>
          <div className="row">
            <div className="field">
              <label htmlFor="llm-timeout">Timeout (s)</label>
              <input
                id="llm-timeout"
                type="number"
                value={llm.timeout_s}
                onChange={(e) =>
                  setLlm({ ...llm, timeout_s: Number(e.target.value) })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="llm-retries">Retries</label>
              <input
                id="llm-retries"
                type="number"
                value={llm.retries}
                onChange={(e) =>
                  setLlm({ ...llm, retries: Number(e.target.value) })
                }
              />
            </div>
          </div>
        </div>
      )}

      {evalParams && (
        <div className="panel">
          <h2>Evaluation parameters</h2>
          <div className="row">
            <div className="field">
              <label htmlFor="eval-clusters">Target clusters (one per line)</label>
              <textarea
                id="eval-clusters"
                value={evalParams.target_clusters}
                onChange={(e) =>
                  setEvalParams({ ...evalParams, target_clusters: e.target.value })
                }
              />
              {connected && collections.domains_collection && (
                <button onClick={fetchClusters} disabled={busy}>
                  Fetch cluster ids from {collections.domains_collection}
                </button>
              )}
            </div>
            <div className="field">
              <label htmlFor="eval-n">Questions per cluster</label>
              <input
                id="eval-n"
                type="number"
                value={evalParams.n_questions}
                onChange={(e) =>
                  setEvalParams({ ...evalParams, n_questions: Number(e.target.value) })
                }
              />
            </div>
          </div>
          <div className="row-3">
            <div className="field">
              <label htmlFor="eval-hop">Hop sizes (comma, all &ge; 2)</label>
              <input
                id="eval-hop"
                type="text"
                value={evalParams.hop_dist}
                onChange={(e) =>
                  setEvalParams({ ...evalParams, hop_dist: e.target.value })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="eval-weights">Weights (sum to 1.0)</label>
              <input
                id="eval-weights"
                type="text"
                value={evalParams.hop_dist_weights}
                onChange={(e) =>
                  setEvalParams({ ...evalParams, hop_dist_weights: e.target.value })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="eval-verify">Max verify rounds</label>
              <input
                id="eval-verify"
                type="number"
                value={evalParams.max_verify_rounds}
                onChange={(e) =>
                  setEvalParams({
                    ...evalParams,
                    max_verify_rounds: Number(e.target.value),
                  })
                }
              />
            </div>
          </div>
          <div className="btn-row">
            <label className="field checkbox">
              <input
                type="checkbox"
                checked={evalParams.save_to_arango}
                onChange={(e) =>
                  setEvalParams({ ...evalParams, save_to_arango: e.target.checked })
                }
              />
              Save accepted rows to ArangoDB
            </label>
            <label className="field checkbox">
              <input
                type="checkbox"
                checked={evalParams.score_with_rubric}
                onChange={(e) =>
                  setEvalParams({
                    ...evalParams,
                    score_with_rubric: e.target.checked,
                  })
                }
              />
              Score with rubric (judge LLM)
            </label>
          </div>
        </div>
      )}

      <PersonaEditor personas={personas} onChange={setPersonas} />
      <RubricEditor rubric={rubric} onChange={setRubric} />

      <div className="panel">
        <div className="btn-row">
          <button className="primary" onClick={save} disabled={busy}>
            Save configuration
          </button>
          <button onClick={loadFromEnv} disabled={busy}>
            Load from env / .env
          </button>
        </div>
        {saveMsg && (
          <div className={`banner ${saveMsg.kind}`} style={{ marginTop: "0.75rem" }}>
            {saveMsg.text}
          </div>
        )}
      </div>
    </div>
  );
}

function PersonaEditor({
  personas,
  onChange,
}: {
  personas: Persona[];
  onChange: (p: Persona[]) => void;
}) {
  const update = (i: number, patch: Partial<Persona>) =>
    onChange(personas.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  return (
    <div className="panel">
      <h2>Personas</h2>
      <table className="editable-table">
        <thead>
          <tr>
            <th style={{ width: "25%" }}>Label</th>
            <th>Instruction</th>
            <th style={{ width: "1%" }}></th>
          </tr>
        </thead>
        <tbody>
          {personas.map((p, i) => (
            <tr key={i}>
              <td>
                <input
                  aria-label={`persona-label-${i}`}
                  type="text"
                  value={p.label}
                  onChange={(e) => update(i, { label: e.target.value })}
                />
              </td>
              <td>
                <textarea
                  aria-label={`persona-instruction-${i}`}
                  value={p.instruction}
                  onChange={(e) => update(i, { instruction: e.target.value })}
                />
              </td>
              <td>
                <button
                  onClick={() => onChange(personas.filter((_, idx) => idx !== i))}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        style={{ marginTop: "0.5rem" }}
        onClick={() => onChange([...personas, { label: "", instruction: "" }])}
      >
        + Add persona
      </button>
    </div>
  );
}

function RubricEditor({
  rubric,
  onChange,
}: {
  rubric: RubricField[];
  onChange: (r: RubricField[]) => void;
}) {
  const update = (i: number, patch: Partial<RubricField>) =>
    onChange(rubric.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <div className="panel">
      <h2>Evaluation rubric</h2>
      <table className="editable-table">
        <thead>
          <tr>
            <th style={{ width: "18%" }}>Name</th>
            <th>Description</th>
            <th style={{ width: "8%" }}>Min</th>
            <th style={{ width: "8%" }}>Max</th>
            <th style={{ width: "10%" }}>Weight</th>
            <th style={{ width: "1%" }}></th>
          </tr>
        </thead>
        <tbody>
          {rubric.map((r, i) => (
            <tr key={i}>
              <td>
                <input
                  aria-label={`rubric-name-${i}`}
                  type="text"
                  value={r.name}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
              </td>
              <td>
                <textarea
                  aria-label={`rubric-desc-${i}`}
                  value={r.description}
                  onChange={(e) => update(i, { description: e.target.value })}
                />
              </td>
              <td>
                <input
                  aria-label={`rubric-min-${i}`}
                  type="number"
                  value={r.scale_min}
                  onChange={(e) => update(i, { scale_min: Number(e.target.value) })}
                />
              </td>
              <td>
                <input
                  aria-label={`rubric-max-${i}`}
                  type="number"
                  value={r.scale_max}
                  onChange={(e) => update(i, { scale_max: Number(e.target.value) })}
                />
              </td>
              <td>
                <input
                  aria-label={`rubric-weight-${i}`}
                  type="number"
                  step="0.1"
                  value={r.weight}
                  onChange={(e) => update(i, { weight: Number(e.target.value) })}
                />
              </td>
              <td>
                <button onClick={() => onChange(rubric.filter((_, idx) => idx !== i))}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        style={{ marginTop: "0.5rem" }}
        onClick={() =>
          onChange([
            ...rubric,
            { name: "", description: "", scale_min: 1, scale_max: 5, weight: 1.0 },
          ])
        }
      >
        + Add rubric field
      </button>
    </div>
  );
}

function splitLines(s: string): string[] {
  return s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

function splitNums(s: string): number[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
}
