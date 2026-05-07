import type { ProgressStep } from "./ProgressTimeline";

const LOW_VALUE_LABELS = new Set([
  "Loaded context",
  "Framed request",
  "Updated plan",
  "Created initial plan",
  "Recorded observation",
  "Chose next action",
  "Inspect repository",
  "Inspect repository tree",
]);

const GENERIC_DETAILS = new Set(["Details", "details"]);
const MAX_PRIMARY_STEPS = 6;

export function compactWorkTraceSteps(steps: ProgressStep[]): ProgressStep[] {
  const primary = mergeAdjacentDuplicates(steps)
    .filter(isPrimaryWorkStep)
    .map((step) => ({
      ...step,
      detail: scrubGenericDetail(step.detail),
    }));

  if (primary.length <= MAX_PRIMARY_STEPS) return primary;
  return [...primary.slice(0, 3), ...primary.slice(-3)];
}

export function workTraceSummary(step: ProgressStep): string {
  return firstText(
    step.safeReasoningSummary,
    step.safetyNote,
    step.observation,
    step.currentAction,
    step.nextAction,
    step.label,
    step.message,
  ) || "Working";
}

export function hasTechnicalDetails(step: ProgressStep): boolean {
  return Boolean(
    scrubGenericDetail(step.detail)
      || step.currentAction
      || step.observation
      || step.nextAction
      || step.evidenceNeeded?.length
      || step.uncertainty?.length
      || step.safetyNote
      || step.relatedSearchQuery
      || step.files?.length
      || step.command
      || aggregateEntries(step).length,
  );
}

export function aggregateEntries(step: ProgressStep): Array<[string, string]> {
  return Object.entries(step.aggregate || {})
    .filter(([, value]) =>
      typeof value === "string" || typeof value === "number" || typeof value === "boolean",
    )
    .map(([key, value]) => [key.replaceAll("_", " "), String(value)]);
}

export function isLowValuePrimaryLabel(label?: string | null): boolean {
  return LOW_VALUE_LABELS.has(String(label || "").trim());
}

function isPrimaryWorkStep(step: ProgressStep): boolean {
  if (step.display === "hidden" || step.visibility === "internal") return false;
  if (step.display === "secondary" || step.visibility === "debug") {
    return Boolean(step.safetyNote && step.eventType === "command_approval");
  }
  if (isLowValuePrimaryLabel(step.label) && !step.safeReasoningSummary && !step.safetyNote) {
    return false;
  }
  if (step.eventType === "action_result") return false;
  if (step.eventType === "work_trace" || step.display === "primary" || step.visibility === "user") {
    return Boolean(workTraceSummary(step).trim());
  }
  return !isLowValuePrimaryLabel(step.label) && Boolean(workTraceSummary(step).trim());
}

function mergeAdjacentDuplicates(steps: ProgressStep[]): ProgressStep[] {
  const merged: ProgressStep[] = [];
  for (const step of steps) {
    const previous = merged[merged.length - 1];
    if (previous && duplicateSummaryKey(previous) === duplicateSummaryKey(step)) {
      merged[merged.length - 1] = {
        ...previous,
        ...step,
        startedAt: previous.startedAt || step.startedAt,
        safeReasoningSummary: previous.safeReasoningSummary || step.safeReasoningSummary,
        currentAction: previous.currentAction || step.currentAction,
        observation: step.observation || previous.observation,
        nextAction: step.nextAction || previous.nextAction,
        evidenceNeeded: mergeLists(previous.evidenceNeeded, step.evidenceNeeded),
        uncertainty: mergeLists(previous.uncertainty, step.uncertainty),
        safetyNote: step.safetyNote || previous.safetyNote,
      };
    } else {
      merged.push(step);
    }
  }
  return merged;
}

function duplicateSummaryKey(step: ProgressStep): string {
  if (step.runId && step.activityId) return `${step.runId}:${step.activityId}`;
  const summary = workTraceSummary(step).toLowerCase().replace(/\s+/g, " ").trim();
  return `${step.runId || "local"}:${summary}:${(step.files || []).join(",")}:${formatCommand(step.command)}`;
}

function mergeLists(a?: string[], b?: string[]): string[] | undefined {
  const out: string[] = [];
  for (const item of [...(a || []), ...(b || [])]) {
    if (item && !out.includes(item)) out.push(item);
  }
  return out.length ? out : undefined;
}

function firstText(...values: Array<string | null | undefined>): string | undefined {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return undefined;
}

function scrubGenericDetail(value?: string | null): string | undefined {
  const text = String(value || "").trim();
  if (!text || GENERIC_DETAILS.has(text)) return undefined;
  return text;
}

function formatCommand(command?: string | string[] | null): string {
  if (!command) return "";
  return Array.isArray(command) ? command.join(" ") : command;
}
