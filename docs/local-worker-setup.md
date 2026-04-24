# Local Worker Setup

This guide is for end users who want to run the OpenPatch local worker on their machine.

## What The Local Worker Does

The local worker is the component that:

- opens repositories under a configured local repo base directory
- reads and writes files
- runs validation commands
- performs git operations such as branch creation, commit, push, and merge request creation
- talks to the centralized model API after gathering local context

Because it can access local repositories and run commands, it should be treated as a trusted local process.

## Localhost Expectation

The worker should run on `127.0.0.1` by default.

This means:

- it is intended for the current machine only
- the browser or local web app connects to it through `localhost`
- it should not be exposed to the network by default

## Requirements

- Python 3.11+
- `git` installed and available on `PATH`
- access to an OpenAI-compatible model API

Optional, for GitLab workflows:

- a GitLab base URL
- a GitLab token with the permissions needed for clone, push, and merge request creation

## Setup Steps

1. Create a virtual environment.
2. Install the package in editable mode.
3. Copy or reference the example environment file.
4. Start the worker on `127.0.0.1:8000`.

## Install

```bash
cd apps/local-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure Environment

Start from [the local worker env example](../apps/local-worker/.env.example).

Required variables for the basic worker flow:

- `LOCAL_REPO_BASE_DIR`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

Optional variables:

- `GITLAB_BASE_URL`
- `GITLAB_TOKEN`
- `OPENPATCH_COMMAND_TIMEOUT_SECONDS`
- `OPENPATCH_GIT_CLONE_TIMEOUT_SECONDS`
- `OPENPATCH_GIT_FETCH_TIMEOUT_SECONDS`
- `OPENPATCH_GIT_PUSH_TIMEOUT_SECONDS`
- `OPENPATCH_MODEL_REQUEST_TIMEOUT_SECONDS`

## Start The Worker

```bash
cd apps/local-worker
source .venv/bin/activate
set -a
source .env
set +a
uvicorn openpatch_worker.main:app --host 127.0.0.1 --port 8000
```

## Verify The Worker

```bash
curl http://127.0.0.1:8000/health
```

You should receive a JSON response indicating:

- `status: ok`
- `service: openpatch-local-worker`
- the configured `repo_base_dir`

## Common User Flows

After the worker is running, users can:

- open a repository under the configured repo base directory
- ask read-only questions about the repository
- request a file proposal
- apply a reviewed file change explicitly
- inspect the git diff
- run validation commands explicitly
- create a branch, commit, push, and open a GitLab merge request explicitly

## Safety Notes

- file writes are explicit
- command execution is explicit
- nothing auto-commits
- nothing auto-pushes
- the worker should remain bound to `localhost`

## Related Docs

- [Local worker README](../apps/local-worker/README.md)
- [Security](security.md)
- [Troubleshooting](troubleshooting.md)
