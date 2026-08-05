"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

type Snapshot = {
  model_name: string;
  provider: string;
  context_window: number;
  max_output_tokens: number;
  components: { system_prompt: number; system_tools: number; mcp_tools: number; skills: number; repo_context?: number };
  deferred: { system_tools: number; mcp_tools: number };
  repo_context_actual?: boolean;
};

type Segment = { key: string; label: string; tokens: number; color: string };

const COLORS = {
  messages: "#4F46E5",
  repo_context: "#7C3AED",
  system_tools: "#6D5EFC",
  mcp_tools: "#8B5CF6",
  system_prompt: "#5B4FF0",
  skills: "#A78BFA",
  free: "var(--border-strong, #3a3f4b)",
};

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function usageColor(pct: number): string {
  return pct >= 90 ? "#DB4437" : pct >= 75 ? "#F4B400" : "#5B4FF0";
}

/**
 * Per-chat context-window usage (Claude Code / Codex style). Rendered as a slim
 * inline chip (mini bar + %) meant to sit left of the send button; click to pop
 * the full breakdown upward.
 */
export function ContextWindow({ messageTokens, threadId }: { messageTokens: number; threadId?: string | null }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const qs = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
        const res = await fetch(`/api/worker/context/window${qs}`);
        if (!res.ok) return;
        const data = (await res.json()) as Snapshot;
        if (!cancelled) setSnap(data);
      } catch {
        /* worker offline — hide */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, messageTokens]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!snap) return null;

  const windowSize = Math.max(1, snap.context_window);
  const cmp = snap.components;
  const repoContext = cmp.repo_context ?? 0;
  const used = messageTokens + repoContext + cmp.system_tools + cmp.mcp_tools + cmp.system_prompt + cmp.skills;
  const free = Math.max(0, windowSize - used);
  const pct = Math.min(100, Math.round((used / windowSize) * 100));

  const segments: Segment[] = [
    { key: "messages", label: "Messages", tokens: messageTokens, color: COLORS.messages },
    { key: "repo_context", label: snap.repo_context_actual ? "Repo context" : "Repo context (max)", tokens: repoContext, color: COLORS.repo_context },
    { key: "system_tools", label: "System tools", tokens: cmp.system_tools, color: COLORS.system_tools },
    { key: "mcp_tools", label: "MCP tools", tokens: cmp.mcp_tools, color: COLORS.mcp_tools },
    { key: "system_prompt", label: "System prompt", tokens: cmp.system_prompt, color: COLORS.system_prompt },
    { key: "skills", label: "Skills", tokens: cmp.skills, color: COLORS.skills },
    { key: "free", label: "Free space", tokens: free, color: COLORS.free },
  ];
  const deferred = [
    { key: "mcp_deferred", label: "MCP tools (deferred)", tokens: snap.deferred.mcp_tools },
    { key: "sys_deferred", label: "System tools (deferred)", tokens: snap.deferred.system_tools },
  ].filter((s) => s.tokens > 0);

  const rowStyle: CSSProperties = { display: "grid", gridTemplateColumns: "14px 1fr auto auto", alignItems: "center", gap: 8 };

  return (
    <div className="context-window-inline" ref={rootRef}>
      {open && (
        <div className="context-window-pop" role="dialog" aria-label="Context window usage">
          <div className="context-window-pop-head">
            <span style={{ fontWeight: 600 }}>Context window</span>
            <span style={{ fontVariantNumeric: "tabular-nums", color: usageColor(pct) }}>
              {fmt(used)} / {fmt(windowSize)} ({pct}%)
            </span>
          </div>
          <div className="context-window-bar" title={`${used} of ${windowSize} tokens`}>
            {segments.map((s) => (s.tokens > 0 ? <span key={s.key} style={{ width: `${(s.tokens / windowSize) * 100}%`, background: s.color }} /> : null))}
          </div>
          <ul className="context-window-list">
            {segments.map((s) => (
              <li key={s.key} style={{ ...rowStyle, opacity: s.key === "free" ? 0.75 : 1 }}>
                <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
                <span>{s.label}</span>
                <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--muted)" }}>{fmt(s.tokens)}</span>
                <span style={{ fontVariantNumeric: "tabular-nums", width: 46, textAlign: "right", color: "var(--muted)" }}>
                  {((s.tokens / windowSize) * 100).toFixed(1)}%
                </span>
              </li>
            ))}
            {deferred.map((s) => (
              <li key={s.key} style={{ ...rowStyle, opacity: 0.5 }}>
                <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, border: "1px solid var(--border)" }} />
                <span>{s.label}</span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(s.tokens)}</span>
                <span style={{ width: 46, textAlign: "right" }}>—</span>
              </li>
            ))}
          </ul>
          <div className="context-window-foot">
            {snap.model_name} · window {fmt(windowSize)} · reserve {fmt(snap.max_output_tokens)} out
          </div>
        </div>
      )}

      <button
        type="button"
        className="context-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={`Context window: ${fmt(used)} / ${fmt(windowSize)} (${pct}%)`}
      >
        <span className="context-trigger-track">
          <span className="context-trigger-fill" style={{ width: `${pct}%`, background: usageColor(pct) }} />
        </span>
        <span className="context-trigger-pct">{pct}%</span>
      </button>
    </div>
  );
}

/** Rough token estimate (~4 chars/token) for a chat's own messages. */
export function estimateMessageTokens(messages: { content?: string }[]): number {
  let chars = 0;
  for (const m of messages) chars += (m.content || "").length;
  return Math.round(chars / 4);
}
