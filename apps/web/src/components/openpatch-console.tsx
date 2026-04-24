"use client";

import { useEffect, useState } from "react";

type HealthPayload = {
  status: string;
  service: string;
  repo_base_dir: string;
};

type RepoOpenPayload = {
  project_path: string;
  local_repo_path: string;
  branch: string;
  head_sha: string;
  cloned: boolean;
  message: string;
};

type AgentRunPayload = {
  repo_path: string;
  model: string;
  context_summary: string;
  response: string;
};

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
    "Summarize the repository and identify the most likely place to start reading.",
  );
  const [repoPending, setRepoPending] = useState(false);
  const [taskPending, setTaskPending] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [agentResult, setAgentResult] = useState<AgentRunPayload | null>(null);

  async function refreshHealthCheck() {
    setConnectionState("checking");
    setHealthDetail("Checking for a reachable local worker.");

    try {
      const response = await fetch("/api/worker/health", { cache: "no-store" });
      const payload = (await response.json()) as HealthPayload | { detail?: string };

      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : "The local worker did not respond successfully.",
        );
      }

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
    setRepoResult(null);
    setAgentResult(null);
    setAgentError(null);

    try {
      const response = await fetch("/api/worker/repo-open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: projectPath,
          branch,
          git_provider: gitProvider || undefined,
        }),
      });
      const payload = (await response.json()) as RepoOpenPayload | { detail?: string };

      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : "Repository open request failed.",
        );
      }

      setRepoResult(payload);
      await refreshHealthCheck();
    } catch (error) {
      setRepoError(
        error instanceof Error ? error.message : "Unable to open the repository.",
      );
    } finally {
      setRepoPending(false);
    }
  }

  async function handleTaskSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTaskPending(true);
    setAgentError(null);
    setAgentResult(null);

    try {
      const response = await fetch("/api/worker/agent-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_path: projectPath,
          task,
        }),
      });
      const payload = (await response.json()) as AgentRunPayload | { detail?: string };

      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : "Agent request failed.",
        );
      }

      setAgentResult(payload);
    } catch (error) {
      setAgentError(
        error instanceof Error ? error.message : "Unable to run the agent task.",
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

  return (
    <>
      <section className="hero">
        <div className="panel hero-panel">
          <span className="hero-kicker">Hosted UI + local worker + central inference</span>
          <h2>OpenPatch can now reach a local worker for read-only repository tasks.</h2>
          <p>
            This connected UI can verify worker availability, open a repository, and
            send a basic read-only task to the worker&apos;s centralized model flow.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>Worker health</strong>
              <span>Visible connection checks and graceful unavailable states.</span>
            </div>
            <div className="mini-card">
              <strong>Repository open</strong>
              <span>Open or fetch a repository through the local worker.</span>
            </div>
            <div className="mini-card">
              <strong>Read-only tasks</strong>
              <span>Submit a task and display the generated response from `/agent/run`.</span>
            </div>
          </div>
        </div>

        <section className="panel status-panel" aria-labelledby="worker-status-title">
          <p className="section-label">Worker Connection</p>
          <div className="status-card">
            <span className={`status-pill status-pill-${connectionState}`}>
              {connectionLabel}
            </span>
            <h3 id="worker-status-title">Local worker connection</h3>
            <p>{healthDetail}</p>
          </div>
          <div className="status-card">
            <strong>Configured worker base URL</strong>
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
          <h3 id="repo-open-title">Open repository through the local worker</h3>
          <p>
            Use a repository path under the worker&apos;s configured local repo base
            directory. The first version remains read-only from the UI.
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
                  <option value="">custom worker config</option>
                </select>
              </div>
            </div>

            {repoError ? <p className="inline-error">{repoError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                The worker will clone if missing, then fetch and check out the branch.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={repoPending || connectionState === "checking"}
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
          ) : null}
        </section>

        <section className="panel response-panel" aria-labelledby="task-run-title">
          <p className="section-label">Task</p>
          <h3 id="task-run-title">Run a read-only repository task</h3>
          <p>
            Submit a task to the local worker. It will gather a small amount of local
            repository context and call the centralized model backend.
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
              placeholder="Ask for a summary, architecture readout, or likely starting point for changes..."
            />

            {agentError ? <p className="inline-error">{agentError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                This first flow is read-only. Editing and patch application are not wired yet.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={taskPending || connectionState !== "connected"}
              >
                {taskPending ? "Running..." : "Run task"}
              </button>
            </div>
          </form>

          <div className="response-shell">
            {agentResult ? (
              <>
                <div className="response-placeholder">
                  <strong>Generated response</strong>
                  <p>{agentResult.response}</p>
                </div>
                <div className="response-meta">
                  <div className="meta-card">
                    <strong>Model</strong>
                    <span>{agentResult.model}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Context summary</strong>
                    <span>{agentResult.context_summary}</span>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="response-placeholder">
                  <strong>Awaiting task result</strong>
                  <p>
                    After a successful task run, the generated response from
                    `/agent/run` will appear here.
                  </p>
                </div>
                <div className="response-meta">
                  <div className="meta-card">
                    <strong>Connection state</strong>
                    <span>{connectionLabel}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Active target</strong>
                    <span className="mono">{workerBaseUrl}</span>
                  </div>
                </div>
              </>
            )}
          </div>
        </section>
      </section>
    </>
  );
}
