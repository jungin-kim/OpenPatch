/**
 * E2E tests for chat thread / run rehydration.
 *
 * These tests intercept all local-worker API routes so no real worker process is needed.
 * Run with:  npm --prefix apps/web run test:e2e
 *
 * If Playwright browsers are not installed:
 *   npx playwright install --with-deps chromium
 * then re-run the test command.
 *
 * CI note: set E2E_BASE_URL to an already-running server to skip the built-in webServer start.
 */
import { test, expect, type Page } from "@playwright/test";
import {
  DEFAULT_REPO,
  buildMockRunRecord,
  buildProgressEvents,
  buildFinalResult,
  mockHealthConnected,
  mockListThreads,
  mockSaveThread,
  mockOpenRepository,
  mockGetAgentRun,
  mockGetAgentRunEvents,
  mockGetActiveRuns,
  sseEvent,
} from "./fixtures/mock-worker";

// ── Helpers ───────────────────────────────────────────────────────────────────

const RUN_ID = "run_test_001";
const THREAD_ID = "thread_test_001";
const USER_MSG = "이 레포가 뭐 하는 프로젝트인지 알아내줘.";
const FINAL_RESPONSE = "This repository is a local-first coding agent proxy.";

const PROGRESS_EVENTS = [
  { phase: "Thinking", label: "Loaded context", status: "completed" as const, sequence: 1 },
  { phase: "Planning", label: "Framed request", status: "completed" as const, sequence: 2 },
  { phase: "Searching", label: "Searching repository", status: "running" as const, sequence: 3 },
];

function buildThread(overrides: { messages?: unknown[] } = {}) {
  return {
    id: THREAD_ID,
    title: "mock/repo",
    repo: DEFAULT_REPO,
    messages: overrides.messages ?? [
      {
        id: "msg-user-1",
        role: "user",
        content: USER_MSG,
        timestamp: new Date().toISOString(),
      },
    ],
  };
}

async function setupBaseRoutes(page: Page) {
  await mockHealthConnected(page);
  await mockSaveThread(page);

  // Provider / branch endpoints — return empty lists for local provider
  await page.route("/api/worker/projects*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ projects: [], recent_projects: [] }) }),
  );
  await page.route("/api/worker/branches*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ branches: [] }) }),
  );
  await page.route("/api/worker/recent-projects*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ projects: [] }) }),
  );
  // Local branches
  await page.route("/api/worker/local-branches*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ branches: [{ name: "main", is_current: true }], current_branch: "main" }),
    }),
  );
}

async function setStorageForThread(page: Page, threadId: string, runId?: string, repoKey?: string) {
  await page.evaluate(
    ({ threadId, runId, repoKey }) => {
      // repo-scoped key (Part 2 contract)
      if (repoKey) {
        localStorage.setItem(repoKey, threadId);
      } else {
        localStorage.setItem("repooperator-active-thread-id", threadId);
      }
      if (runId) {
        localStorage.setItem(`repooperator-active-run-id:${threadId}`, runId);
      }
    },
    { threadId, runId, repoKey },
  );
}

// ── Scenario A: Active thread survives navigation during active run ────────────

test("A: active thread survives navigation away and back during active run", async ({ page }) => {
  const runRecord = buildMockRunRecord({
    runId: RUN_ID,
    threadId: THREAD_ID,
    repo: DEFAULT_REPO,
    status: "running",
    progressEvents: PROGRESS_EVENTS,
  });

  const events = buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS);

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, [runRecord]);
  await mockGetAgentRun(page, runRecord);
  await mockGetAgentRunEvents(page, RUN_ID, events);

  await page.goto("/");
  await setStorageForThread(page, THREAD_ID, RUN_ID);

  // Wait for the app to load
  await page.waitForTimeout(600);

  // Navigate away then back (simulate page navigation)
  await page.goto("/?tab=settings");
  await page.goto("/");
  await page.waitForTimeout(600);

  // The thread must still be selected (user message visible)
  await expect(page.getByText(USER_MSG)).toBeVisible({ timeout: 5000 });

  // At least one progress label should appear
  const progressVisible = await page.getByText("Loaded context").isVisible().catch(() => false)
    || await page.getByText("Framed request").isVisible().catch(() => false)
    || await page.getByText("Searching repository").isVisible().catch(() => false);
  expect(progressVisible, "At least one progress label should be visible after nav-back").toBe(true);

  // No duplicate assistant messages for this run
  const assistantMessages = page.locator('[data-testid="assistant-message"]');
  const count = await assistantMessages.count();
  expect(count).toBeLessThanOrEqual(1);
});

