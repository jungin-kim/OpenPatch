export function TaskComposer() {
  return (
    <section className="panel composer-panel" aria-labelledby="task-composer-title">
      <p className="section-label">Task Input</p>
      <h3 id="task-composer-title">Describe the work</h3>
      <p>
        This first shell keeps task entry local to the page. The next step is wiring
        this form to the central backend while checking worker readiness on localhost.
      </p>

      <form className="task-form">
        <textarea
          className="task-textarea"
          name="task"
          placeholder="Ask OpenPatch to inspect a repository, propose edits, run a command, or prepare a patch..."
          defaultValue=""
        />
        <div className="task-actions">
          <span className="task-hint">
            Planned flow: UI request -> worker context collection -> central model response.
          </span>
          <button className="primary-button" type="button" disabled>
            Submit task
          </button>
        </div>
      </form>
    </section>
  );
}
