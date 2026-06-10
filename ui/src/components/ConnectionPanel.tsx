import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { ConnectionStatus } from "../api/types";

interface Props {
  connection: ConnectionStatus | null;
  onChange: (status: ConnectionStatus) => void;
}

const DEFAULT_DB = "_system";

export function ConnectionPanel({ connection, onChange }: Props) {
  const [host, setHost] = useState("https://");
  const [db, setDb] = useState(DEFAULT_DB);
  const [username, setUsername] = useState("root");
  const [password, setPassword] = useState("");
  const [databases, setDatabases] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const status = connection?.status ?? "disconnected";
  const connected = status.startsWith("connected");
  const ampDetected = connection?.amp.detected ?? false;

  useEffect(() => {
    if (connection?.db) setDb(connection.db);
  }, [connection?.db]);

  useEffect(() => {
    if (!connected) {
      setDatabases([]);
      return;
    }
    api
      .databases()
      .then((r) => setDatabases(r.databases))
      .catch(() => setDatabases([]));
  }, [connected, connection?.db]);

  async function run(fn: () => Promise<ConnectionStatus>) {
    setBusy(true);
    setLocalError(null);
    try {
      onChange(await fn());
    } catch (err) {
      setLocalError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const connectAmp = () => run(() => api.connect({ mode: "amp", db }));
  const connectManual = () =>
    run(() => api.connect({ mode: "password", host, db, username, password }));
  const disconnect = () => run(() => api.disconnect());
  const test = () => run(() => api.testConnection());
  const switchDb = (next: string) => {
    setDb(next);
    run(() =>
      ampDetected && status === "connected_amp"
        ? api.connect({ mode: "amp", db: next })
        : api.connect({ mode: "password", host, db: next, username, password }),
    );
  };

  return (
    <div className="panel">
      <h2>Arango connection</h2>

      {status === "connected_amp" && (
        <div className="banner ok">
          Connected via AMP
          {connection?.amp.deployment_name
            ? ` (deployment ${connection.amp.deployment_name})`
            : ""}
          . The token rotates automatically.
        </div>
      )}
      {status === "connected_manual" && (
        <div className="banner info">Connected with manual credentials.</div>
      )}
      {status === "error" && (
        <div className="banner error">
          Not connected — {connection?.error ?? "unknown error"}
        </div>
      )}
      {status === "disconnected" && ampDetected && (
        <div className="banner info">
          AMP environment detected. Connect via AMP to use deployment credentials,
          or use the manual form.
        </div>
      )}
      {status === "disconnected" && !ampDetected && (
        <div className="banner warn">
          Disconnected. Fill in the connection form below.
        </div>
      )}
      {localError && <div className="banner error">{localError}</div>}

      {ampDetected && !connected && (
        <div className="btn-row" style={{ marginBottom: "0.75rem" }}>
          <button className="primary" onClick={connectAmp} disabled={busy}>
            Connect via AMP
          </button>
        </div>
      )}

      {!connected && (
        <>
          <div className="row">
            <div className="field">
              <label htmlFor="conn-host">Host</label>
              <input
                id="conn-host"
                type="text"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="https://my-cluster.arangodb.cloud"
              />
            </div>
            <div className="field">
              <label htmlFor="conn-db">Database</label>
              <input
                id="conn-db"
                type="text"
                value={db}
                onChange={(e) => setDb(e.target.value)}
              />
            </div>
          </div>
          <div className="row">
            <div className="field">
              <label htmlFor="conn-user">Username</label>
              <input
                id="conn-user"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="conn-pass">Password</label>
              <input
                id="conn-pass"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          <div className="btn-row">
            <button className="primary" onClick={connectManual} disabled={busy}>
              Connect
            </button>
          </div>
        </>
      )}

      {connected && (
        <>
          <div className="field">
            <label htmlFor="conn-db-switch">Database</label>
            <select
              id="conn-db-switch"
              value={db}
              onChange={(e) => switchDb(e.target.value)}
              disabled={busy}
            >
              {(databases.length ? databases : [db]).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="btn-row">
            <button onClick={test} disabled={busy}>
              Test connection
            </button>
            <button className="danger" onClick={disconnect} disabled={busy}>
              Disconnect
            </button>
            {connection?.last_tested && (
              <span className="muted">Last verified {connection.last_tested} UTC</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
