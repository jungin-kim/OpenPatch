"use client";

import { useEffect, useState, type CSSProperties } from "react";

type Snapshot = {
  model_name: string;
  provider: string;
  context_window: number;
  max_output_tokens: number;
  components: { system_prompt: number; system_tools: number; mcp_tools: number; skills: number };
  deferred: { system_tools: number; mcp_tools: number };
};

type Segment = { key: string; label: string; tokens: number; color: string; deferred?: boolean };

const COLORS = {
  messages: "#4C7EF3",
  system_tools: "#6E9BF5",
  mcp_tools: "#8FB4F7",
  system_prompt: "#5B8DEF",
  skills: "#A9C6FA",
  free: "#3a3f4b",
};

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/**
 * Per-chat context-window usage (Claude Code / Codex style). The window size
 * comes from the served model; message tokens are for the active chat only.
 */
export function ContextWindow({ messageTokens }: { messageTokens: number }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/worker/context/window");
        if (!res.ok) return;
        const data = (await res.json()) as Snapshot;
        if (!cancelled) setSnap(data);
      } catch {
        /* worker offline — hide the widget */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!snap) return null;

  const window = Math.max(1, snap.context_window);
  const c = snap.components;
  const used = messageTokens + c.system_tools + c.mcp_tools + c.system_prompt + c.skills;
  const free = Math.max(0, window - used);
  const pct = Math.min(100, Math.round((used / window) * 100));

  const segments: Segment[] = [
    { key: "messages", label: "Messages", tokens: messageTokens, color: COLORS.messages },
    { key: "system_tools", label: "System tools", tokens: c.system_tools, color: COLORS.system_tools },
    { key: "mcp_tools", label: "MCP tools", tokens: c.mcp_tools, color: COLORS.mcp_tools },
    { key: "system_prompt", label: "System prompt", tokens: c.system_prompt, color: COLORS.system_prompt },
    { key: "skills", label: "Skills", tokens: c.skills, color: COLORS.skills },
    { key: "free", label: "Free space", tokens: free, color: COLORS.free },
  ];
  const deferred: Segment[] = [
    { key: "mcp_deferred", label: "MCP tools (deferred)", tokens: snap.deferred.mcp_tools, color: COLORS.free, deferred: true },
    { key: "sys_deferred", label: "System tools (deferred)", tokens: snap.deferred.system_tools, color: COLORS.free, deferred: true },
  ].filter((s) => s.tokens > 0);

  const bar: CSSProperties = { display: "flex", height: 6, borderRadius: 4, overflow: "hidden", background: COLORS.free, marginTop: 6 };
  const usageColor = pct >= 90 ? "#DB4437" : pct >= 75 ? "#F4B400" : "var(--muted)";

  return (
    <div className="context-window" style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "8px 12px", margin: "8px 0", fontSize: 12.5 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, gap: 8 }}
      >
        <span style={{ fontWeight: 600, opacity: 0.9 }}>Context window</span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontVariantNumeric: "tabular-nums", color: usageColor }}>
            {fmt(used)} / {fmt(window)} ({pct}%)
          </span>
          <span aria-hidden style={{ opacity: 0.6 }}>{open ? "▴" : "▾"}</span>
        </span>
      </button>

      <div style={bar} title={`${used} of ${window} tokens`}>
        {segments.map((s) =>
          s.tokens > 0 ? <span key={s.key} style={{ width: `${(s.tokens / window) * 100}%`, background: s.color }} /> : null,
        )}
      </div>

      {open && (
        <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 5 }}>
          {segments.map((s) => (
            <li key={s.key} style={{ display: "grid", gridTemplateColumns: "14px 1fr auto auto", alignItems: "center", gap: 8, opacity: s.key === "free" ? 0.75 : 1 }}>
              <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
              <span>{s.label}</span>
              <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--muted)" }}>{fmt(s.tokens)}</span>
              <span style={{ fontVariantNumeric: "tabular-nums", width: 44, textAlign: "right", color: "var(--muted)" }}>
                {((s.tokens / window) * 100).toFixed(1)}%
              </span>
            </li>
          ))}
          {deferred.map((s) => (
            <li key={s.key} style={{ display: "grid", gridTemplateColumns: "14px 1fr auto auto", alignItems: "center", gap: 8, opacity: 0.5 }}>
              <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, border: "1px solid var(--border)" }} />
              <span>{s.label}</span>
              <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(s.tokens)}</span>
              <span style={{ width: 44, textAlign: "right" }}>—</span>
            </li>
          ))}
          <li style={{ marginTop: 4, color: "var(--muted)", fontSize: 11.5 }}>
            {snap.model_name} · window {fmt(window)} · reserve {fmt(snap.max_output_tokens)} out
          </li>
        </ul>
      )}
    </div>
  );
}

/** Rough token estimate (~4 chars/token) for a chat's own messages. */
export function estimateMessageTokens(messages: { content?: string }[]): number {
  let chars = 0;
  for (const m of messages) chars += (m.content || "").length;
  return Math.round(chars / 4);
}
