# OpenPatch

OpenPatch is an open-source foundation for coding-agent workflows built around a practical split architecture:

- a hosted web UI for interaction and collaboration
- a local worker running on each developer machine
- a centralized model backend for inference and orchestration

The core idea is simple: repositories, file access, diffs, and command execution should stay on the developer's machine, while model inference can be provided by a shared backend.

## Why OpenPatch Exists

Many agent systems choose one of two extremes:

- everything runs remotely on centrally managed clones
- everything runs locally in a single machine or editor integration

OpenPatch aims for a third path that is useful for open-source and general-purpose developer workflows:

- the user experience can be hosted and collaborative
- the model backend can be centralized and reusable
- repository operations remain local to the machine that already has the code, tools, credentials, and runtime context

This design reduces unnecessary repository duplication, keeps command execution close to the actual development environment, and makes it easier to support diverse local setups without forcing all work through a central execution layer.

## Architecture At A Glance

OpenPatch is designed around three major components:

1. Hosted Web UI
   A browser-based interface for task submission, agent state, patch review, and future collaboration features.
2. Local Worker
   A lightweight service on the developer machine that owns repository operations such as file reads and writes, diff generation, and command execution.
3. Central Model Backend
   A shared backend that handles model inference, orchestration logic, streaming responses, and policy-aware request handling.

### High-Level Flow

```text
Browser
  -> Hosted Web UI
  -> Local Worker on developer machine
     -> local repository access
     -> local command execution
     -> local git operations
  -> Central Model Backend
     -> model inference
     -> response streaming
     -> orchestration
```

In this model, the local worker gathers only the necessary repository context, sends minimal task context to the central backend, and applies model-produced edits locally after user review or explicit workflow steps.

## Repository Layout

```text
.
|-- apps/
|   |-- web/
|   `-- local-worker/
|-- packages/
|   |-- cli/
|   |-- shared/
|   `-- agent-core/
|-- docs/
|-- .github/
|   `-- ISSUE_TEMPLATE/
|-- CONTRIBUTING.md
|-- LICENSE
`-- README.md
```

## Project Status

OpenPatch is in the bootstrap stage.

The current repository is establishing the project structure, architecture direction, and contribution guidelines before implementation begins. The first milestone is a minimal vertical slice that proves the hosted UI, local worker, and centralized model backend can cooperate cleanly.

## Phased Roadmap

- Phase 0: Repository bootstrap, documentation, and interface planning
- Phase 1: Local worker MVP for repository and command operations
- Phase 2: Central model integration and execution loop
- Phase 3: Hosted web UI MVP
- Phase 4: Editing workflow with patches and review
- Phase 5: Git workflow support
- Phase 6: Packaging, deployment, and operational hardening

See [the roadmap](docs/roadmap.md) for the fuller phase breakdown.

## Getting Started

The first successful local onboarding flow looks like this:

1. Install the CLI.
2. Run `openpatch onboard`.
3. Choose a model provider such as Ollama.
4. Run `openpatch worker start`.
5. Run `openpatch doctor`.
6. Run `openpatch status`.
7. Verify the local worker health endpoint.

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

All real runtime config lives under `~/.openpatch`, not inside the repository.

During onboarding, OpenPatch now starts with a model provider choice so setup feels product-oriented instead of infrastructure-heavy. Current provider options include OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible backends.
Onboarded GitLab and GitHub settings are also stored under `~/.openpatch/config.json` so the local worker can reuse the same provider configuration without extra manual exports.

### Example Ollama Flow

If you want a simple local-first setup, choose `Ollama` during onboarding and accept the default base URL:

- provider: `ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: for example `llama3.2`

High-level success looks like this:

- `openpatch worker start` reports that the local worker started
- `openpatch doctor` shows the worker process as running and the worker as reachable
- `openpatch status` shows the configured worker URL, model provider, and worker health details
- `curl http://127.0.0.1:8000/health` returns a small JSON response with `status: ok`

### Quick Troubleshooting

- Worker import or startup failure:
  Run `openpatch worker logs`. The CLI now prints the absolute worker `src` path and `PYTHONPATH` during startup, which helps confirm the repo-source worker layout is being launched correctly.
- Port already in use:
  If `127.0.0.1:8000` is occupied, `openpatch worker start` fails fast with a clear error instead of retrying indefinitely. Stop the other process or choose a different worker URL and port.
- Ollama not running:
  `openpatch doctor` or `openpatch status` will report model connectivity failure. Start Ollama and confirm the configured models endpoint is reachable.
- Missing model:
  If Ollama is running but the selected model is unavailable, pull the model locally and rerun `openpatch doctor`.

Helpful onboarding docs:

- [Deployment guide](DEPLOYMENT.md)
- [Onboarding guide](docs/onboarding.md)
- [Local worker setup](docs/local-worker-setup.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture diagram](docs/architecture-diagram.md)

## Contribution Guidance

Contributions are welcome early, especially around:

- architecture review and protocol design
- local worker interfaces
- shared type definitions and message schemas
- security review and threat modeling
- docs, examples, and contributor ergonomics

If you want to help, start with [Contributing](CONTRIBUTING.md). For deeper design context, see:

- [Architecture](docs/architecture.md)
- [Architecture diagram](docs/architecture-diagram.md)
- [Security](docs/security.md)
- [Roadmap](docs/roadmap.md)

## Design Priorities

- Keep repository and execution operations local by default
- Keep interfaces explicit, inspectable, and portable
- Minimize the amount of code and secret context sent to centralized services
- Stay general-purpose and provider-agnostic
- Build for open-source collaboration from day one

## Current Product Step

OpenPatch now includes a real local worker lifecycle flow through the CLI:

- `openpatch config show`
- `openpatch onboard`
- `openpatch worker start`
- `openpatch doctor`
- `openpatch status`

The current implementation manages a development-friendly background worker process with runtime state and logs under `~/.openpatch`, plus a provider-first model onboarding flow that clearly shows which model backend is configured.

The CLI now uses bounded startup and health-check timeouts so `openpatch onboard`, `openpatch doctor`, and `openpatch status` fail fast instead of waiting indefinitely. You can inspect the runtime directly with `openpatch worker status` and `openpatch worker logs`.
For the repo-source worker, the CLI also handles the Python `src` layout automatically during startup with an absolute `PYTHONPATH`, so users do not need to set `PYTHONPATH` by hand.

## License

OpenPatch is released under the MIT License. See [LICENSE](LICENSE).
