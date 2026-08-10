"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import {
  getSettings,
  updateModelSettings,
  updateRepositorySettings,
  getPermissionMode,
  updatePermissionMode,
  getLogs,
  type SettingsSnapshot,
  type LogTail,
  type PermissionMode,
} from "@/lib/local-worker-client";
import { formatBudgetUsage, formatCarryoverSummary, formatTargetCandidates, type ContextBudgetUsage, type TargetCandidateDebug } from "./context-format";

type ModelProfileDebug = {
  provider?: string;
  model_name?: string;
  context_window?: number;
  max_output_tokens?: number;
  compression_strategy?: string;
  tokenizer_hint?: string;
};

type RuntimeDebug = {
  worker?: { status?: string; service?: string };
  model?: { provider?: string | null; connection_mode?: string | null; name?: string | null; base_url?: string | null; profile?: ModelProfileDebug };
  permissions?: {
    write_mode?: string;
    mode?: string;
    sandbox?: Record<string, string | boolean>;
    approval?: Record<string, boolean>;
    tools?: Record<string, string>;
  };
  repository?: {
    source?: string | null;
    project_path?: string | null;
    branch?: string | null;
    configured_default_source?: string | null;
    configured_sources?: Array<{ provider?: string | null; baseUrl?: string | null; tokenConfigured?: boolean; owner?: string }>;
    effective_sources?: Array<{ provider?: string | null; baseUrl?: string | null; tokenConfigured?: boolean; owner?: string }>;
  };
  agent?: {
    orchestration_mode?: string;
    planner?: string;
    planner_label?: string;
    tool_calling_enabled?: boolean;
    tool_calling_active?: boolean;
    model_supports_tool_calls?: boolean;
    model_endpoint_configured?: boolean;
  };
  active_runs?: Array<Record<string, unknown>>;
  recent_runs?: Array<Record<string, unknown>>;
};

type GraphNode = { id: string; label: string; type: string };
type GraphEdge = { source: string; target: string; label: string };

type MemoryDebug = {
  items: Array<{ id: string; type: string; content: string; source: string; repo?: string | null; created_at: string; tags?: string[] }>;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
};

type SkillsDebug = {
  skills: Array<{ name: string; source_path: string; scope: string; description: string; enabled: boolean }>;
};

type IntegrationsDebug = {
  integrations: Array<{
    provider: string;
    status: string;
    configured?: boolean;
    accounts?: Array<{ id?: string; status?: string; toolkit?: string; user_id?: string }>;
    toolkits?: Array<{ id?: string; slug?: string; name?: string; tools_count?: number }>;
    toolkits_count?: number;
    tools_count: number;
    message?: string;
  }>;
};

type ToolsDebug = {
  tools: Array<{ name: string; installed: boolean; path?: string | null; version?: string | null; auth_status?: string | null }>;
  permissions: Record<string, string>;
};

type ToolCatalog = {
  count: number;
  tools: Array<{ name: string; description: string; category: string; read_only: boolean; requires_approval: boolean; side_effect_level: string }>;
};

type ContextPackDebug = {
  run_id?: string;
  timestamp?: string;
  pack_kind?: string;
  trigger_node?: string;
  compression_ratio?: number;
  estimated_input_tokens?: number;
  estimated_output_reserve?: number;
  included_sections?: string[];
  excluded_sections?: string[];
  retained_files?: string[];
  omitted_files?: Array<{ path?: string; reason?: string; chars?: number; included_chars?: number }>;
  retained_web_sources?: Array<{ title?: string | null; url?: string | null; source?: string | null; fetched_at?: string | null }>;
  budget_usage?: ContextBudgetUsage;
  target_candidate_files?: TargetCandidateDebug[];
  prior_target_candidates?: TargetCandidateDebug[];
  prior_evidence_reused?: boolean;
  warnings?: string[];
};

type TargetSelectionDebug = {
  selected_target_files?: string[];
  prior_evidence_reused?: boolean;
  fallback_attempts?: number;
  failed_search_patterns?: string[];
  discovery_queries?: string[];
  discovery_file_globs?: string[];
  blocked_reason?: string | null;
  candidates?: TargetCandidateDebug[];
};

type MemoryCarryoverDebug = {
  target_candidate_summaries?: TargetCandidateDebug[];
  carryover_summaries?: Array<{ kind?: string; selected_target_files?: string[]; candidate_count?: number }>;
  thread_recent_files?: string[];
  thread_target_candidates?: TargetCandidateDebug[];
  last_implementation_plan?: { summary?: string; target_files?: string[] } | null;
  context_source?: string | null;
};

type ContextDebug = {
  model_profile?: ModelProfileDebug;
  latest_pack?: ContextPackDebug | null;
  recent_packs?: ContextPackDebug[];
  user_understanding_context?: {
    normalized_goal?: string;
    requested_outputs?: string[];
    likely_needed_tools?: string[];
    likely_capabilities?: string[];
    mentioned_files?: string[];
    mentioned_symbols?: string[];
    ambiguities?: string[];
    edit_mode?: string | null;
  };
  evidence_basis?: {
    files?: Array<{ path?: string; retained?: boolean; omitted_reason?: string | null; source?: string; summary?: string | null }>;
    web_sources?: Array<{ title?: string | null; url?: string; source?: string | null; untrusted?: boolean }>;
    validation?: Array<{ kind?: string; status?: string; errors?: string[] }>;
    active_proposal?: { proposal_id?: string | null; status?: string | null; files?: string[]; operation_counts?: Record<string, number> } | null;
    worker_reports?: Array<{ worker_task_id?: string; role?: string; summary?: string; files_analyzed?: string[] }>;
    missing_evidence?: string[];
    uncertainty?: string[];
    target_selection?: TargetSelectionDebug;
    memory_carryover?: MemoryCarryoverDebug;
  };
  context_pack_report?: ContextPackDebug & { budget_usage?: ContextBudgetUsage };
  context_pack_summary?: Record<string, unknown>;
  short_term_memory?: {
    files_read_summaries?: Array<{ path?: string; summary?: string }>;
    target_candidate_summaries?: TargetCandidateDebug[];
    carryover_summaries?: Array<{ kind?: string; selected_target_files?: string[]; candidate_count?: number }>;
    symbol_summaries?: Array<{ symbol?: string; summary?: string }>;
  };
  target_selection?: TargetSelectionDebug;
  edit_target_candidates?: TargetCandidateDebug[];
  visible_rationale_log?: Array<{
    id?: string;
    timestamp?: string;
    node?: string;
    action_type?: string | null;
    summary?: string;
    basis_refs?: Array<{ kind?: string; path?: string; url?: string; id?: string; query?: string }>;
    safety_note?: string | null;
    uncertainty?: string[];
  }>;
};

