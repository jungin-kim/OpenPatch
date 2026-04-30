"use client";

import { type KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  pending: boolean;
  writeMode?: "basic" | "auto_review" | "full_access";
  queuedCount?: number;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
  writeMode = "basic",
  queuedCount = 0,
}: ChatComposerProps) {
  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (!disabled && value.trim()) {
        onSubmit();
      }
    }
  }

  // During pending the user can still type and queue messages
  const canSubmit = !disabled && value.trim().length > 0;

  const placeholder = disabled
    ? "Open a repository above before asking a question…"
    : pending
      ? "Type to queue a follow-up message… (⌘+Enter to queue)"
      : writeMode === "auto_review"
        ? "Ask a question or request a change… (⌘+Enter to send)"
        : "Ask a question about the repository… (⌘+Enter to send)";

  const hint = disabled
    ? "Open a repository to start asking questions."
    : pending
      ? queuedCount > 0
        ? `${queuedCount} message${queuedCount === 1 ? "" : "s"} queued — will run after current task finishes.`
        : "Agent is running — type to queue a follow-up."
      : writeMode === "auto_review"
        ? "Auto review — elevated commands and risky actions use approval cards."
        : writeMode === "full_access"
          ? "Full access — broader local actions are enabled and logged."
          : "Basic permissions — repository sandbox work is allowed with guardrails.";

  const buttonLabel = pending
    ? value.trim()
      ? "Queue"
      : writeMode === "auto_review"
        ? "Working…"
        : "Working…"
    : "Ask RepoOperator";

  return (
    <div className="chat-composer-area">
      {queuedCount > 0 && (
        <div className="composer-queue-bar">
          <span className="composer-queue-icon">⏳</span>
          {queuedCount} queued message{queuedCount === 1 ? "" : "s"}
        </div>
      )}
      <div className="composer-form">
        <textarea
          className="composer-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={3}
        />
        <div className="composer-actions">
          <span className="composer-hint">{hint}</span>
          <button
            className={`composer-send-btn${pending && value.trim() ? " composer-send-btn-queue" : ""}`}
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            {buttonLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
