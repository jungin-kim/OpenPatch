"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentRunPayload, CommandResultPayload, RepoOpenPayload } from "@/lib/local-worker-client";
import { MarkdownContent } from "./MarkdownContent";
import {
  ProposalCard,
  type ChangeProposal,
  type ProposalStatus,
} from "./ProposalCard";
import { ProgressTimeline, type ProgressStep } from "./ProgressTimeline";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  metadata?: AgentRunPayload;
  proposal?: ChangeProposal;
};

function CommandApprovalCard({
  metadata,
  onDecision,
}: {
  metadata: AgentRunPayload;
  onDecision?: (metadata: AgentRunPayload, decision: "yes" | "yes_session" | "no_explain") => void;
}) {
  const approval = metadata.command_approval;
  if (!approval) return null;
  return (
    <div className={`command-card command-card-${approval.risk}`}>
      <div className="command-card-heading">Command approval required</div>
      <p>{approval.reason}</p>
      <dl className="command-card-grid">
        <div>
          <dt>Command</dt>
          <dd><code>{approval.display_command}</code></dd>
        </div>
        <div>
          <dt>Working directory</dt>
          <dd>{approval.cwd || "No repository opened"}</dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>{approval.risk}</dd>
        </div>
        <div>
          <dt>Read-only</dt>
          <dd>{approval.read_only ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Network</dt>
          <dd>{approval.needs_network ? "May use network" : "No network expected"}</dd>
        </div>
        <div>
          <dt>Outside repository</dt>
          <dd>{approval.touches_outside_repo ? "Yes" : "No"}</dd>
        </div>
      </dl>
      {approval.blocked ? (
        <div className="command-card-blocked">Blocked by RepoOperator safety policy.</div>
      ) : (
        <div className="command-card-actions">
          <button type="button" onClick={() => onDecision?.(metadata, "yes")}>Yes</button>
          <button type="button" onClick={() => onDecision?.(metadata, "yes_session")}>
            Yes, and don't ask again for this session
          </button>
          <button type="button" onClick={() => onDecision?.(metadata, "no_explain")}>
            No, explain another approach
          </button>
        </div>
      )}
    </div>
  );
}

function CommandResultCard({ result }: { result: CommandResultPayload }) {
  return (
    <div className="command-card">
      <div className="command-card-heading">Command result</div>
      <p><code>{result.display_command}</code> exited with {result.exit_code}.</p>
      <details open>
        <summary>Output</summary>
        <pre>{result.stdout || result.stderr || "No output"}</pre>
      </details>
    </div>
  );
}

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
          {metadata.agent_flow && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Agent flow</span>
              <span className="tool-meta-value">{metadata.agent_flow}</span>
            </div>
          )}
          {metadata.intent_classification && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Intent</span>
              <span className="tool-meta-value">{metadata.intent_classification}</span>
            </div>
          )}
          {metadata.graph_path && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Graph path</span>
              <span className="tool-meta-value">{metadata.graph_path}</span>
            </div>
          )}
          {metadata.run_id && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Run ID</span>
              <span className="tool-meta-value">{metadata.run_id}</span>
            </div>
          )}
          {metadata.skills_used?.length ? (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Skills used</span>
              <span className="tool-meta-value">{metadata.skills_used.join(", ")}</span>
            </div>
          ) : null}
          {metadata.selected_target_file && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Target file</span>
              <span className="tool-meta-value">{metadata.selected_target_file}</span>
            </div>
          )}
          {metadata.context_source && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Context source</span>
              <span className="tool-meta-value">{metadata.context_source}</span>
            </div>
          )}
          {metadata.context_reference_resolver && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Reference resolver</span>
              <span className="tool-meta-value">{metadata.context_reference_resolver}</span>
            </div>
          )}
          {metadata.resolved_reference_type && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Reference type</span>
              <span className="tool-meta-value">{metadata.resolved_reference_type}</span>
            </div>
          )}
          {metadata.reference_confidence !== undefined && metadata.reference_confidence !== null && (
            <div className="tool-meta-item">
              <span className="tool-meta-label">Reference confidence</span>
              <span className="tool-meta-value">{Math.round(metadata.reference_confidence * 100)}%</span>
            </div>
          )}
          {metadata.resolved_files?.length ? (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Resolved files</span>
              <span className="tool-meta-value">{metadata.resolved_files.join(", ")}</span>
            </div>
          ) : null}
          {metadata.resolved_symbols?.length ? (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Resolved symbols</span>
              <span className="tool-meta-value">{metadata.resolved_symbols.join(", ")}</span>
            </div>
          ) : null}
          {metadata.thread_context_files?.length ? (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Thread context files</span>
              <span className="tool-meta-value">{metadata.thread_context_files.join(", ")}</span>
            </div>
          ) : null}
          {metadata.thread_context_symbols?.length ? (
            <div className="tool-meta-item" style={{ gridColumn: "1 / -1" }}>
              <span className="tool-meta-label">Thread context symbols</span>
              <span className="tool-meta-value">{metadata.thread_context_symbols.join(", ")}</span>
            </div>
          ) : null}
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
  progressSteps?: ProgressStep[];
  gitProvider: string;
  writeMode?: "basic" | "auto_review" | "full_access";
  onProposalStatusChange?: (id: string, status: ProposalStatus, message?: string) => void;
  onClarificationSelect?: (candidate: string) => void;
  onCommandDecision?: (metadata: AgentRunPayload, decision: "yes" | "yes_session" | "no_explain") => void;
}

