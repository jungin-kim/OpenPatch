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
      ? "Loading saved threads"
      : threadStoreState === "saving"
        ? "Saving thread history"
        : threadStoreState === "connected"
          ? "Thread history synced"
          : "Thread history unavailable";
  const runningThreads = new Set(runningThreadIds);

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

      {!collapsed && <div className="sidebar-body">
        <button className="sidebar-new-chat" type="button" onClick={onNewChat}>
          + New chat
        </button>

        <div className="sidebar-section">
          <span className="sidebar-section-title">Threads</span>
        </div>
        <span className={`sidebar-sync-note sidebar-sync-note-${threadStoreState}`}>
          {threadStoreLabel}
        </span>

        {threads.length > 0 ? (
          threads.map((thread) => (
            <button
              key={thread.id}
              className={`sidebar-item sidebar-thread${
                thread.id === activeThreadId ? " sidebar-item-active" : ""
              }${runningThreads.has(thread.id) ? " sidebar-thread-running" : ""}`}
              type="button"
              title={`${thread.repoResult.git_provider}:${thread.repoResult.project_path}`}
              onClick={() => onSelectThread(thread.id)}
            >
              <span className="sidebar-thread-title">{thread.title}</span>
              <span className="sidebar-thread-meta">
                {providerLabel(thread.repoResult.git_provider)}
                {thread.repoResult.branch ? ` @ ${thread.repoResult.branch}` : ""}
              </span>
              {runningThreads.has(thread.id) ? <span className="sidebar-thread-spinner" aria-label="Run active" /> : null}
            </button>
          ))
        ) : (
          <span className="sidebar-empty-note">No threads yet</span>
        )}

        {recentProjects.length > 0 && (
          <>
            <div className="sidebar-section">
              <span className="sidebar-section-title">Recent repos</span>
            </div>
            {recentProjects.map((project) => (
              <button
                key={`${project.git_provider}:${project.project_path}`}
                className="sidebar-item sidebar-recent-project"
                type="button"
                title={`${providerLabel(project.git_provider)}:${project.project_path}`}
                onClick={() => onSelectRecentProject(project)}
              >
                <span className="sidebar-recent-project-name">
                  {project.display_name}
                </span>
                <span className="sidebar-recent-project-source">
                  {providerLabel(project.git_provider)}
                </span>
              </button>
            ))}
          </>
        )}

        <div style={{ flex: 1 }} />

        <div className="sidebar-section">
          <Link
            href="/debug"
            className="sidebar-item"
            style={{ display: "block", color: "var(--muted)", fontSize: "0.84rem", marginBottom: 6 }}
          >
            Debug dashboard
          </Link>
          <Link
            href="/"
            className="sidebar-item"
            style={{ display: "block", color: "var(--muted)", fontSize: "0.84rem" }}
          >
            ← Home
          </Link>
        </div>
      </div>}
    </aside>
  );
}
