"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

type Snapshot = {
  model_name: string;
  provider: string;
  context_window: number;
  max_output_tokens: number;
  components: { system_prompt: number; system_tools: number; mcp_tools: number; skills: number };
  deferred: { system_tools: number; mcp_tools: number };
};

type Segment = { key: string; label: string; tokens: number; color: string };

const COLORS = {
  messages: "#4C7EF3",
  system_tools: "#6E9BF5",
  mcp_tools: "#8FB4F7",
  system_prompt: "#5B8DEF",
  skills: "#A9C6FA",
  free: "var(--border-strong, #3a3f4b)",
};

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function usageColor(pct: number): string {
  return pct >= 90 ? "#DB4437" : pct >= 75 ? "#F4B400" : "#4C7EF3";
}

/** Small donut gauge showing % of the context window used. */
function Donut({ pct }: { pct: number }) {
  const r = 12;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.min(100, pct) / 100);
  const color = usageColor(pct);
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden>
      <circle cx="17" cy="17" r={r} fill="none" stroke="var(--border-strong, #3a3f4b)" strokeWidth="3.5" />
      <circle
        cx="17"
        cy="17"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 17 17)"
      />
      <text x="17" y="17" textAnchor="middle" dominantBaseline="central" fontSize="9" fontWeight="700" fill="currentColor">
        {pct}
      </text>
    </svg>
  );
}

/**
 * Per-chat context-window usage (Claude Code / Codex style). Docked as a small
 * donut in the bottom-right of the chat area; click to pop the breakdown up.
 */
export function ContextWindow({ messageTokens }: { messageTokens: number }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [open, setOpen] = useState(false);
  const dockRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/worker/context/window");
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
  }, []);

  // Close the popover on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (dockRef.current && !dockRef.current.contains(e.target as Node)) setOpen(false);
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

  const window = Math.max(1, snap.context_window);
  const cmp = snap.components;
  const used = messageTokens + cmp.system_tools + cmp.mcp_tools + cmp.system_prompt + cmp.skills;
  const free = Math.max(0, window - used);
  const pct = Math.min(100, Math.round((used / window) * 100));

  const segments: Segment[] = [
    { key: "messages", label: "Messages", tokens: messageTokens, color: COLORS.messages },
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
    <div className="context-window-dock" ref={dockRef}>
      {open && (
        <div className="context-window-pop" role="dialog" aria-label="Context window usage">
          <div className="context-window-pop-head">
            <span style={{ fontWeight: 600 }}>Context window</span>
            <span style={{ fontVariantNumeric: "tabular-nums", color: usageColor(pct) }}>
              {fmt(used)} / {fmt(window)} ({pct}%)
            </span>
          </div>
          <div className="context-window-bar" title={`${used} of ${window} tokens`}>
            {segments.map((s) => (s.tokens > 0 ? <span key={s.key} style={{ width: `${(s.tokens / window) * 100}%`, background: s.color }} /> : null))}
          </div>
          <ul className="context-window-list">
            {segments.map((s) => (
              <li key={s.key} style={{ ...rowStyle, opacity: s.key === "free" ? 0.75 : 1 }}>
                <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
                <span>{s.label}</span>
                <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--muted)" }}>{fmt(s.tokens)}</span>
                <span style={{ fontVariantNumeric: "tabular-nums", width: 46, textAlign: "right", color: "var(--muted)" }}>
                  {((s.tokens / window) * 100).toFixed(1)}%
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
            {snap.model_name} · window {fmt(window)} · reserve {fmt(snap.max_output_tokens)} out
          </div>
        </div>
      )}

      <button
        type="button"
        className="context-window-fab"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={`Context window: ${fmt(used)} / ${fmt(window)} (${pct}%)`}
      >
        <Donut pct={pct} />
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
