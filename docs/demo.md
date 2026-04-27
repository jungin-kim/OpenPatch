# OpenPatch Demo

This guide shows the first successful end-to-end read-only OpenPatch workflow.

It covers:

- `openpatch onboard`
- `openpatch worker start`
- `openpatch doctor`
- `openpatch status`
- `repo/open` against a private GitLab repository
- `fs/read`
- `/agent/run` repository summarization

## Overview

OpenPatch now supports a working product flow where:

1. the CLI prepares local runtime config
2. the local worker starts on the developer machine
3. a private repository is opened locally through the worker
4. a file is read locally through the worker
5. a read-only repository understanding task is sent to the configured model backend

Repository operations stay local. The model backend only receives the minimal repository context needed for the task.

## Example Setup

This example uses:

- model provider: `ollama`
- model: `qwen2.5-coder:7b`
- worker URL: `http://127.0.0.1:8000`
- git provider: `gitlab`
- repository path: `group/private-repo`

## Step 1: Onboard

Install the CLI:

```bash
npm install -g openpatch
```

Run onboarding:

```bash
openpatch onboard
```

Suggested choices:

- model provider: `Ollama`
- base URL: `http://127.0.0.1:11434/v1`
- model name: `qwen2.5-coder:7b`
- git provider: `GitLab`
- GitLab base URL: your GitLab host URL
- GitLab token: a token with private repository read access
- local repo base directory: accept the default or choose your own

High-level success:

- OpenPatch writes `~/.openpatch/config.json`
- model and GitLab settings are stored for the worker to reuse
- local runtime directories are prepared under `~/.openpatch`

## Step 2: Start The Worker

```bash
openpatch worker start
```

High-level success:

- the worker starts in the background
- the CLI prints the worker command, worker `src` path, `PYTHONPATH`, health URL, log file, and pid file

## Step 3: Verify Worker Health

```bash
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

High-level success:

- `doctor` shows the worker process as running and the worker as reachable
- `status` shows the configured worker URL, model provider, and worker health detail
- the health endpoint returns JSON with `status: ok`

## Step 4: Open A Private GitLab Repository

```bash
curl -X POST http://127.0.0.1:8000/repo/open \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "branch": "main",
    "git_provider": "gitlab"
  }'
```

High-level success:

- the worker resolves GitLab credentials from `~/.openpatch/config.json`
- clone and fetch happen non-interactively
- the response includes:
  - `project_path`
  - `local_repo_path`
  - `branch`
  - `head_sha`
  - `cloned`
  - `message`

## Step 5: Read A File

```bash
curl -X POST http://127.0.0.1:8000/fs/read \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "relative_path": "README.md"
  }'
```

High-level success:

- the worker returns file content from the local checkout
- no remote repository call is needed for the file read itself

## Step 6: Run A Read-Only Repository Summary

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/private-repo",
    "task": "Summarize the repository and recommend the best starting point for understanding the codebase."
  }'
```

High-level success:

- the worker gathers a minimal local context set
- the response includes structured fields such as:
  - `project_path`
  - `task`
  - `model`
  - `branch`
  - `repo_root_name`
  - `context_summary`
  - `top_level_entries`
  - `response`
- no files are modified

## What The Worker Sends Upstream

In this first read-only flow, the worker keeps context intentionally small:

- current branch
- top-level repository entries
- `git status --short`
- a README excerpt when present
- a truncated working diff when present

This keeps the flow usable while limiting unnecessary repository transmission.

## Troubleshooting

### Worker Not Running

- Run `openpatch worker start`.
- If startup fails, inspect:

```bash
openpatch worker status
openpatch worker logs
```

### Port Already In Use

- If `127.0.0.1:8000` is already occupied, `openpatch worker start` fails fast.
- Stop the existing process or change the configured worker URL and port.

### Wrong Repo Path

- Confirm `project_path` matches the provider path exactly.
- For GitLab, use the project namespace and repository path, for example `group/private-repo`.

### Missing GitLab Permissions

- If `repo/open` reports repository not found or permission denied, confirm the stored GitLab token can read the private repository.
- If needed, rerun `openpatch onboard` and update the GitLab provider settings.

### Missing Ollama Model

- If Ollama is running but the chosen model is missing, pull it locally:

```bash
ollama pull qwen2.5-coder:7b
openpatch doctor
```

## Related Docs

- [README](../README.md)
- [Onboarding](onboarding.md)
- [Local worker setup](local-worker-setup.md)
- [Troubleshooting](troubleshooting.md)
