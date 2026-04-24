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
export OPENPATCH_REPO_BASE_DIR="$HOME/.openpatch/repos"
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
    "project_path": "examples/demo-repo",
    "branch": "main",
    "git": {
      "provider": "generic",
      "clone_url": "https://example.com/examples/demo-repo.git"
    }
  }'
```

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
- All repositories are scoped under `OPENPATCH_REPO_BASE_DIR`.
- Clone and fetch flows currently rely on the local machine's existing `git` configuration and credentials.
- Future auth, provider integrations, approval workflows, and stronger execution policy controls are intentionally left for follow-up work.
