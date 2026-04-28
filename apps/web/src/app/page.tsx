import Link from "next/link";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true" />
          <div className="brand-copy">
            <h1>RepoOperator</h1>
            <p>Local-first repository understanding through guided model connections.</p>
          </div>
        </div>
        <Link href="/app" className="primary-button" style={{ textDecoration: "none" }}>
          Open app →
        </Link>
      </header>

      <section className="hero">
        <div className="panel hero-panel">
          <span className="hero-kicker">Local-first repository assistant</span>
          <h2>Understand any repository through your local worker.</h2>
          <p>
            RepoOperator connects to a worker running on your machine, opens projects
            from your configured source, and routes read-only questions through the model
            connection you set up — without sending code to third-party servers.
          </p>

          <div className="hero-cta">
            <Link href="/app" className="cta-button">
              Open RepoOperator →
            </Link>
          </div>
        </div>

        <div className="panel status-panel">
          <p className="section-label">How it works</p>

          <div className="mini-card">
            <strong>1. Connect</strong>
            <span>
              Start the local worker with{" "}
              <code style={{ fontFamily: "var(--font-mono)", fontSize: "0.9em" }}>
                repooperator up
              </code>
              . It manages repository access and model routing.
            </span>
          </div>
          <div className="mini-card">
            <strong>2. Select</strong>
            <span>
              Pick a project from your configured GitLab, GitHub, or local source. Branches
              load automatically.
            </span>
          </div>
          <div className="mini-card">
            <strong>3. Ask</strong>
            <span>
              Open the project and ask read-only questions. Responses are routed through
              your model connection.
            </span>
          </div>
        </div>
      </section>

      <section className="workspace">
        <div className="panel composer-panel">
          <p className="section-label">Repository sources</p>
          <h3>Works with your existing setup</h3>
          <p>
            RepoOperator reads your worker configuration to find the source you set up.
            You choose what it can access.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>GitLab</strong>
              <span>Load projects from your configured GitLab instance with automatic branch selection.</span>
            </div>
            <div className="mini-card">
              <strong>GitHub</strong>
              <span>Connect to GitHub repositories through your local worker token configuration.</span>
            </div>
            <div className="mini-card">
              <strong>Local paths</strong>
              <span>Open any local directory directly. Works with git repos and plain folders.</span>
            </div>
          </div>
        </div>

        <div className="panel response-panel">
          <p className="section-label">Getting started</p>
          <h3>One-command setup</h3>
          <p>
            Run onboarding once to set up your model connection and repository source.
            Then start with a single command.
          </p>

          <div className="code-block" style={{ marginBottom: "16px" }}>
            {`# Set up RepoOperator once
repooperator onboard

# Start the full local product
repooperator up`}
          </div>

          <Link href="/app" className="primary-button" style={{ textDecoration: "none" }}>
            Open the app →
          </Link>
        </div>
      </section>
    </main>
  );
}
