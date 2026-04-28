# RepoOperator CLI

The RepoOperator CLI is the first product-oriented onboarding surface for the project.

It currently provides:

- `repooperator config show`
- `repooperator onboard`
- `repooperator up`
- `repooperator down`
- `repooperator doctor`
- `repooperator status`
- `repooperator worker start`
- `repooperator worker stop`
- `repooperator worker restart`
- `repooperator worker status`
- `repooperator worker logs`

## Install

Standard user flow:

```bash
npm install -g repooperator
```

## First End-To-End Local Flow

The first public alpha CLI flow is:

```bash
npm install -g repooperator
repooperator onboard
repooperator up
repooperator doctor
repooperator status
```

At a high level, success means:

- Ollama is detected locally or RepoOperator guides the installation path
- local Ollama models are detected or RepoOperator offers to pull a recommended model
- the worker starts in the background during onboarding
- `repooperator up` starts the worker and web UI together and prints the local web URL
- onboarding verifies worker health and model connectivity
- `status` shows the configured worker URL, model connection mode, and model provider clearly
- the local health endpoint returns JSON with `status: ok`
- the machine is ready for the read-only web UI flow

## Commands

### `repooperator onboard`

Creates the local RepoOperator config directory under `~/.repooperator`, writes a config file, starts with a model connection choice, asks only for the fields relevant to that runtime or API type, collects git provider settings, prepares local runtime directories, starts the local worker, and verifies the setup.

For a beginner-friendly local setup, choose `Local model runtime`, then `Ollama`, and accept the default base URL `http://127.0.0.1:11434/v1`.
The Ollama path is now guided: RepoOperator detects whether `ollama` is installed, can offer a Homebrew install on macOS, checks whether the Ollama server is running, lists available local models, and can offer to pull `qwen2.5-coder:7b`.
For GitLab or GitHub repository flows, onboarding now stores the provider base URL and token in `~/.repooperator/config.json` so the local worker can use them without extra manual exports.
Across the product, the repository identifier is `project_path`, and the supported onboarding provider choices for repository access are `gitlab`, `github`, `local`, or `none`.

### `repooperator up`

Starts the local product runtime. This starts the managed local worker, starts the web UI, verifies both are reachable, and prints the local web URL. This is the recommended command for the normal local product experience after onboarding.

### `repooperator down`

Stops the managed web UI and local worker processes started by RepoOperator.

### `repooperator config show`

Prints the current local RepoOperator configuration with secrets redacted.

### `repooperator doctor`

Checks whether the local configuration, worker detection, worker process, worker reachability, worker URL, model connection config, model connectivity, and git provider configuration look healthy. All checks use short bounded timeouts and fail fast.

### `repooperator status`

Prints the current RepoOperator configuration summary and worker status, including worker URL, reachability, configured git provider, repo base directory, model connection mode, model provider, model summary, and model connectivity detail.

### `repooperator worker start`

Starts only the local worker as a managed background process for maintenance and development. For the common product path, use `repooperator up` so the worker and web UI start together. The CLI launches the repo-source worker with an absolute `PYTHONPATH` that points at the worker `src` directory, so users do not need to export `PYTHONPATH` manually for the src-layout package.

### `repooperator worker stop`

Stops the managed local worker process, waits briefly for a graceful shutdown, force-stops it if needed, verifies the configured worker port is no longer occupied by that worker, and cleans up stale runtime state files automatically.

### `repooperator worker restart`

Performs a full stop-and-cleanup cycle first, then starts the worker again. If the configured worker port is still occupied by another process, restart fails clearly instead of trying to start on top of it.

### `repooperator worker status`

Prints the configured worker URL, pid when known, whether the process appears alive, and whether the worker health endpoint responds.

### `repooperator worker logs`

Prints the current local worker log file, using a tail-style view that is easier to scan during startup failures.

## Local Runtime Strategy

The current CLI uses a development-friendly runtime strategy:

- launch the worker from `apps/local-worker`
- use the worker virtual environment in `apps/local-worker/.venv`
- store config under `~/.repooperator/config.json`
- store runtime state and pid files under `~/.repooperator/run`
- store logs under `~/.repooperator/logs`

This is intentionally simple and inspectable. It is not yet an OS-level daemon installer. The worker runs as a background process, not an attached foreground process, and startup waits are short and bounded.
The CLI also checks whether the configured worker port is already in use before starting, and surfaces clear startup diagnostics when import, bind, or health checks fail.
If `~/.repooperator` does not exist yet but `~/.openpatch` does, the CLI will migrate the existing local config and runtime files automatically.

## Model Connection Choices

The onboarding flow starts with two first-class model connection modes:

- `local-runtime`
- `remote-api`

Under those modes, RepoOperator currently supports:

- `ollama`
- `openai-compatible`
- `openai`
- `anthropic`
- `gemini`

Ollama is treated as the first-class local self-served option with product-friendly defaults and guided setup.

## Standard User Flow

```bash
npm install -g repooperator
repooperator onboard
repooperator up
repooperator doctor
repooperator status
```

## Example Ollama Flow

Example choices during onboarding:

- model connection mode: `Local model runtime`
- model provider: `Ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `qwen2.5-coder:7b`

Then run:

```bash
repooperator up
repooperator doctor
repooperator status
```

## Troubleshooting

- Worker import or startup failures:
  Run `repooperator worker logs`. The startup output includes the exact worker command, absolute worker src path, and `PYTHONPATH`.
- Port already in use:
  `repooperator worker start` checks the configured port before launch and fails fast with a clear message.
- Ollama not running:
  `repooperator onboard`, `repooperator doctor`, and `repooperator status` report model connectivity failures and point to the expected Ollama-compatible models endpoint.
- Missing model:
  Pull the model locally, for example `ollama pull qwen2.5-coder:7b`, then rerun `repooperator doctor`.
