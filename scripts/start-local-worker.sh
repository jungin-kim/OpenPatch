#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT_DIR/apps/local-worker"

cd "$WORKER_DIR"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -e .

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

export LOCAL_REPO_BASE_DIR="${LOCAL_REPO_BASE_DIR:-$HOME/.repooperator/repos}"

exec uvicorn openpatch_worker.main:app --reload --host 127.0.0.1 --port 8000