// Editable settings first, then plugins, then read-only diagnostics.
const tabs = ["Model", "Repository", "Permissions", "Logs", "MCP", "Skills", "Tools", "Integrations", "Dashboard", "Agents", "Context", "Memory", "Events / Runs"] as const;
type DebugTab = typeof tabs[number];

async function loadJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return (await response.json()) as T;
}

export default function DebugPage() {
  const [activeTab, setActiveTab] = useState<DebugTab>("Model");
  const [runtime, setRuntime] = useState<RuntimeDebug | null>(null);
  const [context, setContext] = useState<ContextDebug | null>(null);
  const [memory, setMemory] = useState<MemoryDebug | null>(null);
  const [skills, setSkills] = useState<SkillsDebug | null>(null);
  const [integrations, setIntegrations] = useState<IntegrationsDebug | null>(null);
  const [tools, setTools] = useState<ToolsDebug | null>(null);
  const [toolCatalog, setToolCatalog] = useState<ToolCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
      try {
        setError(null);
        const [runtimePayload, contextPayload, memoryPayload, skillsPayload, integrationsPayload, toolsPayload, catalogPayload] = await Promise.all([
          loadJson<RuntimeDebug>("/api/worker/debug/runtime"),
          loadJson<ContextDebug>("/api/worker/debug/context"),
          loadJson<MemoryDebug>("/api/worker/debug/memory"),
          loadJson<SkillsDebug>("/api/worker/debug/skills"),
          loadJson<IntegrationsDebug>("/api/worker/debug/integrations"),
          loadJson<ToolsDebug>("/api/worker/tools"),
          // Optional / newer endpoint — must not break the whole dashboard load.
          loadJson<ToolCatalog>("/api/worker/tools/catalog").catch(() => null),
        ]);
        setRuntime(runtimePayload);
        setContext(contextPayload);
        setMemory(memoryPayload);
        setSkills(skillsPayload);
        setIntegrations(integrationsPayload);
        setTools(toolsPayload);
        setToolCatalog(catalogPayload);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load debug data.");
      }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="debug-shell">
      <aside className="debug-sidebar">
        <div className="debug-brand">RepoOperator Settings</div>
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
          <div className="debug-header-actions">
            <button className="debug-secondary-button" type="button" onClick={() => void load()}>Reload</button>
            <span className={`debug-status${runtime?.worker?.status === "ok" ? " debug-status-ok" : ""}`}>
              {runtime?.worker?.status === "ok" ? "Worker online" : "Worker unavailable"}
            </span>
          </div>
        </header>
        {error && <div className="debug-error">{error}</div>}
        {activeTab === "Model" && <ModelSettingsPanel />}
        {activeTab === "Repository" && <RepositorySettingsPanel />}
        {activeTab === "Permissions" && <PermissionsSettingsPanel />}
        {activeTab === "Logs" && <LogsPanel />}
        {activeTab === "Dashboard" && <Dashboard runtime={runtime} />}
        {activeTab === "Agents" && <Agents runtime={runtime} />}
        {activeTab === "Context" && <ContextPanel context={context} />}
        {activeTab === "Memory" && <MemoryPanel memory={memory} />}
        {activeTab === "Skills" && <SkillsPanel skills={skills} />}
        {activeTab === "Integrations" && <IntegrationsPanel integrations={integrations} />}
        {activeTab === "MCP" && <McpPanel />}
        {activeTab === "Tools" && <ToolsPanel tools={tools} catalog={toolCatalog} />}
        {activeTab === "Events / Runs" && <RunsPanel runtime={runtime} />}
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
        <Row
          label="Active runs"
          value={String(
            (runtime?.active_runs ?? []).filter(
              (r: { status?: string }) => String(r?.status || "") !== "waiting_approval",
            ).length,
          )}
        />
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
        <Row label="Default source" value={runtime?.repository?.configured_default_source ?? "-"} />
        <Row
          label="Configured sources"
          value={
            runtime?.repository?.configured_sources?.length
              ? runtime.repository.configured_sources.map(formatSource).join(", ")
              : "-"
          }
        />
        <Row
          label="Effective sources"
          value={
            runtime?.repository?.effective_sources?.length
              ? runtime.repository.effective_sources.map(formatSource).join(", ")
              : "-"
          }
        />
      </Card>
      <Card title="Permissions">
        <Row label="Mode" value={runtime?.permissions?.mode ?? "-"} />
        <Row label="Sandbox scope" value={String(runtime?.permissions?.sandbox?.scope ?? "-")} />
        <Row label="Approval policy" value={runtime?.permissions?.approval ? "Elevated actions require review" : "-"} />
      </Card>
    </div>
  );
}

function formatBool(value?: boolean): string {
  if (value === undefined) return "-";
  return value ? "Yes" : "No";
}

function formatSource(source: { provider?: string | null; baseUrl?: string | null; tokenConfigured?: boolean; owner?: string }): string {
  const bits = [source.provider || "unknown"];
  if (source.baseUrl) bits.push(source.baseUrl);
  if (source.owner) bits.push(`owner: ${source.owner}`);
  bits.push(source.tokenConfigured ? "token configured" : "no token");
  return bits.join(" · ");
}

