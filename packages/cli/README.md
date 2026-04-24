# OpenPatch CLI

The OpenPatch CLI is the first product-oriented onboarding surface for the project.

It currently provides:

- `openpatch onboard`
- `openpatch doctor`
- `openpatch status`
- `openpatch worker start`
- `openpatch worker stop`
- `openpatch worker restart`
- `openpatch worker logs`

## Install

From the repository root:

```bash
npm install -g ./packages/cli
```

## Commands

### `openpatch onboard`

Creates the local OpenPatch config directory, writes a config file, prepares the local runtime directories, and can optionally start the local worker.

### `openpatch doctor`

Checks whether the local configuration, worker detection, worker process, worker reachability, worker URL, model backend config, and git provider config look healthy.

### `openpatch status`

Prints the current OpenPatch configuration summary and worker status.

### `openpatch worker start`

Starts the local worker as a managed background process for development.

### `openpatch worker stop`

Stops the managed local worker process.

### `openpatch worker restart`

Restarts the managed local worker process.

### `openpatch worker logs`

Prints the current local worker log file.

## Local Runtime Strategy

The current CLI uses a development-friendly runtime strategy:

- launch the worker from `apps/local-worker`
- use the worker virtual environment in `apps/local-worker/.venv`
- store runtime state under `~/.openpatch/daemon`
- store logs under `~/.openpatch/logs`

This is intentionally simple and inspectable. It is not yet an OS-level daemon installer.
