# OpenPatch Onboarding

OpenPatch is moving toward a developer-product onboarding flow built around:

- one-command install
- one-command onboarding
- a local worker on each developer machine
- a centralized model backend
- pluggable git providers such as GitLab and GitHub

The first step in that direction is the new `openpatch` CLI.

## Install The CLI

Standard install:

```bash
npm install -g openpatch
```

This makes the `openpatch` command available on your machine.

## Run Onboarding

```bash
openpatch onboard
```

This is the first complete local onboarding path for OpenPatch. A new user can now install the CLI, choose a model provider, start the local worker, run diagnostics, and verify the local health endpoint end to end.

The onboarding flow will:

1. create the local OpenPatch config directory
2. create a config file
3. prompt for a model provider first
4. ask only for the model fields that match that provider
5. prompt for git provider selection and provider base URL
6. prompt for a local repo base directory
7. detect whether a local worker installation is already present
8. prepare local runtime directories under `~/.openpatch`
9. optionally start the local worker immediately

If you choose to start the worker during onboarding, OpenPatch launches it as a background process, waits for health for a short bounded timeout, prints success or failure, and exits cleanly.
For the repo-source local worker, the CLI handles the Python src-layout automatically with an absolute `PYTHONPATH`, so users do not need to export `PYTHONPATH` during normal CLI startup.

Current model provider choices:

- OpenAI
- Anthropic
- Gemini
- Ollama
- OpenAI-compatible

Examples of the provider-aware prompts:

- OpenAI: API key and model name, with the default base URL set to `https://api.openai.com/v1`
- Anthropic: API key and model name, with the default base URL set to `https://api.anthropic.com`
- Gemini: API key and model name, with the default base URL set to `https://generativelanguage.googleapis.com/v1beta/openai`
- Ollama: base URL and model name, with defaults of `http://127.0.0.1:11434/v1` and `ollama`
- OpenAI-compatible: base URL, API key, and model name

The resulting config stores model settings under a nested `model` object in `~/.openpatch/config.json`:

```json
{
  "model": {
    "provider": "ollama",
    "baseUrl": "http://127.0.0.1:11434/v1",
    "apiKey": "ollama",
    "model": "llama3.2"
  }
}
```

## Run Diagnostics

After onboarding:

```bash
openpatch doctor
```

This validates:

- config file exists
- local worker installation is detected
- local worker process is running
- local worker is reachable
- configured worker URL matches the running instance
- model provider config is present
- model connectivity responds within a short timeout
- git provider is configured or clearly marked as not configured

## Show The Current Config

```bash
openpatch config show
```

This prints the current local OpenPatch config with secrets redacted.

## View Current Status

```bash
openpatch status
```

This prints the current configuration summary and worker reachability.
It also shows the configured model provider clearly.

To inspect the worker runtime directly:

```bash
openpatch worker status
```

## Manage The Local Worker

Start the worker:

```bash
openpatch worker start
```

Stop the worker:

```bash
openpatch worker stop
```

Restart the worker:

```bash
openpatch worker restart
```

Show the worker logs:

```bash
openpatch worker logs
```

The log command prints a tail-style view of the current worker log file so startup failures are easy to inspect.

## Standard Flow

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

## Example Ollama Setup

For a simple local-first setup:

1. Install the CLI:

```bash
npm install -g openpatch
```

2. Run onboarding:

```bash
openpatch onboard
```

3. Choose these onboarding values at a high level:

- model provider: `Ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `llama3.2` or another local Ollama model
- git provider: your choice, or `None for now`
- local repo base directory: accept the default or choose your own

4. Start the worker if you skipped it during onboarding:

```bash
openpatch worker start
```

5. Verify the setup:

```bash
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

Expected success output at a high level:

- `openpatch worker start` prints the worker command, worker src path, expected health URL, log path, and a success message
- `openpatch doctor` reports the worker process as running and the worker as reachable
- `openpatch status` shows the configured worker URL, model provider `ollama`, and healthy worker details
- `curl http://127.0.0.1:8000/health` returns JSON with `status: ok`

## Troubleshooting Notes

### Worker Import Or Startup Failures

- Run `openpatch worker logs` to inspect recent worker output.
- The CLI startup diagnostics print the absolute worker `src` path and `PYTHONPATH`.
- If the worker app still cannot be imported, confirm the repo-source worker exists under `apps/local-worker/src/openpatch_worker`.

### Port Already In Use

- `openpatch worker start` now checks the configured port before launch.
- If port `8000` is already occupied, the CLI reports that clearly and does not keep retrying.
- Stop the existing process or reconfigure the worker URL to use another port.

### Ollama Not Running

- `openpatch doctor` and `openpatch status` report model connectivity failures with actionable guidance.
- Start Ollama and make sure `http://127.0.0.1:11434/v1/models` responds.

### Missing Model

- If Ollama is running but your chosen model is not available, pull it locally and rerun the checks.
- Example:

```bash
ollama pull llama3.2
openpatch doctor
```

## Development-Friendly Runtime

The current runtime model is intentionally simple:

- the CLI launches the FastAPI worker from `apps/local-worker`
- the worker runs as a managed background process
- runtime state and pid files are stored under `~/.openpatch/run`
- logs are written to `~/.openpatch/logs`
- worker and model connectivity checks use short bounded timeouts so CLI commands fail fast instead of hanging

This is a real local process flow, but it is not yet an OS daemon installer.

## Localhost Worker Expectation

At the current phase, OpenPatch still assumes the worker runs on the local machine and binds to `127.0.0.1`.

That means:

- the worker remains the trusted local execution layer
- repository reads, writes, diffs, commands, and git actions stay local
- the CLI and current web flow assume a localhost worker URL
- all real runtime config is stored under `~/.openpatch`, not inside the repository

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
- [Deployment guide](../DEPLOYMENT.md)
- [Local worker setup](local-worker-setup.md)
- [Troubleshooting](troubleshooting.md)
