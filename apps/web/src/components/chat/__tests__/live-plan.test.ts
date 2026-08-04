import { describe, expect, it } from "vitest";
import { livePlanFromEvent, livePlanFromEvents, type AgentRunEvent } from "../run-event-state";

function planEvent(plan: unknown, overrides: Partial<AgentRunEvent> = {}): AgentRunEvent {
  return {
    id: "event-plan",
    type: "progress_delta",
    event_type: "activity_updated",
    run_id: "run-1",
    thread_id: "thread-1",
    activity_id: "langgraph-plan",
    sequence: 1,
    phase: "Planning",
    label: "Updated plan",
    status: "running",
    aggregate: { plan },
    ...overrides,
  } as AgentRunEvent;
}

describe("livePlanFromEvent", () => {
  it("extracts structured plan items", () => {
    const plan = livePlanFromEvent(
      planEvent([
        { id: "s1", title: "Gather evidence", status: "completed", goal: "read files" },
        { id: "s2", title: "Propose edit", status: "running" },
      ]),
    );
    expect(plan).not.toBeNull();
    expect(plan).toHaveLength(2);
    expect(plan![0]).toEqual({ id: "s1", title: "Gather evidence", status: "completed", goal: "read files" });
    expect(plan![1].status).toBe("running");
  });

  it("drops entries without a title and defaults status", () => {
    const plan = livePlanFromEvent(planEvent([{ id: "s1", title: "Keep" }, { id: "s2", title: "" }]));
    expect(plan).toHaveLength(1);
    expect(plan![0].status).toBe("pending");
  });

  it("returns null for non-plan events", () => {
    const event = planEvent(undefined, { activity_id: "something-else", aggregate: { action_type: "read_file" } });
    expect(livePlanFromEvent(event)).toBeNull();
  });

  it("returns null when aggregate is missing", () => {
    const event = planEvent(undefined, { aggregate: null });
    expect(livePlanFromEvent(event)).toBeNull();
  });
});

describe("livePlanFromEvents", () => {
  it("returns the most recent plan across a batch", () => {
    const events = [
      planEvent([{ id: "s1", title: "First", status: "running" }], { sequence: 1 }),
      { ...planEvent([]), type: "assistant_delta", delta: "hi" } as AgentRunEvent,
      planEvent([{ id: "s1", title: "First", status: "completed" }], { sequence: 3 }),
    ];
    const plan = livePlanFromEvents(events);
    expect(plan).not.toBeNull();
    expect(plan![0].status).toBe("completed");
  });

  it("returns null when no plan events are present", () => {
    const events = [{ id: "e", type: "assistant_delta", delta: "x" } as AgentRunEvent];
    expect(livePlanFromEvents(events)).toBeNull();
  });
});
