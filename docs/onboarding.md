# RepoOperator Onboarding

RepoOperator is moving toward a developer-product onboarding flow built around:

- one-command install
- one-command onboarding
- one-command local product startup
- a local worker on each developer machine
- a centralized model backend
- pluggable repository sources such as GitLab, GitHub, and local projects

The first step in that direction is the new `repooperator` CLI.

## Install The CLI

Standard install:

```bash
npm install -g repooperator
```

This makes the `repooperator` command available on your machine.

## Run Onboarding

```bash
repooperator onboard
```

This is the first complete local onboarding path for RepoOperator. A new user can now install the CLI, choose a model connection mode, start the local worker, run diagnostics, and verify the local health endpoint end to end.
It also supports the first real read-only repository workflow: open a private hosted repository or a local project through the local worker, read a file locally, and ask for a repository summary through `/agent/run`.

The normalized product contract for this flow is:

- use `project_path` as the repository identifier across worker APIs
- choose `gitlab`, `github`, `local`, or `none` during onboarding
- keep canonical runtime configuration in `~/.repooperator/config.json`
- treat environment variables as advanced overrides, not the standard setup path

If `~/.repooperator` does not exist yet but `~/.openpatch` does, the CLI will migrate the existing local config and runtime files into the new RepoOperator home automatically.

The onboarding flow will:

1. create the local RepoOperator config directory
2. create a config file
3. prompt for a model connection mode first
4. either guide a local model runtime setup or prompt for a remote model API type
5. ask only for the fields that match that runtime or API type
6. guide the Ollama setup automatically when `Ollama` is selected
7. prompt for repository source selection, plus provider base URL and token when needed
8. prompt for a local repo base directory
9. detect whether a local worker installation is already present
10. prepare local runtime directories under `~/.repooperator`
11. start the local worker automatically
12. verify worker health and model connectivity before finishing

RepoOperator now finishes onboarding by launching the worker as a background process, waiting for health for a short bounded timeout, checking model connectivity, and printing a concise success summary.
For the repo-source local worker, the CLI handles the Python src-layout automatically with an absolute `PYTHONPATH`, so users do not need to export `PYTHONPATH` during normal CLI startup.

## Start The Local Product

After onboarding, use the product command:

```bash
repooperator up
```

This starts the local worker and web UI, verifies that both are reachable, and prints the local web URL. Use `repooperator down` to stop the managed local runtime.

Current model connection choices:

- Local model runtime
  Ollama
- Remote model API
  OpenAI-compatible
  OpenAI
  Anthropic
  Gemini

Examples of the provider-aware prompts:

- Local model runtime, Ollama: guided local detection, server reachability checks, model discovery, and a default base URL of `http://127.0.0.1:11434/v1`
- Remote model API, OpenAI: API key and model name, with the default base URL set to `https://api.openai.com/v1`
- Remote model API, Anthropic: API key and model name, with the default base URL set to `https://api.anthropic.com`
- Remote model API, Gemini: API key and model name, with the default base URL set to `https://generativelanguage.googleapis.com/v1beta/openai`
- Remote model API, OpenAI-compatible: base URL, API key, and model name

The resulting config stores model settings under a nested `model` object in `~/.repooperator/config.json`:

```json
{
  "model": {
    "connectionMode": "local-runtime",
    "provider": "ollama",
    "baseUrl": "http://127.0.0.1:11434/v1",
    "apiKey": "ollama",
    "model": "qwen2.5-coder:7b"
  }
}
```

## Run Diagnostics

After onboarding:

```bash
repooperator doctor
```

This validates:

- config file exists
- local worker installation is detected
- local worker process is running
- local worker is reachable
- configured worker URL matches the running instance
- model connection config is present
- model connectivity responds within a short timeout
- git provider is configured or clearly marked as not configured

## Show The Current Config

```bash
repooperator config show
```

This prints the current local RepoOperator config with secrets redacted.

## View Current Status

```bash
repooperator status
```

This prints the current configuration summary and worker reachability.
It also shows the configured model connection mode and provider clearly.

To inspect the worker runtime directly:

```bash
repooperator worker status
```

## Manage The Local Worker

Start only the worker for maintenance or development:

```bash
repooperator worker start
```

Stop the worker:

```bash
repooperator worker stop
```

Restart the worker:

```bash
repooperator worker restart
```

Show the worker logs:

```bash
repooperator worker logs
```

The log command prints a tail-style view of the current worker log file so startup failures are easy to inspect.

## Standard Flow

```bash
npm install -g repooperator
repooperator onboard
repooperator up
repooperator doctor
repooperator status
```

## Example Ollama Setup

For a simple local-first setup:

1. Install the CLI:

```bash
npm install -g repooperator
```

2. Run onboarding:

```bash
repooperator onboard
```

3. RepoOperator will guide these Ollama-specific steps:

- detect whether the `ollama` command is installed
- on macOS, offer a Homebrew install when available
- detect whether the Ollama server is running
- offer to start the server if needed
- list available local models
- offer to pull `qwen2.5-coder:7b` if no suitable model is available

4. Choose these onboarding values at a high level:

