"use client";

import { useEffect, useRef, useState } from "react";
import type { PermissionMode } from "@/lib/local-worker-client";

const permissionModes: Array<{
  mode: PermissionMode;
  label: string;
  description: string;
  disabled?: boolean;
}> = [
  {
    mode: "default",
    label: "Default",
    description: "Work inside the active repository sandbox with approval gates.",
  },
  {
    mode: "accept_edits",
    label: "Accept edits",
    description: "Use approval cards for elevated actions, network, and risky tools.",
  },
  {
    mode: "auto_readonly",
    label: "Read-only",
    description: "Allow repository reads and safe git inspection without writes.",
  },
  {
    mode: "full_access",
    label: "Full access",
    description: "Dangerous broader local access after confirmation.",
  },
];

export function permissionLabel(mode: PermissionMode): string {
  return permissionModes.find((item) => item.mode === mode)?.label ?? mode.replaceAll("_", " ");
}

export function permissionTone(mode: PermissionMode): "review" | "full" | "default" {
  if (mode === "accept_edits" || mode === "routine_safe" || mode === "headless_safe") return "review";
  if (mode === "full_access") return "full";
  return "default";
}

interface PermissionControlProps {
  writeMode: PermissionMode;
  permissionPending: boolean;
  permissionMessage?: string | null;
  permissionError?: string | null;
  onPermissionModeChange: (mode: PermissionMode) => void;
  /** "up" opens the menu above the trigger (for the composer at the bottom). */
  menuDirection?: "up" | "down";
}

export function PermissionControl({
  writeMode,
  permissionPending,
  permissionMessage,
  permissionError,
  onPermissionModeChange,
  menuDirection = "down",
}: PermissionControlProps) {
  const [showPermissions, setShowPermissions] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPermissions) return;
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setShowPermissions(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [showPermissions]);

  return (
    <div ref={rootRef} className={`permission-control permission-control-${menuDirection}`}>
      <button
        className={`permission-trigger${permissionTone(writeMode) === "review" ? " permission-trigger-review" : ""}`}
        type="button"
        aria-label="Permission mode"
        aria-expanded={showPermissions}
        onClick={() => setShowPermissions((value) => !value)}
        disabled={permissionPending}
        title="Change RepoOperator permission mode"
      >
        <span className="permission-trigger-icon" aria-hidden="true">
          {permissionTone(writeMode) === "review" ? "◇" : permissionTone(writeMode) === "full" ? "!" : "●"}
        </span>
        {permissionPending ? "Updating…" : permissionLabel(writeMode)}
        <span className="permission-trigger-caret" aria-hidden="true">{menuDirection === "up" ? "▴" : "▾"}</span>
      </button>
      {showPermissions && (
        <div className={`permission-menu permission-menu-${menuDirection}`} role="menu">
          {permissionModes.map((item) => (
            <button
              key={item.mode}
              className={`permission-option${item.mode === writeMode ? " permission-option-selected" : ""}`}
              type="button"
              role="menuitemradio"
              aria-checked={item.mode === writeMode}
              disabled={permissionPending || item.disabled}
              onClick={() => {
                if (item.disabled) return;
                setShowPermissions(false);
                onPermissionModeChange(item.mode);
              }}
            >
              <span className="permission-option-check" aria-hidden="true">
                {item.mode === writeMode ? "✓" : ""}
              </span>
              <span className="permission-option-copy">
                <span className="permission-option-label">
                  {item.label}
                  {item.disabled ? " — Coming soon" : ""}
                </span>
                <span className="permission-option-description">{item.description}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      {(permissionMessage || permissionError) && (
        <p className={`permission-inline-message${permissionError ? " permission-inline-message-error" : ""}`}>
          {permissionError || permissionMessage}
        </p>
      )}
    </div>
  );
}