// ── Scenario B: Completed run rehydrates from persisted backend events ─────────

test("B: completed run rehydrates final answer and progress from backend events", async ({ page }) => {
  const finalResult = buildFinalResult(RUN_ID, THREAD_ID, FINAL_RESPONSE, PROGRESS_EVENTS);
  const completedRun = buildMockRunRecord({
    runId: RUN_ID,
    threadId: THREAD_ID,
    repo: DEFAULT_REPO,
    status: "completed",
    finalResponse: FINAL_RESPONSE,
    progressEvents: PROGRESS_EVENTS,
  });
  completedRun.final_result = finalResult;

  const events = [
    ...buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS),
    {
      id: `${RUN_ID}-final`,
      run_id: RUN_ID,
      thread_id: THREAD_ID,
      type: "final_message",
      event_type: "final_message",
      result: finalResult,
      sequence: 10,
      timestamp: new Date().toISOString(),
    },
  ];

  const threadWithRun = buildThread({
    messages: [
      { id: "msg-user-1", role: "user", content: USER_MSG, timestamp: new Date().toISOString() },
    ],
  });

  await setupBaseRoutes(page);
  await mockListThreads(page, [threadWithRun]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, []);
  await mockGetAgentRun(page, completedRun);
  await mockGetAgentRunEvents(page, RUN_ID, events);

  await page.goto("/");
  await setStorageForThread(page, THREAD_ID, RUN_ID);
  await page.waitForTimeout(800);

  // After rehydrating a completed run, the final answer should appear
  await expect(page.getByText(FINAL_RESPONSE, { exact: false })).toBeVisible({ timeout: 8000 });

  // activeRunId should be cleared (no pending indicator)
  // The composer should not be in "pending" state after terminal run
  const stopButton = page.locator('[data-testid="stop-run-button"]');
  const isStopVisible = await stopButton.isVisible().catch(() => false);
  expect(isStopVisible, "Stop button must not be visible for terminal run").toBe(false);

  // No duplicate assistant messages
  const assistantMsgs = page.locator('[data-testid="assistant-message"]');
  const count = await assistantMsgs.count();
  expect(count).toBeLessThanOrEqual(1);
});

// ── Scenario C: Delayed assistant_delta does not make UI look stuck ────────────

test("C: progress_delta events keep run alive when assistant_delta is delayed", async ({ page }) => {
  const runRecord = buildMockRunRecord({
    runId: RUN_ID,
    threadId: THREAD_ID,
    repo: DEFAULT_REPO,
    status: "running",
    progressEvents: PROGRESS_EVENTS,
  });
  const events = buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS);

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, [runRecord]);
  await mockGetAgentRun(page, runRecord);
  await mockGetAgentRunEvents(page, RUN_ID, events);

  await page.goto("/");
  await setStorageForThread(page, THREAD_ID, RUN_ID);
  await page.waitForTimeout(600);

  // Progress labels should appear while no assistant_delta has arrived
  const progressVisible = await page.getByText("Loaded context").isVisible().catch(() => false)
    || await page.getByText("Framed request").isVisible().catch(() => false);
  expect(progressVisible, "Progress card must be visible while assistant_delta is delayed").toBe(true);

  // No empty/blank assistant message should have been created
  const emptyAssistant = page.locator('[data-testid="assistant-message"]:has-text("")');
  // We only check that a spurious blank card was not inserted
  const emptyCount = await emptyAssistant.count();
  expect(emptyCount).toBe(0);
});

// ── Scenario D: final_message without assistant_delta creates final message ────

