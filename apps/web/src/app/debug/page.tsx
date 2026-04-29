"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type RuntimeDebug = {
  worker?: { status?: string; service?: string };
  model?: { provider?: string | null; connection_mode?: string | null; name?: string | null; base_url?: string | null };
  permissions?: { write_mode?: string };
  repository?: { source?: string | null; project_path?: string | null; branch?: string | null };
  agent?: { orchestration_mode?: string };
  recent_runs?: Array<Record<string, unknown>>;
};

type MemoryDebug = {
  items: Array<{ id: string; type: string; content: string; source: string; created_at: string }>;
  graph: { nodes: unknown[]; edges: unknown[] };
};

type SkillsDebug = {
  skills: Array<{ name: string; source_path: string; description: string; enabled: boolean }>;
};

type IntegrationsDebug = {
  integrations: Array<{ provider: string; status: string; account?: string | null; tools_count: number; message?: string }>;
};

const tabs = ["Dashboard", "Agents", "Memory", "Skills", "Integrations", "Events / Runs", "Settings"] as const;
type DebugTab = typeof tabs[number];

async function loadJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return (await response.json()) as T;
}

export default function DebugPage() {
  const [activeTab, setActiveTab] = useState<DebugTab>("Dashboard");
  const [runtime, setRuntime] = useState<RuntimeDebug | null>(null);
  const [memory, setMemory] = useState<MemoryDebug | null>(null);
  const [skills, setSkills] = useState<SkillsDebug | null>(null);
  const [integrations, setIntegrations] = useState<IntegrationsDebug | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [runtimePayload, memoryPayload, skillsPayload, integrationsPayload] = await Promise.all([
          loadJson<RuntimeDebug>("/api/worker/debug/runtime"),
          loadJson<MemoryDebug>("/api/worker/debug/memory"),
          loadJson<SkillsDebug>("/api/worker/debug/skills"),
          loadJson<IntegrationsDebug>("/api/worker/debug/integrations"),
        ]);
        setRuntime(runtimePayload);
        setMemory(memoryPayload);
        setSkills(skillsPayload);
        setIntegrations(integrationsPayload);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load debug data.");
      }
    }
    void load();
  }, []);

  return (
    <div className="debug-shell">
      <aside className="debug-sidebar">
        <div className="debug-brand">RepoOperator Debug</div>
        {tabs.map((tab) => (
          <button
            key={tab}
            className={`debug-tab${activeTab === tab ? " debug-tab-active" : ""}`}
            type="button"
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
        <Link className="debug-back-link" href="/app">Back to app</Link>
      </aside>
      <main className="debug-main">
        <header className="debug-header">
          <h1>{activeTab}</h1>
          <span className={`debug-status${runtime?.worker?.status === "ok" ? " debug-status-ok" : ""}`}>
            {runtime?.worker?.status === "ok" ? "Worker online" : "Worker unavailable"}
          </span>
        </header>
        {error && <div className="debug-error">{error}</div>}
        {activeTab === "Dashboard" && <Dashboard runtime={runtime} />}
        {activeTab === "Agents" && <Agents runtime={runtime} />}
        {activeTab === "Memory" && <MemoryPanel memory={memory} />}
        {activeTab === "Skills" && <SkillsPanel skills={skills} />}
        {activeTab === "Integrations" && <IntegrationsPanel integrations={integrations} />}
        {activeTab === "Events / Runs" && <RunsPanel runtime={runtime} />}
        {activeTab === "Settings" && <SettingsPanel runtime={runtime} />}
      </main>
    </div>
  );
}

function Dashboard({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <div className="debug-grid">
      <Card title="Worker">
        <Row label="Status" value={runtime?.worker?.status ?? "-"} />
        <Row label="Service" value={runtime?.worker?.service ?? "-"} />
      </Card>
      <Card title="Model">
        <Row label="Provider" value={runtime?.model?.provider ?? "-"} />
        <Row label="Model" value={runtime?.model?.name ?? "-"} />
        <Row label="Base URL" value={runtime?.model?.base_url ?? "-"} />
      </Card>
      <Card title="Repository">
        <Row label="Source" value={runtime?.repository?.source ?? "-"} />
        <Row label="Project" value={runtime?.repository?.project_path ?? "-"} />
        <Row label="Branch" value={runtime?.repository?.branch ?? "-"} />
      </Card>
      <Card title="Permissions">
        <Row label="Write mode" value={runtime?.permissions?.write_mode ?? "-"} />
      </Card>
    </div>
  );
}

function Agents({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <Card title="Agent Orchestration">
      <Row label="Mode" value={runtime?.agent?.orchestration_mode ?? "LangGraph"} />
      <Row label="Write router" value="LangGraph intent and proposal flow" />
    </Card>
  );
}

function MemoryPanel({ memory }: { memory: MemoryDebug | null }) {
  return (
    <>
      <Card title="Memory Table">
        <table className="debug-table">
          <thead><tr><th>id</th><th>type</th><th>content</th><th>source</th><th>created_at</th></tr></thead>
          <tbody>
            {memory?.items.length ? memory.items.map((item) => (
              <tr key={item.id}><td>{item.id}</td><td>{item.type}</td><td>{item.content}</td><td>{item.source}</td><td>{item.created_at}</td></tr>
            )) : <tr><td colSpan={5}>No memory records yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      <Card title="Memory Graph">
        <div className="debug-placeholder">Graph view placeholder: {memory?.graph.nodes.length ?? 0} nodes, {memory?.graph.edges.length ?? 0} edges.</div>
      </Card>
    </>
  );
}

function SkillsPanel({ skills }: { skills: SkillsDebug | null }) {
  return (
    <Card title="Discovered Skills">
      {skills?.skills.length ? skills.skills.map((skill) => (
        <div className="debug-list-item" key={`${skill.source_path}:${skill.name}`}>
          <strong>{skill.name}</strong>
          <span>{skill.description || "No description"}</span>
          <code>{skill.source_path}</code>
        </div>
      )) : <div className="debug-placeholder">No skills.md files discovered.</div>}
    </Card>
  );
}

function IntegrationsPanel({ integrations }: { integrations: IntegrationsDebug | null }) {
  return (
    <Card title="Integration Status">
      {integrations?.integrations.map((integration) => (
        <div className="debug-list-item" key={integration.provider}>
          <strong>{integration.provider}</strong>
          <span>{integration.status} · tools: {integration.tools_count}</span>
          <button className="debug-disabled-button" disabled>Connect coming soon</button>
        </div>
      ))}
    </Card>
  );
}

function RunsPanel({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <Card title="Recent Runs">
      {runtime?.recent_runs?.length ? JSON.stringify(runtime.recent_runs) : <div className="debug-placeholder">No recent runs recorded yet.</div>}
    </Card>
  );
}

function SettingsPanel({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <Card title="Settings Snapshot">
      <Row label="Connection mode" value={runtime?.model?.connection_mode ?? "-"} />
      <Row label="Write mode" value={runtime?.permissions?.write_mode ?? "-"} />
    </Card>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="debug-card"><h2>{title}</h2>{children}</section>;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="debug-row"><span>{label}</span><strong>{value}</strong></div>;
}
