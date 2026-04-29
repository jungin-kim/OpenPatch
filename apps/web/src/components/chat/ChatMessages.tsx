"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentRunPayload, RepoOpenPayload } from "@/lib/local-worker-client";
import { MarkdownContent } from "./MarkdownContent";
import {
  ProposalCard,
  type ChangeProposal,
  type ProposalStatus,
} from "./ProposalCard";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  metadata?: AgentRunPayload;
  proposal?: ChangeProposal;
};

function ToolCard({ metadata }: { metadata: AgentRunPayload }) {
  const [open, setOpen] = useState(false);
  const filesRead = metadata.files_read ?? [];
  const fileCount = filesRead.length;

  const headerLabel = fileCount > 0
    ? `${fileCount} file${fileCount === 1 ? "" : "s"} read`
    : "Answer trust trace";

  return (
    <div className="tool-card">
      <button
        className="tool-card-header"
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {headerLabel}
        <span className={`tool-card-caret${open ? " tool-card-caret-open" : ""}`}>▼</span>
      </button>
      {open && (
        <div className="tool-card-body">
          <div className="tool-meta-item">
            <span className="tool-meta-label">Source</span>
            <span className="tool-meta-value">
              {metadata.active_repository_source || metadata.git_provider || "unknown"}
            </span>
          </div>
          <div className="tool-meta-item">
            <span className="tool-meta-label">Project</span>
            <span className="tool-meta-value">
              {metadata.active_repository_path || metadata.project_path}
            </span>
          </div>
          <div className="tool-meta-item">
            <span className="tool-meta-label">Active branch</span>
            <span className="tool-meta-value">
              {metadata.active_branch || metadata.branch || "none"}
            </span>
          </div>
          {filesRead.length > 0 && (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Files read</span>
              <ul style={{ margin: "4px 0 0", padding: 0, listStyle: "none" }}>
                {filesRead.map((f) => (
                  <li key={f} className="tool-meta-value" style={{ paddingBottom: "2px" }}>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {metadata.model && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Model</span>
              <span className="tool-meta-value">{metadata.model}</span>
            </div>
          )}
          {metadata.branch && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Branch</span>
              <span className="tool-meta-value">{metadata.branch}</span>
            </div>
          )}
          {metadata.repo_root_name && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Repository</span>
              <span className="tool-meta-value">{metadata.repo_root_name}</span>
            </div>
          )}
          <div className="tool-meta-item">
            <span className="tool-meta-label">Git repo</span>
            <span className="tool-meta-value">
              {metadata.is_git_repository ? "yes" : "no"}
            </span>
          </div>
          {metadata.context_summary && (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Context summary</span>
              <span
                className="tool-meta-value"
                style={{ fontFamily: "inherit", fontSize: "0.86rem", whiteSpace: "normal" }}
              >
                {metadata.context_summary}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

interface ChatMessagesProps {
  messages: ChatMessage[];
  repoResult: RepoOpenPayload | null;
  questionPending: boolean;
  gitProvider: string;
  writeMode?: "read-only" | "write-with-approval" | "auto-apply";
  onProposalStatusChange?: (id: string, status: ProposalStatus, message?: string) => void;
}

export function ChatMessages({
  messages,
  repoResult,
  questionPending,
  gitProvider,
  writeMode = "read-only",
  onProposalStatusChange,
}: ChatMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, questionPending]);

  const activeProvider = repoResult?.git_provider || gitProvider;
  const providerLabel =
    activeProvider === "local"
      ? "Local project"
      : activeProvider === "gitlab"
        ? "GitLab"
        : "GitHub";

  return (
    <div className="chat-body">
      {repoResult && (
        <div className="repo-banner">
          <div className="repo-banner-icon" aria-hidden="true" />
          <div className="repo-banner-content">
            <div className="repo-banner-title" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span>Repository ready</span>
              {repoResult.branch ? (
                <span style={{ opacity: 0.75 }}>· {repoResult.branch}</span>
              ) : null}
            </div>
            <div className="repo-banner-detail">
              {repoResult.local_repo_path} · {providerLabel}
              {repoResult.head_sha ? ` · ${repoResult.head_sha.slice(0, 8)}` : ""}
            </div>
          </div>
        </div>
      )}

      {messages.length === 0 && !questionPending ? (
        <div className="chat-empty">
          <div className="chat-empty-icon" aria-hidden="true" />
          <h2>RepoOperator</h2>
          <p>
            {repoResult
              ? "Repository is open. Ask a question about the codebase below."
              : "Select a repository above and click Open repository, then ask questions."}
          </p>
        </div>
      ) : (
        <>
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-group message-group-${msg.role}`}
            >
              <span className="message-role-label">
                {msg.role === "user"
                  ? "You"
                  : msg.role === "system"
                    ? "Context"
                    : "RepoOperator"}
              </span>
              {msg.proposal ? (
                <ProposalCard
                  proposal={msg.proposal}
                  writeMode={writeMode}
                  onStatusChange={onProposalStatusChange ?? (() => {})}
                />
              ) : msg.role === "assistant" ? (
                <div className="message-bubble message-bubble-md">
                  <MarkdownContent content={msg.content} />
                </div>
              ) : msg.role === "system" ? (
                <div className="message-bubble message-bubble-system">{msg.content}</div>
              ) : (
                <div className="message-bubble">{msg.content}</div>
              )}
              {msg.metadata && <ToolCard metadata={msg.metadata} />}
              <span className="message-timestamp">{formatTime(msg.timestamp)}</span>
            </div>
          ))}

          {questionPending && (
            <div className="message-group message-group-assistant">
              <span className="message-role-label">RepoOperator</span>
              <div className="typing-indicator">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
