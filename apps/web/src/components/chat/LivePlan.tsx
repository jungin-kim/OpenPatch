"use client";

import type { CSSProperties } from "react";
import type { LivePlanItem } from "./run-event-state";

const STATUS_ICON: Record<string, string> = {
  completed: "✓",
  running: "◐",
  failed: "✗",
  blocked: "⚠",
  pending: "○",
};

const STATUS_COLOR: Record<string, string> = {
  completed: "#0F9D58",
  running: "#3B82F6",
  failed: "#DB4437",
  blocked: "#F4B400",
  pending: "currentColor",
};

/**
 * Live plan / todo checklist shown while the agent works. Driven by the
 * structured `aggregate.plan` streamed on the `langgraph-plan` run event.
 */
export function LivePlan({ items }: { items: LivePlanItem[] }) {
  if (!items.length) return null;
  const done = items.filter((item) => item.status === "completed" || item.status === "failed").length;

  const container: CSSProperties = {
    border: "1px solid color-mix(in srgb, currentColor 15%, transparent)",
    borderRadius: 10,
    padding: "10px 12px",
    margin: "8px 0",
    fontSize: 13,
    background: "color-mix(in srgb, currentColor 4%, transparent)",
  };
  const header: CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
    fontWeight: 600,
    opacity: 0.85,
  };

  return (
    <div style={container} aria-label="Agent plan" data-testid="live-plan">
      <div style={header}>
        <span>Plan</span>
        <span style={{ opacity: 0.7, fontVariantNumeric: "tabular-nums" }}>
          {done}/{items.length}
        </span>
      </div>
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        {items.map((item) => {
          const running = item.status === "running";
          return (
            <li
              key={item.id}
              title={item.goal || item.title}
              style={{
                display: "flex",
                gap: 8,
                alignItems: "baseline",
                opacity: item.status === "pending" ? 0.6 : 1,
              }}
            >
              <span
                aria-hidden
                style={{ color: STATUS_COLOR[item.status] || "currentColor", width: 14, flexShrink: 0 }}
              >
                {STATUS_ICON[item.status] || STATUS_ICON.pending}
              </span>
              <span
                style={{
                  textDecoration: item.status === "completed" ? "line-through" : "none",
                  fontWeight: running ? 600 : 400,
                }}
              >
                {item.title}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
