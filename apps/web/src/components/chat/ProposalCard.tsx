"use client";

import { useState } from "react";
import {
  writeRepositoryFile,
  LocalWorkerClientError,
  type AgentProposeFilePayload,
} from "@/lib/local-worker-client";

export type ProposalStatus = "proposed" | "applied" | "rejected" | "failed";

export type ChangeProposal = {
  id: string;
  projectPath: string;
  branch: string | null | undefined;
  relativePath: string;
  originalContent: string;
  proposedContent: string;
  model: string;
  status: ProposalStatus;
};

interface ProposalCardProps {
  proposal: ChangeProposal;
  writeMode: "read-only" | "write-with-approval" | "auto-apply";
  onStatusChange: (id: string, status: ProposalStatus, message?: string) => void;
}

/** Build a simple unified-style line diff for display (no external library needed). */
function buildLineDiff(original: string, proposed: string): Array<{ kind: "ctx" | "add" | "del"; line: string }> {
  const oldLines = original.split("\n");
  const newLines = proposed.split("\n");

  // Simple longest-common-subsequence diff (good enough for small files)
  const m = oldLines.length;
  const n = newLines.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (oldLines[i] === newLines[j]) {
        dp[i][j] = 1 + dp[i + 1][j + 1];
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  const result: Array<{ kind: "ctx" | "add" | "del"; line: string }> = [];
  let i = 0;
  let j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && oldLines[i] === newLines[j]) {
      result.push({ kind: "ctx", line: oldLines[i] });
      i++;
      j++;
    } else if (j < n && (i >= m || dp[i + 1][j] <= dp[i][j + 1])) {
      result.push({ kind: "add", line: newLines[j] });
      j++;
    } else {
      result.push({ kind: "del", line: oldLines[i] });
      i++;
    }
  }

  return result;
}

function DiffView({ original, proposed }: { original: string; proposed: string }) {
  const diff = buildLineDiff(original, proposed);
  const hasChanges = diff.some((d) => d.kind !== "ctx");

  if (!hasChanges) {
    return (
      <div className="proposal-diff-empty">No changes detected between original and proposed content.</div>
    );
  }

  return (
    <div className="proposal-diff">
      {diff.map((entry, idx) => (
        <div
          key={idx}
          className={`proposal-diff-line proposal-diff-line-${entry.kind}`}
        >
          <span className="proposal-diff-gutter" aria-hidden="true">
            {entry.kind === "add" ? "+" : entry.kind === "del" ? "−" : " "}
          </span>
          <span className="proposal-diff-text">{entry.line}</span>
        </div>
      ))}
    </div>
  );
}

