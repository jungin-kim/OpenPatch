# OpenPatch Web UI

The OpenPatch web UI is a minimal Next.js application that provides the first hosted interface shell for the project.

This scaffold includes:

- a top-level layout
- a landing page
- a worker connection status section
- a repository open flow through the local worker
- a read-only task input flow
- a response panel for worker results

The current version is intentionally minimal and product-oriented. It focuses on the first end-to-end hosted UI to local worker flow.

## Local Development

### Requirements

- Node.js 20+
- npm 10+

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
- repository open flow through the local worker
- read-only task submission to `/agent/run`
- result display for the generated response
- graceful unavailable-worker errors in the UI
- clear connection state for worker health and basic task usability

## Notes

- The UI currently uses local Next.js route handlers under `src/app/api/worker/*` as a simple proxy to the configured worker base URL.
- This keeps the browser flow easy to run locally while avoiding direct browser-to-worker CORS setup in the first version.
- A future truly hosted deployment will need a browser-to-local-worker connection strategy rather than this server-side proxy approach.
- The current interface assumes the worker runs on the local machine, typically at `http://127.0.0.1:8000`.
- This first version stays read-only in the UI so the connection, repository open flow, and task submission flow are easy to understand.

## Next Steps

The current UI still needs:

- browser-to-local-worker pairing for a real hosted deployment
- richer repository setup and provider-specific repo-open inputs
- task streaming and progress updates
- editing and patch review UX
- file selection and explicit context controls
- authentication and session wiring for a future hosted deployment
