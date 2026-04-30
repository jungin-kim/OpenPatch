import type { ReactNode } from "react";

interface ChatLayoutProps {
  sidebar: ReactNode;
  header: ReactNode;
  messages: ReactNode;
  composer: ReactNode;
  sidebarCollapsed?: boolean;
}

export function ChatLayout({ sidebar, header, messages, composer, sidebarCollapsed = false }: ChatLayoutProps) {
  return (
    <div className={`chat-app${sidebarCollapsed ? " chat-app-sidebar-collapsed" : ""}`}>
      {sidebar}
      <div className="chat-main">
        {header}
        {messages}
        {composer}
      </div>
    </div>
  );
}
