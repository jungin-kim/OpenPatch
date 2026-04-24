export function ResponsePanel() {
  return (
    <section className="panel response-panel" aria-labelledby="response-panel-title">
      <p className="section-label">Response Panel</p>
      <h3 id="response-panel-title">Awaiting worker and backend wiring</h3>
      <p>
        This area is reserved for streamed model output, execution steps, patches, and
        review controls once the UI is connected to the local worker and central model
        backend.
      </p>

      <div className="response-shell">
        <div className="response-placeholder">
          <strong>Placeholder response</strong>
          <p>
            No task has been submitted yet. Future versions will render assistant
            output, worker actions, command results, and patch previews here.
          </p>
        </div>

        <div className="response-meta">
          <div className="meta-card">
            <strong>Stream state</strong>
            <span>Idle</span>
          </div>
          <div className="meta-card">
            <strong>Active target</strong>
            <span className="mono">127.0.0.1:8000</span>
          </div>
        </div>
      </div>
    </section>
  );
}
