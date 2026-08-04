"use client";

import { type KeyboardEvent, type ReactNode } from "react";
import type { PermissionMode } from "@/lib/local-worker-client";
import { PermissionControl } from "./PermissionControl";

type ConnectionState = "checking" | "connected" | "unavailable";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancelQueuedMessage?: (id: string) => void;
  onSteerQueuedMessage?: (id: string) => void;
  onStopRun?: () => void;
  disabled: boolean;
  pending: boolean;
  writeMode?: PermissionMode;
  queuedMessages?: Array<{ id: string; text: string; status: string; error?: string | null }>;
  contextSlot?: ReactNode;
  onPropose?: () => void;
  connectionState?: ConnectionState;
  configuredModelName?: string;
  configuredModelProvider?: string;
  permissionPending?: boolean;
  permissionMessage?: string | null;
  permissionError?: string | null;
  onPermissionModeChange?: (mode: PermissionMode) => void;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onCancelQueuedMessage,
  onSteerQueuedMessage,
  onStopRun,
  disabled,
  pending,
  writeMode = "default",
  queuedMessages = [],
  contextSlot,
  onPropose,
  connectionState = "connected",
  configuredModelName,
  configuredModelProvider,
  permissionPending = false,
  permissionMessage,
  permissionError,
  onPermissionModeChange,
}: ChatComposerProps) {
  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "checking"
        ? "Checking"
        : "Unavailable";
  const modelLabel = configuredModelName || configuredModelProvider || "No model";
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
      : writeMode === "accept_edits"
        ? "Ask a question or request a change… (⌘+Enter to send)"
        : "Ask a question about the repository… (⌘+Enter to send)";

  const buttonLabel = pending
    ? value.trim()
      ? "Queue"
      : writeMode === "accept_edits"
        ? "Working…"
        : "Working…"
    : "Ask RepoOperator";

  return (
    <div className="chat-composer-area">
      {queuedMessages.length > 0 && (
        <div className="composer-queue-list" aria-label="Queued messages">
          <div className="composer-queue-title">Queued next</div>
          {queuedMessages.map((item, index) => (
            <div className="composer-queue-item" key={item.id}>
              <span className="composer-queue-order">{index + 1}</span>
              <span className="composer-queue-text">{item.text}</span>
              <span className={`composer-queue-status composer-queue-status-${item.status}`}>{item.status}</span>
              <button type="button" onClick={() => onSteerQueuedMessage?.(item.id)} aria-label="Steer current run with queued message">
                Steer
              </button>
              {item.status === "queued" ? (
                <button type="button" onClick={() => onCancelQueuedMessage?.(item.id)} aria-label="Cancel queued message">
                  Cancel
                </button>
              ) : null}
              {item.error ? <span className="composer-queue-error">{item.error}</span> : null}
            </div>
          ))}
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
          <div className="composer-hint-stack">
            {onPermissionModeChange ? (
              <PermissionControl
                writeMode={writeMode}
                permissionPending={permissionPending}
                permissionMessage={permissionMessage}
                permissionError={permissionError}
                onPermissionModeChange={onPermissionModeChange}
                menuDirection="up"
              />
            ) : null}
            {pending ? (
              <div className="composer-run-controls" aria-label="Active run controls">
                <button type="button" className="composer-stop-btn" data-testid="stop-run-button" onClick={onStopRun}>
                  Stop
                </button>
              </div>
            ) : null}
          </div>
          <div className="composer-send-group">
            <span
              className={`status-pill-sm${
                connectionState === "connected"
                  ? " status-pill-sm-connected"
                  : connectionState === "checking"
                    ? " status-pill-sm-checking"
                    : ""
              }`}
            >
              {connectionLabel}
            </span>
            {configuredModelProvider ? (
              <span className="model-chip" title={modelLabel}>
                {modelLabel}
              </span>
            ) : null}
            {onPropose ? (
              <button
                type="button"
                className="composer-propose-btn"
                onClick={onPropose}
                disabled={disabled}
                title="Propose a change to a specific file (review the diff, then apply)"
              >
                Propose change
              </button>
            ) : null}
            {contextSlot}
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
    </div>
  );
}
