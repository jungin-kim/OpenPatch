"use client";

import { useCallback, useEffect, useState } from "react";

import { listRepositoryDir, type DirEntryPayload } from "@/lib/local-worker-client";

interface FilePickerProps {
  projectPath: string;
  value: string;
  onSelect: (relativePath: string) => void;
  disabled?: boolean;
}

export function FilePicker({ projectPath, value, onSelect, disabled }: FilePickerProps) {
  const [currentDir, setCurrentDir] = useState("");
  const [entries, setEntries] = useState<DirEntryPayload[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDir = useCallback(
    async (relativePath: string) => {
      if (!projectPath) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await listRepositoryDir({ project_path: projectPath, relative_path: relativePath });
        setCurrentDir(payload.relative_path);
        setEntries(payload.entries);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to list files.");
        setEntries([]);
      } finally {
        setLoading(false);
      }
    },
    [projectPath],
  );

  useEffect(() => {
    void loadDir("");
  }, [loadDir]);

  const segments = currentDir ? currentDir.split("/") : [];

  function crumbPath(index: number): string {
    return segments.slice(0, index + 1).join("/");
  }

  return (
    <div className="file-picker">
      <div className="file-picker-breadcrumbs" aria-label="Current folder">
        <button
          type="button"
          className="file-picker-crumb"
          onClick={() => void loadDir("")}
          disabled={disabled || loading || currentDir === ""}
        >
          repo
        </button>
        {segments.map((segment, index) => (
          <span key={crumbPath(index)} className="file-picker-crumb-wrap">
            <span className="file-picker-crumb-sep">/</span>
            <button
              type="button"
              className="file-picker-crumb"
              onClick={() => void loadDir(crumbPath(index))}
              disabled={disabled || loading || index === segments.length - 1}
            >
              {segment}
            </button>
          </span>
        ))}
      </div>

      <div className="file-picker-list" role="listbox" aria-label="Files and folders">
        {currentDir ? (
          <button
            type="button"
            className="file-picker-item file-picker-item-up"
            onClick={() => void loadDir(segments.slice(0, -1).join("/"))}
            disabled={disabled || loading}
          >
            <span className="file-picker-icon">↩</span>
            <span className="file-picker-name">..</span>
          </button>
        ) : null}

        {loading ? (
          <div className="file-picker-empty">Loading…</div>
        ) : error ? (
          <div className="file-picker-error">{error}</div>
        ) : entries.length === 0 ? (
          <div className="file-picker-empty">Empty folder</div>
        ) : (
          entries.map((entry) =>
            entry.type === "dir" ? (
              <button
                key={entry.relative_path}
                type="button"
                className="file-picker-item file-picker-item-dir"
                onClick={() => void loadDir(entry.relative_path)}
                disabled={disabled || loading}
              >
                <span className="file-picker-icon">📁</span>
                <span className="file-picker-name">{entry.name}</span>
                <span className="file-picker-chevron">›</span>
              </button>
            ) : (
              <button
                key={entry.relative_path}
                type="button"
                className={`file-picker-item file-picker-item-file${
                  value === entry.relative_path ? " file-picker-item-selected" : ""
                }`}
                onClick={() => onSelect(entry.relative_path)}
                disabled={disabled}
                role="option"
                aria-selected={value === entry.relative_path}
              >
                <span className="file-picker-icon">📄</span>
                <span className="file-picker-name">{entry.name}</span>
                {value === entry.relative_path ? <span className="file-picker-check">✓</span> : null}
              </button>
            ),
          )
        )}
      </div>
    </div>
  );
}
