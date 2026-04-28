# RepoOperator

[![CI](https://img.shields.io/github/actions/workflow/status/jungin-kim/RepoOperator/ci.yml?branch=main&label=CI)](https://github.com/jungin-kim/RepoOperator/actions)
[![Web E2E](https://img.shields.io/github/actions/workflow/status/jungin-kim/RepoOperator/web-e2e.yml?branch=main&label=Web%20E2E)](https://github.com/jungin-kim/RepoOperator/actions)
[![npm](https://img.shields.io/npm/v/repooperator?label=npm)](https://www.npmjs.com/package/repooperator)
[![License](https://img.shields.io/github/license/jungin-kim/RepoOperator)](LICENSE)
[![GitHub repo](https://img.shields.io/badge/GitHub-RepoOperator-181717?logo=github)](https://github.com/jungin-kim/RepoOperator)
[![Issues](https://img.shields.io/github/issues/jungin-kim/RepoOperator)](https://github.com/jungin-kim/RepoOperator/issues)

RepoOperator is a local-first repository assistant for opening private codebases, asking read-only questions, and keeping repository access on your machine.

## Why RepoOperator

Many coding-agent products choose one of two extremes: clone everything into a hosted environment, or run the entire experience inside one local editor.

RepoOperator explores a third path:

- repository access, credentials, tools, and working copies stay local
- the user experience can still be browser-based and product-oriented
- model access can be local through Ollama or remote through an enterprise-compatible API

The current alpha is intentionally focused: onboard a machine, start the local runtime, open a repository, and ask read-only questions.

## Features

- One-command local product startup with `repooperator up`
- Guided onboarding for repository source and model connection setup
- Local worker that performs repository operations on the developer machine
- Browser UI with project selection, branch selection, and repository-aware chat
- GitLab and GitHub project discovery through stored provider config
- First-class local project support using absolute filesystem paths
- Ollama-first local model runtime support
- Remote model API support for OpenAI-compatible and enterprise-style APIs
- Read-only repository Q&A through the local worker
- Runtime config stored under `~/.repooperator`
- Practical migration support from older `~/.openpatch` config paths

## Quickstart

Install the CLI:

```bash
npm install -g repooperator
```

Run onboarding once:

```bash
repooperator onboard
```

Start the local product runtime:

```bash
repooperator up
```

Open the printed local web URL, choose a repository, and ask a read-only question.

## First End-To-End Local Flow

The intended common path is:

1. Install the CLI.
2. Run `repooperator onboard`.
3. Choose a repository source: GitLab, GitHub, or local project.
4. Choose a model connection mode: local runtime or remote API.
5. Run `repooperator up`.
6. Open the printed web URL.
7. Select a project and branch.
8. Open the repository locally.
9. Ask a read-only repository question.
10. Review the answer in the browser.

```bash
npm install -g repooperator
repooperator onboard
repooperator up
repooperator doctor
repooperator status
```

Health can also be checked directly:

```bash
curl http://127.0.0.1:8000/health
```

## Supported Repository Sources

RepoOperator currently supports these repository sources:

| Source | Status | Notes |
| --- | --- | --- |
| GitLab | Working alpha path | Project listing, branch listing, clone/fetch, and read-only Q&A are the most exercised path. |
| GitHub | Supported alpha path | Uses the same provider-oriented flow, with GitHub token and base URL from onboarding. |
| Local project | Supported alpha path | Uses absolute filesystem paths and can work with git repositories or plain directories. |

Provider credentials are stored in `~/.repooperator/config.json` by onboarding. Raw environment variables remain available as advanced overrides.

## Supported Model Connection Modes

RepoOperator supports two model connection modes:

| Mode | Providers | Notes |
| --- | --- | --- |
| Local self-served runtime | Ollama | First-class local path. The default suggested model is `qwen2.5-coder:7b`. |
| Remote model API | OpenAI-compatible, OpenAI, Anthropic, Gemini | Intended for enterprise API gateways and hosted model providers. |

For a local Ollama setup, onboarding uses:

```text
http://127.0.0.1:11434/v1
```

## Web App

The web app is split into two experiences:

- `/` is a lightweight landing page.
- `/app` is the repository-aware chat workspace.

The app screen includes:

- a sidebar for new chat, thread state, and recent repositories
- a top bar for repository source, project, branch, worker status, and model status
- a chat area with repository context, messages, collapsible tool/result cards, and a composer

For local development:

```bash
cd apps/web
npm install
npm run dev
```

Then open:

```text
http://127.0.0.1:3000
```

## CLI Commands

Core commands:

```bash
repooperator onboard
repooperator up
repooperator down
repooperator doctor
repooperator status
repooperator config show
```

Worker maintenance commands:

```bash
repooperator worker start
repooperator worker stop
repooperator worker restart
repooperator worker status
repooperator worker logs
```

The recommended product flow is:

```bash
repooperator onboard
repooperator up
```

Use `worker` commands when you need lower-level runtime inspection or maintenance.

## Architecture Overview

RepoOperator is built from three main pieces:

```text
Browser UI
  |
  | local HTTP proxy
  v
Local worker on the developer machine
  |
  | git, filesystem, command, provider APIs
  v
Local repositories and configured model backend
```

Key directories:

- `packages/cli` contains the `repooperator` CLI.
- `apps/local-worker` contains the Python local worker and API routes.
- `apps/web` contains the Next.js web app.
- `docs` contains architecture, onboarding, demo, security, roadmap, and troubleshooting notes.

Helpful docs:

- [Onboarding guide](docs/onboarding.md)
- [Read-only demo](docs/demo.md)
- [Architecture](docs/architecture.md)
- [Architecture diagram](docs/architecture-diagram.md)
- [Security](docs/security.md)
- [Roadmap](docs/roadmap.md)
- [Troubleshooting](docs/troubleshooting.md)

## Current Capabilities

RepoOperator currently supports:

- CLI onboarding with repository provider and model connection setup
- one-command local runtime startup through `repooperator up`
- worker lifecycle management through the CLI
- bounded health checks through `doctor` and `status`
- GitLab and GitHub provider-backed repository open flows
- local project open flows with absolute paths
- visible project lists and branch lists in the web UI
- non-interactive clone/fetch for private repositories when provider credentials are configured
- read-only repository questions through the local worker
- query-aware repository context retrieval for more useful answers than a README-only flow

## Current Limitations

RepoOperator is still alpha-stage software. Important limitations:

- The main polished flow is read-only.
- Editing, patch review, validation, commit, and merge-request workflows are still evolving.
- Hosted-to-local worker pairing is currently development-style rather than packaged desktop software.
- GitLab is the most exercised provider path today.
- GitHub and local project flows follow the same direction, but need more real-world hardening.
- Web chat history is currently local UI state, not a durable multi-user collaboration system.
- CI/Web E2E workflows are expected project surfaces, but this repository may not yet include complete workflow definitions.

## Roadmap

Near-term priorities:

- harden `repooperator up` and `repooperator down` across more local environments
- improve repository selection and branch-selection UX
- improve file-aware retrieval for code-specific questions
- show which files were used in each answer more consistently
- expand GitHub provider coverage
- add stronger web end-to-end coverage
- continue the OpenPatch-to-RepoOperator cleanup where legacy names remain in internal module paths

Longer-term direction:

- richer repository understanding workflows
- review and patch proposal flows
- team-friendly hosted UI pairing with local workers
- safer write workflows with explicit review and confirmation steps

See [docs/roadmap.md](docs/roadmap.md) for more detail.

## Contributing

Contributions are welcome, especially around:

- worker reliability and API contracts
- provider integrations
- web app usability
- retrieval quality
- onboarding and documentation
- security review and threat modeling

Start with [CONTRIBUTING.md](CONTRIBUTING.md). For bugs or feature requests, open an issue on [GitHub](https://github.com/jungin-kim/RepoOperator/issues).

## License

RepoOperator is released under the MIT License. See [LICENSE](LICENSE).
