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

  const [projectPath, setProjectPath] = useState("group/private-repo");
  const [branch, setBranch] = useState("main");
  const [gitProvider, setGitProvider] = useState("gitlab");
  const [question, setQuestion] = useState(
    "Summarize this repository and tell me the best place to start reading the code.",
  );

  const [repoPending, setRepoPending] = useState(false);
  const [questionPending, setQuestionPending] = useState(false);

  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [questionResult, setQuestionResult] = useState<AgentRunPayload | null>(null);

  const [repoError, setRepoError] = useState<string | null>(null);
  const [questionError, setQuestionError] = useState<string | null>(null);

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
    setQuestionError(null);
    setQuestionResult(null);

    try {
      const payload = await openRepository({
        project_path: projectPath.trim(),
        branch: branch.trim(),
        git_provider: gitProvider.trim() || undefined,
      });
      setRepoResult(payload);
      await refreshHealthCheck();
    } catch (error) {
      setRepoResult(null);
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to open the repository through the local worker.",
      );
    } finally {
      setRepoPending(false);
    }
  }

  async function handleQuestionSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuestionPending(true);
    setQuestionError(null);
    setQuestionResult(null);

    try {
      const payload = await runAgentTask({
        project_path: projectPath.trim(),
        task: question.trim(),
      });
      setQuestionResult(payload);
    } catch (error) {
      setQuestionError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to run the read-only task through the local worker.",
      );
    } finally {
      setQuestionPending(false);
    }
  }

  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "checking"
        ? "Checking"
        : "Unavailable";

  const repositoryReady = connectionState === "connected" && Boolean(repoResult);

  return (
    <>
      <section className="hero">
        <div className="panel hero-panel">
          <span className="hero-kicker">Read-only repository flow</span>
          <h2>Use OpenPatch from the browser while repository access stays local.</h2>
          <p>
            Open a repository through the local worker, ask a read-only question, and
            review the model response in one simple product flow.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>1. Connect</strong>
              <span>Confirm the local worker is reachable on your machine.</span>
            </div>
            <div className="mini-card">
              <strong>2. Open</strong>
              <span>Prepare the repository locally with provider, path, and branch.</span>
            </div>
            <div className="mini-card">
              <strong>3. Ask</strong>
              <span>Send a read-only repository question and review the response here.</span>
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
            Choose the git provider, repository path, and branch. OpenPatch will ask the
            local worker to clone or refresh the repository on your machine.
          </p>

          <form className="task-form" onSubmit={handleRepoOpen}>
            <div className="inline-fields inline-fields-three">
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
                </select>
              </div>

              <div className="field-group field-group-wide">
                <label className="field-label" htmlFor="project-path">
                  Project path
                </label>
                <input
                  id="project-path"
                  className="text-input mono"
                  value={projectPath}
                  onChange={(event) => setProjectPath(event.target.value)}
                  placeholder="group/private-repo"
                />
              </div>

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
            </div>

            {repoError ? <p className="inline-error">{repoError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                Repository operations happen locally through the worker that is already running.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={repoPending || connectionState !== "connected"}
              >
                {repoPending ? "Opening repository..." : "Open repository"}
              </button>
            </div>
          </form>

          <div className="response-shell">
            {repoResult ? (
              <div className="result-card">
                <strong>Repository ready</strong>
                <p>{repoResult.message}</p>
                <p className="mono">{repoResult.local_repo_path}</p>
                <p className="result-meta">
                  Provider: {gitProvider} | Branch: {repoResult.branch}
                </p>
                <p className="result-meta">HEAD: {repoResult.head_sha}</p>
              </div>
            ) : (
              <div className="response-placeholder">
                <strong>Awaiting repository open</strong>
                <p>
                  Open a repository first so the worker has a local checkout to inspect
                  for your question.
                </p>
              </div>
            )}
          </div>
        </section>

        <section className="panel response-panel" aria-labelledby="question-title">
          <p className="section-label">Question</p>
          <h3 id="question-title">Ask a read-only question</h3>
          <p>
            Submit a repository question. The worker gathers minimal local context and
            calls the configured model backend for a read-only response.
          </p>

          <form className="task-form" onSubmit={handleQuestionSubmit}>
            <label className="field-label" htmlFor="question-input">
              Question
            </label>
            <textarea
              id="question-input"
              className="task-textarea"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask for a summary, architecture walkthrough, or likely starting point for understanding the codebase..."
            />

            {questionError ? <p className="inline-error">{questionError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                This first web flow is read-only and does not modify files or branches.
              </span>
              <button
                className="primary-button"
                type="submit"
                disabled={questionPending || !repositoryReady}
              >
                {questionPending ? "Running question..." : "Ask OpenPatch"}
              </button>
            </div>
          </form>

          <div className="response-shell">
            {questionResult ? (
              <>
                <div className="response-card">
                  <strong>Model response</strong>
                  <p>{questionResult.response}</p>
                </div>

                <div className="response-meta">
                  <div className="meta-card">
                    <strong>Model</strong>
                    <span>{questionResult.model}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Branch</strong>
                    <span>{questionResult.branch}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Repository root</strong>
                    <span>{questionResult.repo_root_name}</span>
                  </div>
                  <div className="meta-card">
                    <strong>Context summary</strong>
                    <span>{questionResult.context_summary}</span>
                  </div>
                </div>
              </>
            ) : (
              <div className="response-placeholder">
                <strong>Awaiting response</strong>
                <p>
                  Once the repository is ready, ask a question and the model response
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
