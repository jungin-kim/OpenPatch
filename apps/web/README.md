# OpenPatch Web UI

The OpenPatch web UI is a minimal Next.js application that provides the first hosted interface shell for the project.

This scaffold includes:

- a top-level layout
- a landing page
- a worker connection status section
- a task input form
- a placeholder response panel

The current version is intentionally minimal, but it now supports a first worker-connected read-only flow plus an explicit first editing review flow.

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
- file edit proposal flow through `/agent/propose-file`
- explicit file write through `/fs/write`
- diff review for the written file through `/git/diff`
- graceful unavailable-worker errors in the UI

## Notes

- The UI currently uses local Next.js route handlers under `src/app/api/worker/*` as a simple proxy to the configured worker base URL.
- This keeps the browser flow easy to run locally while avoiding direct browser-to-worker CORS setup in the first version.
- A future truly hosted deployment will need a browser-to-local-worker connection strategy rather than this server-side proxy approach.
- File edits remain explicit: the model proposes content, the user reviews it, and the UI only writes the file after an explicit apply step.

## Next Steps

The current UI still needs:

- browser-to-local-worker pairing for a real hosted deployment
- richer repository setup and provider-specific repo-open inputs
- task streaming and progress updates
- better patch and diff presentation
- file selection and explicit context controls
- validation command execution after a write
- commit and push workflows
- authentication and session wiring for a future hosted deployment
