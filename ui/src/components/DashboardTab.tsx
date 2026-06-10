import { useCallback, useEffect, useState } from "react";
import { ApiError, api, downloadFile } from "../api/client";
import type {
  DashboardResponse,
  DashboardSource,
  DashboardSummary,
} from "../api/types";

interface Props {
  connected: boolean;
}

const ROW_LIMIT = 100;

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

function Distribution({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div>
      <h3>{title}</h3>
      <div className="dist">
        {entries
          .sort((a, b) => b[1] - a[1])
          .map(([key, value]) => (
            <div className="dist-row" key={key}>
              <span className="key" title={key}>
                {key}
              </span>
              <span className="dist-track">
                <span
                  className="fill"
                  style={{ width: `${Math.round((value / max) * 100)}%` }}
                />
              </span>
              <span className="num">{value}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

function Kpis({ summary, source }: { summary: DashboardSummary; source: DashboardSource }) {
  return (
    <div className="kpi-grid">
      <div className="kpi">
        <div className="value">{summary.total_accepted}</div>
        <div className="label">Accepted</div>
      </div>
      {source === "session" && (
        <>
          <div className="kpi">
            <div className="value">{summary.total_rejected}</div>
            <div className="label">Rejected</div>
          </div>
          <div className="kpi">
            <div className="value">{(summary.accept_rate * 100).toFixed(1)}%</div>
            <div className="label">Accept rate</div>
          </div>
        </>
      )}
      <div className="kpi">
        <div className="value">{fmtNum(summary.avg_hop_count)}</div>
        <div className="label">Avg hops</div>
      </div>
      <div className="kpi">
        <div className="value">{fmtNum(summary.avg_weighted_rubric)}</div>
        <div className="label">Avg rubric</div>
      </div>
      {summary.duration_s !== null && (
        <div className="kpi">
          <div className="value">{summary.duration_s.toFixed(1)}s</div>
          <div className="label">Duration</div>
        </div>
      )}
    </div>
  );
}

export function DashboardTab({ connected }: Props) {
  const [source, setSource] = useState<DashboardSource>("session");
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (src: DashboardSource) => {
    setBusy(true);
    setError(null);
    try {
      setData(await api.dashboardSummary(src));
    } catch (err) {
      setData(null);
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(source);
  }, [load, source]);

  async function exportAs(fmt: "json" | "excel") {
    setError(null);
    try {
      const ext = fmt === "excel" ? "xlsx" : "json";
      await downloadFile(
        `/dashboard/export?source=${source}&fmt=${fmt}`,
        `multihop_eval_${source}.${ext}`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const summary = data?.summary ?? null;
  const rows = data?.rows ?? [];
  const rowColumns = ["cluster_id", "hop_count", "persona", "question", "answer"];

  return (
    <div className="panel">
      <h2>Dashboard</h2>

      <div className="btn-row" style={{ marginBottom: "0.75rem" }}>
        <div className="field" style={{ marginBottom: 0, minWidth: 220 }}>
          <label htmlFor="dash-source">Data source</label>
          <select
            id="dash-source"
            value={source}
            onChange={(e) => setSource(e.target.value as DashboardSource)}
          >
            <option value="session">Current session run</option>
            <option value="arango">Persisted (ArangoDB)</option>
          </select>
        </div>
        <button onClick={() => load(source)} disabled={busy}>
          Refresh
        </button>
        <button onClick={() => exportAs("json")} disabled={busy || !data?.available}>
          Download JSON
        </button>
        {source === "session" && (
          <button
            onClick={() => exportAs("excel")}
            disabled={busy || !data?.available}
          >
            Download Excel
          </button>
        )}
      </div>

      {source === "arango" && !connected && (
        <div className="banner warn">
          Persisted data is read live from ArangoDB. Connect on the Configure tab first.
        </div>
      )}

      {error && <div className="banner error">{error}</div>}

      {data && !data.available && !error && (
        <div className="banner info">
          {source === "session"
            ? "No run has completed in this session yet. Start a run on the Run tab."
            : "No persisted QA rows found in the configured collection."}
        </div>
      )}

      {summary && data?.available && (
        <>
          <Kpis summary={summary} source={source} />

          <div className="row">
            <Distribution title="Hop distribution" data={summary.hop_distribution} />
            <Distribution
              title="Persona distribution"
              data={summary.persona_distribution}
            />
          </div>
          <div className="row">
            <Distribution title="Cluster coverage" data={summary.cluster_coverage} />
            {source === "session" ? (
              <Distribution
                title="Rejection breakdown"
                data={summary.rejection_breakdown}
              />
            ) : (
              <div />
            )}
          </div>
          {Object.keys(summary.rubric_means).length > 0 && (
            <Distribution title="Rubric means" data={summary.rubric_means} />
          )}

          <h3>
            Accepted rows{" "}
            {rows.length > ROW_LIMIT ? `(showing first ${ROW_LIMIT} of ${rows.length})` : `(${rows.length})`}
          </h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {rowColumns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, ROW_LIMIT).map((row, i) => (
                  <tr key={i}>
                    {rowColumns.map((c) => (
                      <td key={c}>{String(row[c] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
