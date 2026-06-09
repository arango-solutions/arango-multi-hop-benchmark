import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, runEventsUrl } from "../api/client";
import type { RunStreamEvent, RunSummary } from "../api/types";

interface Props {
  connected: boolean;
  hasConfig: boolean;
}

const ACTIVE = new Set(["running"]);

export function RunTab({ connected, hasConfig }: Props) {
  const [status, setStatus] = useState("idle");
  const [log, setLog] = useState<string[]>([]);
  const [accepted, setAccepted] = useState(0);
  const [target, setTarget] = useState(0);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const closeStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const openStream = useCallback(() => {
    closeStream();
    const es = new EventSource(runEventsUrl());
    esRef.current = es;
    es.onmessage = (msg) => {
      let ev: RunStreamEvent;
      try {
        ev = JSON.parse(msg.data);
      } catch {
        return;
      }
      if (ev.kind === "status") {
        setStatus(ev.status ?? "done");
        setSummary(ev.summary ?? null);
        setError(ev.error ?? null);
        if (ev.summary) {
          setAccepted(ev.summary.accepted);
          setTarget((t) => Math.max(t, ev.summary!.accepted));
        }
        closeStream();
        return;
      }
      if (ev.line) setLog((prev) => [...prev, ev.line as string]);
      const p = ev.payload ?? {};
      if (typeof p.accepted === "number") setAccepted(p.accepted);
      if (typeof p.target === "number") setTarget(p.target);
    };
    es.onerror = () => {
      // The stream closes normally when the run ends; refetch status to settle.
      closeStream();
      api
        .runStatus()
        .then((s) => {
          setStatus(s.status);
          setSummary(s.summary);
          setError(s.error);
        })
        .catch(() => undefined);
    };
  }, [closeStream]);

  // Restore state on mount; resume streaming if a run is still active.
  useEffect(() => {
    let cancelled = false;
    api
      .runStatus()
      .then((s) => {
        if (cancelled) return;
        setStatus(s.status);
        setLog(s.log);
        setAccepted(s.accepted);
        setTarget(s.target);
        setSummary(s.summary);
        setError(s.error);
        if (ACTIVE.has(s.status)) openStream();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      closeStream();
    };
  }, [openStream, closeStream]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const s = await api.startRun();
      setStatus(s.status);
      setLog([]);
      setAccepted(0);
      setTarget(s.target);
      setSummary(null);
      openStream();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await api.stopRun();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const running = ACTIVE.has(status);
  const pct = target > 0 ? Math.min(100, Math.round((accepted / target) * 100)) : 0;
  const tail = log.slice(-200).reverse();

  return (
    <div className="panel">
      <h2>Run</h2>

      {!connected && (
        <div className="banner warn">
          No live ArangoDB connection. Connect on the Configure tab before running.
        </div>
      )}
      {connected && !hasConfig && (
        <div className="banner warn">
          Save a configuration on the Configure tab before running.
        </div>
      )}

      <div className="btn-row" style={{ marginBottom: "0.75rem" }}>
        <button
          className="primary"
          onClick={start}
          disabled={busy || running || !connected || !hasConfig}
        >
          Run
        </button>
        <button className="danger" onClick={stop} disabled={busy || !running}>
          Stop
        </button>
        <span className="muted">
          Status: <strong>{status}</strong>
        </span>
      </div>

      <div className="progress" style={{ marginBottom: "0.75rem" }}>
        <div className="bar" style={{ width: `${running || summary ? pct : 0}%` }} />
        <div className="label">
          {running ? `${accepted}/${target}` : status === "idle" ? "" : status}
        </div>
      </div>

      {error && <div className="banner error">Run failed: {error}</div>}

      {summary && (
        <div className="banner ok">
          {status === "stopped" ? "Run stopped. " : "Run complete. "}
          {summary.accepted} accepted, {summary.rejected} rejected (accept rate{" "}
          {(summary.accept_rate * 100).toFixed(1)}%) in {summary.duration_s.toFixed(1)}s.
        </div>
      )}

      <h3>Live log (most recent first)</h3>
      <div className="log">{tail.length ? tail.join("\n") : "(no events yet)"}</div>
    </div>
  );
}
