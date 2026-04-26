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

The onboarding flow will:

1. create the local OpenPatch config directory
2. create a config file
3. prompt for a model provider first
4. ask only for the model fields that match that provider
5. prompt for git provider selection and provider base URL
6. prompt for a local repo base directory
7. detect whether a local worker installation is already present
8. prepare local directories for a future daemon installation flow
9. optionally start the local worker immediately

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
- git provider config is present

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

## Standard Flow

```bash
npm install -g openpatch
openpatch onboard
openpatch worker start
openpatch doctor
```

## Development-Friendly Runtime

The current runtime model is intentionally simple:

- the CLI launches the FastAPI worker from `apps/local-worker`
- the worker runs as a managed background process
- runtime state is stored under `~/.openpatch`
- logs are written to `~/.openpatch/logs`

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
