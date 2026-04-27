# OpenPatch Local Worker

The OpenPatch local worker is a FastAPI service that runs on a developer machine and performs local repository operations on behalf of the OpenPatch system.

This worker provides the first Phase 1 endpoints:

- `GET /health`
- `POST /repo/open`
- `POST /fs/read`
- `POST /fs/write`
- `POST /cmd/run`
- `POST /git/branch`
- `POST /git/diff`
- `POST /git/commit`
- `POST /git/push`
- `POST /git/merge-request`
- `POST /agent/run`
- `POST /agent/propose-file`

The worker is intentionally small and modular:

- API routes live in `openpatch_worker/api`
- repository, filesystem, command, and git logic live in `openpatch_worker/services`
- environment-based settings live in `openpatch_worker/config.py`
- request and response schemas live in `openpatch_worker/schemas`

## Local Development

### Requirements

- Python 3.11+
- `git` installed and available on `PATH`

### Install

```bash
cd apps/local-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run

```bash
export LOCAL_REPO_BASE_DIR="$HOME/.openpatch/repos"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4.1-mini"
uvicorn openpatch_worker.main:app --reload --host 127.0.0.1 --port 8000
```

### Quick Check

```bash
curl http://127.0.0.1:8000/health
```

### Example Requests

Open or clone a repository into the configured repo base directory:

```bash
curl -X POST http://127.0.0.1:8000/repo/open \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/demo-repo",
    "branch": "main",
    "git_provider": "gitlab"
  }'
```

GitLab setup:

```bash
cat ~/.openpatch/config.json
uvicorn openpatch_worker.main:app --reload --host 127.0.0.1 --port 8000
```

In the product flow, git provider settings come from `~/.openpatch/config.json` first, with environment variables remaining available as advanced overrides.

When `git_provider` is set to `"gitlab"` or `"github"`, the worker builds the clone URL as:

```text
{provider_base_url}/{project_path}.git
```

The token stays server-side and is passed to git through temporary command configuration rather than being embedded in the request payload.

Read a file relative to the repository root:

```bash
curl -X POST http://127.0.0.1:8000/fs/read \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "relative_path": "README.md"
  }'
```

Write a reviewed file change explicitly:

```bash
curl -X POST http://127.0.0.1:8000/fs/write \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "relative_path": "README.md",
    "content": "# Updated README\n"
  }'
```

Run a task through the centralized model backend using minimal local context:

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "task": "Summarize the repository and identify the most likely starting point for changes."
  }'
```

This first read-only task flow gathers a small local context set before calling the model backend:

- current branch
- top-level repository entries
- `git status --short`
- a README excerpt when present
- a truncated working diff when present

The response is structured for the web UI and includes:

- `project_path`
- `task`
- `model`
- `branch`
- `repo_root_name`
- `context_summary`
- `top_level_entries`
- `readme_included`
- `diff_included`
- `response`

### Minimal Test Flow

1. Open or clone a repository locally through `/repo/open`.
2. Confirm the worker is healthy:

```bash
curl http://127.0.0.1:8000/health
```

3. Run a read-only repository understanding task:

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "task": "Summarize the repository and recommend the best starting point for understanding the codebase."
  }'
```

At a high level, success means:

- the worker returns a structured JSON payload
- `context_summary` describes the local repository snapshot the worker used
- `response` contains the model-generated read-only answer
- no files are modified and no git state changes are applied

Ask the model for a full replacement file proposal:

```bash
curl -X POST http://127.0.0.1:8000/agent/propose-file \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "relative_path": "README.md",
    "instruction": "Rewrite the README introduction to explain the local worker architecture more clearly."
  }'
```

Run an explicit validation command after a write:

```bash
curl -X POST http://127.0.0.1:8000/cmd/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "command": "npm test",
    "timeout_seconds": 120
  }'
```

Common validation examples:

```text
npm test
npm run lint
pytest
pytest tests/unit
cargo test
go test ./...
```

Create a new local branch explicitly:

```bash
curl -X POST http://127.0.0.1:8000/git/branch \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "branch": "openpatch/readme-update",
    "from_ref": "main",
    "checkout": true
  }'
```

Create a commit explicitly:

```bash
curl -X POST http://127.0.0.1:8000/git/commit \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "message": "Update README introduction"
  }'
```

Push a branch explicitly:

```bash
curl -X POST http://127.0.0.1:8000/git/push \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "examples/demo-repo",
    "branch": "openpatch/readme-update",
    "git_provider": "gitlab"
  }'
```

Create a GitLab merge request explicitly:

```bash
curl -X POST http://127.0.0.1:8000/git/merge-request \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "group/demo-repo",
    "git_provider": "gitlab",
    "source_branch": "openpatch/readme-update",
    "target_branch": "main",
    "title": "Update README introduction",
    "description": "Refines the README intro after local review and validation."
  }'
```

## Notes

- The worker is intended to bind to `localhost` during early development.
- All repositories are scoped under `LOCAL_REPO_BASE_DIR`.
- Git provider settings are resolved from `~/.openpatch/config.json` first, with environment variables available as advanced overrides.
- GitLab and GitHub clone and fetch support use the same provider resolution path.
- Centralized model calls use `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`.
- `/agent/run` gathers a small, explicit repo summary locally before sending it upstream.
- `/agent/run` is intentionally read-only in this first version and is designed for repository understanding tasks.
- `/agent/propose-file` returns a visible full-file proposal; the worker does not write it until `/fs/write` is called explicitly.
- `/cmd/run` remains explicit and returns the command, timeout, exit code, stdout, stderr, and timeout state.
- Branch creation, commit, push, and merge request creation are all explicit user-triggered operations.
- Provider-specific merge request code is isolated so future PR and MR providers can be added alongside GitLab support.
- Future provider integrations, approval workflows, and stronger execution policy controls are intentionally left for follow-up work.
