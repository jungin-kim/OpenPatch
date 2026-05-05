"use client";

import { useEffect, useState } from "react";

export type ProgressStep = {
  id?: string;
  runId?: string;
  sequence?: number | null;
  eventType?: string | null;
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

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
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
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (done) return;
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, [done]);

  useEffect(() => {
    if (!done) return;
    const timeout = setTimeout(() => setCollapsed(true), 2400);
    return () => clearTimeout(timeout);
  }, [done]);

  if (steps.length === 0) return null;

  const totalMs = runDurationMs(steps, done, now);

  if (done && collapsed) {
    return (
      <button
        type="button"
        className="progress-timeline-summary"
        onClick={() => setCollapsed(false)}
        title="Show agent activity"
      >
        <span>Worked for {formatDuration(totalMs)}</span>
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
        <span>{done ? `Worked for ${formatDuration(totalMs)}` : `Agent Activity · ${formatDuration(totalMs)}`}</span>
        {done ? <span className="progress-timeline-collapse">hide</span> : null}
      </button>
      <div className="progress-steps">
        {steps.map((step, index) => {
          const isCurrent = index === steps.length - 1 && !done && step.status === "running";
          const duration = stepDurationMs(step, now);
          return (
            <div
              key={progressStepKey(step, index)}
              className={`progress-step progress-step-${step.status || "completed"}${isCurrent ? " progress-step-active" : ""}`}
            >
              <span className="progress-step-marker" aria-hidden="true" />
              <span className="progress-step-content">
                <span className="progress-step-mainline">
                  <span className="progress-step-label">{step.label || step.message || "Working"}</span>
                  <span className="progress-step-phase">{step.phase || "Activity"}</span>
                </span>
                {step.detail ? <span className="progress-step-detail">{step.detail}</span> : null}
                {step.files?.length ? (
                  <span className="progress-step-related">{step.files.join(", ")}</span>
                ) : null}
                {step.command ? (
                  <span className="progress-step-related"><code>{step.command}</code></span>
                ) : null}
              </span>
              <span className="progress-step-status">{statusLabel(step.status)}</span>
              <span className="progress-step-time">{formatDuration(duration)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function progressStepKey(step: ProgressStep, index: number): string {
  if (step.runId && step.sequence !== undefined && step.sequence !== null) {
    return `${step.runId}:${step.sequence}:${step.eventType || "activity"}:${index}`;
  }
  if (step.id && step.runId) return `${step.runId}:${step.id}:${index}`;
  if (step.id) return `${step.id}:${index}`;
  return `${step.runId || "local"}:${step.startedAt || "no-start"}:${step.phase || "activity"}:${step.label || step.message || "step"}:${index}`;
}

function stepDurationMs(step: ProgressStep, now: number): number {
  if (step.durationMs !== undefined && step.durationMs !== null) return Math.max(0, step.durationMs);
  const startedMs = step.startedAt ? Date.parse(step.startedAt) : Number.NaN;
  const endedMs = step.endedAt ? Date.parse(step.endedAt) : Number.NaN;
  if (step.status === "running" && Number.isFinite(startedMs)) return Math.max(0, now - startedMs);
  if (Number.isFinite(startedMs) && Number.isFinite(endedMs)) return Math.max(0, endedMs - startedMs);
  if (step.elapsedMs !== undefined && step.elapsedMs !== null) return Math.max(0, step.elapsedMs);
  return 0;
}

function runDurationMs(steps: ProgressStep[], done: boolean, now: number): number {
  const starts = steps
    .map((step) => (step.startedAt ? Date.parse(step.startedAt) : Number.NaN))
    .filter(Number.isFinite);
  if (!starts.length) {
    return steps[steps.length - 1]?.elapsedMs ?? steps[steps.length - 1]?.durationMs ?? 0;
  }
  const firstStarted = Math.min(...starts);
  if (!done) return Math.max(0, now - firstStarted);
  const ends = steps
    .map((step) => (step.endedAt ? Date.parse(step.endedAt) : Number.NaN))
    .filter(Number.isFinite);
  if (ends.length) return Math.max(0, Math.max(...ends) - firstStarted);
  return steps[steps.length - 1]?.elapsedMs ?? steps[steps.length - 1]?.durationMs ?? 0;
}
