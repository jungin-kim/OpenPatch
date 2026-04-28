"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentRunPayload, RepoOpenPayload } from "@/lib/local-worker-client";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  metadata?: AgentRunPayload;
};

function ToolCard({ metadata }: { metadata: AgentRunPayload }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="tool-card">
      <button
        className="tool-card-header"
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Context &amp; metadata
        <span className={`tool-card-caret${open ? " tool-card-caret-open" : ""}`}>▼</span>
      </button>
      {open && (
        <div className="tool-card-body">
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
}

export function ChatMessages({
  messages,
  repoResult,
  questionPending,
  gitProvider,
}: ChatMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, questionPending]);

  const providerLabel =
    gitProvider === "local"
      ? "Local project"
      : gitProvider === "gitlab"
        ? "GitLab"
        : "GitHub";

  return (
    <div className="chat-body">
      {repoResult && (
        <div className="repo-banner">
          <div className="repo-banner-icon" aria-hidden="true" />
          <div className="repo-banner-content">
            <div className="repo-banner-title">
              Repository ready
              {repoResult.branch ? ` · ${repoResult.branch}` : ""}
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
                {msg.role === "user" ? "You" : "RepoOperator"}
              </span>
              <div className="message-bubble">{msg.content}</div>
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
