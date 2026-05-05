"use client";

import { useEffect, useState } from "react";

type HealthData = {
  status: string;
  service: string;
  repo_base_dir: string;
  configured_git_provider?: string | null;
  configured_model_connection_mode?: string | null;
  configured_model_provider?: string | null;
  configured_model_name?: string | null;
  write_mode?: string;
  recent_projects?: string[];
};

function StatusBadge({ value, ok }: { value: string; ok: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: 12,
        fontWeight: 600,
        background: ok ? "var(--color-success-bg, #d1fae5)" : "var(--color-error-bg, #fee2e2)",
        color: ok ? "var(--color-success-text, #065f46)" : "var(--color-error-text, #991b1b)",
      }}
    >
      {value}
    </span>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "var(--color-surface, #fff)",
        border: "1px solid var(--color-border, #e5e7eb)",
        borderRadius: 8,
        padding: "16px 20px",
        marginBottom: 16,
      }}
    >
      <h2
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-text-secondary, #6b7280)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          margin: "0 0 12px",
        }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "6px 0",
        borderBottom: "1px solid var(--color-border, #f3f4f6)",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--color-text-secondary, #6b7280)" }}>{label}</span>
      <span style={{ fontSize: 13, fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

function PlaceholderSection({ title, description }: { title: string; description: string }) {
  return (
    <Card title={title}>
      <div
        style={{
          padding: "20px 0",
          textAlign: "center",
          color: "var(--color-text-secondary, #9ca3af)",
          fontSize: 13,
        }}
      >
        <div style={{ fontSize: 24, marginBottom: 8 }}>⋯</div>
        <div>{description}</div>
        <div
          style={{
            marginTop: 6,
            fontSize: 11,
            background: "var(--color-surface-alt, #f9fafb)",
            border: "1px dashed var(--color-border, #e5e7eb)",
            borderRadius: 4,
            padding: "4px 8px",
            display: "inline-block",
          }}
        >
          Placeholder — not yet implemented
        </div>
      </div>
    </Card>
  );
}

export default function DebugPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/worker/health", { cache: "no-store" });
        if (!res.ok) {
          setError(`Worker returned ${res.status}`);
          return;
        }
        const data = (await res.json()) as HealthData;
        setHealth(data);
      } catch {
        setError("Unable to reach the local worker. Make sure it is running.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const workerOk = health?.status === "ok";
  const hasModel = Boolean(health?.configured_model_name);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--color-bg, #f9fafb)",
        padding: "32px 24px",
        fontFamily: "var(--font-sans, system-ui, sans-serif)",
      }}
    >
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <a
            href="/app"
            style={{
              fontSize: 13,
              color: "var(--color-text-secondary, #6b7280)",
              textDecoration: "none",
            }}
          >
            ← Back to workspace
          </a>
          <span style={{ color: "var(--color-border, #d1d5db)" }}>|</span>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Debug Dashboard</h1>
          <StatusBadge value={loading ? "Loading…" : workerOk ? "Worker online" : "Worker offline"} ok={!loading && workerOk} />
        </div>

        {error && (
          <div
            style={{
              background: "var(--color-error-bg, #fee2e2)",
              color: "var(--color-error-text, #991b1b)",
              borderRadius: 6,
              padding: "10px 14px",
              marginBottom: 16,
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        {/* Worker Status */}
        <Card title="Worker Status">
          <Row label="Status" value={<StatusBadge value={health?.status ?? "—"} ok={workerOk} />} />
          <Row label="Service" value={health?.service ?? "—"} />
          <Row label="Repo base dir" value={health?.repo_base_dir ?? "—"} />
          <Row label="Write mode" value={health?.write_mode ?? "—"} />
        </Card>

        {/* Model */}
        <Card title="Model Configuration">
          <Row label="Provider" value={health?.configured_model_provider ?? "—"} />
          <Row label="Connection mode" value={health?.configured_model_connection_mode ?? "—"} />
          <Row label="Model name" value={<StatusBadge value={health?.configured_model_name ?? "not configured"} ok={hasModel} />} />
        </Card>

        {/* Repository */}
        <Card title="Repository Source">
          <Row label="Git provider" value={health?.configured_git_provider ?? "—"} />
          <Row
            label="Recent projects"
            value={
              health?.recent_projects?.length
                ? `${health.recent_projects.length} project(s)`
                : "none"
            }
          />
          {health?.recent_projects?.slice(0, 3).map((p) => (
            <Row key={p} label="" value={<span style={{ fontFamily: "monospace", fontSize: 11 }}>{p}</span>} />
          ))}
        </Card>

        {/* Placeholders for future sections */}
        <PlaceholderSection
          title="Agent Runs"
          description="Timeline of recent agent executions, proposals, and applied changes."
        />

        <PlaceholderSection
          title="Memory"
          description="Persistent memory store — table and graph views. Requires memory backend."
        />

        <PlaceholderSection
          title="Skills"
          description="Installed skills from skills.md registry — name, path, enabled state."
        />

        <PlaceholderSection
          title="Integrations"
          description="Connected integrations (Composio, GitHub Apps, etc.) — status and tools count."
        />

        <div style={{ textAlign: "center", marginTop: 24, fontSize: 12, color: "var(--color-text-secondary, #9ca3af)" }}>
          RepoOperator Debug Dashboard — placeholders are planned features, not active yet.
        </div>
      </div>
    </div>
  );
}
