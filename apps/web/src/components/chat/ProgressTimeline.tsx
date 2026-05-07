"use client";

import { useEffect, useState } from "react";
import {
  aggregateEntries,
  compactWorkTraceSteps,
  hasTechnicalDetails,
  isLowValuePrimaryLabel,
  workTraceSummary,
} from "./work-trace-display";

export type ProgressStep = {
  id?: string;
  activityId?: string | null;
  runId?: string;
  sequence?: number | null;
  eventType?: string | null;
  visibility?: "user" | "debug" | "internal" | string | null;
  display?: "primary" | "secondary" | "hidden" | string | null;
  phase?: string;
  label?: string;
  detail?: string;
  detailDelta?: string | null;
  message?: string;
  safeReasoningSummary?: string | null;
  summaryDelta?: string | null;
  evidenceNeeded?: string[];
  uncertainty?: string[];
  safetyNote?: string | null;
  currentAction?: string | null;
  observation?: string | null;
  observationDelta?: string | null;
  nextAction?: string | null;
  nextActionDelta?: string | null;
  relatedSearchQuery?: string | null;
  aggregate?: Record<string, unknown> | null;
  status?: string;
  startedAt?: string | null;
  endedAt?: string | null;
  durationMs?: number | null;
  elapsedMs?: number | null;
  files?: string[];
  command?: string | string[] | null;
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
  const [showTechnicalLog, setShowTechnicalLog] = useState(false);
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

  const primarySteps = compactWorkTraceSteps(steps);
  if (primarySteps.length === 0) return null;

  const totalMs = runDurationMs(primarySteps, done, now);
  const hasHiddenTechnicalSteps = steps.length > primarySteps.length;

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
        {primarySteps.map((step, index) => {
          const isCurrent = index === primarySteps.length - 1 && !done && step.status === "running";
          const duration = stepDurationMs(step, now);
          const summary = workTraceSummary(step);
          const showLabelAsMetadata = Boolean(step.safeReasoningSummary || step.safetyNote || step.observation);
          return (
            <div
              key={progressStepKey(step, index)}
              className={`progress-step progress-step-${step.status || "completed"}${isCurrent ? " progress-step-active" : ""}`}
            >
              <span className="progress-step-marker" aria-hidden="true" />
              <span className="progress-step-content">
                <span className="progress-step-mainline">
                  <span className="progress-step-label">{summary}</span>
                  <span className="progress-step-phase">{step.phase || "Step"}</span>
                </span>
                {showLabelAsMetadata && step.label && !isLowValuePrimaryLabel(step.label) ? (
                  <span className="progress-step-reason">{step.label}</span>
                ) : null}
                {hasTechnicalDetails(step) ? (
                  <details className="progress-step-details">
                    <summary>Technical details</summary>
                    {step.detail ? <span className="progress-step-detail">{step.detail}</span> : null}
                    {step.currentAction ? (
                      <span className="progress-step-detail"><strong>Current:</strong> {step.currentAction}</span>
                    ) : null}
                    {step.observation ? (
                      <span className="progress-step-detail"><strong>Observation:</strong> {step.observation}</span>
                    ) : null}
                    {step.nextAction ? (
                      <span className="progress-step-detail"><strong>Next:</strong> {step.nextAction}</span>
                    ) : null}
                    {step.evidenceNeeded?.length ? (
                      <span className="progress-step-detail"><strong>Evidence:</strong> {step.evidenceNeeded.join("; ")}</span>
                    ) : null}
                    {step.uncertainty?.length ? (
                      <span className="progress-step-detail"><strong>Uncertain:</strong> {step.uncertainty.join("; ")}</span>
                    ) : null}
                    {step.safetyNote ? (
                      <span className="progress-step-detail"><strong>Safety:</strong> {step.safetyNote}</span>
                    ) : null}
                    {step.relatedSearchQuery ? (
                      <span className="progress-step-detail"><strong>Search:</strong> <code>{step.relatedSearchQuery}</code></span>
                    ) : null}
                    {step.files?.length ? (
                      <span className="progress-step-detail"><strong>Files:</strong> {step.files.join(", ")}</span>
                    ) : null}
                    {step.command ? (
                      <span className="progress-step-detail"><strong>Command:</strong> <code>{formatCommand(step.command)}</code></span>
                    ) : null}
                    {aggregateEntries(step).map(([key, value]) => (
                      <span className="progress-step-detail" key={key}><strong>{key}:</strong> {value}</span>
                    ))}
                  </details>
                ) : null}
              </span>
              <span className="progress-step-status">{statusLabel(step.status)}</span>
              <span className="progress-step-time">{formatDuration(duration)}</span>
            </div>
          );
        })}
      </div>
      {hasHiddenTechnicalSteps ? (
        <div className="progress-technical-log">
          <button
            type="button"
            className="progress-technical-toggle"
            onClick={() => setShowTechnicalLog((value) => !value)}
          >
            {showTechnicalLog ? "Hide technical log" : "Show technical log"}
          </button>
          {showTechnicalLog ? (
            <div className="progress-technical-events">
              {steps.map((step, index) => (
                <div className="progress-technical-event" key={`technical-${progressStepKey(step, index)}`}>
                  <span>{step.phase || "Step"}</span>
                  <strong>{step.label || step.message || step.eventType || "Event"}</strong>
                  <small>{statusLabel(step.status)}</small>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function formatCommand(command: string | string[]): string {
  return Array.isArray(command) ? command.join(" ") : command;
}

function progressStepKey(step: ProgressStep, index: number): string {
  if (step.runId && step.activityId) return `${step.runId}:${step.activityId}`;
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