function Agents({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <Card title="Agent Orchestration">
      <Row label="Mode" value={runtime?.agent?.orchestration_mode ?? "LangGraph"} />
      <Row label="Planner" value={runtime?.agent?.planner_label ?? "-"} />
      <Row label="Tool calling enabled" value={formatBool(runtime?.agent?.tool_calling_enabled)} />
      <Row label="Tool calling active" value={formatBool(runtime?.agent?.tool_calling_active)} />
      <Row label="Model supports tool calls" value={formatBool(runtime?.agent?.model_supports_tool_calls)} />
      <Row label="Model endpoint configured" value={formatBool(runtime?.agent?.model_endpoint_configured)} />
      <Row label="Write router" value="LangGraph intent and proposal flow" />
    </Card>
  );
}

function ContextPanel({ context }: { context: ContextDebug | null }) {
  const latest = context?.latest_pack;
  return (
    <>
      <Card title="Model Profile">
        <Row label="Model" value={context?.model_profile?.model_name ?? "-"} />
        <Row label="Provider" value={context?.model_profile?.provider ?? "-"} />
        <Row label="Context window" value={String(context?.model_profile?.context_window ?? "-")} />
        <Row label="Output reserve" value={String(context?.model_profile?.max_output_tokens ?? "-")} />
        <Row label="Compression" value={context?.model_profile?.compression_strategy ?? "-"} />
      </Card>
      <Card title="Latest Context Pack">
        {latest ? (
          <>
            <Row label="Kind" value={latest.pack_kind ?? "-"} />
            <Row label="Trigger" value={latest.trigger_node ?? "-"} />
            <Row label="Compression ratio" value={latest.compression_ratio != null ? latest.compression_ratio.toFixed(4) : "-"} />
            <Row label="Input tokens" value={String(latest.estimated_input_tokens ?? "-")} />
            <Row label="Output reserve" value={String(latest.estimated_output_reserve ?? "-")} />
            <Row label="Budget" value={formatBudgetUsage(latest.budget_usage ?? context?.context_pack_report?.budget_usage)} />
            <Row label="Included" value={latest.included_sections?.join(", ") || "-"} />
            <Row label="Excluded" value={latest.excluded_sections?.join(", ") || "-"} />
            <Row label="Warnings" value={latest.warnings?.join(" · ") || "-"} />
          </>
        ) : <div className="debug-placeholder">No context pack reports recorded yet.</div>}
      </Card>
      <Card title="Included Evidence">
        <Row label="Retained files" value={latest?.retained_files?.join(", ") || "-"} />
        <Row label="Omitted files" value={latest?.omitted_files?.map((file) => `${file.path ?? "unknown"} (${file.reason ?? "omitted"})`).join(", ") || "-"} />
        <Row label="Web sources" value={latest?.retained_web_sources?.map((source) => source.url || source.title || source.source || "source").join(", ") || "-"} />
        <Row label="Target candidates" value={formatTargetCandidates(latest?.target_candidate_files ?? context?.edit_target_candidates)} />
        <Row label="Prior candidates" value={formatTargetCandidates(latest?.prior_target_candidates)} />
      </Card>
      <Card title="User Understanding">
        <Row label="Goal" value={context?.user_understanding_context?.normalized_goal ?? "-"} />
        <Row label="Requested outputs" value={context?.user_understanding_context?.requested_outputs?.join(", ") || "-"} />
        <Row label="Likely tools" value={context?.user_understanding_context?.likely_needed_tools?.join(", ") || "-"} />
        <Row label="Capabilities" value={context?.user_understanding_context?.likely_capabilities?.join(", ") || "-"} />
        <Row label="Mentioned files" value={context?.user_understanding_context?.mentioned_files?.join(", ") || "-"} />
        <Row label="Mentioned symbols" value={context?.user_understanding_context?.mentioned_symbols?.join(", ") || "-"} />
        <Row label="Ambiguities" value={context?.user_understanding_context?.ambiguities?.join(" · ") || "-"} />
        <Row label="Edit mode" value={context?.user_understanding_context?.edit_mode ?? "-"} />
      </Card>
      <Card title="Evidence Basis">
        <Row label="Files used" value={context?.evidence_basis?.files?.filter((file) => file.retained !== false).map((file) => file.path).filter(Boolean).join(", ") || "-"} />
        <Row label="Files omitted" value={context?.evidence_basis?.files?.filter((file) => file.retained === false).map((file) => `${file.path ?? "unknown"} (${file.omitted_reason ?? "omitted"})`).join(", ") || "-"} />
        <Row label="Web sources" value={context?.evidence_basis?.web_sources?.map((source) => source.url || source.title || source.source || "source").join(", ") || "-"} />
        <Row label="Validation errors" value={context?.evidence_basis?.validation?.flatMap((item) => item.errors || []).join(" · ") || "-"} />
        <Row label="Active proposal" value={formatActiveProposal(context?.evidence_basis?.active_proposal)} />
        <Row label="Worker reports" value={context?.evidence_basis?.worker_reports?.map((report) => `${report.role ?? "worker"}: ${report.summary ?? ""}`).join(" · ") || "-"} />
        <Row label="Missing evidence" value={context?.evidence_basis?.missing_evidence?.join(" · ") || "-"} />
        <Row label="Uncertainty" value={context?.evidence_basis?.uncertainty?.join(" · ") || "-"} />
      </Card>
      <Card title="Target Selection">
        <Row label="Selected" value={context?.target_selection?.selected_target_files?.join(", ") || context?.evidence_basis?.target_selection?.selected_target_files?.join(", ") || "-"} />
        <Row label="Candidates" value={formatTargetCandidates(context?.target_selection?.candidates ?? context?.evidence_basis?.target_selection?.candidates ?? context?.edit_target_candidates)} />
        <Row label="Prior reused" value={String(context?.target_selection?.prior_evidence_reused ?? context?.evidence_basis?.target_selection?.prior_evidence_reused ?? latest?.prior_evidence_reused ?? false)} />
        <Row label="Fallback attempts" value={String(context?.target_selection?.fallback_attempts ?? context?.evidence_basis?.target_selection?.fallback_attempts ?? "-")} />
        <Row label="Discovery" value={(context?.target_selection?.discovery_queries ?? context?.evidence_basis?.target_selection?.discovery_queries ?? []).join(", ") || "-"} />
        <Row label="Failed searches" value={(context?.target_selection?.failed_search_patterns ?? context?.evidence_basis?.target_selection?.failed_search_patterns ?? []).join(", ") || "-"} />
        <Row label="Blocked reason" value={context?.target_selection?.blocked_reason ?? context?.evidence_basis?.target_selection?.blocked_reason ?? "-"} />
      </Card>
      <Card title="Memory / Carryover">
        <Row label="Carryover" value={formatCarryoverSummary(context?.short_term_memory ?? context?.evidence_basis?.memory_carryover)} />
        <Row label="Thread files" value={context?.evidence_basis?.memory_carryover?.thread_recent_files?.join(", ") || "-"} />
        <Row label="Thread candidates" value={formatTargetCandidates(context?.evidence_basis?.memory_carryover?.thread_target_candidates)} />
        <Row label="Plan" value={context?.evidence_basis?.memory_carryover?.last_implementation_plan?.summary ?? "-"} />
        <Row label="Source" value={context?.evidence_basis?.memory_carryover?.context_source ?? "-"} />
      </Card>
      <Card title="Visible Rationale">
        {context?.visible_rationale_log?.length ? (
          <ul className="debug-list">
            {context.visible_rationale_log.slice(-8).reverse().map((item) => (
              <li className="debug-list-item" key={item.id ?? `${item.timestamp}-${item.node}`}>
                <strong>{item.node ?? "node"}</strong>
                <span>{item.action_type ? ` · ${item.action_type}` : ""}</span>
                <p>{item.summary ?? "-"}</p>
                <small>{formatBasisRefs(item.basis_refs)}{item.safety_note ? ` · ${item.safety_note}` : ""}</small>
              </li>
            ))}
          </ul>
        ) : <div className="debug-placeholder">No visible rationale entries recorded yet.</div>}
      </Card>
    </>
  );
}

