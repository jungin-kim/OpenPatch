import type {
  AgentActivityEvent,
  AgentRunPayload,
  AgentRunRecord,
} from "@/lib/local-worker-client";
import type { ChatMessage } from "./ChatMessages";
import type { ProgressStep } from "./ProgressTimeline";

export type AgentRunEvent = AgentActivityEvent & {
  type?: string;
  delta?: string;
  result?: AgentRunPayload;
  message?: string;
};

const ACTIVE_RUN_STATUSES = new Set(["pending", "running", "waiting_approval", "cancelling"]);
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled", "timed_out"]);

export function isActiveRunStatus(status?: string | null): boolean {
  return ACTIVE_RUN_STATUSES.has(String(status || ""));
}

export function isTerminalRunStatus(status?: string | null): boolean {
  return TERMINAL_RUN_STATUSES.has(String(status || ""));
}

export function getMessageKeyForRun(runId: string): string {
  return `assistant-run:${runId}`;
}

export function progressStepFromEvent(
  event: AgentRunEvent,
  options: { finalizeRunning?: boolean } = {},
): ProgressStep {
  const status =
    options.finalizeRunning && event.status === "running" ? "completed" : event.status;
  return {
    id: event.id,
    activityId: event.activity_id,
    runId: event.run_id,
    sequence: event.sequence,
    eventType: event.event_type,
    phase: event.phase,
    label: event.label ?? event.message,
    detail: event.detail,
    detailDelta: event.detail_delta,
    message: event.message,
    safeReasoningSummary: event.safe_reasoning_summary,
    summaryDelta: event.summary_delta,
    currentAction: event.current_action,
    observation: event.observation,
    observationDelta: event.observation_delta,
    nextAction: event.next_action,
    nextActionDelta: event.next_action_delta,
    relatedSearchQuery: event.related_search_query,
    aggregate: event.aggregate,
    status,
    startedAt: event.started_at,
    endedAt: event.ended_at,
    durationMs: event.duration_ms,
    elapsedMs: event.elapsed_ms,
    files: event.files,
    command: event.command,
    proposalId: event.proposal_id,
  };
}

export function mergeRunEventsIntoProgressSteps(
  events?: AgentRunEvent[],
  finalResult?: AgentRunPayload | null,
  options: { finalizeRunning?: boolean } = {},
): ProgressStep[] {
  let steps: ProgressStep[] = [];
  for (const event of events || []) {
    if (event.type !== "progress_delta" || !(event.label || event.message)) continue;
    steps = mergeProgressStep(steps, progressStepFromEvent(event, options));
  }
  if (steps.length === 0 && finalResult?.activity_events?.length) {
    for (const event of finalResult.activity_events) {
      if (event.type !== "progress_delta" || !(event.label || event.message)) continue;
      steps = mergeProgressStep(steps, progressStepFromEvent(event as AgentRunEvent, options));
    }
  }
  return options.finalizeRunning
    ? steps.map((step) => (step.status === "running" ? { ...step, status: "completed" } : step))
    : steps;
}

export function progressStepsForCompletedRun(
  events?: AgentRunEvent[],
  finalResult?: AgentRunPayload | null,
): ProgressStep[] {
  return mergeRunEventsIntoProgressSteps(events, finalResult, { finalizeRunning: true });
}

export function assistantTextFromRunEvents(
  events?: AgentRunEvent[],
  finalResult?: AgentRunPayload | null,
): string {
  const finalFromEvents = finalResultFromRunEvents(events, finalResult);
  if (finalFromEvents?.response) return finalFromEvents.response;
  return (events || [])
    .filter((event) => event.type === "assistant_delta")
    .map((event) => String(event.delta || ""))
    .join("");
}

export function finalResultFromRunEvents(
  events?: AgentRunEvent[],
  finalResult?: AgentRunPayload | null,
): AgentRunPayload | null {
  if (finalResult?.response) return finalResult;
  for (const event of [...(events || [])].reverse()) {
    if (event.type === "final_message" && event.result) return event.result;
  }
  return finalResult || null;
}

export function upsertAssistantMessageForRun(
  messages: ChatMessage[],
  runId: string,
  patch: Partial<ChatMessage> & { content?: string },
): ChatMessage[] {
  const messageKey = getMessageKeyForRun(runId);
  const existingIndex = messages.findIndex(
    (message) => message.id === messageKey || message.metadata?.run_id === runId,
  );
  if (existingIndex >= 0) {
    return messages.map((message, index) =>
      index === existingIndex
        ? {
            ...message,
            ...patch,
            id: message.id || messageKey,
            role: "assistant",
            content: patch.content ?? message.content,
            timestamp: patch.timestamp ?? message.timestamp,
            metadata: patch.metadata ?? message.metadata,
            progressSteps: patch.progressSteps ?? message.progressSteps,
          }
        : message,
    );
  }
  return [
    ...messages,
    {
      id: messageKey,
      role: "assistant",
      content: patch.content || "",
      timestamp: patch.timestamp || new Date(),
      metadata: patch.metadata,
      proposal: patch.proposal,
      progressSteps: patch.progressSteps,
    },
  ];
}

export function mergeProgressStep(current: ProgressStep[], incoming: ProgressStep): ProgressStep[] {
  if (!incoming.label && !incoming.message) return current;
  const incomingKey = progressStepIdentity(incoming, current.length);
  const existingIndex = current.findIndex((step, index) => progressStepIdentity(step, index) === incomingKey);
  if (existingIndex >= 0) {
    return current.map((step, index) => (index === existingIndex ? mergeProgressStepFields(step, incoming) : step));
  }
  return [...current, incoming];
}

export function maxEventSequence(events?: AgentRunEvent[]): number {
  return Math.max(0, ...(events || []).map((event) => Number(event.sequence || 0)));
}

export function runIdForThread(activeRuns: AgentRunRecord[], threadId: string): string | null {
  return activeRuns.find((run) => run.thread_id === threadId && isActiveRunStatus(run.status))?.id || null;
}

function progressStepIdentity(step: ProgressStep, fallbackIndex: number): string {
  if (step.runId && step.activityId) return `${step.runId}:${step.activityId}`;
  if (step.runId && step.eventType && step.label) return `${step.runId}:${step.eventType}:${step.label}`;
  if (step.runId && step.sequence !== undefined && step.sequence !== null) return `${step.runId}:${step.sequence}`;
  if (step.runId && step.id) return `${step.runId}:${step.id}`;
  if (step.id) return step.id;
  return `${step.runId || "local"}:${step.startedAt || fallbackIndex}:${step.phase || ""}:${step.label || step.message || ""}`;
}

function mergeProgressStepFields(existing: ProgressStep, incoming: ProgressStep): ProgressStep {
  return {
    ...existing,
    ...incoming,
    startedAt: existing.startedAt || incoming.startedAt,
    detail: incoming.detail ?? appendDelta(existing.detail, incoming.detailDelta),
    observation: incoming.observation ?? appendDelta(existing.observation, incoming.observationDelta),
    nextAction: incoming.nextAction ?? appendDelta(existing.nextAction, incoming.nextActionDelta),
    safeReasoningSummary: incoming.safeReasoningSummary ?? appendDelta(existing.safeReasoningSummary, incoming.summaryDelta),
  };
}

function appendDelta(base?: string | null, delta?: string | null): string | undefined {
  const current = base || "";
  if (!delta) return current || undefined;
  return `${current}${delta}`;
}
