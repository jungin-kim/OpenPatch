# OpenPatch Deployment Guide

This guide covers the first practical deployment and onboarding setup for OpenPatch as it exists today.

OpenPatch currently consists of:

- a local worker that runs on each developer machine
- a web app that can be run locally for development
- a centralized model API endpoint configured through environment variables

## Current Deployment Model

The current project is best understood as a hybrid local setup:

- the local worker runs on `localhost` on the developer machine
- the web app can also run locally for development
- model inference is delegated to a configured OpenAI-compatible API

At this stage, the web app is not yet ready for a fully hosted production deployment where a remote browser session connects directly to a local worker across machines. The current web integration uses local Next.js proxy routes, which is practical for onboarding and development, but not a final hosted pairing architecture.

## Components

### Local Worker

The local worker is the high-trust component. It:

- reads and writes repository files
- runs commands locally
- performs git operations locally
- talks to the centralized model API

The worker should bind to `127.0.0.1` during normal use.

### Web App

The web app currently acts as a local control surface for:

- worker health checks
- repository open flow
- read-only task submission
- edit proposal review
- explicit file write
- diff review
- validation command execution

### Centralized Model API

The model backend is configured through:

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

The worker calls this backend after gathering minimal repository context locally.

## Recommended First Deployment

For open-source users, the simplest working setup is:

1. Run the local worker on the developer machine.
2. Run the web app locally on the same machine.
3. Point the worker at an OpenAI-compatible model endpoint.

This avoids premature complexity while preserving the intended architectural boundary: repository operations remain local.

## Localhost Worker Expectations

The current system assumes:

- the worker is running on `http://127.0.0.1:8000`
- the worker is reachable only from the local machine
- the web app points to the worker using `NEXT_PUBLIC_LOCAL_WORKER_BASE_URL`
- the worker is the only component that touches the filesystem or runs commands

Do not expose the worker on a public interface unless you have added additional authentication, origin protections, and transport controls.

## Environment Setup

Use the example files as a starting point:

- [apps/local-worker/.env.example](/Users/junginkim/Documents/GitHub/OpenPatch/apps/local-worker/.env.example)
- [apps/web/.env.example](/Users/junginkim/Documents/GitHub/OpenPatch/apps/web/.env.example)

## Startup Scripts

The repository includes simple startup helpers:

- [scripts/start-local-worker.sh](/Users/junginkim/Documents/GitHub/OpenPatch/scripts/start-local-worker.sh)
- [scripts/start-web.sh](/Users/junginkim/Documents/GitHub/OpenPatch/scripts/start-web.sh)

These are intentionally lightweight and intended for local development and onboarding.

## First Run Checklist

1. Configure environment variables for the local worker.
2. Start the local worker on `127.0.0.1:8000`.
3. Configure the web app to point at the local worker base URL.
4. Start the web app.
5. Open the web UI and verify the worker health check passes.
6. Open a repository through the UI.
7. Run a read-only task.
8. Optionally test the edit proposal, write, diff, and validation flow.

## What Is Not Yet Production-Ready

The following areas still need more work before a broader hosted deployment story is complete:

- browser-to-local-worker pairing for a truly hosted web app
- approval and allowlist policies for command execution
- stronger authentication around sensitive worker actions
- deployment packaging for background worker installation
- operational logging and observability for multi-user hosting
- first-class PR and MR workflows in the web app

## Related Docs

- [README.md](/Users/junginkim/Documents/GitHub/OpenPatch/README.md)
- [docs/architecture.md](/Users/junginkim/Documents/GitHub/OpenPatch/docs/architecture.md)
- [docs/architecture-diagram.md](/Users/junginkim/Documents/GitHub/OpenPatch/docs/architecture-diagram.md)
- [docs/security.md](/Users/junginkim/Documents/GitHub/OpenPatch/docs/security.md)
- [docs/troubleshooting.md](/Users/junginkim/Documents/GitHub/OpenPatch/docs/troubleshooting.md)
