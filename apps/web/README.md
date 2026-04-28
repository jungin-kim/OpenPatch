# RepoOperator Web UI

The RepoOperator web UI is the first browser-based product surface for the project.

The current alpha flow is intentionally small:

- confirm local worker connectivity
- view the configured repository source and model connection mode
- choose a repository source, project, and branch through guided lists
- open a repository through the local worker
- ask a read-only repository question
- review the model response in the browser

This UI is intentionally focused on the working read-only path. It does not present editing as a finished experience yet.

## Local Development

### Requirements

- Node.js 20+
- npm 10+
- a running RepoOperator local worker on `http://127.0.0.1:8000` or another configured URL

### Install

```bash
cd apps/web
npm install
```

### Run

```bash
export NEXT_PUBLIC_LOCAL_WORKER_BASE_URL="http://127.0.0.1:8000"
export OPENPATCH_WORKER_PROXY_TIMEOUT_MS="5000"
export OPENPATCH_WORKER_PROXY_AGENT_TIMEOUT_MS="60000"
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

## What Works

- worker health check from the UI
- repository source status for GitLab, GitHub, or local project
- model connection status for local model runtime or remote model API
- provider-aware project list loading
- list-first project selection where search filters the loaded list
- provider-aware branch list loading
- recent project shortcuts
- local project path entry for local-source workflows
- repository open flow through `/repo/open`
- read-only repository question flow through `/agent/run`
- clear loading, success, and error states
- response display for the generated model answer
- graceful unavailable-worker errors in the UI
- advanced manual project and branch overrides when discovery is not enough

## Expected Product Flow

1. Run `repooperator onboard`
2. Run `repooperator up`
3. Run `repooperator doctor`
4. Run `repooperator status`
5. Open the local web URL printed by `repooperator up`
6. Choose `gitlab`, `github`, or `local project`
7. Select a project from the visible list, or enter a local project path
8. Select a branch when the chosen source is a git repository
9. Open the repository locally
10. Ask a read-only repository question
11. Review the response in the browser

## Notes

- The UI uses local Next.js route handlers under `src/app/api/worker/*` as a simple proxy to the configured worker base URL.
- Guided repository selection uses structured provider listing endpoints under `/api/worker/provider/projects` and `/api/worker/provider/branches`.
- This keeps local development easy while avoiding direct browser-to-worker CORS setup in the first version.
- The current interface assumes the worker runs on the local machine, typically at `http://127.0.0.1:8000`.
- Health-style worker requests keep a short timeout, while `/agent/run` now uses a longer inference timeout that is suitable for local Ollama usage by default.
- You can override proxy timeouts with `OPENPATCH_WORKER_PROXY_TIMEOUT_MS` and `OPENPATCH_WORKER_PROXY_AGENT_TIMEOUT_MS`.
- The alpha UI now defaults to guided repository selection instead of manual `project_path` and branch entry.
- Search filters loaded projects; it is not required before projects appear.
- Local projects are a first-class source and support direct absolute-path entry plus recent-project suggestions.
- Manual hosted-repository overrides remain available only under an Advanced toggle.

## Next Steps

The current UI still needs:

- browser-to-local-worker pairing for a truly hosted deployment
- full task streaming and progress updates
- richer repository setup and context controls
- editing and patch review UX
- authentication and session wiring for future hosted deployments
