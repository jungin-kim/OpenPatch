import type { ProviderProjectSummary } from "@/lib/local-worker-client";
import type { ChatThread } from "./ChatApp";
import Link from "next/link";

interface ChatSidebarProps {
  recentProjects: ProviderProjectSummary[];
  threads: ChatThread[];
  activeThreadId: string | null;
  onNewChat: () => void;
  onSelectThread: (threadId: string) => void;
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
  onNewChat,
  onSelectThread,
}: ChatSidebarProps) {
  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar-header">
        <div className="sidebar-brand-mark" aria-hidden="true" />
        <span className="sidebar-brand-name">RepoOperator</span>
      </div>

      <div className="sidebar-body">
        <button className="sidebar-new-chat" type="button" onClick={onNewChat}>
          + New chat
        </button>

        <div className="sidebar-section">
          <span className="sidebar-section-title">Threads</span>
        </div>

        {threads.length > 0 ? (
          threads.map((thread) => (
            <button
              key={thread.id}
              className={`sidebar-item sidebar-thread${
                thread.id === activeThreadId ? " sidebar-item-active" : ""
              }`}
              type="button"
              title={`${thread.repoResult.git_provider}:${thread.repoResult.project_path}`}
              onClick={() => onSelectThread(thread.id)}
            >
              <span className="sidebar-thread-title">{thread.title}</span>
              <span className="sidebar-thread-meta">
                {providerLabel(thread.repoResult.git_provider)}
                {thread.repoResult.branch ? ` @ ${thread.repoResult.branch}` : ""}
              </span>
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
                className="sidebar-item sidebar-item-mono"
                type="button"
                title={project.project_path}
              >
                {project.display_name}
              </button>
            ))}
          </>
        )}

        <div style={{ flex: 1 }} />

        <div className="sidebar-section">
          <Link
            href="/"
            className="sidebar-item"
            style={{ display: "block", color: "var(--muted)", fontSize: "0.84rem" }}
          >
            ← Home
          </Link>
        </div>
      </div>
    </aside>
  );
}
