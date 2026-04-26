# OpenPatch CLI

The OpenPatch CLI is the first product-oriented onboarding surface for the project.

It currently provides:

- `openpatch config show`
- `openpatch onboard`
- `openpatch doctor`
- `openpatch status`
- `openpatch worker start`
- `openpatch worker stop`
- `openpatch worker restart`
- `openpatch worker logs`

## Install

Standard user flow:

```bash
npm install -g openpatch
```

## Commands

### `openpatch onboard`

Creates the local OpenPatch config directory under `~/.openpatch`, writes a config file, collects model and provider settings, prepares local runtime directories, and can optionally start the local worker.

### `openpatch config show`

Prints the current local OpenPatch configuration with secrets redacted.

### `openpatch doctor`

Checks whether the local configuration, worker detection, worker process, worker reachability, worker URL, model backend config, and git provider config look healthy.

### `openpatch status`

Prints the current OpenPatch configuration summary and worker status, including worker URL, reachability, selected provider, repo base directory, and model backend summary.

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
- store config under `~/.openpatch/config.json`
- store runtime state under `~/.openpatch/daemon`
- store logs under `~/.openpatch/logs`

This is intentionally simple and inspectable. It is not yet an OS-level daemon installer.

## Standard User Flow

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
```
