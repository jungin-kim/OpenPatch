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

type AgentProposeFilePayload = {
  repo_path: string;
  relative_path: string;
  model: string;
  context_summary: string;
  original_content: string;
  proposed_content: string;
};

type FileWritePayload = {
  project_path: string;
  relative_path: string;
  bytes_written: number;
  message: string;
};

type GitDiffPayload = {
  project_path: string;
  diff: string;
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
  const [editPath, setEditPath] = useState("README.md");
  const [editInstruction, setEditInstruction] = useState(
    "Rewrite the introduction to explain the local worker architecture more clearly.",
  );

  const [repoPending, setRepoPending] = useState(false);
  const [taskPending, setTaskPending] = useState(false);
  const [proposalPending, setProposalPending] = useState(false);
  const [applyPending, setApplyPending] = useState(false);

  const [repoError, setRepoError] = useState<string | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [agentResult, setAgentResult] = useState<AgentRunPayload | null>(null);
  const [proposalResult, setProposalResult] =
    useState<AgentProposeFilePayload | null>(null);
  const [writeResult, setWriteResult] = useState<FileWritePayload | null>(null);
  const [diffResult, setDiffResult] = useState<GitDiffPayload | null>(null);

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
    setProposalResult(null);
    setDiffResult(null);
    setWriteResult(null);

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

  async function handleProposalSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProposalPending(true);
    setProposalError(null);
    setApplyError(null);
    setWriteResult(null);
    setDiffResult(null);
    setProposalResult(null);

    try {
      const response = await fetch("/api/worker/propose-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_path: projectPath,
          relative_path: editPath,
          instruction: editInstruction,
        }),
      });
      const payload = (await response.json()) as
        | AgentProposeFilePayload
        | { detail?: string };

      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : "File proposal request failed.",
        );
      }

      setProposalResult(payload);
    } catch (error) {
      setProposalError(
        error instanceof Error ? error.message : "Unable to propose a file change.",
      );
    } finally {
      setProposalPending(false);
    }
  }

  async function handleApplyProposal() {
    if (!proposalResult) {
      return;
    }

    setApplyPending(true);
    setApplyError(null);
    setWriteResult(null);
    setDiffResult(null);

    try {
      const writeResponse = await fetch("/api/worker/fs-write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: projectPath,
          relative_path: proposalResult.relative_path,
          content: proposalResult.proposed_content,
        }),
      });
      const writePayload = (await writeResponse.json()) as
        | FileWritePayload
        | { detail?: string };

      if (!writeResponse.ok) {
        throw new Error(
          "detail" in writePayload && writePayload.detail
            ? writePayload.detail
            : "File write request failed.",
        );
      }

      setWriteResult(writePayload);

      const diffResponse = await fetch("/api/worker/git-diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: projectPath,
          relative_paths: [proposalResult.relative_path],
        }),
      });
      const diffPayload = (await diffResponse.json()) as
        | GitDiffPayload
        | { detail?: string };

      if (!diffResponse.ok) {
        throw new Error(
          "detail" in diffPayload && diffPayload.detail
            ? diffPayload.detail
            : "Git diff request failed.",
        );
      }

      setDiffResult(diffPayload);
    } catch (error) {
      setApplyError(
        error instanceof Error ? error.message : "Unable to apply the proposed change.",
      );
    } finally {
      setApplyPending(false);
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
          <h2>OpenPatch now supports explicit proposal, write, and diff review steps.</h2>
          <p>
            The UI can verify worker availability, open a repository, run read-only
            tasks, request a file proposal, apply that exact content explicitly, and
            show the resulting git diff.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>Worker health</strong>
              <span>Visible connection checks and graceful unavailable states.</span>
            </div>
            <div className="mini-card">
              <strong>Proposal review</strong>
              <span>Current and proposed file content are visible before writing.</span>
            </div>
            <div className="mini-card">
              <strong>Explicit write</strong>
              <span>No auto-commit and no auto-push. Diff review stays in the UI.</span>
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
            directory. This sets up the read-only and edit-review flows.
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
          <p className="section-label">Read-Only Task</p>
          <h3 id="task-run-title">Run a repository task</h3>
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
                This flow remains read-only and does not change files.
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
              <div className="response-placeholder">
                <strong>Awaiting task result</strong>
                <p>
                  After a successful task run, the generated response from `/agent/run`
                  will appear here.
                </p>
              </div>
            )}
          </div>
        </section>
      </section>

      <section className="edit-workspace">
        <section className="panel composer-panel" aria-labelledby="proposal-title">
          <p className="section-label">Edit Proposal</p>
          <h3 id="proposal-title">Ask the model to propose a full-file replacement</h3>
          <p>
            This first editing flow is explicit: propose content for one file, inspect
            it, then choose whether to write it.
          </p>

          <form className="task-form" onSubmit={handleProposalSubmit}>
            <label className="field-label" htmlFor="edit-path">
              File path
            </label>
            <input
              id="edit-path"
              className="text-input mono"
              value={editPath}
              onChange={(event) => setEditPath(event.target.value)}
              placeholder="README.md"
            />

            <label className="field-label" htmlFor="edit-instruction">
              Change request
            </label>
            <textarea
              id="edit-instruction"
              className="task-textarea task-textarea-compact"
              value={editInstruction}
              onChange={(event) => setEditInstruction(event.target.value)}
              placeholder="Describe the exact change you want proposed..."
            />

            {proposalError ? <p className="inline-error">{proposalError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                The model returns a visible full replacement file, not an automatic edit.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={proposalPending || connectionState !== "connected"}
              >
                {proposalPending ? "Proposing..." : "Propose change"}
              </button>
            </div>
          </form>

          {proposalResult ? (
            <div className="response-meta">
              <div className="meta-card">
                <strong>Proposal model</strong>
                <span>{proposalResult.model}</span>
              </div>
              <div className="meta-card">
                <strong>Context summary</strong>
                <span>{proposalResult.context_summary}</span>
              </div>
            </div>
          ) : null}
        </section>

        <section className="panel response-panel" aria-labelledby="review-title">
          <p className="section-label">Review</p>
          <h3 id="review-title">Inspect the current and proposed file content</h3>
          <p>
            File writes only happen when you explicitly apply the proposal below.
          </p>

          {proposalResult ? (
            <>
              <div className="code-review-grid">
                <div className="code-card">
                  <strong>Current content</strong>
                  <pre className="code-block">{proposalResult.original_content || "(file does not exist yet)"}</pre>
                </div>
                <div className="code-card">
                  <strong>Proposed content</strong>
                  <pre className="code-block">{proposalResult.proposed_content}</pre>
                </div>
              </div>

              {applyError ? <p className="inline-error">{applyError}</p> : null}

              <div className="task-actions">
                <span className="task-hint">
                  Apply writes only this file and does not commit or push anything.
                </span>
                <button
                  className="primary-button"
                  type="button"
                  onClick={() => void handleApplyProposal()}
                  disabled={applyPending}
                >
                  {applyPending ? "Applying..." : "Apply proposed file"}
                </button>
              </div>
            </>
          ) : (
            <div className="response-placeholder">
              <strong>Awaiting proposal</strong>
              <p>
                Request a file proposal to inspect the current content, the proposed
                replacement, and the resulting diff after an explicit write.
              </p>
            </div>
          )}
        </section>
      </section>

      <section className="workspace">
        <section className="panel response-panel" aria-labelledby="diff-title">
          <p className="section-label">Result</p>
          <h3 id="diff-title">Inspect the write result and git diff</h3>
          <p>
            After applying a proposal, the worker returns the write result and the
            current unstaged diff for the edited file.
          </p>

          {writeResult ? (
            <div className="result-card">
              <strong>Write complete</strong>
              <p>{writeResult.message}</p>
              <p className="result-meta">
                File: {writeResult.relative_path} | Bytes written: {writeResult.bytes_written}
              </p>
            </div>
          ) : null}

          <div className="response-shell">
            {diffResult ? (
              <div className="code-card">
                <strong>Git diff</strong>
                <pre className="code-block">{diffResult.diff || "(no diff returned)"}</pre>
              </div>
            ) : (
              <div className="response-placeholder">
                <strong>Awaiting write result</strong>
                <p>The git diff for the edited file will appear here after an explicit apply step.</p>
              </div>
            )}
          </div>
        </section>
      </section>
    </>
  );
}
