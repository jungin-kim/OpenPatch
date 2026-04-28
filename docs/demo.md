# RepoOperator Demo

This guide shows the first successful end-to-end read-only RepoOperator workflow.

It covers:

- `repooperator onboard`
- `repooperator up`
- `repooperator doctor`
- `repooperator status`
- provider-aware project and branch selection in the web UI
- `repo/open` against a private GitLab repository
- `/agent/run` repository summarization

## Overview

RepoOperator now supports a working product flow where:

1. the CLI prepares local runtime config
2. the local worker and web UI start on the developer machine with `repooperator up`
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
npm install -g repooperator
```

Run onboarding:

```bash
repooperator onboard
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

- RepoOperator writes `~/.repooperator/config.json`
- model and GitLab settings are stored for the worker to reuse
- local runtime directories are prepared under `~/.repooperator`

## Step 2: Start The Local Product

```bash
repooperator up
```

High-level success:

- the local worker starts
- the web UI starts
- both local URLs are verified
- the local web URL is printed

## Step 3: Verify Worker Health

```bash
repooperator doctor
repooperator status
curl http://127.0.0.1:8000/health
```

High-level success:

- `repooperator onboard` has already started the worker
- `doctor` shows the worker process as running and the worker as reachable
- `status` shows the configured worker URL, model provider, and worker health detail
- the health endpoint returns JSON with `status: ok`

## Step 4: Choose A Repository In The Web UI

In the web UI:

1. choose `gitlab` as the provider
2. wait for the project list to load
3. choose a project from the visible list, or type to filter it
4. wait for the branch list to load
5. choose a branch, with the provider default selected automatically when available
6. use the Advanced toggle only if you need a manual override

High-level success:

- the UI loads provider-backed projects instead of asking for a manual path first
- search narrows the loaded project list instead of populating it
- recent local projects appear as shortcuts when available
- local projects can be entered directly as absolute filesystem paths
- the default branch is selected automatically when the provider returns one

## Step 5: Open A Private GitLab Repository

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

- the worker resolves GitLab credentials from `~/.repooperator/config.json`
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

- Run `repooperator worker start`.
- If startup fails, inspect:

```bash
repooperator worker status
repooperator worker logs
```

### Port Already In Use

- If `127.0.0.1:8000` is already occupied, `repooperator worker start` fails fast.
- Stop the existing process or change the configured worker URL and port.

### Wrong Repo Path

- Confirm `project_path` matches the provider path exactly.
- For GitLab, use the project namespace and repository path, for example `group/private-repo`.
- For local projects, use an absolute filesystem path such as `/Users/you/my-project`.

### Missing GitLab Permissions

- If `repo/open` reports repository not found or permission denied, confirm the stored GitLab token can read the private repository.
- If needed, rerun `repooperator onboard` and update the GitLab provider settings.

### Missing Ollama Model

- If Ollama is running but the chosen model is missing, pull it locally:

```bash
ollama pull qwen2.5-coder:7b
repooperator doctor
```

## Related Docs

- [README](../README.md)
- [Onboarding](onboarding.md)
- [Local worker setup](local-worker-setup.md)
- [Troubleshooting](troubleshooting.md)
