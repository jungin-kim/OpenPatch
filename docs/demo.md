# OpenPatch Demo

This guide shows the first successful end-to-end read-only OpenPatch workflow.

It covers:

- `openpatch onboard`
- `openpatch doctor`
- `openpatch status`
- provider-aware project and branch selection in the web UI
- `repo/open` against a private GitLab repository
- `/agent/run` repository summarization

## Overview

OpenPatch now supports a working product flow where:

1. the CLI prepares local runtime config
2. the local worker starts on the developer machine
3. the web UI loads projects and branches from the configured git provider
4. a private repository is opened locally through the worker
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

## Step 2: Verify Worker Health

```bash
openpatch doctor
openpatch status
curl http://127.0.0.1:8000/health
```

High-level success:

- `openpatch onboard` has already started the worker
- `doctor` shows the worker process as running and the worker as reachable
- `status` shows the configured worker URL, model provider, and worker health detail
- the health endpoint returns JSON with `status: ok`

## Step 3: Choose A Repository In The Web UI

In the web UI:

1. choose `gitlab` as the provider
2. wait for the project list to load
3. choose a project from the searchable list
4. wait for the branch list to load
5. choose a branch, with the provider default selected automatically when available
6. use the Advanced toggle only if you need a manual override

High-level success:

- the UI loads provider-backed projects instead of asking for a manual path first
- recent local projects appear as shortcuts when available
- local projects can be entered directly as absolute filesystem paths
- the default branch is selected automatically when the provider returns one

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

## Step 5: Run A Read-Only Repository Summary

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
- For local projects, use an absolute filesystem path such as `/Users/you/my-project`.

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
