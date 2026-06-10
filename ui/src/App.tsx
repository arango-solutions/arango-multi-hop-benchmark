import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import type { ConfigResponse, ConnectionStatus } from "./api/types";
import { ConfigureTab } from "./components/ConfigureTab";
import { RunTab } from "./components/RunTab";
import { DashboardTab } from "./components/DashboardTab";
import { AdhocTab } from "./components/AdhocTab";
import { RagEvalTab } from "./components/RagEvalTab";

type TabId = "configure" | "run" | "dashboard" | "adhoc" | "rag_eval";

const TABS: { id: TabId; label: string }[] = [
  { id: "configure", label: "Configure" },
  { id: "run", label: "Run" },
  { id: "dashboard", label: "Dashboard" },
  { id: "adhoc", label: "Ad-hoc" },
  { id: "rag_eval", label: "RAG Eval" },
];

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>("configure");
  const [connection, setConnection] = useState<ConnectionStatus | null>(null);
  const [configResp, setConfigResp] = useState<ConfigResponse | null>(null);

  const refreshConnection = useCallback(async () => {
    const status = await api.connectionStatus();
    setConnection(status);
    return status;
  }, []);

  const refreshConfig = useCallback(async () => {
    const resp = await api.getConfig();
    setConfigResp(resp);
    return resp;
  }, []);

  useEffect(() => {
    void refreshConnection().catch(() => undefined);
    void refreshConfig().catch(() => undefined);
  }, [refreshConnection, refreshConfig]);

  const connected = connection?.status?.startsWith("connected") ?? false;
  const hasConfig = Boolean(configResp?.saved);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Multi-Hop Eval</h1>
        <span className="subtitle">
          QA dataset generation & evaluation against Arango graph data
        </span>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            className={`tab${activeTab === t.id ? " active" : ""}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {activeTab === "configure" && (
        <ConfigureTab
          connection={connection}
          configResp={configResp}
          onConnectionChange={setConnection}
          refreshConnection={refreshConnection}
          refreshConfig={refreshConfig}
        />
      )}
      {activeTab === "run" && (
        <RunTab connected={connected} hasConfig={hasConfig} />
      )}
      {activeTab === "dashboard" && <DashboardTab connected={connected} />}
      {activeTab === "adhoc" && <AdhocTab hasConfig={hasConfig} />}
      {activeTab === "rag_eval" && <RagEvalTab connected={connected} />}
    </div>
  );
}
