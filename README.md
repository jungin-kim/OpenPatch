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

## Product Direction

OpenPatch is evolving from a raw architecture prototype into an easy-to-adopt developer product.

The next product goals are:

- one-command install
- one-command onboarding
- a local worker on each developer machine
- a centralized model backend
- pluggable git providers such as GitLab and GitHub

The first step in that direction is the new `openpatch` CLI under `packages/cli`.

## Getting Started

For the current practical setup:

1. Install the CLI from this repository.
2. Run `openpatch onboard`.
3. Run `openpatch doctor`.
4. Start the local worker and web app as needed during development.

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

## License

OpenPatch is released under the MIT License. See [LICENSE](LICENSE).
