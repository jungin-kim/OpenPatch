# OpenPatch Local Worker

The OpenPatch local worker is a FastAPI service that runs on a developer machine and performs local repository operations on behalf of the OpenPatch system.

This worker provides the first Phase 1 endpoints:

- `GET /health`
- `POST /repo/open`
- `POST /fs/read`
- `POST /fs/write`
- `POST /cmd/run`
- `POST /git/diff`
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
export LOCAL_REPO_BASE_DIR="$HOME/.openpatch/repos"
export GITLAB_BASE_URL="https://gitlab.example.com"
export GITLAB_TOKEN="your-gitlab-token"
uvicorn openpatch_worker.main:app --reload --host 127.0.0.1 --port 8000
```

When `git_provider` is set to `"gitlab"`, the worker builds the clone URL as:

```text
{GITLAB_BASE_URL}/{project_path}.git
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
    "repo_path": "examples/demo-repo",
    "task": "Summarize the repository and identify the most likely starting point for changes."
  }'
```

Ask the model for a full replacement file proposal:

```bash
curl -X POST http://127.0.0.1:8000/agent/propose-file \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "examples/demo-repo",
    "relative_path": "README.md",
    "instruction": "Rewrite the README introduction to explain the local worker architecture more clearly."
  }'
```

## Notes

- The worker is intended to bind to `localhost` during early development.
- All repositories are scoped under `LOCAL_REPO_BASE_DIR`.
- GitLab clone and fetch support uses `GITLAB_BASE_URL` and `GITLAB_TOKEN` from the server environment.
- Centralized model calls use `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`.
- `/agent/run` gathers a small, explicit repo summary locally before sending it upstream.
- `/agent/propose-file` returns a visible full-file proposal; the worker does not write it until `/fs/write` is called explicitly.
- Future provider integrations, approval workflows, and stronger execution policy controls are intentionally left for follow-up work.