function formatActiveProposal(proposal?: { proposal_id?: string | null; status?: string | null; files?: string[] } | null): string {
  if (!proposal || typeof proposal !== "object") return "-";
  const files = proposal.files?.length ? ` · ${proposal.files.join(", ")}` : "";
  return `${proposal.proposal_id ?? "proposal"} (${proposal.status ?? "unknown"})${files}`;
}

function formatBasisRefs(refs?: Array<{ kind?: string; path?: string; url?: string; id?: string; query?: string }>): string {
  if (!refs?.length) return "No source refs";
  return refs
    .map((ref) => ref.path || ref.url || ref.id || ref.query || ref.kind || "ref")
    .filter(Boolean)
    .join(", ");
}

function MemoryPanel({ memory }: { memory: MemoryDebug | null }) {
  const [view, setView] = useState<"table" | "graph">("table");
  const [filters, setFilters] = useState<Record<string, boolean>>({
    memory: true,
    file: true,
    symbol: true,
    run: true,
    skill: true,
    thread: true,
    repository: true,
    proposal: true,
    edit: true,
    command: true,
  });
  const graph = memory?.graph;
  const visibleNodes = graph?.nodes.filter((node) => filters[node.type] ?? true) ?? [];
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = graph?.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)) ?? [];
  return (
    <>
      <div className="debug-toggle-row">
        <button className={`debug-secondary-button${view === "table" ? " debug-button-active" : ""}`} type="button" onClick={() => setView("table")}>Table</button>
        <button className={`debug-secondary-button${view === "graph" ? " debug-button-active" : ""}`} type="button" onClick={() => setView("graph")}>Graph</button>
      </div>
      {view === "table" ? (
      <Card title="Memory Table">
        <table className="debug-table">
          <thead><tr><th>id</th><th>type</th><th>content</th><th>source</th><th>repo</th><th>tags</th><th>created_at</th></tr></thead>
          <tbody>
            {memory?.items.length ? memory.items.map((item) => (
              <tr key={item.id}><td>{item.id}</td><td>{item.type}</td><td>{item.content}</td><td>{item.source}</td><td>{item.repo ?? "-"}</td><td>{item.tags?.join(", ") || "-"}</td><td>{item.created_at}</td></tr>
            )) : <tr><td colSpan={7}>No memory records yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      ) : (
      <Card title="Memory Graph">
        <div className="debug-filter-row">
          {Object.keys(filters).map((key) => (
            <label key={key}>
              <input type="checkbox" checked={filters[key]} onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.checked }))} />
              {key}
            </label>
          ))}
        </div>
        {visibleNodes.length ? <MemoryGraph nodes={visibleNodes} edges={visibleEdges} /> : <div className="debug-placeholder">No graph data yet.</div>}
      </Card>
      )}
    </>
  );
}

const MAX_NODES_PER_CLUSTER = 18;
const MAX_RENDERED_EDGES = 160;
const NODES_PER_RING = 9;

function MemoryGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const width = 960;
  const height = 640;
  const columns = 3;
  const clusterOrder = ["repository", "thread", "run", "file", "symbol", "proposal", "edit", "command", "skill", "memory"];
  const clusters = clusterOrder
    .map((type) => {
      const all = nodes.filter((node) => node.type === type);
      return { type, all, shown: all.slice(0, MAX_NODES_PER_CLUSTER), overflow: Math.max(0, all.length - MAX_NODES_PER_CLUSTER) };
    })
    .filter((cluster) => cluster.all.length);

  const rows = Math.ceil(Math.max(clusters.length, 1) / columns);
  const clusterWidth = width / columns;
  const clusterHeight = height / rows;

  // Lay each cluster's nodes out on concentric rings (small dots) so dense
  // clusters stay legible instead of collapsing into an overlapping hairball.
  const positioned = clusters.flatMap((cluster, clusterIndex) => {
    const centerX = (clusterIndex % columns) * clusterWidth + clusterWidth / 2;
    const centerY = Math.floor(clusterIndex / columns) * clusterHeight + clusterHeight / 2 + 16;
    const baseRadius = Math.min(clusterWidth, clusterHeight) * 0.16;
    return cluster.shown.map((node, nodeIndex) => {
      const ring = Math.floor(nodeIndex / NODES_PER_RING);
      const indexInRing = nodeIndex % NODES_PER_RING;
      const inThisRing = Math.min(NODES_PER_RING, cluster.shown.length - ring * NODES_PER_RING);
      const radius = cluster.shown.length === 1 ? 0 : baseRadius + ring * 22;
      const angle = (Math.PI * 2 * indexInRing) / Math.max(inThisRing, 1) + ring * 0.4;
      return { ...node, cluster: cluster.type, x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius };
    });
  });

  const byId = new Map(positioned.map((node) => [node.id, node]));
  const selected = positioned.find((node) => node.id === selectedNodeId);
  const drawableEdges = edges
    .map((edge, index) => ({ edge, index, source: byId.get(edge.source), target: byId.get(edge.target) }))
    .filter((entry) => entry.source && entry.target);
  const cappedEdges = drawableEdges.slice(0, MAX_RENDERED_EDGES);
  const selectedEdgeCount = selected
    ? edges.filter((edge) => edge.source === selected.id || edge.target === selected.id).length
    : 0;

  return (
    <div className="memory-graph-layout">
      <svg className="memory-graph" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Memory relationship graph">
        {clusters.map((cluster, index) => {
          const x = (index % columns) * clusterWidth + 10;
          const y = Math.floor(index / columns) * clusterHeight + 10;
          return (
            <g key={cluster.type}>
              <rect x={x} y={y} width={clusterWidth - 20} height={clusterHeight - 20} rx={16} className="memory-graph-cluster" />
              <text x={x + 14} y={y + 24} className="memory-graph-cluster-label">
                {clusterLabel(cluster.type)} ({cluster.all.length})
              </text>
              {cluster.overflow ? (
                <text x={x + 14} y={y + 42} className="memory-graph-cluster-more">+{cluster.overflow} more</text>
              ) : null}
            </g>
          );
        })}
        {cappedEdges.map(({ edge, index, source, target }) => {
          const active = Boolean(selected) && (edge.source === selected!.id || edge.target === selected!.id);
          const edgeClass = active
            ? "memory-graph-edge memory-graph-edge-active"
            : `memory-graph-edge${selected ? " memory-graph-edge-dim" : ""}`;
          return (
            <line
              key={`${edge.source}-${edge.target}-${index}`}
              x1={source!.x}
              y1={source!.y}
              x2={target!.x}
              y2={target!.y}
              className={edgeClass}
            />
          );
        })}
        {positioned.map((node) => {
          const isSelected = node.id === selectedNodeId;
          const baseRadius = node.type === "repository" ? 9 : 6;
          return (
            <g
              key={node.id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedNodeId((current) => (current === node.id ? null : node.id))}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedNodeId((current) => (current === node.id ? null : node.id));
                }
              }}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={isSelected ? baseRadius + 3 : baseRadius}
                className={`memory-graph-node memory-graph-node-${node.type}${isSelected ? " memory-graph-node-selected" : ""}`}
              />
              {isSelected ? (
                <text x={node.x} y={node.y - (baseRadius + 8)} textAnchor="middle" className="memory-graph-label">
                  {node.label.slice(0, 28)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <aside className="memory-graph-details">
        {selected ? (
          <>
            <strong>{selected.label}</strong>
            <span>{clusterLabel(selected.type)}</span>
            <code>{selected.id}</code>
            <span>Related edges: {selectedEdgeCount}</span>
          </>
        ) : (
          <>
            <strong>Memory graph</strong>
            <span>{positioned.length} nodes shown · {drawableEdges.length} links</span>
            <span>Click a node to highlight its relationships.</span>
          </>
        )}
      </aside>
    </div>
  );
}

function clusterLabel(type: string): string {
  const labels: Record<string, string> = {
    repository: "Repositories",
    thread: "Threads",
    run: "Runs",
    file: "Files",
    symbol: "Symbols",
    skill: "Skills",
    proposal: "Proposals",
    edit: "Edits",
    command: "Commands",
    memory: "Memories",
  };
  return labels[type] || type;
}

function SkillsPanel({ skills }: { skills: SkillsDebug | null }) {
  return (
    <Card title="Discovered Skills">
      {skills?.skills.length ? skills.skills.map((skill) => (
        <div className="debug-list-item" key={`${skill.source_path}:${skill.name}`}>
          <strong>{skill.name}</strong>
          <span>{skill.scope} · {skill.enabled ? "enabled" : "disabled"}</span>
          <span>{skill.description || "No description"}</span>
          <code>{skill.source_path}</code>
        </div>
      )) : <div className="debug-placeholder">No skills.md files discovered.</div>}
    </Card>
  );
}

type McpServerRow = {
  id: string;
  name: string;
  description?: string;
  transport?: string;
  command?: string;
  args?: string[];
  url?: string;
  runtime?: string;
  runtime_available?: boolean;
  bundled: boolean;
  enabled?: boolean;
  configured?: boolean;
  tool_count?: number;
  env_keys?: string[];
  overlap?: string;
};

function McpPanel() {
  const [status, setStatus] = useState<{ bundled: McpServerRow[]; custom: McpServerRow[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [envInputs, setEnvInputs] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState({ name: "", transport: "stdio", command: "", args: "", url: "" });

  async function refresh() {
    try {
      const res = await fetch("/api/worker/mcp/servers");
      if (res.ok) setStatus(await res.json());
    } catch {
      /* worker offline */
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(id: string, action: "enable" | "disable" | "test", body?: unknown) {
    setBusy(id);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`/api/worker/mcp/servers/${encodeURIComponent(id)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.detail || `${action} failed`);
      setNotice(
        action === "disable"
          ? `${id} disabled.`
          : `${id}: ${payload.tool_count ?? 0} tools ${action === "test" ? "reachable" : "enabled"}${payload.tools ? ` — ${payload.tools.slice(0, 6).map((t: { name?: string }) => t.name).join(", ")}${payload.tools.length > 6 ? "…" : ""}` : ""}`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${action} failed`);
    } finally {
      setBusy(null);
    }
  }

  async function addCustom() {
    setBusy("__custom__");
    setError(null);
    setNotice(null);
    try {
      const body: Record<string, unknown> = { name: custom.name, transport: custom.transport };
      if (custom.transport === "stdio") {
        body.command = custom.command;
        body.args = custom.args.split(/\s+/).filter(Boolean);
      } else {
        body.url = custom.url;
      }
      const res = await fetch("/api/worker/mcp/servers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.detail || "Failed to add the MCP server.");
      setNotice(`${payload.id}: ${payload.tool_count ?? 0} tools enabled.`);
      setCustom({ name: "", transport: "stdio", command: "", args: "", url: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add the MCP server.");
    } finally {
      setBusy(null);
    }
  }

  async function removeCustom(id: string) {
    setBusy(id);
    try {
      await fetch(`/api/worker/mcp/servers/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  function renderRow(row: McpServerRow) {
    const needsEnv = (row.env_keys ?? []).length > 0 && !row.enabled;
    return (
      <div className="debug-list-item" key={row.id}>
        <strong>
          {row.name} {row.enabled ? "· enabled" : row.configured ? "· disabled" : ""}
          {typeof row.tool_count === "number" && row.tool_count > 0 ? ` · ${row.tool_count} tools` : ""}
        </strong>
        {row.description && <span>{row.description}</span>}
        <code>{row.transport === "http" || row.url ? row.url : [row.command, ...(row.args ?? [])].join(" ")}</code>
        {row.overlap && <span style={{ color: "var(--muted)", fontSize: "0.8em" }}>↔ {row.overlap}</span>}
        {row.runtime && row.runtime_available === false && (
          <span style={{ color: "#c58b22" }}>Requires {row.runtime} (not installed on this machine).</span>
        )}
        {needsEnv &&
          (row.env_keys ?? []).map((key) => (
            <input
              key={key}
              className="debug-input"
              placeholder={key}
              value={envInputs[`${row.id}:${key}`] ?? ""}
              onChange={(e) => setEnvInputs((prev) => ({ ...prev, [`${row.id}:${key}`]: e.target.value }))}
            />
          ))}
        <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
          {row.enabled ? (
            <>
              <button type="button" className="debug-secondary-button" disabled={busy !== null} onClick={() => void act(row.id, "disable")}>
                Disable
              </button>
              <button type="button" className="debug-secondary-button" disabled={busy !== null} onClick={() => void act(row.id, "test")}>
                {busy === row.id ? "Testing…" : "Test"}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="debug-secondary-button"
              disabled={busy !== null || row.runtime_available === false}
              onClick={() => {
                const env: Record<string, string> = {};
                for (const key of row.env_keys ?? []) {
                  const value = envInputs[`${row.id}:${key}`];
                  if (value) env[key] = value;
                }
                void act(row.id, "enable", Object.keys(env).length ? { env } : {});
              }}
            >
              {busy === row.id ? "Enabling…" : "Enable"}
            </button>
          )}
          {!row.bundled && (
            <button type="button" className="debug-secondary-button" disabled={busy !== null} onClick={() => void removeCustom(row.id)}>
              Remove
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      <Card title="MCP servers (bundled)">
        <span>Standard coding-agent MCP set. Enabling a server connects to it, discovers its tools, and exposes them to the agent (approval-gated).</span>
        {error && <span style={{ color: "#DB4437" }}>{error}</span>}
        {notice && <span style={{ color: "var(--accent)" }}>{notice}</span>}
        {status ? status.bundled.map(renderRow) : <div className="debug-placeholder">Loading MCP status…</div>}
      </Card>
      <Card title="Custom MCP servers">
        {status?.custom.length ? status.custom.map(renderRow) : <div className="debug-placeholder">No custom servers yet.</div>}
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          <input className="debug-input" placeholder="name (e.g. my-server)" value={custom.name} onChange={(e) => setCustom({ ...custom, name: e.target.value })} />
          <select className="debug-input" value={custom.transport} onChange={(e) => setCustom({ ...custom, transport: e.target.value })}>
            <option value="stdio">stdio (command)</option>
            <option value="http">http / sse (url)</option>
          </select>
          {custom.transport === "stdio" ? (
            <>
              <input className="debug-input" placeholder="command (e.g. npx)" value={custom.command} onChange={(e) => setCustom({ ...custom, command: e.target.value })} />
              <input className="debug-input" placeholder="args (space separated)" value={custom.args} onChange={(e) => setCustom({ ...custom, args: e.target.value })} />
            </>
          ) : (
            <input className="debug-input" placeholder="url (e.g. http://127.0.0.1:8080/mcp)" value={custom.url} onChange={(e) => setCustom({ ...custom, url: e.target.value })} />
          )}
          <button type="button" className="debug-secondary-button" disabled={busy !== null || !custom.name} onClick={() => void addCustom()}>
            {busy === "__custom__" ? "Connecting…" : "Add & discover tools"}
          </button>
        </div>
      </Card>
    </>
  );
}

function IntegrationsPanel({ integrations }: { integrations: IntegrationsDebug | null }) {
  return (
    <Card title="Integration Status">
      {integrations?.integrations.map((integration) => (
        <div className="debug-list-item" key={integration.provider}>
          <strong>{integration.provider}</strong>
          <span>{integration.status} · toolkits: {integration.toolkits_count ?? integration.toolkits?.length ?? 0} · tools: {integration.tools_count}</span>
          {integration.message && <span>{integration.message}</span>}
          {integration.accounts?.length ? (
            <span>Connected accounts: {integration.accounts.map((account) => `${account.toolkit ?? "unknown"}:${account.status ?? "unknown"}`).join(", ")}</span>
          ) : <span>No connected accounts reported.</span>}
          <button className="debug-secondary-button" type="button" onClick={() => window.open("https://docs.composio.dev/docs/authenticating-tools", "_blank", "noopener,noreferrer")}>
            Open setup docs
          </button>
        </div>
      ))}
    </Card>
  );
}

const TOOL_CATEGORY_LABELS: Record<string, string> = {
  read: "Read & search",
  mcp: "MCP (external)",
  edit: "Edit files",
  git: "Git & PRs",
  command: "Run commands",
  web: "Web research",
  context: "Context",
  control: "Control",
};

function ToolsPanel({ tools, catalog }: { tools: ToolsDebug | null; catalog: ToolCatalog | null }) {
  const grouped = (catalog?.tools ?? []).reduce<Record<string, ToolCatalog["tools"]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});
  const order = ["read", "edit", "git", "command", "web", "context", "control"];
  const categories = Object.keys(grouped).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return (
    <>
      <Card title={`Agent tools (built-in)${catalog ? ` — ${catalog.count}` : ""}`}>
        {catalog ? (
          categories.map((cat) => (
            <div key={cat} className="debug-list-item">
              <strong>{TOOL_CATEGORY_LABELS[cat] ?? cat} · {grouped[cat].length}</strong>
              {grouped[cat].map((t) => (
                <div key={t.name} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", margin: "2px 0" }}>
                  <code>{t.name}</code>
                  <span style={{ opacity: 0.6, fontSize: "0.85em" }}>
                    {t.read_only ? "read-only" : "writes"}{t.requires_approval ? " · needs approval" : ""}
                  </span>
                  <span style={{ opacity: 0.75 }}>{t.description}</span>
                </div>
              ))}
            </div>
          ))
        ) : (
          <div className="debug-placeholder">Tool catalog is not loaded yet.</div>
        )}
      </Card>
      <Card title="External CLI tools">
        {tools?.tools.map((tool) => (
          <div className="debug-list-item" key={tool.name}>
            <strong>{tool.name}</strong>
            <span>{tool.installed ? "installed" : "missing"} · {tool.version ?? "no version detected"}</span>
            <span>Auth status: {tool.auth_status ?? "unknown"}</span>
            {tool.path && <code>{tool.path}</code>}
          </div>
        ))}
      </Card>
      <Card title="Tool Permission Layers">
        {tools?.permissions ? Object.entries(tools.permissions).map(([key, value]) => (
          <Row key={key} label={key.replaceAll("_", " ")} value={value} />
        )) : <div className="debug-placeholder">Tool permissions are not loaded yet.</div>}
      </Card>
    </>
  );
}

function RunsPanel({ runtime }: { runtime: RuntimeDebug | null }) {
  return (
    <Card title="Recent Runs">
      {runtime?.recent_runs?.length ? (
        <table className="debug-table">
          <thead><tr><th>run</th><th>time</th><th>repo</th><th>branch</th><th>intent</th><th>status</th><th>latency</th></tr></thead>
          <tbody>
            {runtime.recent_runs.map((run) => (
              <tr key={String(run.id)}>
                <td>{String(run.id ?? "-")}</td>
                <td>{String(run.timestamp ?? "-")}</td>
                <td>{String(run.repo ?? "-")}</td>
                <td>{String(run.branch ?? "-")}</td>
                <td>{String(run.intent ?? "-")}</td>
                <td>{String(run.status ?? "-")}</td>
                <td>{String(run.latency_ms ?? "-")} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <div className="debug-placeholder">No recent runs recorded yet.</div>}
    </Card>
  );
}

const SECRET_SENTINEL = "__stored__";

function ModelSettingsPanel() {
  const [snap, setSnap] = useState<SettingsSnapshot | null>(null);
  const [form, setForm] = useState({ connectionMode: "", provider: "", baseUrl: "", model: "", contextWindow: "", apiKey: "" });
  const [ctxMode, setCtxMode] = useState<"auto" | "manual">("manual");
  const [status, setStatus] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void getSettings().then((s) => {
      setSnap(s);
      setForm({
        connectionMode: s.model.connectionMode,
        provider: s.model.provider,
        baseUrl: s.model.baseUrl,
        model: s.model.model,
        contextWindow: s.model.contextWindow ? String(s.model.contextWindow) : "",
        apiKey: "",
      });
    }).catch((e) => setStatus({ kind: "err", msg: String(e) }));
  }, []);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      const payload: Parameters<typeof updateModelSettings>[0] = {
        connectionMode: form.connectionMode || undefined,
        provider: form.provider,
        baseUrl: form.baseUrl,
        model: form.model,
        contextWindow: ctxMode === "auto" ? (snap?.autoContextWindow ?? undefined) : (form.contextWindow ? Number(form.contextWindow) : undefined),
      };
      if (form.apiKey.trim()) payload.apiKey = form.apiKey.trim();
      const next = await updateModelSettings(payload);
      setSnap(next);
      setForm((f) => ({ ...f, apiKey: "" }));
      setStatus({ kind: "ok", msg: "모델 설정을 저장했습니다." });
    } catch (e) {
      setStatus({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Model connection">
      <FormRow label="Connection mode">
        <select value={form.connectionMode} onChange={(e) => setForm({ ...form, connectionMode: e.target.value })}>
          <option value="local-runtime">Local model runtime</option>
          <option value="remote-api">Remote model API</option>
        </select>
      </FormRow>
      <FormRow label="Provider">
        <input value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} placeholder="ollama / openai / anthropic …" />
      </FormRow>
      <FormRow label="Base URL">
        <input value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} placeholder="http://127.0.0.1:11434/v1" />
      </FormRow>
      <FormRow label="Model">
        <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="qwen3-coder:30b" />
      </FormRow>
      <FormRow label="API key">
        <input type="password" value={form.apiKey} onChange={(e) => setForm({ ...form, apiKey: e.target.value })} placeholder={snap?.model.apiKey === SECRET_SENTINEL ? "설정됨 · 변경 시에만 입력" : "필요 시 입력"} />
      </FormRow>
      <FormRow label="Context window">
        <div className="debug-inline">
          <label><input type="radio" checked={ctxMode === "auto"} onChange={() => setCtxMode("auto")} /> Auto (RAM: {snap?.autoContextWindow ?? "-"})</label>
          <label><input type="radio" checked={ctxMode === "manual"} onChange={() => setCtxMode("manual")} /> Manual</label>
          {ctxMode === "manual" && <input value={form.contextWindow} onChange={(e) => setForm({ ...form, contextWindow: e.target.value })} placeholder="131072" style={{ width: 120 }} />}
        </div>
      </FormRow>
      <div className="debug-form-actions">
        <button className="debug-primary-button" type="button" disabled={saving} onClick={() => void save()}>{saving ? "저장 중…" : "저장"}</button>
        {status && <span className={status.kind === "ok" ? "debug-form-ok" : "debug-form-err"}>{status.msg}</span>}
      </div>
    </Card>
  );
}

function RepositorySettingsPanel() {
  const [snap, setSnap] = useState<SettingsSnapshot | null>(null);
  const [form, setForm] = useState({ provider: "github", baseUrl: "", owner: "", token: "", makeDefault: false });
  const [status, setStatus] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void getSettings().then((s) => {
      setSnap(s);
      const first = s.repositorySources[0];
      if (first) setForm((f) => ({ ...f, provider: first.provider, baseUrl: first.baseUrl || "", owner: first.owner || "" }));
    }).catch((e) => setStatus({ kind: "err", msg: String(e) }));
  }, []);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      const payload: Parameters<typeof updateRepositorySettings>[0] = {
        provider: form.provider,
        baseUrl: form.baseUrl || undefined,
        owner: form.owner || undefined,
        makeDefault: form.makeDefault,
      };
      if (form.token.trim()) payload.token = form.token.trim();
      const next = await updateRepositorySettings(payload);
      setSnap(next);
      setForm((f) => ({ ...f, token: "" }));
      setStatus({ kind: "ok", msg: "저장소 설정을 저장했습니다." });
    } catch (e) {
      setStatus({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  const existing = snap?.repositorySources.find((s) => s.provider === form.provider);
  return (
    <Card title="Repository source">
      <FormRow label="Provider">
        <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
          <option value="github">GitHub</option>
          <option value="gitlab">GitLab</option>
          <option value="local">Local</option>
        </select>
      </FormRow>
      {form.provider !== "local" && (
        <>
          <FormRow label="Base URL">
            <input value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} placeholder={form.provider === "github" ? "https://github.com" : "https://gitlab.com"} />
          </FormRow>
          <FormRow label="Owner / org (선택)">
            <input value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} placeholder="jungin-kim" />
          </FormRow>
          <FormRow label="Token">
            <input type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} placeholder={existing?.token === SECRET_SENTINEL ? "설정됨 · 변경 시에만 입력" : "토큰 입력"} />
          </FormRow>
        </>
      )}
      <FormRow label="기본 소스로 지정">
        <input type="checkbox" checked={form.makeDefault} onChange={(e) => setForm({ ...form, makeDefault: e.target.checked })} />
      </FormRow>
      <div className="debug-form-actions">
        <button className="debug-primary-button" type="button" disabled={saving} onClick={() => void save()}>{saving ? "저장 중…" : "저장"}</button>
        {status && <span className={status.kind === "ok" ? "debug-form-ok" : "debug-form-err"}>{status.msg}</span>}
      </div>
    </Card>
  );
}

function PermissionsSettingsPanel() {
  const [mode, setMode] = useState<string>("");
  const [status, setStatus] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const modes: Array<{ value: PermissionMode; label: string; desc: string }> = [
    { value: "default", label: "Default", desc: "모든 변경을 승인 후 적용" },
    { value: "accept_edits", label: "Accept edits", desc: "검증된 편집은 자동 적용, 명령은 승인" },
    { value: "auto_readonly", label: "Read-only", desc: "읽기/검색만 허용, 쓰기 차단" },
    { value: "full_access", label: "Full access", desc: "로컬 편집·명령 자동, 원격 push·삭제만 승인" },
  ];
  useEffect(() => {
    void getPermissionMode().then((p) => setMode(p.mode)).catch((e) => setStatus({ kind: "err", msg: String(e) }));
  }, []);
  async function choose(next: PermissionMode) {
    setStatus(null);
    try {
      const res = await updatePermissionMode(next);
      setMode(res.mode);
      setStatus({ kind: "ok", msg: "권한 모드를 변경했습니다." });
    } catch (e) {
      setStatus({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  }
  return (
    <Card title="Permission mode">
      {modes.map((m) => (
        <button key={m.value} type="button" className={`debug-mode-option${mode === m.value ? " debug-mode-active" : ""}`} onClick={() => void choose(m.value)}>
          <strong>{m.label}</strong>
          <span>{m.desc}</span>
        </button>
      ))}
      {status && <div className={status.kind === "ok" ? "debug-form-ok" : "debug-form-err"} style={{ marginTop: 10 }}>{status.msg}</div>}
    </Card>
  );
}

function LogsPanel() {
  const [target, setTarget] = useState<"worker" | "web" | "ollama">("worker");
  const [tail, setTail] = useState<LogTail | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      setTail(await getLogs(target, 400));
    } catch {
      setTail(null);
    } finally {
      setLoading(false);
    }
  }, [target]);
  useEffect(() => { void refresh(); }, [refresh]);
  return (
    <Card title="Logs">
      <div className="debug-inline" style={{ marginBottom: 10 }}>
        {(["worker", "web", "ollama"] as const).map((t) => (
          <button key={t} type="button" className={`debug-tab${target === t ? " debug-tab-active" : ""}`} onClick={() => setTarget(t)}>{t}</button>
        ))}
        <button type="button" className="debug-secondary-button" onClick={() => void refresh()}>{loading ? "불러오는 중…" : "새로고침"}</button>
      </div>
      {tail?.path && <div className="debug-row"><span>Path</span><strong style={{ fontWeight: 400, fontSize: "0.78rem" }}>{tail.path}</strong></div>}
      <pre className="debug-log-view">{tail && tail.lines.length ? tail.lines.join("\n") : (tail && !tail.exists ? "(로그 파일이 아직 없습니다)" : "(비어 있음)")}</pre>
    </Card>
  );
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="debug-form-row"><label>{label}</label><div className="debug-form-field">{children}</div></div>;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="debug-card"><h2>{title}</h2>{children}</section>;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="debug-row"><span>{label}</span><strong>{value}</strong></div>;
}