export function ProposalCard({ proposal, writeMode, onStatusChange }: ProposalCardProps) {
  const [applying, setApplying] = useState(false);
  const [showFull, setShowFull] = useState(false);

  const isReadOnly = writeMode === "read-only";
  const isSettled = proposal.status !== "proposed";

  async function handleApply() {
    if (isReadOnly || applying || isSettled) return;
    setApplying(true);
    try {
      await writeRepositoryFile({
        project_path: proposal.projectPath,
        relative_path: proposal.relativePath,
        content: proposal.proposedContent,
      });
      onStatusChange(proposal.id, "applied", `Applied changes to ${proposal.relativePath}`);
    } catch (err) {
      const msg =
        err instanceof LocalWorkerClientError || err instanceof Error
          ? err.message
          : "Unable to apply the changes.";
      onStatusChange(proposal.id, "failed", msg);
    } finally {
      setApplying(false);
    }
  }

  function handleReject() {
    onStatusChange(proposal.id, "rejected", "Change proposal rejected.");
  }

  const statusLabel: Record<ProposalStatus, string> = {
    proposed: "Pending approval",
    applied: "Applied",
    rejected: "Rejected",
    failed: "Failed to apply",
  };

  const statusClass: Record<ProposalStatus, string> = {
    proposed: "proposal-status-proposed",
    applied: "proposal-status-applied",
    rejected: "proposal-status-rejected",
    failed: "proposal-status-failed",
  };

  return (
    <div className={`proposal-card${isSettled ? ` proposal-card-${proposal.status}` : ""}`}>
      {/* Header */}
      <div className="proposal-card-header">
        <div className="proposal-card-header-left">
          <span className="proposal-card-icon" aria-hidden="true" />
          <div>
            <div className="proposal-card-title">RepoOperator wants to modify 1 file</div>
            <div className="proposal-card-path">{proposal.relativePath}</div>
          </div>
        </div>
        <span className={`proposal-status-badge ${statusClass[proposal.status]}`}>
          {statusLabel[proposal.status]}
        </span>
      </div>

      {proposal.branch && (
        <div className="proposal-card-meta">
          Branch: <strong>{proposal.branch}</strong>
          {" · "}Model: <strong>{proposal.model}</strong>
        </div>
      )}

      {/* Diff preview */}
      <div className="proposal-diff-wrapper">
        <div className="proposal-diff-titlebar">
          <span>Diff preview</span>
          <button
            className="proposal-diff-toggle"
            type="button"
            onClick={() => setShowFull((v) => !v)}
          >
            {showFull ? "Collapse" : "Expand full diff"}
          </button>
        </div>
        <div
          className="proposal-diff-scroll"
          style={{ maxHeight: showFull ? "none" : "260px" }}
        >
          <DiffView original={proposal.originalContent} proposed={proposal.proposedContent} />
        </div>
      </div>

      {/* Actions */}
      {!isSettled && (
        <div className="proposal-card-actions">
          {isReadOnly ? (
            <p className="proposal-readonly-notice">
              Write operations are disabled. Switch to Auto review to apply changes.
            </p>
          ) : (
            <>
              <p className="proposal-warning">
                Review the diff before applying. RepoOperator will modify only{" "}
                <strong>{proposal.relativePath}</strong> on the current branch.
              </p>
              <div className="proposal-card-buttons">
                <button
                  className="proposal-btn-apply"
                  type="button"
                  onClick={() => void handleApply()}
                  disabled={applying}
                >
                  {applying ? "Applying…" : `Apply changes to ${proposal.relativePath}`}
                </button>
                <button
                  className="proposal-btn-reject"
                  type="button"
                  onClick={handleReject}
                  disabled={applying}
                >
                  Reject
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {isSettled && proposal.status !== "proposed" && (
        <div className={`proposal-settled-notice proposal-settled-${proposal.status}`}>
          {proposal.status === "applied" && `✓ Changes applied to ${proposal.relativePath}`}
          {proposal.status === "rejected" && "✕ Proposal rejected."}
          {proposal.status === "failed" && "⚠ Failed to apply changes."}
        </div>
      )}
    </div>
  );
}

/** Helper to turn an AgentProposeFilePayload into a ChangeProposal. */
export function proposalFromPayload(
  payload: AgentProposeFilePayload,
  opts: { projectPath: string; branch?: string | null },
): ChangeProposal {
  return {
    id: `${Date.now()}-proposal-${payload.relative_path}`,
    projectPath: opts.projectPath,
    branch: opts.branch,
    relativePath: payload.relative_path,
    originalContent: payload.original_content,
    proposedContent: payload.proposed_content,
    model: payload.model,
    status: "proposed",
  };
}

/** Helper to turn a change_proposal AgentRunPayload into a ChangeProposal. */
export function proposalFromRunPayload(
  payload: {
    model: string;
    proposal_relative_path?: string | null;
    proposal_original_content?: string | null;
    proposal_proposed_content?: string | null;
  },
  opts: { projectPath: string; branch?: string | null },
): ChangeProposal {
  const relativePath = payload.proposal_relative_path ?? "unknown";
  return {
    id: `${Date.now()}-proposal-${relativePath}`,
    projectPath: opts.projectPath,
    branch: opts.branch,
    relativePath,
    originalContent: payload.proposal_original_content ?? "",
    proposedContent: payload.proposal_proposed_content ?? "",
    model: payload.model,
    status: "proposed",
  };
}
