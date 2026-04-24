# OpenPatch Web UI

The OpenPatch web UI is a minimal Next.js application that provides the first hosted interface shell for the project.

This scaffold includes:

- a top-level layout
- a landing page
- a worker connection status section
- a task input form
- a placeholder response panel

The current version is intentionally static and lightweight. It is structured so future work can connect the browser UI to a local worker running on `localhost`.

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
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

## Next Steps

The current UI still needs:

- real worker health checks against a local worker endpoint
- browser-safe connection logic for a localhost worker
- task submission and streamed response handling
- patch and diff presentation
- authentication and session wiring for a future hosted deployment
