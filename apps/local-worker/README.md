# OpenPatch Local Worker

The OpenPatch local worker is a FastAPI service that runs on a developer machine and performs local repository operations on behalf of the OpenPatch system.

This scaffold provides the first Phase 1 worker endpoints:

- `GET /health`
- `POST /repo/open`
- `POST /fs/read`
- `POST /cmd/run`
- `POST /git/diff`

The worker is intentionally small and modular:

- API routes live in `openpatch_worker/api`
- request and response models live in `openpatch_worker/models`
- repository, filesystem, command, and git logic live in `openpatch_worker/services`

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
uvicorn openpatch_worker.main:app --reload --host 127.0.0.1 --port 8000
```

### Quick Check

```bash
curl http://127.0.0.1:8000/health
```

## Notes

- The worker is intended to bind to `localhost` during early development.
- Clone and pull flows currently rely on the local machine's existing `git` configuration and credentials.
- Future auth, provider integrations, approval workflows, and stronger execution policy controls are intentionally left for follow-up work.
