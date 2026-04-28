import type { ReactNode } from "react";

interface ChatLayoutProps {
  sidebar: ReactNode;
  header: ReactNode;
  messages: ReactNode;
  composer: ReactNode;
}

export function ChatLayout({ sidebar, header, messages, composer }: ChatLayoutProps) {
  return (
    <div className="chat-app">
      {sidebar}
      <div className="chat-main">
        {header}
        {messages}
        {composer}
      </div>
    </div>
  );
}
