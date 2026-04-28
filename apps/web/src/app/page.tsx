import { RepoOperatorConsole } from "@/components/openpatch-console";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true" />
          <div className="brand-copy">
            <h1>RepoOperator</h1>
            <p>Hosted interface for repository understanding through local sources and guided model connections.</p>
          </div>
        </div>
        <div className="topbar-note">Read-only product flow</div>
      </header>

      <RepoOperatorConsole />
    </main>
  );
}
