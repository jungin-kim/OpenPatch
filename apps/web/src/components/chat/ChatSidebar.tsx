"use client";

import { useEffect, useState } from "react";
import type { ProviderProjectSummary } from "@/lib/local-worker-client";
import type { ChatThread } from "./ChatApp";
import Link from "next/link";

interface ChatSidebarProps {
  recentProjects: ProviderProjectSummary[];
  threads: ChatThread[];
  activeThreadId: string | null;
  runningThreadIds?: string[];
  threadStoreState: "loading" | "connected" | "saving" | "unavailable";
  onNewChat: () => void;
  onSelectThread: (threadId: string) => void;
  onSelectRecentProject: (project: ProviderProjectSummary) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
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

/** Count non-system messages — a lightweight proxy for a chat's own context. */
function contextTurns(thread: ChatThread): number {
  return thread.messages.filter((m) => m.role !== "system").length;
}

/** Prefer the first user message as the chat label so chats in one project are
 *  distinguishable (the persisted title defaults to the repo name). */
function chatTitle(thread: ChatThread): string {
  const firstUser = thread.messages.find((m) => m.role === "user" && m.content.trim());
  if (firstUser) {
    const text = firstUser.content.trim().replace(/\s+/g, " ");
    return text.length > 40 ? `${text.slice(0, 40)}…` : text;
  }
  return thread.title || "New chat";
}

export function ChatSidebar({
  recentProjects,
  threads,
  activeThreadId,
  runningThreadIds = [],
  threadStoreState,
  onNewChat,
  onSelectThread,
  onSelectRecentProject,
  collapsed = false,
  onToggleCollapsed,
}: ChatSidebarProps) {
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
                    </span>
                    {runningInGroup ? <span className="sidebar-thread-spinner" aria-label="Run active" /> : null}
                  </button>

                  {!isCollapsed && (
                    <div className="sidebar-project-chats">
                      {group.chats.map((thread) => (
                        <button
                          key={thread.id}
                          className={`sidebar-item sidebar-thread${
                            thread.id === activeThreadId ? " sidebar-item-active" : ""
                          }${runningThreads.has(thread.id) ? " sidebar-thread-running" : ""}`}
                          type="button"
                          title={`${chatTitle(thread)} — independent context`}
                          onClick={() => onSelectThread(thread.id)}
                        >
                          <span className="sidebar-thread-title">{chatTitle(thread)}</span>
                          <span className="sidebar-thread-meta">
                            {contextTurns(thread) > 0 ? `${contextTurns(thread)} turns · own context` : "new · own context"}
                          </span>
                          {runningThreads.has(thread.id) ? <span className="sidebar-thread-spinner" aria-label="Run active" /> : null}
                        </button>
                      ))}
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
            <Link href="/" className="sidebar-item" style={{ display: "block", color: "var(--muted)", fontSize: "0.84rem" }}>
              ← Home
            </Link>
          </div>
        </div>
      )}
    </aside>
  );
}
