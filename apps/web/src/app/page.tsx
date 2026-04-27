import { OpenPatchConsole } from "@/components/openpatch-console";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true" />
          <div className="brand-copy">
            <h1>OpenPatch</h1>
            <p>Hosted interface for local repository understanding.</p>
          </div>
        </div>
        <div className="topbar-note">Read-only web flow</div>
      </header>

      <OpenPatchConsole />
    </main>
  );
}
