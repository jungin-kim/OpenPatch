# OpenPatch Local Worker

The OpenPatch local worker is a FastAPI service that runs on a developer machine and performs local repository operations on behalf of the OpenPatch system.

This worker provides the first Phase 1 endpoints:

- `GET /health`
- `POST /repo/open`
- `POST /fs/read`
- `POST /cmd/run`
- `POST /git/diff`

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

## Notes

- The worker is intended to bind to `localhost` during early development.
- All repositories are scoped under `LOCAL_REPO_BASE_DIR`.
- GitLab clone and fetch support uses `GITLAB_BASE_URL` and `GITLAB_TOKEN` from the server environment.
- Future provider integrations, approval workflows, and stronger execution policy controls are intentionally left for follow-up work.