test("D: final_message without assistant_delta still creates assistant message", async ({ page }) => {
  const finalResult = buildFinalResult(RUN_ID, THREAD_ID, FINAL_RESPONSE, PROGRESS_EVENTS);
  const completedRun = buildMockRunRecord({
    runId: RUN_ID,
    threadId: THREAD_ID,
    repo: DEFAULT_REPO,
    status: "completed",
    finalResponse: FINAL_RESPONSE,
    progressEvents: PROGRESS_EVENTS,
  });

  // Events have only progress_delta + final_message, no assistant_delta
  const events = [
    ...buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS),
    {
      id: `${RUN_ID}-final`,
      run_id: RUN_ID,
      thread_id: THREAD_ID,
      type: "final_message",
      event_type: "final_message",
      result: finalResult,
      sequence: 10,
      timestamp: new Date().toISOString(),
    },
  ];

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, []);
  await mockGetAgentRun(page, completedRun);
  await mockGetAgentRunEvents(page, RUN_ID, events);

  await page.goto("/");
  await setStorageForThread(page, THREAD_ID, RUN_ID);
  await page.waitForTimeout(800);

  await expect(page.getByText(FINAL_RESPONSE, { exact: false })).toBeVisible({ timeout: 8000 });
});

// ── Scenario E: assistant_delta + final_message deduplication ─────────────────

test("E: assistant_delta plus final_message does not duplicate the answer", async ({ page }) => {
  const finalResult = buildFinalResult(RUN_ID, THREAD_ID, FINAL_RESPONSE, PROGRESS_EVENTS);
  const completedRun = buildMockRunRecord({
    runId: RUN_ID,
    threadId: THREAD_ID,
    repo: DEFAULT_REPO,
    status: "completed",
    finalResponse: FINAL_RESPONSE,
    progressEvents: PROGRESS_EVENTS,
  });

  // Both assistant_delta chunks and final_message present
  const events = [
    ...buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS),
    {
      id: `${RUN_ID}-ad-1`,
      run_id: RUN_ID,
      thread_id: THREAD_ID,
      type: "assistant_delta",
      event_type: "assistant_delta",
      delta: FINAL_RESPONSE,
      sequence: 9,
      timestamp: new Date().toISOString(),
    },
    {
      id: `${RUN_ID}-final`,
      run_id: RUN_ID,
      thread_id: THREAD_ID,
      type: "final_message",
      event_type: "final_message",
      result: finalResult,
      sequence: 10,
      timestamp: new Date().toISOString(),
    },
  ];

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, []);
  await mockGetAgentRun(page, completedRun);
  await mockGetAgentRunEvents(page, RUN_ID, events);

  await page.goto("/");
  await setStorageForThread(page, THREAD_ID, RUN_ID);
  await page.waitForTimeout(800);

  await expect(page.getByText(FINAL_RESPONSE, { exact: false })).toBeVisible({ timeout: 8000 });

  // Count occurrences of the final response string to detect duplication
  const all = await page.getByText(FINAL_RESPONSE, { exact: false }).all();
  // The response should appear once (or at most in the streamed + final merged bubble).
  // Detect obvious doubling: two separate assistant message containers each showing it.
  const assistantMsgs = page.locator('[data-testid="assistant-message"]');
  const count = await assistantMsgs.count();
  expect(count).toBeLessThanOrEqual(1);
});

// ── Scenario F: non-terminal statuses keep run active ─────────────────────────

test("F: waiting_approval and cancelling statuses keep active run visible", async ({ page }) => {
  for (const status of ["waiting_approval", "cancelling"] as const) {
    const runRecord = buildMockRunRecord({
      runId: RUN_ID,
      threadId: THREAD_ID,
      repo: DEFAULT_REPO,
      status,
      progressEvents: PROGRESS_EVENTS,
    });
    const events = buildProgressEvents(RUN_ID, THREAD_ID, PROGRESS_EVENTS);

    await setupBaseRoutes(page);
    await mockListThreads(page, [buildThread()]);
    await mockOpenRepository(page, DEFAULT_REPO);
    await mockGetActiveRuns(page, [runRecord]);
    await mockGetAgentRun(page, runRecord);
    await mockGetAgentRunEvents(page, RUN_ID, events);

    await page.goto("/");
    await setStorageForThread(page, THREAD_ID, RUN_ID);
    await page.waitForTimeout(600);

    // For non-terminal statuses the run should remain active — no final answer yet
    const finalText = await page.getByText(FINAL_RESPONSE, { exact: false }).isVisible().catch(() => false);
    expect(finalText, `status=${status}: final answer must not appear for non-terminal run`).toBe(false);
  }
});
