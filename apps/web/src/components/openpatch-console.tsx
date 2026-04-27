"use client";

import { useEffect, useState } from "react";

import {
  getWorkerHealth,
  LocalWorkerClientError,
  openRepository,
  runAgentTask,
  type AgentRunPayload,
  type RepoOpenPayload,
} from "@/lib/local-worker-client";

type ConnectionState = "checking" | "connected" | "unavailable";

const workerBaseUrl =
  process.env.NEXT_PUBLIC_LOCAL_WORKER_BASE_URL?.trim() || "http://127.0.0.1:8000";

export function OpenPatchConsole() {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("checking");
  const [healthDetail, setHealthDetail] = useState(
    "Checking for a reachable local worker.",
  );
  const [repoBaseDir, setRepoBaseDir] = useState("");

  const [projectPath, setProjectPath] = useState("examples/demo-repo");
  const [branch, setBranch] = useState("main");
  const [gitProvider, setGitProvider] = useState("gitlab");
  const [task, setTask] = useState(
    "Summarize the repository and identify the best starting point for understanding the codebase.",
  );

  const [repoPending, setRepoPending] = useState(false);
  const [taskPending, setTaskPending] = useState(false);

  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [taskResult, setTaskResult] = useState<AgentRunPayload | null>(null);

  const [repoError, setRepoError] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);

  async function refreshHealthCheck() {
    setConnectionState("checking");
    setHealthDetail("Checking for a reachable local worker.");

    try {
      const payload = await getWorkerHealth();
      setConnectionState("connected");
      setHealthDetail(`Worker is available and reporting status '${payload.status}'.`);
      setRepoBaseDir(payload.repo_base_dir);
    } catch (error) {
      setConnectionState("unavailable");
      setRepoBaseDir("");
      setHealthDetail(
        error instanceof Error
          ? error.message
          : "The local worker could not be reached.",
      );
    }
  }

  useEffect(() => {
    void refreshHealthCheck();
  }, []);

  async function handleRepoOpen(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRepoPending(true);
    setRepoError(null);
    setTaskError(null);
    setRepoResult(null);
    setTaskResult(null);

    try {
      const payload = await openRepository({
        project_path: projectPath.trim(),
        branch: branch.trim(),
        git_provider: gitProvider || undefined,
      });
      setRepoResult(payload);
      await refreshHealthCheck();
    } catch (error) {
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to open the repository through the local worker.",
      );
    } finally {
      setRepoPending(false);
    }
  }

  async function handleTaskSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTaskPending(true);
    setTaskError(null);
    setTaskResult(null);

    try {
      const payload = await runAgentTask({
        project_path: projectPath.trim(),
        task: task.trim(),
      });
      setTaskResult(payload);
    } catch (error) {
      setTaskError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to run the task through the local worker.",
      );
    } finally {
      setTaskPending(false);
    }
  }

  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "checking"
        ? "Checking"
        : "Unavailable";

  const canRunTask = connectionState === "connected" && Boolean(repoResult);

  return (
    <>
      <section className="hero">
        <div className="panel hero-panel">
          <span className="hero-kicker">Hosted UI + local worker</span>
          <h2>OpenPatch can now drive a local worker from the web UI.</h2>
          <p>
            Use the hosted interface to confirm worker availability, open a repository
            on your machine, and run a basic read-only task through the local worker.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>Local by default</strong>
              <span>Repository access and command execution stay on the developer machine.</span>
            </div>
            <div className="mini-card">
              <strong>Simple onboarding</strong>
              <span>Health status, repository open, and task execution are visible in one place.</span>
            </div>
            <div className="mini-card">
              <strong>Read-only first</strong>
              <span>This first flow focuses on clarity and end-to-end usability before editing UX.</span>
            </div>
          </div>
        </div>

        <section className="panel status-panel" aria-labelledby="worker-status-title">
          <p className="section-label">Worker Connection</p>
          <div className="status-card">
            <span className={`status-pill status-pill-${connectionState}`}>
              {connectionLabel}
            </span>
            <h3 id="worker-status-title">Local worker status</h3>
            <p>{healthDetail}</p>
          </div>
          <div className="status-card">
            <strong>Configured worker URL</strong>
            <p className="mono">{workerBaseUrl}</p>
          </div>
          <div className="status-card">
            <strong>Reported repo base directory</strong>
            <p className="mono">{repoBaseDir || "Waiting for worker health response"}</p>
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={() => void refreshHealthCheck()}
            disabled={connectionState === "checking"}
          >
            Refresh status
          </button>
        </section>
      </section>

      <section className="workspace">
        <section className="panel composer-panel" aria-labelledby="repo-open-title">
          <p className="section-label">Repository</p>
          <h3 id="repo-open-title">Open a repository through the local worker</h3>
          <p>
            Enter a project path and branch. The local worker will clone the repository
            if needed, then fetch and check out the requested branch on your machine.
          </p>

          <form className="task-form" onSubmit={handleRepoOpen}>
            <label className="field-label" htmlFor="project-path">
              Project path
            </label>
            <input
              id="project-path"
              className="text-input mono"
              value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)}
              placeholder="group/demo-repo"
            />

            <div className="inline-fields">
              <div className="field-group">
                <label className="field-label" htmlFor="branch">
                  Branch
                </label>
                <input
                  id="branch"
                  className="text-input mono"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  placeholder="main"
                />
              </div>

              <div className="field-group">
                <label className="field-label" htmlFor="git-provider">
                  Git provider
                </label>
                <select
                  id="git-provider"
                  className="text-input"
                  value={gitProvider}
                  onChange={(event) => setGitProvider(event.target.value)}
                >
                  <option value="gitlab">gitlab</option>
                  <option value="github">github</option>
                  <option value="">use worker defaults</option>
                </select>
              </div>
            </div>

            {repoError ? <p className="inline-error">{repoError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                This request is sent to the local worker, not directly to your repository host.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={repoPending || connectionState !== "connected"}
              >
                {repoPending ? "Opening..." : "Open repository"}
              </button>
            </div>
          </form>

          {repoResult ? (
            <div className="result-card">
              <strong>Repository ready</strong>
              <p>{repoResult.message}</p>
              <p className="mono">{repoResult.local_repo_path}</p>
              <p className="result-meta">
                Branch: {repoResult.branch} | HEAD: {repoResult.head_sha}
              </p>
            </div>
          ) : (
            <div className="response-placeholder">
              <strong>Awaiting repository open</strong>
              <p>
                Open a repository first so the worker has a local repo to inspect for
                the read-only task flow.
              </p>
            </div>
          )}
        </section>

        <section className="panel response-panel" aria-labelledby="task-run-title">
          <p className="section-label">Read-Only Task</p>
          <h3 id="task-run-title">Ask the worker to run a task</h3>
          <p>
            Submit a question or request. The worker gathers a small amount of local
            repository context, calls the centralized model backend, and returns the
            response here.
          </p>

          <form className="task-form" onSubmit={handleTaskSubmit}>
            <label className="field-label" htmlFor="task-input">
              Task
            </label>
            <textarea
              id="task-input"
              className="task-textarea"
              value={task}
              onChange={(event) => setTask(event.target.value)}
              placeholder="Ask for a summary, architecture walkthrough, or likely starting point for changes..."
            />

            {taskError ? <p className="inline-error">{taskError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                This first hosted flow is read-only and does not modify files.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={taskPending || !canRunTask}
              >
                {taskPending ? "Running..." : "Run task"}
              </button>
            </div>
          </form>

          <div className="response-shell">
            {taskResult ? (
              <>
                <div className="response-placeholder">
                  <strong>Generated response</strong>
                  <p>{taskResult.response}</p>
                </div>
                <div className="response-meta">
                  <div className="meta-card">
                    <strong>Model</strong>
                    <span>{taskResult.model}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Context summary</strong>
                    <span>{taskResult.context_summary}</span>
                  </div>
                </div>
              </>
            ) : (
              <div className="response-placeholder">
                <strong>Awaiting task result</strong>
                <p>
                  After you open a repository and run a task, the local worker response
                  will appear here.
                </p>
              </div>
            )}
          </div>
        </section>
      </section>
    </>
  );
}
