"use client";

import { useEffect, useRef, useState } from "react";
import {
  checkoutLocalBranch,
  createLocalBranch,
  listLocalBranches,
  LocalWorkerClientError,
  type LocalBranchSummary,
} from "@/lib/local-worker-client";

interface BranchPanelProps {
  projectPath: string;
  currentBranch: string | null | undefined;
  /** Called after a successful branch create or checkout so the parent can update its state. */
  onBranchChange: (newBranch: string) => void;
}

type PanelMode = "idle" | "list" | "create";

const BRANCH_RE = /^[a-zA-Z0-9._/\-]+$/;

function validateBranchName(name: string): string | null {
  if (!name.trim()) return "Branch name is required.";
  if (name.startsWith("-")) return "Branch name must not start with a hyphen.";
  if (name.includes("..")) return "Branch name must not contain '..'";
  if (name.includes(" ")) return "Branch name must not contain spaces.";
  if (!BRANCH_RE.test(name)) return "Branch name contains invalid characters.";
  return null;
}

export function BranchPanel({ projectPath, currentBranch, onBranchChange }: BranchPanelProps) {
  const [mode, setMode] = useState<PanelMode>("idle");
  const [branches, setBranches] = useState<LocalBranchSummary[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [baseBranch, setBaseBranch] = useState(currentBranch ?? "HEAD");
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Keep baseBranch in sync when currentBranch changes from the outside.
  useEffect(() => {
    setBaseBranch(currentBranch ?? "HEAD");
  }, [currentBranch]);

  // Load branches when entering list or create mode.
  useEffect(() => {
    if (mode === "idle") return;
    let cancelled = false;

    async function load() {
      setLoadingBranches(true);
      setError(null);
      try {
        const payload = await listLocalBranches({ project_path: projectPath });
        if (!cancelled) setBranches(payload.branches);
      } catch {
        if (!cancelled) setError("Unable to load local branches.");
      } finally {
        if (!cancelled) setLoadingBranches(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [mode, projectPath]);

  // Auto-focus the new-branch input.
  useEffect(() => {
    if (mode === "create") {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [mode]);

  // Close panel on outside click.
  useEffect(() => {
    if (mode === "idle") return;
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        handleClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [mode]);

  function handleClose() {
    setMode("idle");
    setNewBranchName("");
    setError(null);
    setSuccessMessage(null);
  }

  async function handleCheckout(branchName: string) {
    if (branchName === currentBranch) return handleClose();
    setActionPending(true);
    setError(null);
    try {
      const result = await checkoutLocalBranch({
        project_path: projectPath,
        branch: branchName,
      });
      setSuccessMessage(result.message);
      onBranchChange(result.branch);
      setTimeout(handleClose, 1200);
    } catch (err) {
      setError(
        err instanceof LocalWorkerClientError || err instanceof Error
          ? err.message
          : "Unable to switch branch.",
      );
    } finally {
      setActionPending(false);
    }
  }

  async function handleCreateBranch(e: React.FormEvent) {
    e.preventDefault();
    const name = newBranchName.trim();
    const validationError = validateBranchName(name);
    if (validationError) {
      setError(validationError);
      return;
    }
    setActionPending(true);
    setError(null);
    try {
      const result = await createLocalBranch({
        project_path: projectPath,
        branch: name,
        from_ref: baseBranch || "HEAD",
        checkout: true,
      });
      setSuccessMessage(result.message);
      onBranchChange(result.branch);
      setTimeout(handleClose, 1200);
    } catch (err) {
      setError(
        err instanceof LocalWorkerClientError || err instanceof Error
          ? err.message
          : "Unable to create branch.",
      );
    } finally {
      setActionPending(false);
    }
  }

  const branchLabel = currentBranch || "no branch";

  return (
    <div className="branch-panel-wrapper" ref={panelRef}>
      {/* Trigger button */}
      <button
        className="branch-pill"
        type="button"
        onClick={() => setMode((m) => (m === "idle" ? "list" : "idle"))}
        title="Branch options"
      >
        <span className="branch-pill-icon" aria-hidden="true" />
        <span className="branch-pill-label">{branchLabel}</span>
        <span className="branch-pill-caret">▾</span>
      </button>

      {/* Dropdown panel */}
      {mode !== "idle" && (
        <div className="branch-dropdown">
          {/* Header */}
          <div className="branch-dropdown-header">
            <span className="branch-dropdown-title">
              {mode === "create" ? "New branch" : "Branches"}
            </span>
            <div style={{ display: "flex", gap: 6 }}>
              {mode === "list" && (
                <button
                  className="branch-action-btn"
                  type="button"
                  onClick={() => { setMode("create"); setError(null); }}
                >
                  + New
                </button>
              )}
              {mode === "create" && (
                <button
                  className="branch-action-btn branch-action-btn-ghost"
                  type="button"
                  onClick={() => setMode("list")}
                >
                  ← Back
                </button>
              )}
              <button
                className="branch-action-btn branch-action-btn-ghost"
                type="button"
                onClick={handleClose}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
          </div>

          {successMessage && (
            <div className="branch-feedback branch-feedback-ok">{successMessage}</div>
          )}
          {error && (
            <div className="branch-feedback branch-feedback-err">{error}</div>
          )}

          {/* Branch list */}
          {mode === "list" && (
            <ul className="branch-list">
              {loadingBranches ? (
                <li className="branch-list-item branch-list-empty">Loading…</li>
              ) : branches.length === 0 ? (
                <li className="branch-list-item branch-list-empty">No local branches found.</li>
              ) : (
                branches.map((b) => (
                  <li key={b.name}>
                    <button
                      className={`branch-list-item${b.is_current ? " branch-list-item-active" : ""}`}
                      type="button"
                      disabled={actionPending}
                      onClick={() => void handleCheckout(b.name)}
                    >
                      <span className="branch-list-name">{b.name}</span>
                      {b.is_current && <span className="branch-list-badge">current</span>}
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}

          {/* Create branch form */}
          {mode === "create" && (
            <form className="branch-create-form" onSubmit={(e) => void handleCreateBranch(e)}>
              <label className="branch-create-label" htmlFor="new-branch-name">
                Branch name
              </label>
              <input
                id="new-branch-name"
                ref={inputRef}
                className="branch-create-input"
                type="text"
                value={newBranchName}
                onChange={(e) => { setNewBranchName(e.target.value); setError(null); }}
                placeholder="feature/my-change"
                disabled={actionPending}
                autoComplete="off"
                spellCheck={false}
              />
              <label className="branch-create-label" htmlFor="base-branch">
                Base branch
              </label>
              {loadingBranches ? (
                <div className="branch-create-base-placeholder">Loading…</div>
              ) : (
                <select
                  id="base-branch"
                  className="branch-create-select"
                  value={baseBranch}
                  onChange={(e) => setBaseBranch(e.target.value)}
                  disabled={actionPending}
                >
                  {branches.map((b) => (
                    <option key={b.name} value={b.name}>{b.name}</option>
                  ))}
                  {branches.length === 0 && (
                    <option value="HEAD">HEAD</option>
                  )}
                </select>
              )}
              <button
                className="branch-create-submit"
                type="submit"
                disabled={actionPending || !newBranchName.trim()}
              >
                {actionPending ? "Creating…" : "Create and switch"}
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
