type WorkerStatusProps = {
  workerBaseUrl: string;
  statusLabel: string;
  statusDetail: string;
};

export function WorkerStatus({
  workerBaseUrl,
  statusLabel,
  statusDetail,
}: WorkerStatusProps) {
  return (
    <section className="panel status-panel" aria-labelledby="worker-status-title">
      <p className="section-label">Worker Connection</p>
      <div className="status-card">
        <span className="status-pill">{statusLabel}</span>
        <h3 id="worker-status-title">Local worker connection</h3>
        <p>{statusDetail}</p>
      </div>
      <div className="status-card">
        <strong>Planned endpoint</strong>
        <p className="mono">{workerBaseUrl}</p>
      </div>
      <div className="status-card">
        <strong>Next integration points</strong>
        <ul className="status-list">
          <li>Poll the worker health endpoint over localhost.</li>
          <li>Show connection, mismatch, and unavailable states.</li>
          <li>Use worker status to gate task submission.</li>
        </ul>
      </div>
    </section>
  );
}
