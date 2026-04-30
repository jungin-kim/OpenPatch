"use client";

import { type KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  pending: boolean;
  writeMode?: "basic" | "auto_review" | "full_access";
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
  writeMode = "basic",
}: ChatComposerProps) {
  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (!disabled && !pending && value.trim()) {
        onSubmit();
      }
    }
  }

  const canSubmit = !disabled && !pending && value.trim().length > 0;

  const placeholder = disabled
    ? "Open a repository above before asking a question…"
    : writeMode === "auto_review"
      ? "Ask a question or request a change… (⌘+Enter to send)"
      : "Ask a question about the repository… (⌘+Enter to send)";

  const hint = disabled
    ? "Open a repository to start asking questions."
    : writeMode === "auto_review"
      ? "Auto review — elevated commands and risky actions use approval cards."
      : writeMode === "full_access"
        ? "Full access — broader local actions are enabled and logged."
        : "Basic permissions — repository sandbox work is allowed with guardrails.";

  const buttonLabel = pending
    ? writeMode === "auto_review"
      ? "Working…"
      : "Asking…"
    : "Ask RepoOperator";

  return (
    <div className="chat-composer-area">
      <div className="composer-form">
        <textarea
          className="composer-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled || pending}
          rows={3}
        />
        <div className="composer-actions">
          <span className="composer-hint">{hint}</span>
          <button
            className="composer-send-btn"
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
