import type { KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  pending: boolean;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
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

  return (
    <div className="chat-composer-area">
      <div className="composer-form">
        <textarea
          className="composer-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? "Open a repository above before asking a question…"
              : "Ask a question about the repository… (⌘+Enter to send)"
          }
          disabled={disabled || pending}
          rows={3}
        />
        <div className="composer-actions">
          <span className="composer-hint">
            {disabled
              ? "Open a repository to start asking questions."
              : "Read-only — no files or branches are modified."}
          </span>
          <button
            className="composer-send-btn"
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            {pending ? "Asking…" : "Ask RepoOperator"}
          </button>
        </div>
      </div>
    </div>
  );
}
