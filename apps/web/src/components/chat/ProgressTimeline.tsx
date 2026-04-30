"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type ProgressStep = {
  id?: string;
  runId?: string;
  phase?: string;
  label?: string;
  detail?: string;
  message?: string;
  status?: string;
  startedAt?: string | null;
  endedAt?: string | null;
  durationMs?: number | null;
  elapsedMs?: number | null;
  files?: string[];
  command?: string | null;
  proposalId?: string | null;
};

type Props = {
  steps: ProgressStep[];
  done: boolean;
};

const PHASE_ORDER = [
  "Thinking",
  "Repository",
  "Searching",
  "Reading files",
  "Planning",
  "Editing",
  "Commands",
  "Applying changes",
  "Finished",
];

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

function statusLabel(status?: string): string {
  if (status === "waiting") return "waiting";
  if (status === "failed") return "failed";
  if (status === "completed") return "done";
  if (status === "running") return "running";
  return status || "done";
}

export function ProgressTimeline({ steps, done }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [liveSec, setLiveSec] = useState(0);
  const lastStepCountRef = useRef(0);
  const lastStepStartRef = useRef(Date.now());

  useEffect(() => {
    if (steps.length > lastStepCountRef.current) {
      lastStepStartRef.current = Date.now();
      lastStepCountRef.current = steps.length;
      setLiveSec(0);
    }
  }, [steps.length]);

  useEffect(() => {
    if (done) return;
    const timer = setInterval(() => {
      setLiveSec((current) => current + 1);
    }, 500);
    return () => clearInterval(timer);
  }, [done]);

  useEffect(() => {
    if (!done) return;
    const timeout = setTimeout(() => setCollapsed(true), 2400);
    return () => clearTimeout(timeout);
  }, [done]);

  const grouped = useMemo(() => {
    const buckets = new Map<string, ProgressStep[]>();
    for (const step of steps) {
      const phase = step.phase || "Thinking";
      buckets.set(phase, [...(buckets.get(phase) || []), step]);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => {
      const ai = PHASE_ORDER.indexOf(a);
      const bi = PHASE_ORDER.indexOf(b);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  }, [steps]);

  if (steps.length === 0) return null;

  const totalMs = steps[steps.length - 1]?.elapsedMs ?? steps[steps.length - 1]?.durationMs ?? undefined;

  if (done && collapsed) {
    return (
      <button
        type="button"
        className="progress-timeline-summary"
        onClick={() => setCollapsed(false)}
        title="Show agent activity"
      >
        <span>Worked for {totalMs !== undefined ? formatDuration(totalMs) : "a moment"}</span>
        <span className="progress-timeline-expand">Show work log</span>
      </button>
    );
  }

  return (
    <section className="progress-timeline" aria-label="Agent activity">
      <button
        type="button"
        className="progress-timeline-header"
        onClick={() => done && setCollapsed(true)}
        disabled={!done}
        title={done ? "Collapse work log" : "Agent activity"}
      >
        <span>{done && totalMs !== undefined ? `Worked for ${formatDuration(totalMs)}` : "Agent Activity"}</span>
        {done ? <span className="progress-timeline-collapse">hide</span> : null}
      </button>
      <div className="progress-groups">
        {grouped.map(([phase, phaseSteps]) => (
          <div key={phase} className="progress-group">
            <div className="progress-group-title">{phase}</div>
            <div className="progress-group-steps">
              {phaseSteps.map((step, i) => {
                const isLast = steps[steps.length - 1] === step;
                const isActive = isLast && !done && step.status !== "completed";
                const startedMs = step.startedAt ? Date.parse(step.startedAt) : Number.NaN;
                const endedMs = step.endedAt ? Date.parse(step.endedAt) : Number.NaN;
                const liveDurationMs =
                  step.status === "running" && Number.isFinite(startedMs)
                    ? Date.now() - startedMs
                    : Number.isFinite(startedMs) && Number.isFinite(endedMs)
                      ? endedMs - startedMs
                      : null;
                const time =
                  step.durationMs !== undefined && step.durationMs !== null
                    ? formatDuration(step.durationMs)
                    : liveDurationMs !== null
                      ? formatDuration(Math.max(0, liveDurationMs))
                    : step.elapsedMs !== undefined && step.elapsedMs !== null
                      ? formatDuration(step.elapsedMs)
                      : isActive
                        ? `${liveSec}s`
                        : null;

                return (
                  <div
                    key={step.id || `${phase}-${i}-${step.label || step.message}`}
                    className={`progress-step progress-step-${step.status || "completed"}${isActive ? " progress-step-active" : ""}`}
                  >
                    <span className="progress-step-marker" aria-hidden="true" />
                    <span className="progress-step-content">
                      <span className="progress-step-label">{step.label || step.message || "Working"}</span>
                      {step.detail ? <span className="progress-step-detail">{step.detail}</span> : null}
                      {step.files?.length ? (
                        <span className="progress-step-related">{step.files.join(", ")}</span>
                      ) : null}
                      {step.command ? (
                        <span className="progress-step-related"><code>{step.command}</code></span>
                      ) : null}
                    </span>
                    <span className="progress-step-status">{statusLabel(step.status)}</span>
                    {time ? <span className="progress-step-time">{time}</span> : null}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
