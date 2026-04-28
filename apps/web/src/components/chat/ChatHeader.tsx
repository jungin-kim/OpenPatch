"use client";

import { useState } from "react";
import type { ProviderBranchSummary, ProviderProjectSummary } from "@/lib/local-worker-client";

type ConnectionState = "checking" | "connected" | "unavailable";

interface ChatHeaderProps {
  connectionState: ConnectionState;
  configuredModelName: string;
  configuredModelProvider: string;

  gitProvider: string;
  onGitProviderChange: (value: string) => void;

  projects: ProviderProjectSummary[];
  recentProjects: ProviderProjectSummary[];
  projectsPending: boolean;
  selectedProjectPath: string;
  onProjectChange: (path: string) => void;

  branches: ProviderBranchSummary[];
  branchesPending: boolean;
  selectedBranch: string;
  onBranchChange: (branch: string) => void;

  useAdvanced: boolean;
  manualProjectPath: string;
  manualBranch: string;
  onManualProjectPathChange: (v: string) => void;
  onManualBranchChange: (v: string) => void;
  onToggleAdvanced: () => void;

  repoPending: boolean;
  repoError: string | null;
  onOpenRepo: () => void;
}

export function ChatHeader({
  connectionState,
  configuredModelName,
  configuredModelProvider,
  gitProvider,
  onGitProviderChange,
  projects,
  recentProjects,
  projectsPending,
  selectedProjectPath,
  onProjectChange,
  branches,
  branchesPending,
  selectedBranch,
  onBranchChange,
  useAdvanced,
  manualProjectPath,
  manualBranch,
  onManualProjectPathChange,
  onManualBranchChange,
  onToggleAdvanced,
  repoPending,
  repoError,
  onOpenRepo,
}: ChatHeaderProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "checking"
        ? "Checking"
        : "Unavailable";

  const modelLabel = configuredModelName || configuredModelProvider || "No model";

  const allProjects = [
    ...recentProjects,
    ...projects.filter(
      (p) => !recentProjects.some((r) => r.project_path === p.project_path),
    ),
  ];

  const branchRequired = gitProvider !== "local";
  const effectiveProject = useAdvanced ? manualProjectPath.trim() : selectedProjectPath;
  const effectiveBranch = useAdvanced ? manualBranch.trim() : selectedBranch;
  const canOpen =
    connectionState === "connected" &&
    !repoPending &&
    Boolean(effectiveProject) &&
    (!branchRequired || Boolean(effectiveBranch));

  function handleAdvancedToggle() {
    setShowAdvanced((v) => !v);
    onToggleAdvanced();
  }

  return (
    <div className="chat-header">
      <div className="chat-header-row">
        <div className="chat-header-selectors">
          <select
            className="header-select"
            value={gitProvider}
            onChange={(e) => onGitProviderChange(e.target.value)}
            aria-label="Repository source"
          >
            <option value="gitlab">GitLab</option>
            <option value="github">GitHub</option>
            <option value="local">Local project</option>
          </select>

          <span className="header-sep">/</span>

          <select
            className="header-select"
            value={selectedProjectPath}
            onChange={(e) => onProjectChange(e.target.value)}
            disabled={
              projectsPending ||
              connectionState !== "connected" ||
              allProjects.length === 0
            }
            aria-label="Project"
          >
            {allProjects.length === 0 ? (
              <option value="">
                {projectsPending
                  ? "Loading…"
                  : connectionState !== "connected"
                    ? "Not connected"
                    : gitProvider === "local"
                      ? "No recent local projects"
                      : "No projects"}
              </option>
            ) : null}
            {allProjects.map((p) => (
              <option key={p.project_path} value={p.project_path}>
                {p.display_name}
              </option>
            ))}
          </select>

          {branchRequired && (
            <>
              <span className="header-sep">@</span>
              <select
                className="header-select"
                value={selectedBranch}
                onChange={(e) => onBranchChange(e.target.value)}
                disabled={
                  branchesPending ||
                  connectionState !== "connected" ||
                  !selectedProjectPath ||
                  branches.length === 0
                }
                aria-label="Branch"
              >
                {branches.length === 0 ? (
                  <option value="">
                    {branchesPending ? "Loading…" : "No branch"}
                  </option>
                ) : null}
                {branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                    {b.is_default ? " (default)" : ""}
                  </option>
                ))}
              </select>
            </>
          )}

          {gitProvider === "local" && (
            <input
              className="header-advanced-input"
              value={manualProjectPath}
              onChange={(e) => onManualProjectPathChange(e.target.value)}
              placeholder="/path/to/project"
              aria-label="Local project path"
              style={{ flex: 1, minWidth: "160px", maxWidth: "300px" }}
            />
          )}

          <button
            className="header-open-btn"
            type="button"
            onClick={onOpenRepo}
            disabled={!canOpen}
          >
            {repoPending ? "Opening…" : "Open repository"}
          </button>

          {gitProvider !== "local" && (
            <button
              className="header-icon-btn"
              type="button"
              onClick={handleAdvancedToggle}
              title="Manual path override"
            >
              {showAdvanced ? "▲" : "▼"} Advanced
            </button>
          )}
        </div>

        <div className="chat-header-status">
          <span
            className={`status-pill-sm${
              connectionState === "connected"
                ? " status-pill-sm-connected"
                : connectionState === "checking"
                  ? " status-pill-sm-checking"
                  : ""
            }`}
          >
            {connectionLabel}
          </span>
          {configuredModelProvider && (
            <span className="model-chip" title={modelLabel}>
              {modelLabel}
            </span>
          )}
        </div>
      </div>

      {showAdvanced && gitProvider !== "local" && (
        <div className="chat-header-advanced">
          <div className="header-advanced-field">
            <label className="header-advanced-label" htmlFor="adv-project">
              Manual project path
            </label>
            <input
              id="adv-project"
              className="header-advanced-input"
              value={manualProjectPath}
              onChange={(e) => onManualProjectPathChange(e.target.value)}
              placeholder="group/my-repo"
            />
          </div>
          <div className="header-advanced-field">
            <label className="header-advanced-label" htmlFor="adv-branch">
              Manual branch
            </label>
            <input
              id="adv-branch"
              className="header-advanced-input"
              value={manualBranch}
              onChange={(e) => onManualBranchChange(e.target.value)}
              placeholder="main"
            />
          </div>
          <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--muted)", alignSelf: "flex-end" }}>
            Use only when the project list is missing the repo you need.
          </p>
        </div>
      )}

      {repoError && <p className="header-error">{repoError}</p>}
    </div>
  );
}
