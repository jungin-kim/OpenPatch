# OpenPatch Web UI

The OpenPatch web UI is the first browser-based product surface for the project.

The current alpha flow is intentionally small:

- confirm local worker connectivity
- open a repository through the local worker
- ask a read-only repository question
- review the model response in the browser

This UI is intentionally focused on the working read-only path. It does not present editing as a finished experience yet.

## Local Development

### Requirements

- Node.js 20+
- npm 10+
- a running OpenPatch local worker on `http://127.0.0.1:8000` or another configured URL

### Install

```bash
cd apps/web
npm install
```

### Run

```bash
export NEXT_PUBLIC_LOCAL_WORKER_BASE_URL="http://127.0.0.1:8000"
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

## What Works

- worker health check from the UI
- repository open flow through `/repo/open`
- read-only repository question flow through `/agent/run`
- clear loading, success, and error states
- response display for the generated model answer
- graceful unavailable-worker errors in the UI

## Expected Product Flow

1. Run `openpatch onboard`
2. Run `openpatch worker start`
3. Run `openpatch doctor`
4. Run `openpatch status`
5. Start the web UI
6. Open a private GitLab repository
7. Ask a read-only repository question
8. Review the response in the browser

## Notes

- The UI uses local Next.js route handlers under `src/app/api/worker/*` as a simple proxy to the configured worker base URL.
- This keeps local development easy while avoiding direct browser-to-worker CORS setup in the first version.
- The current interface assumes the worker runs on the local machine, typically at `http://127.0.0.1:8000`.
- The alpha UI stays focused on repository open and read-only Q&A so the main product flow is easy to understand.

## Next Steps

The current UI still needs:

- browser-to-local-worker pairing for a truly hosted deployment
- task streaming and progress updates
- richer repository setup and context controls
- editing and patch review UX
- authentication and session wiring for future hosted deployments
