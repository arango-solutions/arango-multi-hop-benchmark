import { useState } from "react";
import { ApiError, api, downloadFile } from "../api/client";
import type {
  RagEvalResponse,
  RagEvalRun,
  RagRelevanceMode,
  RagResponseSource,
} from "../api/types";

interface Props {
  connected: boolean;
}

function parseInts(value: string): number[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isFinite(n));
}

function parseStrings(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function MetricTable({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <div>
      <h3>{title}</h3>
      <table className="data-table">
        <tbody>
          {entries
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([metric, value]) => (
              <tr key={metric}>
                <td>{metric}</td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {typeof value === "number" ? value.toFixed(4) : String(value)}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function SystemCard({ run }: { run: RagEvalRun }) {
  return (
    <div className="panel">
      <h2>{run.system_name}</h2>
      <div className="muted" style={{ marginBottom: "0.5rem" }}>
        {run.n_responses} responses · {run.n_matched_goldens} matched goldens
      </div>
      <div className="row">
        <MetricTable title="Retrieval metrics" data={run.metrics.retrieval} />
        <MetricTable title="Generation metrics" data={run.metrics.generation} />
      </div>
    </div>
  );
}

export function RagEvalTab({ connected }: Props) {
  const [relevanceMode, setRelevanceMode] = useState<RagRelevanceMode>("binary");
  const [kValues, setKValues] = useState("1, 3, 5, 10");
  const [responseSource, setResponseSource] = useState<RagResponseSource>("jsonl");
  const [arangoCollection, setArangoCollection] = useState("rag_responses_v1");
  const [systemFilter, setSystemFilter] = useState("");
  const [lengthZ, setLengthZ] = useState(2.0);
  const [fuzzThreshold, setFuzzThreshold] = useState(75);
  const [emptyRetrievalMin, setEmptyRetrievalMin] = useState("");
  const [goldenLimit, setGoldenLimit] = useState("");
  const [jsonlText, setJsonlText] = useState<string | null>(null);
  const [jsonlName, setJsonlName] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RagEvalResponse | null>(null);

  function onFile(file: File | undefined) {
    if (!file) {
      setJsonlText(null);
      setJsonlName(null);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setJsonlText(String(reader.result ?? ""));
      setJsonlName(file.name);
    };
    reader.readAsText(file);
  }

  async function evaluate() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.ragEvalEvaluate({
        relevance_mode: relevanceMode,
        k_values: parseInts(kValues),
        response_source: responseSource,
        response_arango_collection: arangoCollection,
        system_filter: parseStrings(systemFilter),
        length_z_threshold: lengthZ,
        groundedness_fuzz_threshold: fuzzThreshold,
        empty_retrieval_min_score:
          emptyRetrievalMin.trim() === "" ? null : Number(emptyRetrievalMin),
        jsonl_text: responseSource === "jsonl" ? jsonlText : null,
        golden_limit: goldenLimit.trim() === "" ? null : Number(goldenLimit),
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function exportAs(fmt: "json" | "excel") {
    setError(null);
    try {
      const ext = fmt === "excel" ? "xlsx" : "json";
      await downloadFile(`/rag_eval/export?fmt=${fmt}`, `rag_eval.${ext}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const canSubmit =
    connected &&
    !busy &&
    (responseSource === "arango" || (jsonlText !== null && jsonlText.length > 0));

  return (
    <div>
      <div className="panel">
        <h2>RAG Eval</h2>
        <p className="muted">
          Score one or more RAG systems against the golden QA set: retrieval
          (P@K, R@K, MRR, NDCG@K, …) and rule-based generation metrics.
        </p>

        {!connected && (
          <div className="banner warn">
            Goldens are read from ArangoDB. Connect on the Configure tab first.
          </div>
        )}

        <div className="row-3">
          <div className="field">
            <label htmlFor="rag-relevance">Relevance mode</label>
            <select
              id="rag-relevance"
              value={relevanceMode}
              onChange={(e) => setRelevanceMode(e.target.value as RagRelevanceMode)}
            >
              <option value="binary">binary</option>
              <option value="graded">graded</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="rag-k">K values (comma-separated)</label>
            <input
              id="rag-k"
              type="text"
              value={kValues}
              onChange={(e) => setKValues(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="rag-source">Response source</label>
            <select
              id="rag-source"
              value={responseSource}
              onChange={(e) => setResponseSource(e.target.value as RagResponseSource)}
            >
              <option value="jsonl">JSONL upload</option>
              <option value="arango">ArangoDB collection</option>
            </select>
          </div>
        </div>

        {responseSource === "jsonl" ? (
          <div className="field">
            <label htmlFor="rag-file">Responses JSONL</label>
            <input
              id="rag-file"
              type="file"
              accept=".jsonl,.json,application/json,text/plain"
              onChange={(e) => onFile(e.target.files?.[0])}
            />
            {jsonlName && (
              <span className="muted">
                Loaded {jsonlName} ({jsonlText?.split("\n").filter(Boolean).length ?? 0} lines)
              </span>
            )}
          </div>
        ) : (
          <div className="field">
            <label htmlFor="rag-collection">Response collection</label>
            <input
              id="rag-collection"
              type="text"
              value={arangoCollection}
              onChange={(e) => setArangoCollection(e.target.value)}
            />
          </div>
        )}

        <div className="row-3">
          <div className="field">
            <label htmlFor="rag-filter">System filter (comma-separated, optional)</label>
            <input
              id="rag-filter"
              type="text"
              value={systemFilter}
              onChange={(e) => setSystemFilter(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="rag-lenz">Length z-threshold</label>
            <input
              id="rag-lenz"
              type="number"
              step="0.1"
              value={lengthZ}
              onChange={(e) => setLengthZ(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="rag-fuzz">Groundedness fuzz threshold</label>
            <input
              id="rag-fuzz"
              type="number"
              value={fuzzThreshold}
              onChange={(e) => setFuzzThreshold(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="rag-empty">Empty-retrieval min score (optional)</label>
            <input
              id="rag-empty"
              type="number"
              step="0.1"
              value={emptyRetrievalMin}
              onChange={(e) => setEmptyRetrievalMin(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="rag-golden">Golden limit (optional)</label>
            <input
              id="rag-golden"
              type="number"
              value={goldenLimit}
              onChange={(e) => setGoldenLimit(e.target.value)}
            />
          </div>
        </div>

        <div className="btn-row">
          <button className="primary" onClick={evaluate} disabled={!canSubmit}>
            Evaluate
          </button>
          {busy && <span className="muted">Evaluating…</span>}
          {result && result.runs.length > 0 && (
            <>
              <button onClick={() => exportAs("json")} disabled={busy}>
                Download JSON
              </button>
              <button onClick={() => exportAs("excel")} disabled={busy}>
                Download Excel
              </button>
            </>
          )}
        </div>

        {error && <div className="banner error" style={{ marginTop: "0.75rem" }}>{error}</div>}

        {result && (
          <div style={{ marginTop: "0.75rem" }}>
            <div className="banner ok">
              {result.n_systems} system(s) · {result.n_responses} responses ·{" "}
              {result.n_goldens} goldens.
            </div>
            {result.load_errors.length > 0 && (
              <div className="banner warn">
                {result.load_errors.length} response row(s) skipped:
                <div className="log" style={{ marginTop: "0.4rem" }}>
                  {result.load_errors.join("\n")}
                </div>
              </div>
            )}
            {result.runs.length === 0 && (
              <div className="banner info">
                No responses matched. Check the system filter and that the
                responses' qa_pair_key values match the goldens' _key.
              </div>
            )}
          </div>
        )}
      </div>

      {result?.runs.map((run) => (
        <SystemCard key={run.system_name} run={run} />
      ))}
    </div>
  );
}
