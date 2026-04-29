"use client";

import { type KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  pending: boolean;
  writeMode?: "read-only" | "write-with-approval" | "auto-apply";
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
  writeMode = "read-only",
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
    : writeMode === "write-with-approval"
      ? "Ask a question or request a change… (⌘+Enter to send)"
      : "Ask a question about the repository… (⌘+Enter to send)";

  const hint = disabled
    ? "Open a repository to start asking questions."
    : writeMode === "write-with-approval"
      ? "Auto review — change requests will generate a diff for your approval."
      : "Basic permissions — no files are modified.";

  const buttonLabel = pending
    ? writeMode === "write-with-approval"
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