- model connection mode: `Local model runtime`
- model provider: `Ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `qwen2.5-coder:7b`
- repository source: `gitlab`, `github`, `local`, or `None for now`
- if you choose GitLab or GitHub, provide the provider base URL and token so the worker can reuse the same config later
- if you choose `local`, RepoOperator will treat absolute local filesystem paths as first-class project identifiers
- local repo base directory: accept the default or choose your own

5. Verify the setup:

```bash
repooperator up
repooperator doctor
repooperator status
```

Expected success output at a high level:

- `repooperator onboard` prints a concise onboarding summary
- the worker starts during onboarding
- `repooperator up` starts the local worker and web UI together and prints the local web URL
- worker health and model connectivity are verified before onboarding finishes
- `repooperator status` shows the configured worker URL, model connection mode `local runtime`, model provider `ollama`, and healthy worker details
- `curl http://127.0.0.1:8000/health` returns JSON with `status: ok`

## First Read-Only Workflow

Once onboarding is complete, this is the first real read-only flow:

```bash
repooperator up
```

1. Open a private repository through the local worker:

```bash
curl -X POST http://127.0.0.1:8000/repo/open \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "branch": "main",
    "git_provider": "gitlab"
  }'
```

2. Read a file from the repository:

```bash
curl -X POST http://127.0.0.1:8000/fs/read \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "relative_path": "README.md"
  }'
```

3. Ask the worker for a read-only repository summary:

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "task": "Summarize the repository and recommend the best starting point for understanding the codebase."
  }'
```

Expected success output at a high level:

- `repo/open` returns the resolved local repo path, branch, head SHA, and a success message
- `fs/read` returns the requested file content from the local checkout
- `/agent/run` returns structured JSON with:
  `project_path`, `task`, `model`, `branch`, `repo_root_name`, `context_summary`, and `response`

## Private GitLab Example

For a private GitLab repository, normal product usage is:

1. Run `repooperator onboard`.
2. Choose `gitlab` as the git provider.
3. Provide the GitLab base URL and a token with repository read access.
4. Start the local product with `repooperator up`.
5. Open the printed web URL and choose the project from the visible list.

The worker will use the stored provider config from `~/.repooperator/config.json` and perform clone and fetch non-interactively.
GitHub follows the same repository-open flow with `git_provider: "github"` and matching provider settings from onboarding.

## Troubleshooting Notes

### Worker Import Or Startup Failures

- Run `repooperator worker logs` to inspect recent worker output.
- The CLI startup diagnostics print the absolute worker `src` path and `PYTHONPATH`.
- If the worker app still cannot be imported, confirm the repo-source worker exists under `apps/local-worker/src/openpatch_worker`.

### Port Already In Use

- `repooperator worker start` now checks the configured port before launch.
- If port `8000` is already occupied, the CLI reports that clearly and does not keep retrying.
- Stop the existing process or reconfigure the worker URL to use another port.

### Wrong Repo Path

- For GitLab or GitHub, confirm `project_path` matches the provider path exactly, for example `group/private-repo` or `owner/repo`.
- For local projects, use an absolute filesystem path such as `/Users/you/my-project`.

### Missing GitLab Permissions

- If `repo/open` reports repository not found or permission denied, confirm the stored GitLab token can read that private repository.
- If onboarding was completed without a token, rerun `repooperator onboard` and update the git provider settings.

### Ollama Not Running

- `repooperator doctor` and `repooperator status` report model connectivity failures with actionable guidance.
- Start Ollama and make sure `http://127.0.0.1:11434/v1/models` responds.

### Missing Model

- If Ollama is running but `qwen2.5-coder:7b` is not available, pull it locally and rerun the checks.
- Example:

```bash
ollama pull qwen2.5-coder:7b
repooperator doctor
```

## Development-Friendly Runtime

The current runtime model is intentionally simple:

- the CLI launches the FastAPI worker from `apps/local-worker`
- the worker runs as a managed background process
- runtime state and pid files are stored under `~/.repooperator/run`
- logs are written to `~/.repooperator/logs`
- worker and model connectivity checks use short bounded timeouts so CLI commands fail fast instead of hanging

This is a real local process flow, but it is not yet an OS daemon installer.

## Localhost Worker Expectation

At the current phase, RepoOperator still assumes the worker runs on the local machine and binds to `127.0.0.1`.

That means:

- the worker remains the trusted local execution layer
- repository reads, writes, diffs, commands, and git actions stay local
- the CLI and current web flow assume a localhost worker URL
- all real runtime config is stored under `~/.repooperator`, not inside the repository

## Current Limits

The current onboarding phase is real, but intentionally minimal:

- it prepares configuration and local directories
- it detects repo-source worker availability
- it can manage a local background worker process
- it does not yet install an OS-level daemon automatically
- it does not yet provide a one-command hosted pairing flow

Those are the next product steps after the first onboarding surface is stable.

## Related Docs

- [README](../README.md)
- [Read-only demo](demo.md)
- [Deployment guide](../DEPLOYMENT.md)
- [Local worker setup](local-worker-setup.md)
- [Troubleshooting](troubleshooting.md)
