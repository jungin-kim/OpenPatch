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
- `openpatch worker status`
- `openpatch worker logs`

## Install

Standard user flow:

```bash
npm install -g openpatch
```

## First End-To-End Local Flow

The first complete local OpenPatch flow is now:

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

At a high level, success means:

- the worker starts in the background
- `doctor` reports the worker process as running and the worker as reachable
- `status` shows the configured worker URL and model provider clearly
- the local health endpoint returns JSON with `status: ok`

## Commands

### `openpatch onboard`

Creates the local OpenPatch config directory under `~/.openpatch`, writes a config file, starts with a model provider choice, asks only for the fields relevant to that provider, collects git provider settings, prepares local runtime directories, and can optionally start the local worker.

For a beginner-friendly local setup, choose `Ollama` during onboarding and accept the default base URL `http://127.0.0.1:11434/v1`.

### `openpatch config show`

Prints the current local OpenPatch configuration with secrets redacted.

### `openpatch doctor`

Checks whether the local configuration, worker detection, worker process, worker reachability, worker URL, model provider config, model connectivity, and git provider config look healthy. All checks use short bounded timeouts and fail fast.

### `openpatch status`

Prints the current OpenPatch configuration summary and worker status, including worker URL, reachability, selected git provider, repo base directory, model provider, model summary, and model connectivity detail.

### `openpatch worker start`

Starts the local worker as a managed background process for development. The CLI launches the repo-source worker with an absolute `PYTHONPATH` that points at the worker `src` directory, so users do not need to export `PYTHONPATH` manually for the src-layout package.

### `openpatch worker stop`

Stops the managed local worker process.

### `openpatch worker restart`

Restarts the managed local worker process.

### `openpatch worker status`

Prints the configured worker URL, pid when known, whether the process appears alive, and whether the worker health endpoint responds.

### `openpatch worker logs`

Prints the current local worker log file, using a tail-style view that is easier to scan during startup failures.

## Local Runtime Strategy

The current CLI uses a development-friendly runtime strategy:

- launch the worker from `apps/local-worker`
- use the worker virtual environment in `apps/local-worker/.venv`
- store config under `~/.openpatch/config.json`
- store runtime state and pid files under `~/.openpatch/run`
- store logs under `~/.openpatch/logs`

This is intentionally simple and inspectable. It is not yet an OS-level daemon installer. The worker runs as a background process, not an attached foreground process, and startup waits are short and bounded.
The CLI also checks whether the configured worker port is already in use before starting, and surfaces clear startup diagnostics when import, bind, or health checks fail.

## Model Provider Choices

The onboarding flow currently supports:

- `openai`
- `anthropic`
- `gemini`
- `ollama`
- `openai-compatible`

Ollama is treated as a first-class option with product-friendly defaults for a local model setup.

## Standard User Flow

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
```

## Example Ollama Flow

Example choices during onboarding:

- model provider: `Ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `llama3.2`

Then run:

```bash
openpatch worker start
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

## Troubleshooting

- Worker import or startup failures:
  Run `openpatch worker logs`. The startup output includes the exact worker command, absolute worker src path, and `PYTHONPATH`.
- Port already in use:
  `openpatch worker start` checks the configured port before launch and fails fast with a clear message.
- Ollama not running:
  `openpatch doctor` and `openpatch status` report model connectivity failures and point to the expected Ollama-compatible models endpoint.
- Missing model:
  Pull the model locally, for example `ollama pull llama3.2`, then rerun `openpatch doctor`.
