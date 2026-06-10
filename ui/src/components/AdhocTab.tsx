import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { AdhocProofPoint, AdhocResponse } from "../api/types";

interface Props {
  hasConfig: boolean;
}

interface SourceRow {
  _id: string;
  content: string;
}

const EMPTY_PROOF: AdhocProofPoint = { point: "", source_id: "" };
const EMPTY_SOURCE: SourceRow = { _id: "", content: "" };

export function AdhocTab({ hasConfig }: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [proof, setProof] = useState<AdhocProofPoint[]>([{ ...EMPTY_PROOF }]);
  const [sources, setSources] = useState<SourceRow[]>([
    { ...EMPTY_SOURCE },
    { ...EMPTY_SOURCE },
  ]);
  const [scoreWithRubric, setScoreWithRubric] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AdhocResponse | null>(null);

  function updateProof(i: number, patch: Partial<AdhocProofPoint>) {
    setProof((prev) => prev.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  }
  function updateSource(i: number, patch: Partial<SourceRow>) {
    setSources((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  async function evaluate() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.adhocEvaluate({
        question,
        answer,
        reasoning_chain: reasoning,
        proof: proof.filter((p) => p.point.trim() || p.source_id.trim()),
        sources: sources
          .filter((s) => s._id.trim())
          .map((s) => ({ _id: s._id.trim(), content: s.content })),
        score_with_rubric: scoreWithRubric,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    hasConfig &&
    !busy &&
    question.trim().length > 0 &&
    answer.trim().length > 0 &&
    sources.filter((s) => s._id.trim()).length >= 2;

  return (
    <div className="panel">
      <h2>Ad-hoc</h2>
      <p className="muted">
        Validate a single QA pair against its source documents — the same
        multi-hop &amp; proof checks the generation pipeline runs.
      </p>

      {!hasConfig && (
        <div className="banner warn">
          Save a configuration on the Configure tab first (it supplies the LLM
          credentials and rubric).
        </div>
      )}

      <div className="field">
        <label htmlFor="adhoc-q">Question</label>
        <textarea
          id="adhoc-q"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="adhoc-a">Answer</label>
        <textarea
          id="adhoc-a"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="adhoc-r">Reasoning chain (optional)</label>
        <textarea
          id="adhoc-r"
          value={reasoning}
          onChange={(e) => setReasoning(e.target.value)}
        />
      </div>

      <h3>Proof points</h3>
      <table className="editable-table">
        <thead>
          <tr>
            <th style={{ width: "60%" }}>Point</th>
            <th>Source id</th>
            <th style={{ width: 40 }} />
          </tr>
        </thead>
        <tbody>
          {proof.map((p, i) => (
            <tr key={i}>
              <td>
                <input
                  aria-label={`proof-point-${i}`}
                  value={p.point}
                  onChange={(e) => updateProof(i, { point: e.target.value })}
                />
              </td>
              <td>
                <input
                  aria-label={`proof-source-${i}`}
                  value={p.source_id}
                  onChange={(e) => updateProof(i, { source_id: e.target.value })}
                />
              </td>
              <td>
                <button
                  onClick={() => setProof((prev) => prev.filter((_, idx) => idx !== i))}
                  disabled={proof.length <= 1}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="btn-row" style={{ margin: "0.5rem 0 1rem" }}>
        <button onClick={() => setProof((prev) => [...prev, { ...EMPTY_PROOF }])}>
          + Add proof point
        </button>
      </div>

      <h3>Source documents (≥ 2)</h3>
      <table className="editable-table">
        <thead>
          <tr>
            <th style={{ width: "30%" }}>_id</th>
            <th>Content</th>
            <th style={{ width: 40 }} />
          </tr>
        </thead>
        <tbody>
          {sources.map((s, i) => (
            <tr key={i}>
              <td>
                <input
                  aria-label={`source-id-${i}`}
                  value={s._id}
                  onChange={(e) => updateSource(i, { _id: e.target.value })}
                />
              </td>
              <td>
                <textarea
                  aria-label={`source-content-${i}`}
                  value={s.content}
                  onChange={(e) => updateSource(i, { content: e.target.value })}
                />
              </td>
              <td>
                <button
                  onClick={() => setSources((prev) => prev.filter((_, idx) => idx !== i))}
                  disabled={sources.length <= 2}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="btn-row" style={{ margin: "0.5rem 0 1rem" }}>
        <button onClick={() => setSources((prev) => [...prev, { ...EMPTY_SOURCE }])}>
          + Add source
        </button>
      </div>

      <div className="field checkbox">
        <input
          id="adhoc-rubric"
          type="checkbox"
          checked={scoreWithRubric}
          onChange={(e) => setScoreWithRubric(e.target.checked)}
        />
        <label htmlFor="adhoc-rubric">Score with rubric</label>
      </div>

      <div className="btn-row">
        <button className="primary" onClick={evaluate} disabled={!canSubmit}>
          Evaluate
        </button>
        {busy && <span className="muted">Evaluating…</span>}
      </div>

      {error && <div className="banner error" style={{ marginTop: "0.75rem" }}>{error}</div>}

      {result && (
        <div style={{ marginTop: "1rem" }}>
          <h3>Result</h3>
          <div className="btn-row" style={{ marginBottom: "0.75rem" }}>
            <span className={`badge ${result.multi_hop_pass ? "pass" : "fail"}`}>
              Multi-hop {result.multi_hop_pass ? "pass" : "fail"}
            </span>
            <span className={`badge ${result.proof_verdict === "pass" ? "pass" : "fail"}`}>
              Proof {result.proof_verdict}
            </span>
            <span className="muted">Genuine hops: {result.genuine_hop_count}</span>
            {result.rubric_weighted_score !== null && (
              <span className="muted">
                Weighted rubric: {result.rubric_weighted_score.toFixed(3)}
              </span>
            )}
          </div>

          <div className="field">
            <label>Multi-hop reasoning</label>
            <div className="banner info">{result.multi_hop_reason || "—"}</div>
          </div>

          {Object.keys(result.rubric_scores).length > 0 && (
            <>
              <h3>Rubric scores</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th style={{ width: 70 }}>Score</th>
                    <th>Justification</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.rubric_scores).map(([name, s]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>{s.score}</td>
                      <td>{s.justification}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Corrected proof</h3>
          <div className="log">
            {JSON.stringify(result.corrected_proof, null, 2)}
          </div>
        </div>
      )}
    </div>
  );
}
