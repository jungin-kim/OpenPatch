"use client";

import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import type { ProviderProjectSummary } from "@/lib/local-worker-client";
import type { ChatThread } from "./ChatApp";
import { ThemeToggle } from "./ThemeToggle";
import Link from "next/link";

interface ChatSidebarProps {
  recentProjects: ProviderProjectSummary[];
  threads: ChatThread[];
  activeThreadId: string | null;
  runningThreadIds?: string[];
  threadStoreState: "loading" | "connected" | "saving" | "unavailable";
  onNewChat: () => void;
  onSelectThread: (threadId: string) => void;
  onDeleteThread?: (threadId: string) => void;
  onRenameThread?: (threadId: string, title: string) => void;
  onDeleteProject?: (threadIds: string[]) => void;
  onSelectRecentProject: (project: ProviderProjectSummary) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  theme?: "light" | "dark";
  onThemeToggle?: () => void;
}

type MenuItem = { label: string; danger?: boolean; confirm?: string; onClick: () => void };

const MENU_WIDTH = 190;

/** A hover "…" trigger that opens a small actions menu. The menu is rendered in
 *  a portal (position: fixed) so it is always opaque and on top of other rows. */
function MoreMenu({ items, label }: { items: MenuItem[]; label: string }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<MenuItem | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) setConfirming(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  const toggle = (e: ReactMouseEvent) => {
    e.stopPropagation();
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8));
      setPos({ top: r.bottom + 4, left });
    }
    setOpen((v) => !v);
  };

  return (
    <div className={`sidebar-more${open ? " sidebar-more-open" : ""}`}>
      <button
        ref={btnRef}
        type="button"
        className="sidebar-more-btn"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        ⋯
      </button>
      {open && pos && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={menuRef}
              className="sidebar-more-menu"
              role="menu"
              style={{ position: "fixed", top: pos.top, left: pos.left, width: MENU_WIDTH }}
            >
              {confirming ? (
                <div className="sidebar-more-confirm">
                  <div className="sidebar-more-confirm-text">{confirming.confirm}</div>
                  <div className="sidebar-more-confirm-actions">
                    <button
                      type="button"
                      className="sidebar-more-item sidebar-more-item-danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        const action = confirming.onClick;
                        setOpen(false);
                        action();
                      }}
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      className="sidebar-more-item"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirming(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                items.map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    role="menuitem"
                    className={`sidebar-more-item${item.danger ? " sidebar-more-item-danger" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (item.confirm) {
                        setConfirming(item);
                      } else {
                        setOpen(false);
                        item.onClick();
                      }
                    }}
                  >
                    {item.label}
                  </button>
                ))
              )}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function providerLabel(provider: string): string {
  if (provider === "local") return "Local";
  if (provider === "gitlab") return "GitLab";
  if (provider === "github") return "GitHub";
  return provider;
}

type ProjectGroup = {
  key: string;
  provider: string;
  projectPath: string;
  branch: string | null;
  name: string;
  chats: ChatThread[];
};

function projectKey(thread: ChatThread): string {
  const repo = thread.repoResult;
  return `${repo.git_provider}:${repo.project_path}:${repo.branch || "default"}`;
}

function groupThreadsByProject(threads: ChatThread[]): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();
  for (const thread of threads) {
    const key = projectKey(thread);
    let group = groups.get(key);
    if (!group) {
      const repo = thread.repoResult;
      const name = (repo.project_path || "").split(/[\\/]/).filter(Boolean).at(-1) || repo.project_path;
      group = { key, provider: repo.git_provider, projectPath: repo.project_path, branch: repo.branch ?? null, name, chats: [] };
      groups.set(key, group);
    }
    group.chats.push(thread);
  }
  return [...groups.values()];
}

/** Chat label: prefer a work-generated title; else the first user message; else
 *  "New chat". The persisted title defaults to the repo name until named. */
function chatTitle(thread: ChatThread): string {
  const repoDefault = (thread.repoResult.project_path || "").split(/[\\/]/).filter(Boolean).at(-1) || thread.repoResult.project_path;
  const title = (thread.title || "").trim();
  if (title && title !== repoDefault && title !== "New chat") return title;
  const firstUser = thread.messages.find((m) => m.role === "user" && m.content.trim());
  if (firstUser) {
    const text = firstUser.content.trim().replace(/\s+/g, " ");
    return text.length > 40 ? `${text.slice(0, 40)}…` : text;
  }
  return title || "New chat";
}

export function ChatSidebar({
  recentProjects,
  threads,
  activeThreadId,
  runningThreadIds = [],
  threadStoreState,
  onNewChat,
  onSelectThread,
  onDeleteThread,
  onRenameThread,
  onDeleteProject,
  onSelectRecentProject,
  collapsed = false,
  onToggleCollapsed,
  theme = "light",
  onThemeToggle,
}: ChatSidebarProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const threadStoreLabel =
    threadStoreState === "loading"
      ? "Loading saved chats"
      : threadStoreState === "saving"
        ? "Saving chat history"
        : threadStoreState === "connected"
          ? "Chat history synced"
          : "Chat history unavailable";
  const runningThreads = new Set(runningThreadIds);
  const groups = groupThreadsByProject(threads);
  const activeThread = threads.find((t) => t.id === activeThreadId);
  const activeKey = activeThread ? projectKey(activeThread) : null;

  // Track which project groups are collapsed; the active project starts open.
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (activeKey) setCollapsedGroups((prev) => ({ ...prev, [activeKey]: false }));
  }, [activeKey]);

  return (
    <aside className={`chat-sidebar${collapsed ? " chat-sidebar-collapsed" : ""}`}>
      <div className="chat-sidebar-header">
        <div className="sidebar-brand-mark" aria-hidden="true" />
        {!collapsed && <span className="sidebar-brand-name">RepoOperator</span>}
        <button
          className="sidebar-collapse-toggle"
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      {!collapsed && (
        <div className="sidebar-body">
          <button className="sidebar-new-chat" type="button" onClick={onNewChat}>
            + New chat
          </button>

          <div className="sidebar-section">
            <span className="sidebar-section-title">Projects &amp; chats</span>
          </div>
          <span className={`sidebar-sync-note sidebar-sync-note-${threadStoreState}`}>{threadStoreLabel}</span>

          {groups.length > 0 ? (
            groups.map((group) => {
              const isCollapsed = collapsedGroups[group.key] ?? group.key !== activeKey;
              const runningInGroup = group.chats.some((c) => runningThreads.has(c.id));
              return (
                <div key={group.key} className="sidebar-project-group">
                  <div className="sidebar-project-headrow">
                    <button
                      className={`sidebar-project-header${group.key === activeKey ? " sidebar-project-header-active" : ""}`}
                      type="button"
                      onClick={() => setCollapsedGroups((prev) => ({ ...prev, [group.key]: !isCollapsed }))}
                      title={`${providerLabel(group.provider)}:${group.projectPath}${group.branch ? ` @ ${group.branch}` : ""}`}
                    >
                      <span className="sidebar-project-caret" aria-hidden="true">{isCollapsed ? "▸" : "▾"}</span>
                      <span className="sidebar-project-name">{group.name}</span>
                      <span className="sidebar-project-meta">
                        {providerLabel(group.provider)}
                        {group.branch ? ` @ ${group.branch}` : ""} · {group.chats.length}
                        {runningInGroup ? <span className="sidebar-project-runningdot" aria-label="Run active" /> : null}
                      </span>
                    </button>
                    {onDeleteProject ? (
                      <MoreMenu
                        label="Project actions"
                        items={[
                          {
                            label: `Delete project (${group.chats.length} chats)`,
                            danger: true,
                            confirm: `Delete this project and its ${group.chats.length} chat(s)?`,
                            onClick: () => onDeleteProject(group.chats.map((c) => c.id)),
                          },
                        ]}
                      />
                    ) : null}
                  </div>

                  {!isCollapsed && (
                    <div className="sidebar-project-chats">
                      {group.chats.map((thread) => {
                        const renaming = renamingId === thread.id;
                        return (
                          <div key={thread.id} className="sidebar-thread-row">
                            {renaming ? (
                              <input
                                className="sidebar-thread-rename"
                                autoFocus
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    const v = renameValue.trim();
                                    if (v) onRenameThread?.(thread.id, v);
                                    setRenamingId(null);
                                  } else if (e.key === "Escape") {
                                    setRenamingId(null);
                                  }
                                }}
                                onBlur={() => {
                                  const v = renameValue.trim();
                                  if (v && v !== chatTitle(thread)) onRenameThread?.(thread.id, v);
                                  setRenamingId(null);
                                }}
                              />
                            ) : (
                              <button
                                className={`sidebar-item sidebar-thread${
                                  thread.id === activeThreadId ? " sidebar-item-active" : ""
                                }${runningThreads.has(thread.id) ? " sidebar-thread-running" : ""}`}
                                type="button"
                                title={`${chatTitle(thread)} — independent context`}
                                onClick={() => onSelectThread(thread.id)}
                              >
                                <span className="sidebar-thread-title">{chatTitle(thread)}</span>
                                {runningThreads.has(thread.id) ? <span className="sidebar-thread-spinner" aria-label="Run active" /> : null}
                              </button>
                            )}
                            {!renaming && (onRenameThread || onDeleteThread) ? (
                              <MoreMenu
                                label="Chat actions"
                                items={[
                                  ...(onRenameThread
                                    ? [
                                        {
                                          label: "Rename",
                                          onClick: () => {
                                            setRenameValue(chatTitle(thread));
                                            setRenamingId(thread.id);
                                          },
                                        },
                                      ]
                                    : []),
                                  ...(onDeleteThread
                                    ? [{ label: "Delete chat", danger: true, confirm: "Delete this chat?", onClick: () => onDeleteThread(thread.id) }]
                                    : []),
                                ]}
                              />
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })
          ) : (
            <span className="sidebar-empty-note">No chats yet</span>
          )}

          {recentProjects.length > 0 && (
            <>
              <div className="sidebar-section">
                <span className="sidebar-section-title">Open a project</span>
              </div>
              {recentProjects.map((project) => (
                <button
                  key={`${project.git_provider}:${project.project_path}`}
                  className="sidebar-item sidebar-recent-project"
                  type="button"
                  title={`${providerLabel(project.git_provider)}:${project.project_path}`}
                  onClick={() => onSelectRecentProject(project)}
                >
                  <span className="sidebar-recent-project-name">{project.display_name}</span>
                  <span className="sidebar-recent-project-source">{providerLabel(project.git_provider)}</span>
                </button>
              ))}
            </>
          )}

          <div style={{ flex: 1 }} />

          <div className="sidebar-section">
            <Link href="/debug" className="sidebar-item" style={{ display: "block", color: "var(--muted)", fontSize: "0.84rem", marginBottom: 6 }}>
              Debug dashboard
            </Link>
            <div className="sidebar-home-row">
              <Link href="/" className="sidebar-item sidebar-home-link" style={{ color: "var(--muted)", fontSize: "0.84rem" }}>
                ← Home
              </Link>
              {onThemeToggle && <ThemeToggle theme={theme} onThemeToggle={onThemeToggle} />}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
