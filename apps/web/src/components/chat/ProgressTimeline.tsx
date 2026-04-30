"use client";

import { useEffect, useRef, useState } from "react";

export type ProgressStep = {
  node: string;
  phase?: string;
  message: string;
  status?: string;
  elapsedMs?: number;
};

type Props = {
  steps: ProgressStep[];
  done: boolean;
};

const NODE_ICONS: Record<string, string> = {
  load_context: "📂",
  classify_intent: "🔍",
  resolve_target_files: "🎯",
  generate_change_plan: "📝",
  generate_patch: "⚡",
  validate_patch: "✅",
  return_proposal: "📋",
  answer_read_only: "💬",
  ask_clarification: "❓",
  recommend_change_targets: "📌",
  decompose_and_execute: "🔀",
  plan_step: "▶",
  run_local_tool_request: "🛠",
  run_local_command_request: "⚙️",
  permission_required: "🔒",
  proposal_error: "⚠️",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

export function ProgressTimeline({ steps, done }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  // Live seconds counter for the currently-running last step
  const [liveSec, setLiveSec] = useState(0);
  const lastStepCountRef = useRef(0);
  const lastStepStartRef = useRef(Date.now());

  // Reset live timer when a new step arrives
  useEffect(() => {
    if (steps.length > lastStepCountRef.current) {
      lastStepStartRef.current = Date.now();
      lastStepCountRef.current = steps.length;
      setLiveSec(0);
    }
  }, [steps.length]);

  // Tick live timer while running
  useEffect(() => {
    if (done) return;
    const timer = setInterval(() => {
      setLiveSec(Math.floor((Date.now() - lastStepStartRef.current) / 1000));
    }, 500);
    return () => clearInterval(timer);
  }, [done]);

  // Auto-collapse after run completes (with a small delay so user sees the final state)
  useEffect(() => {
    if (!done) return;
    const timeout = setTimeout(() => setCollapsed(true), 2800);
    return () => clearTimeout(timeout);
  }, [done]);

  if (steps.length === 0) return null;

  const totalMs = steps[steps.length - 1]?.elapsedMs;

  if (done && collapsed) {
    return (
      <button
        type="button"
        className="progress-timeline-summary"
        onClick={() => setCollapsed(false)}
        title="Show steps"
      >
        <span className="progress-timeline-summary-icon">⏱</span>
        <span>Worked for {totalMs !== undefined ? formatDuration(totalMs) : "…"}</span>
        <span className="progress-timeline-expand">▸</span>
      </button>
    );
  }

  return (
    <div className="progress-timeline">
      {done && (
        <button
          type="button"
          className="progress-timeline-header"
          onClick={() => setCollapsed(true)}
          title="Collapse"
        >
          <span>
            {totalMs !== undefined ? `Worked for ${formatDuration(totalMs)}` : "Completed"}
          </span>
          <span className="progress-timeline-collapse">▾ hide</span>
        </button>
      )}
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const isActive = isLast && !done;
        // Per-step duration: delta from the previous step's elapsed time
        const prevMs = steps[i - 1]?.elapsedMs ?? 0;
        const stepMs =
          step.elapsedMs !== undefined ? step.elapsedMs - prevMs : undefined;

        return (
          <div
            key={`${step.node}-${i}`}
            className={`progress-step${isActive ? " progress-step-active" : ""}`}
          >
            <span className="progress-step-icon">{NODE_ICONS[step.node] ?? "▸"}</span>
            <span className="progress-step-content">
              <span className="progress-step-phase">{step.phase || step.node}</span>
              <span>{step.message}</span>
            </span>
            {isActive ? (
              <span className="progress-step-time progress-step-live">{liveSec}s…</span>
            ) : stepMs !== undefined ? (
              <span className="progress-step-time">{formatDuration(stepMs)}</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
