/**
 * E2E coverage for the change-set proposal (diff) card and the permission-mode
 * selector — the two 0.10.x surfaces that had no browser-level regression net.
 *
 * All local-worker API routes are intercepted; no real worker is needed.
 * Run with:  npm --prefix apps/web run test:e2e
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import {
  DEFAULT_REPO,
  buildMockRunRecord,
  buildFinalResult,
  mockHealthConnected,
  mockListThreads,
  mockSaveThread,
  mockOpenRepository,
  mockGetAgentRun,
  mockGetAgentRunEvents,
  mockGetActiveRuns,
} from "./fixtures/mock-worker";

const RUN_ID = "run_proposal_001";
const THREAD_ID = "thread_proposal_001";
const USER_MSG = "calc.py의 add 함수에 docstring을 추가해줘";

const ORIGINAL = "def add(a, b):\n    return a + b\n";
const PROPOSED = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n';

function buildProposalFinalResult() {
  const base = buildFinalResult(RUN_ID, THREAD_ID, "I prepared a proposed patch only as a ChangeSetProposal. No files were modified.");
  return {
    ...base,
    response_type: "change_proposal",
    stop_reason: "waiting_approval",
    change_set_proposal: {
      proposal_id: "proposal:e2e123",
      status: "valid",
      applied: false,
      plan: { summary: "Add docstring to add()", target_files: ["calc.py"], operations: ["modify"] },
      changes: [
        {
          path: "calc.py",
          operation: "modify",
          summary: "Add docstring",
          original_content: ORIGINAL,
          proposed_content: PROPOSED,
        },
      ],
    },
  };
}

function buildThread() {
  return {
    id: THREAD_ID,
    title: "mock/repo",
    repo: DEFAULT_REPO,
    messages: [{ id: "msg-user-1", role: "user", content: USER_MSG, timestamp: new Date().toISOString() }],
  };
}

async function setupBaseRoutes(page: Page) {
  await mockHealthConnected(page);
  await mockSaveThread(page);
  await page.route("/api/worker/provider/projects*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ projects: [], recent_projects: [] }) }),
  );
  await page.route("/api/worker/provider/branches*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ branches: [] }) }),
  );
  await page.route("/api/worker/provider/recent-projects*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ projects: [] }) }),
  );
  await page.route("/api/worker/git-branches*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ branches: [{ name: "main", is_current: true }], current_branch: "main" }),
    }),
  );
}

async function setStorageForThread(page: Page, threadId: string, runId?: string) {
  await page.addInitScript(
    ({ threadId, runId }) => {
      const key = "repooperator-active-thread:local:%2Fmock%2Frepo:main";
      localStorage.setItem(key, threadId);
      localStorage.setItem("repooperator-active-repo-identity", key.replace("repooperator-active-thread:", ""));
      if (runId) localStorage.setItem(`repooperator-active-run-id:${threadId}`, runId);
    },
    { threadId, runId },
  );
}

test("proposal diff card renders and Apply posts the approval", async ({ page }) => {
  const finalResult = buildProposalFinalResult();
  const run = buildMockRunRecord({ runId: RUN_ID, threadId: THREAD_ID, repo: DEFAULT_REPO, status: "waiting_approval" });
  run.final_result = finalResult as never;

  const events = [
    {
      id: `${RUN_ID}-final`,
      run_id: RUN_ID,
      thread_id: THREAD_ID,
      type: "final_message",
      event_type: "final_message",
      result: finalResult,
      sequence: 5,
      timestamp: new Date().toISOString(),
    },
  ];

  let applyBody: unknown = null;
  await page.route(`/api/worker/agent/runs/${RUN_ID}/change-set/apply`, async (route: Route) => {
    applyBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        run_id: RUN_ID,
        response: "Applied the approved ChangeSetProposal. Files were modified.",
        response_type: "edit_applied",
        change_set_proposal: {
          ...(finalResult.change_set_proposal as object),
          applied: true,
          status: "applied",
          applied_at: new Date().toISOString(),
        },
      }),
    });
  });

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, []);
  await mockGetAgentRun(page, run);
  await mockGetAgentRunEvents(page, RUN_ID, events);
  await setStorageForThread(page, THREAD_ID, RUN_ID);

  await page.goto("/app");

  // Diff card renders with the proposed line and both decision buttons.
  await expect(page.getByText("Apply changes")).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("Reject")).toBeVisible();
  await expect(page.getByText('"""Add two numbers."""', { exact: false })).toBeVisible();

  // New diff UX: each diff line carries two line-number gutters (old + new).
  await expect(page.locator(".proposal-diff-line-add").first()).toBeVisible();
  await expect(page.locator(".proposal-diff-line-add").first().locator(".proposal-diff-lineno")).toHaveCount(2);

  await page.getByText("Apply changes").click();

  // The approval reaches the worker with the proposal id…
  await expect.poll(() => applyBody, { timeout: 8000 }).toBeTruthy();
  expect(JSON.stringify(applyBody)).toContain("proposal:e2e123");

  // …and the card flips to the applied confirmation.
  await expect(page.getByText(/applied at/i)).toBeVisible({ timeout: 8000 });
});

test("permission mode selector posts the chosen mode", async ({ page }) => {
  let postedMode: string | null = null;
  await page.route("/api/worker/permissions", async (route: Route) => {
    if (route.request().method() === "POST") {
      postedMode = (route.request().postDataJSON() as { mode?: string })?.mode ?? null;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ mode: postedMode, write_mode: "auto-apply", available_modes: [] }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ mode: "default", write_mode: "default", available_modes: [] }),
    });
  });

  await setupBaseRoutes(page);
  await mockListThreads(page, [buildThread()]);
  await mockOpenRepository(page, DEFAULT_REPO);
  await mockGetActiveRuns(page, []);
  await setStorageForThread(page, THREAD_ID);

  await page.goto("/app");

  const trigger = page.locator('button[aria-label="Permission mode"]');
  await expect(trigger).toBeVisible({ timeout: 10000 });
  await trigger.click();

  // accept_edits has no confirm() gate (full_access does), so it exercises
  // the POST path deterministically.
  await page.getByRole("menuitemradio", { name: /Accept edits/ }).click();

  await expect.poll(() => postedMode, { timeout: 8000 }).toBe("accept_edits");
  await expect(trigger).toContainText("Accept edits", { timeout: 8000 });
});
