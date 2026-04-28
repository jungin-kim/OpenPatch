"use client";

import { type KeyboardEvent, useState } from "react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  pending: boolean;
  writeMode?: "read-only" | "write-with-approval";
  onProposeChange?: (relativePath: string, instruction: string) => void;
  proposePending?: boolean;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
  writeMode = "read-only",
  onProposeChange,
  proposePending = false,
}: ChatComposerProps) {
  const [mode, setMode] = useState<"ask" | "propose">("ask");
  const [relativePath, setRelativePath] = useState("");
  const [instruction, setInstruction] = useState("");

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (!disabled && !pending && value.trim()) {
        onSubmit();
      }
    }
  }

  function handlePropose() {
    if (!onProposeChange || !relativePath.trim() || !instruction.trim() || proposePending) return;
    onProposeChange(relativePath.trim(), instruction.trim());
    // Reset form after submitting
    setRelativePath("");
    setInstruction("");
    setMode("ask");
  }

  function handleProposeKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handlePropose();
    }
  }

  const canSubmit = !disabled && !pending && value.trim().length > 0;
  const canPropose =
    !disabled &&
    !proposePending &&
    relativePath.trim().length > 0 &&
    instruction.trim().length > 0;
  const showProposeToggle =
    writeMode === "write-with-approval" && Boolean(onProposeChange) && !disabled;

  if (mode === "propose") {
    return (
      <div className="chat-composer-area">
        <div className="composer-form">
          <div className="composer-propose-bar">
            <span className="composer-propose-label">Propose a file change</span>
            <button
              className="composer-mode-link"
              type="button"
              onClick={() => setMode("ask")}
            >
              ← Back to Q&amp;A
            </button>
          </div>
          <input
            className="composer-propose-path"
            type="text"
            value={relativePath}
            onChange={(e) => setRelativePath(e.target.value)}
            placeholder="Relative path, e.g. src/utils/helpers.py"
            disabled={proposePending}
            spellCheck={false}
            autoComplete="off"
          />
          <textarea
            className="composer-textarea"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={handleProposeKeyDown}
            placeholder="Describe the change you want… (⌘+Enter to generate proposal)"
            disabled={proposePending}
            rows={3}
          />
          <div className="composer-actions">
            <span className="composer-hint">
              RepoOperator will propose a diff. You must review and approve before any file is
              modified.
            </span>
            <button
              className="composer-send-btn"
              type="button"
              onClick={handlePropose}
              disabled={!canPropose}
            >
              {proposePending ? "Generating proposal…" : "Generate proposal"}
            </button>
          </div>
        </div>
      </div>
    );
  }

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
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="composer-hint">
              {disabled
                ? "Open a repository to start asking questions."
                : writeMode === "write-with-approval"
                  ? "Write-with-approval — changes require your explicit approval."
                  : "Read-only — no files or branches are modified."}
            </span>
            {showProposeToggle && (
              <button
                className="composer-propose-toggle"
                type="button"
                onClick={() => setMode("propose")}
              >
                Propose change
              </button>
            )}
          </div>
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