export function ChatMessages({
  messages,
  repoResult,
  questionPending,
  progressSteps = [],
  gitProvider,
  writeMode = "basic",
  onProposalStatusChange,
  onClarificationSelect,
  onCommandDecision,
}: ChatMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

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

  function speakerLabel(message: ChatMessage): string {
    return message.role === "user"
      ? "You"
      : message.role === "system"
        ? "Context"
        : "RepoOperator";
  }

  function formatMessageForCopy(message: ChatMessage): string {
    const lines = [
      `[${message.timestamp.toLocaleString()}] ${speakerLabel(message)}`,
      message.content,
    ];
    if (message.proposal) {
      lines.push(`Proposal: ${message.proposal.relativePath}`);
      lines.push(`Status: ${message.proposal.status}`);
    }
    if (message.metadata?.selected_target_file) {
      lines.push(`Target file: ${message.metadata.selected_target_file}`);
    }
    if (message.metadata?.clarification_candidates?.length) {
      lines.push(`Candidates: ${message.metadata.clarification_candidates.join(", ")}`);
    }
    if (message.metadata?.proposal_error_details) {
      lines.push(`Error: ${message.metadata.proposal_error_details}`);
    }
    return lines.filter(Boolean).join("\n");
  }

  function formatChatForCopy(): string {
    return messages.map(formatMessageForCopy).join("\n\n---\n\n");
  }

  async function copyText(text: string, id: string) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch {
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 1800);
    }
  }

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

      {messages.length > 0 && (
        <div className="chat-copy-bar">
          <button
            className="message-copy-btn"
            type="button"
            onClick={() => void copyText(formatChatForCopy(), "chat")}
          >
            {copiedId === "chat" ? "Copied" : "Copy chat"}
          </button>
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
              <div className="message-meta-row">
                <span className="message-role-label">{speakerLabel(msg)}</span>
                <button
                  className="message-copy-btn"
                  type="button"
                  onClick={() => void copyText(formatMessageForCopy(msg), msg.id)}
                >
                  {copiedId === msg.id ? "Copied" : "Copy message"}
                </button>
              </div>
              {msg.proposal ? (
                <ProposalCard
                  proposal={msg.proposal}
                  writeMode={writeMode}
                  onStatusChange={onProposalStatusChange ?? (() => {})}
                />
              ) : msg.role === "assistant" && msg.metadata?.response_type === "permission_required" ? (
                <div className="message-bubble message-bubble-permission">
                  <div className="permission-callout">
                    <span className="permission-callout-icon" aria-hidden="true" />
                    <div>
                      <div className="permission-callout-title">Write permission required</div>
                      <div className="permission-callout-body">{msg.content}</div>
                    </div>
                  </div>
                </div>
              ) : msg.role === "assistant" && msg.metadata?.response_type === "clarification" ? (
                <div className="message-bubble message-bubble-md">
                  <MarkdownContent content={msg.content} />
                  {msg.metadata.clarification_candidates?.length ? (
                    <div className="clarification-options">
                      {msg.metadata.clarification_candidates.map((candidate) => (
                        <button
                          key={candidate}
                          className="clarification-option"
                          type="button"
                          onClick={() => onClarificationSelect?.(candidate)}
                        >
                          {candidate}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : msg.role === "assistant" && msg.metadata?.response_type === "command_approval" ? (
                <CommandApprovalCard metadata={msg.metadata} onDecision={onCommandDecision} />
              ) : msg.role === "assistant" && msg.metadata?.response_type === "command_result" && msg.metadata.command_result ? (
                <CommandResultCard result={msg.metadata.command_result as CommandResultPayload} />
              ) : msg.role === "assistant" && msg.metadata?.response_type === "command_denied" ? (
                <CommandApprovalCard metadata={msg.metadata} onDecision={onCommandDecision} />
              ) : msg.role === "assistant" && msg.metadata?.response_type === "proposal_error" ? (
                <div className="proposal-error-card">
                  <div className="proposal-error-title">No valid diff produced</div>
                  <p>{msg.content}</p>
                  {msg.metadata.proposal_error_details && (
                    <details>
                      <summary>View details</summary>
                      <pre>{msg.metadata.proposal_error_details}</pre>
                    </details>
                  )}
                  <button className="proposal-btn-reject" type="button" onClick={() => onClarificationSelect?.(msg.content)}>
                    Retry with more detail
                  </button>
                </div>
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
              {progressSteps.length > 0 ? (
                <ProgressTimeline steps={progressSteps} done={false} />
              ) : (
                <div className="typing-indicator">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              )}
            </div>
          )}
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
