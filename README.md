# RepoOperator

RepoOperator is an open-source developer product for local-repo agent workflows.

It is built around a practical split architecture:

- a hosted web UI for interaction
- a local worker running on each developer machine
- a centralized model backend for reasoning and generation

The core idea is simple: repository access and execution stay local, while model inference can be centralized.

## Why RepoOperator Exists

Many coding-agent systems choose one of two extremes:

- everything runs remotely on centrally managed clones
- everything runs locally inside one editor or one machine

RepoOperator aims for a third path:

- the user experience can be product-oriented and browser-based
- repository operations remain local to the developer machine
- model access can be shared through a centralized backend

This keeps repository state, credentials, tools, and runtime context close to the developer environment without requiring the full agent stack to live locally.

## Project Status

RepoOperator is preparing for its first public alpha release.

The current working milestone is a real end-to-end read-only flow:

- onboard a machine with the CLI
- start the local worker
- verify worker and model connectivity
- open a private GitLab or GitHub repository locally through the worker, or attach a local project path
- ask a read-only repository question from the web UI
- receive a response in the browser

Editing and review flows are still in progress and should not be treated as finished alpha features yet.

## Quickstart

The first public alpha flow is:

1. Install the CLI.
2. Run `repooperator onboard`.
3. Choose a model connection mode: local model runtime or remote model API.
4. If you choose a local runtime, let RepoOperator detect or guide the Ollama setup.
5. Let RepoOperator start the local worker and verify health.
6. Run `repooperator worker start` if you want to restart the worker explicitly or start it again later.
7. Run `repooperator doctor`.
8. Run `repooperator status`.
9. Start the web UI.
10. Open a private GitLab or GitHub repository, or choose a local project in the UI.
11. Ask a read-only repository question.
12. Review the response in the browser.

```bash
npm install -g repooperator
repooperator onboard
repooperator worker start
repooperator doctor
repooperator status
curl http://127.0.0.1:8000/health
```

For a simple local-first setup during onboarding, choose:

- model connection mode: `local runtime`
- model provider: `ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `qwen2.5-coder:7b`
- git provider: `gitlab`, `github`, or `local`

High-level success looks like this:

- `repooperator onboard` detects or guides the local Ollama setup
- `repooperator onboard` starts the local worker and verifies worker and model connectivity
- `repooperator doctor` confirms the worker and model are healthy after onboarding
- `repooperator status` shows the configured worker URL, model connection mode, model provider, and worker health details
- `curl http://127.0.0.1:8000/health` returns JSON with `status: ok`
- the web UI can load provider-backed project and branch lists
- the web UI can open a private repository through `/repo/open`
- the web UI can send a read-only repository question through `/agent/run`
- the response appears in the browser without modifying local files

All real runtime config lives under `~/.repooperator`, not inside the repository.
If `~/.repooperator` does not exist yet but `~/.openpatch` does, the CLI reuses and migrates the existing local config and runtime state automatically.

## Current Capabilities

RepoOperator currently supports these alpha-stage capabilities:

- CLI onboarding with a model-connection-first setup
- local worker lifecycle management through `repooperator worker start`, `stop`, `restart`, `status`, and `logs`
- bounded `doctor` and `status` checks for worker and model connectivity
- provider-backed repository open flows for GitLab and GitHub
- first-class local project open flows using absolute filesystem paths
- provider-backed and local project discovery for guided repository selection
- non-interactive private repository clone and fetch through the local worker
- read-only repository questions through the local worker and centralized model backend
- a simple hosted web UI flow for repository open, question submission, and response display

## Current Limitations

RepoOperator is not a full coding-agent product yet. Current limitations include:

- the main polished flow is read-only
- editing support is not ready to present as a finished alpha experience
- validation, patch review, and commit workflows are still evolving
- hosted-to-local worker pairing assumes a local development-style setup today
- provider-specific review flows are limited, with merge request support currently GitLab-specific
- runtime packaging and installation are still geared toward open-source early adopters rather than one-click desktop distribution

## Product Contract

The current public contract is intentionally small and explicit:

- use `project_path` as the repository identifier across worker APIs
- use `gitlab`, `github`, or `local` as repository sources
- choose either a local model runtime or a remote model API during onboarding
- keep user runtime configuration under `~/.repooperator/config.json`
- treat raw environment variables as advanced overrides rather than the normal onboarding path

## Working Read-Only Flow

The current end-to-end read-only path is:

1. `repooperator onboard`
2. `repooperator doctor`
3. `repooperator status`
4. choose a provider, project, and branch in the web UI
5. open a private GitLab repository, GitHub repository, or local project through the worker
6. ask a read-only repository question from the web UI
7. receive a response in the browser

The repository-open request looks like this:

```bash
curl -X POST http://127.0.0.1:8000/repo/open \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "branch": "main",
    "git_provider": "gitlab"
  }'
```

For a local project, use an absolute filesystem path instead:

```bash
curl -X POST http://127.0.0.1:8000/repo/open \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/Users/you/my-project",
    "git_provider": "local"
  }'
```

The matching read-only repository question looks like this:

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "task": "Summarize the repository and recommend the best starting point for understanding the codebase."
  }'
```

## Troubleshooting

- Worker not running:
  Run `repooperator worker start`, then verify with `repooperator doctor`, `repooperator status`, and `curl http://127.0.0.1:8000/health`.
- Worker import or startup failure:
  Run `repooperator worker logs`. The CLI prints the absolute worker `src` path and `PYTHONPATH` during startup.
- Port already in use:
  If `127.0.0.1:8000` is occupied, `repooperator worker start` fails fast with a clear error. Stop the other process or choose a different worker URL and port.
- Wrong repo path:
  For GitLab and GitHub, confirm `project_path` matches the provider path exactly. For local projects, use an absolute filesystem path that already exists on disk.
- Missing repository permissions:
  If `repo/open` reports repository not found or permission denied, confirm the stored GitLab or GitHub token can read the target private repository.
- Ollama not running:
  `repooperator doctor` or `repooperator status` will report model connectivity failure. Start Ollama and confirm the configured models endpoint is reachable.
- Missing model:
  If Ollama is running but `qwen2.5-coder:7b` is unavailable, pull it locally and rerun `repooperator doctor`.

## Helpful Docs

- [Onboarding guide](docs/onboarding.md)
- [Read-only demo](docs/demo.md)
- [v0.1.0-alpha checklist](docs/v0.1.0-alpha-checklist.md)
- [Architecture](docs/architecture.md)
- [Security](docs/security.md)
- [Roadmap](docs/roadmap.md)
- [Troubleshooting](docs/troubleshooting.md)

## Contributing

Contributions are welcome, especially around:

- worker reliability and API contracts
- hosted UI polish for the read-only flow
- provider integrations
- docs and onboarding ergonomics
- security review and threat modeling

Start with [Contributing](CONTRIBUTING.md).

## License

RepoOperator is released under the MIT License. See [LICENSE](LICENSE).
