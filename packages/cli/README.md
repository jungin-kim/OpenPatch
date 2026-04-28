# RepoOperator CLI

The RepoOperator CLI is the local-first setup and runtime surface for RepoOperator.
It guides first-time users through model setup, repository access, local worker preparation, and the one-command product startup flow.

## Install

```bash
npm install -g repooperator
```

## Recommended Local Flow

```bash
repooperator onboard
repooperator up
```

`repooperator onboard` creates the local configuration under `~/.repooperator`.
`repooperator up` starts the local worker and web app together, verifies both are healthy, and prints the local web URL.

## Guided Onboarding

The onboarding wizard is organized into six sections:

1. Welcome
2. Environment checks
3. Model connection
4. Repository source
5. Local worker setup
6. Final summary

The wizard uses structured terminal output, bounded health checks, and clear success, warning, and failure states.

## Re-Onboarding

Run onboarding again whenever you want to update the local setup:

```bash
repooperator onboard
```

If a config already exists, RepoOperator shows the current model, default repository source, saved repository sources, local repo directory, worker URL, and web URL. You can then choose to:

- keep the current setup and validate it
- update only model settings
- update or add repository sources
- update model and repository sources together
- fully review model, repository, and local runtime paths

Re-onboarding preserves working settings by default. Repository sources are retained, and adding another source does not erase existing GitLab, GitHub, or local project settings unless you explicitly choose to replace them.

## Model Connection Modes

RepoOperator supports two model connection modes:

- Local model runtime
- Remote model API

Supported providers:

- Ollama
- OpenAI-compatible API
- OpenAI
- Anthropic
- Gemini

Ollama is the first-class local runtime path. During onboarding, RepoOperator checks whether the `ollama` command exists, checks whether the local Ollama server is reachable, runs `ollama list` when available, displays discovered models, and lets the user select a local model. If no models are found, the wizard recommends:

```bash
ollama pull qwen2.5-coder:7b
```

## Repository Sources

Onboarding currently supports:

- GitLab
- GitHub
- Local project
- None for now

For GitLab and GitHub, RepoOperator stores the provider base URL and token locally in `~/.repooperator/config.json` so the worker can use them without manual environment exports.

## Product Runtime Commands

```bash
repooperator up
repooperator down
```

`repooperator up` is the recommended common-path command. It starts:

- the local worker
- the web UI, when the project repo contains `apps/web`

It then verifies both endpoints and prints the web URL.

`repooperator down` stops the managed web UI and worker processes cleanly.

## Diagnostics

```bash
repooperator doctor
repooperator status
```

`doctor` runs a structured health check for configuration, worker detection, worker reachability, model configuration, model connectivity, and repository provider configuration.

`status` prints a scannable runtime summary with the worker URL, process state, model summary, git provider, repository base directory, and runtime files.

## Worker Maintenance

These commands remain available for development and troubleshooting:

```bash
repooperator worker start
repooperator worker stop
repooperator worker restart
repooperator worker status
repooperator worker logs
```

For the normal product experience, prefer:

```bash
repooperator up
```

## Local Runtime Strategy

The current CLI uses a development-friendly runtime strategy:

- launch the worker from `apps/local-worker`
- use the worker virtual environment in `apps/local-worker/.venv`
- store config under `~/.repooperator/config.json`
- store runtime state and pid files under `~/.repooperator/run`
- store logs under `~/.repooperator/logs`

If `~/.repooperator` does not exist yet but `~/.openpatch` does, the CLI attempts a practical migration of existing local config and runtime files.

## Troubleshooting

- Worker startup failure: run `repooperator worker logs`.
- Runtime health issue: run `repooperator doctor` and `repooperator status`.
- Port already in use: stop the existing process or run `repooperator down`.
- Ollama not running: start it with `ollama serve`, then rerun `repooperator doctor`.
- Missing model: run `ollama pull qwen2.5-coder:7b`, then rerun onboarding or update the config.
