"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getProviderBranches,
  getProviderProjects,
  getWorkerHealth,
  LocalWorkerClientError,
  openRepository,
  runAgentTask,
  type AgentRunPayload,
  type ProviderBranchSummary,
  type ProviderProjectSummary,
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

  const [gitProvider, setGitProvider] = useState("gitlab");
  const [projectSearch, setProjectSearch] = useState("");
  const [selectedProjectPath, setSelectedProjectPath] = useState("");
  const [selectedBranch, setSelectedBranch] = useState("");
  const [useAdvanced, setUseAdvanced] = useState(false);
  const [manualProjectPath, setManualProjectPath] = useState("");
  const [manualBranch, setManualBranch] = useState("");

  const [projectsPending, setProjectsPending] = useState(false);
  const [branchesPending, setBranchesPending] = useState(false);
  const [repoPending, setRepoPending] = useState(false);
  const [questionPending, setQuestionPending] = useState(false);

  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [branchesError, setBranchesError] = useState<string | null>(null);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [questionError, setQuestionError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ProviderProjectSummary[]>([]);
  const [recentProjects, setRecentProjects] = useState<ProviderProjectSummary[]>([]);
  const [branches, setBranches] = useState<ProviderBranchSummary[]>([]);

  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [questionResult, setQuestionResult] = useState<AgentRunPayload | null>(null);
  const [question, setQuestion] = useState(
    "Summarize this repository and tell me the best place to start reading the code.",
  );

  async function refreshHealthCheck() {
    setConnectionState("checking");
    setHealthDetail("Checking for a reachable local worker.");

    try {
      const payload = await getWorkerHealth();
      setConnectionState("connected");
      setHealthDetail(`Worker is available and reporting status '${payload.status}'.`);
      setRepoBaseDir(payload.repo_base_dir);
      if (payload.configured_git_provider) {
        setGitProvider(payload.configured_git_provider);
      }
      if (payload.recent_projects?.length) {
        setManualProjectPath((current) => current || payload.recent_projects?.[0] || "");
      }
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

  useEffect(() => {
    if (connectionState !== "connected") {
      return;
    }

    let cancelled = false;
    async function loadProjects() {
      setProjectsPending(true);
      setProjectsError(null);

      try {
        const payload = await getProviderProjects({
          git_provider: gitProvider,
          search: projectSearch.trim() || undefined,
        });
        if (cancelled) {
          return;
        }

        setProjects(payload.projects);
        setRecentProjects(payload.recent_projects);

        const availablePaths = new Set([
          ...payload.projects.map((project) => project.project_path),
          ...payload.recent_projects.map((project) => project.project_path),
        ]);

        if (!selectedProjectPath || !availablePaths.has(selectedProjectPath)) {
          const preferred =
            payload.recent_projects[0]?.project_path ||
            payload.projects[0]?.project_path ||
            "";
          setSelectedProjectPath(preferred);
          setManualProjectPath((current) => current || preferred);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setProjects([]);
        setRecentProjects([]);
        setProjectsError(
          error instanceof LocalWorkerClientError || error instanceof Error
            ? error.message
            : "Unable to load projects from the configured git provider.",
        );
      } finally {
        if (!cancelled) {
          setProjectsPending(false);
        }
      }
    }

    void loadProjects();
    return () => {
      cancelled = true;
    };
  }, [connectionState, gitProvider, projectSearch]);

  useEffect(() => {
    if (connectionState !== "connected" || !selectedProjectPath || useAdvanced) {
      return;
    }

    let cancelled = false;
    async function loadBranches() {
      setBranchesPending(true);
      setBranchesError(null);

      try {
        const payload = await getProviderBranches({
          git_provider: gitProvider,
          project_path: selectedProjectPath,
        });
        if (cancelled) {
          return;
        }

        setBranches(payload.branches);
        const nextBranch =
          payload.default_branch ||
          payload.branches.find((branch) => branch.is_default)?.name ||
          payload.branches[0]?.name ||
          "";
        setSelectedBranch(nextBranch);
        setManualBranch((current) => current || nextBranch);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setBranches([]);
        setSelectedBranch("");
        setBranchesError(
          error instanceof LocalWorkerClientError || error instanceof Error
            ? error.message
            : "Unable to load branches for the selected project.",
        );
      } finally {
        if (!cancelled) {
          setBranchesPending(false);
        }
      }
    }

    void loadBranches();
    return () => {
      cancelled = true;
    };
  }, [connectionState, gitProvider, selectedProjectPath, useAdvanced]);

  const filteredProjects = useMemo(() => {
    if (!projectSearch.trim()) {
      return projects;
    }
    const query = projectSearch.trim().toLowerCase();
    return projects.filter(
      (project) =>
        project.project_path.toLowerCase().includes(query) ||
        project.display_name.toLowerCase().includes(query),
    );
  }, [projectSearch, projects]);

  const effectiveProjectPath = useAdvanced
    ? manualProjectPath.trim()
    : selectedProjectPath.trim();
  const effectiveBranch = useAdvanced ? manualBranch.trim() : selectedBranch.trim();

  async function handleRepoOpen(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRepoPending(true);
    setRepoError(null);
    setQuestionError(null);
    setQuestionResult(null);

    if (!effectiveProjectPath || !effectiveBranch) {
      setRepoPending(false);
      setRepoError("Choose a project and branch, or use the advanced override fields.");
      return;
    }

    try {
      const payload = await openRepository({
        project_path: effectiveProjectPath,
        branch: effectiveBranch,
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
        project_path: effectiveProjectPath,
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
          <span className="hero-kicker">Guided repository selection</span>
          <h2>Choose a project from your provider instead of typing repository details manually.</h2>
          <p>
            OpenPatch can now load available projects and branches from the configured
            provider, suggest recent repositories, and keep manual entry tucked away as
            an advanced fallback.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>1. Connect</strong>
              <span>Confirm the local worker is reachable on your machine.</span>
            </div>
            <div className="mini-card">
              <strong>2. Select</strong>
              <span>Choose a provider, project, and branch from guided lists.</span>
            </div>
            <div className="mini-card">
              <strong>3. Ask</strong>
              <span>Open the repository locally and run a read-only question.</span>
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
          <h3 id="repo-open-title">Select a repository through the local worker</h3>
          <p>
            Choose a provider first, then load available projects and branches. Manual
            repository and branch entry is still available under Advanced when you need it.
          </p>

          <form className="task-form" onSubmit={handleRepoOpen}>
            <div className="inline-fields inline-fields-two">
              <div className="field-group">
                <label className="field-label" htmlFor="git-provider">
                  Git provider
                </label>
                <select
                  id="git-provider"
                  className="text-input"
                  value={gitProvider}
                  onChange={(event) => {
                    const nextProvider = event.target.value;
                    setGitProvider(nextProvider);
                    setSelectedProjectPath("");
                    setSelectedBranch("");
                    setProjects([]);
                    setBranches([]);
                    setRepoResult(null);
                  }}
                >
                  <option value="gitlab">gitlab</option>
                  <option value="github">github</option>
                </select>
              </div>

              <div className="field-group">
                <label className="field-label" htmlFor="project-search">
                  Search projects
                </label>
                <input
                  id="project-search"
                  className="text-input"
                  value={projectSearch}
                  onChange={(event) => setProjectSearch(event.target.value)}
                  placeholder="Search by project name or path"
                />
              </div>
            </div>

            {recentProjects.length ? (
              <div className="recent-projects">
                <strong>Recent projects</strong>
                <div className="recent-project-list">
                  {recentProjects.map((project) => (
                    <button
                      key={`${project.git_provider}:${project.project_path}`}
                      className={`recent-project-chip${selectedProjectPath === project.project_path ? " recent-project-chip-active" : ""}`}
                      type="button"
                      onClick={() => {
                        setUseAdvanced(false);
                        setSelectedProjectPath(project.project_path);
                        setProjectSearch(project.project_path);
                        setRepoResult(null);
                      }}
                    >
                      {project.display_name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="field-group">
              <label className="field-label" htmlFor="project-select">
                Project
              </label>
              <select
                id="project-select"
                className="text-input text-select-list mono"
                size={Math.min(Math.max(filteredProjects.length, 4), 8)}
                value={selectedProjectPath}
                onChange={(event) => {
                  setUseAdvanced(false);
                  setSelectedProjectPath(event.target.value);
                  setRepoResult(null);
                }}
                disabled={projectsPending || connectionState !== "connected" || filteredProjects.length === 0}
              >
                {filteredProjects.map((project) => (
                  <option key={project.project_path} value={project.project_path}>
                    {project.display_name}
                  </option>
                ))}
              </select>
              <p className="field-help">
                {projectsPending
                  ? "Loading projects from the configured provider..."
                  : filteredProjects.length
                    ? "Choose a project from the provider response."
                    : "No projects are available for the current search or provider."}
              </p>
            </div>

            <div className="field-group">
              <label className="field-label" htmlFor="branch-select">
                Branch
              </label>
              <select
                id="branch-select"
                className="text-input mono"
                value={selectedBranch}
                onChange={(event) => {
                  setUseAdvanced(false);
                  setSelectedBranch(event.target.value);
                  setRepoResult(null);
                }}
                disabled={
                  branchesPending ||
                  connectionState !== "connected" ||
                  !selectedProjectPath ||
                  branches.length === 0
                }
              >
                {branches.map((branch) => (
                  <option key={branch.name} value={branch.name}>
                    {branch.name}{branch.is_default ? " (default)" : ""}
                  </option>
                ))}
              </select>
              <p className="field-help">
                {branchesPending
                  ? "Loading branches for the selected project..."
                  : branches.length
                    ? "The default branch is selected automatically when the provider reports one."
                    : "Branches will appear here after you choose a project."}
              </p>
            </div>

            {(projectsError || branchesError) ? (
              <p className="inline-error">
                {projectsError || branchesError}
              </p>
            ) : null}

            <div className="advanced-toggle-row">
              <button
                className="secondary-button"
                type="button"
                onClick={() => {
                  const nextValue = !useAdvanced;
                  setUseAdvanced(nextValue);
                  if (nextValue) {
                    setManualProjectPath(selectedProjectPath);
                    setManualBranch(selectedBranch);
                  }
                }}
              >
                {useAdvanced ? "Hide advanced fields" : "Advanced manual override"}
              </button>
            </div>

            {useAdvanced ? (
              <div className="advanced-panel">
                <div className="inline-fields inline-fields-two">
                  <div className="field-group">
                    <label className="field-label" htmlFor="manual-project-path">
                      Manual project path
                    </label>
                    <input
                      id="manual-project-path"
                      className="text-input mono"
                      value={manualProjectPath}
                      onChange={(event) => setManualProjectPath(event.target.value)}
                      placeholder="group/private-repo"
                    />
                  </div>
                  <div className="field-group">
                    <label className="field-label" htmlFor="manual-branch">
                      Manual branch
                    </label>
                    <input
                      id="manual-branch"
                      className="text-input mono"
                      value={manualBranch}
                      onChange={(event) => setManualBranch(event.target.value)}
                      placeholder="main"
                    />
                  </div>
                </div>
                <p className="field-help">
                  Use this only when the guided provider lists are missing the repository or branch you need.
                </p>
              </div>
            ) : null}

            {repoError ? <p className="inline-error">{repoError}</p> : null}

            <div className="task-actions">
              <span className="task-hint">
                OpenPatch keeps guided selection as the default experience and falls back to manual entry only when needed.
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
                  Choose a provider, project, and branch first so the local worker can
                  prepare a repository for your question.
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
                This flow stays read-only. It does not modify files, branches, or commits.
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
