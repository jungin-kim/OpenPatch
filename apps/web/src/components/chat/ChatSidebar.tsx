import type { ProviderProjectSummary } from "@/lib/local-worker-client";
import Link from "next/link";

interface ChatSidebarProps {
  recentProjects: ProviderProjectSummary[];
  hasMessages: boolean;
  onNewChat: () => void;
}

export function ChatSidebar({ recentProjects, hasMessages, onNewChat }: ChatSidebarProps) {
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

        {hasMessages ? (
          <button className="sidebar-item sidebar-item-active" type="button">
            Current session
          </button>
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
