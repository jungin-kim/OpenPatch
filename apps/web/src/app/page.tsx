import { ResponsePanel } from "@/components/response-panel";
import { TaskComposer } from "@/components/task-composer";
import { WorkerStatus } from "@/components/worker-status";

const workerBaseUrl = "http://127.0.0.1:8000";

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
        <div className="topbar-note">Minimal preview for Phase 3 UI work</div>
      </header>

      <section className="hero">
        <div className="panel hero-panel">
          <span className="hero-kicker">Hosted UI + local worker + central inference</span>
          <h2>OpenPatch keeps repository work local and the interface easy to extend.</h2>
          <p>
            This first web scaffold is a clean landing surface for task entry, worker
            status, and future streamed responses. It is intentionally small so the next
            iteration can focus on wiring localhost worker checks and real task flow.
          </p>

          <div className="hero-grid">
            <div className="mini-card">
              <strong>Local worker</strong>
              <span>Repository reads, writes, git actions, and command execution.</span>
            </div>
            <div className="mini-card">
              <strong>Hosted UI</strong>
              <span>Task submission, state visibility, patch review, and control flow.</span>
            </div>
            <div className="mini-card">
              <strong>Central backend</strong>
              <span>Model inference, streaming, orchestration, and provider routing.</span>
            </div>
          </div>
        </div>

        <WorkerStatus
          workerBaseUrl={workerBaseUrl}
          statusLabel="Not connected"
          statusDetail="The UI is ready to be wired to a local worker on localhost, but no health check is active yet."
        />
      </section>

      <section className="workspace">
        <TaskComposer />
        <ResponsePanel />
      </section>
    </main>
  );
}
