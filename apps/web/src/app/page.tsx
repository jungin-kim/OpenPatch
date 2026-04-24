import { OpenPatchConsole } from "@/components/openpatch-console";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true" />
          <div className="brand-copy">
            <h1>OpenPatch</h1>
            <p>Hosted UI shell for local-repo agent workflows.</p>
          </div>
        </div>
        <div className="topbar-note">Read-only worker integration preview</div>
      </header>

      <OpenPatchConsole />
    </main>
  );
}
