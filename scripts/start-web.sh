#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/apps/web"

cd "$WEB_DIR"

if [[ -f ".env.local" ]]; then
  set -a
  source .env.local
  set +a
fi

export NEXT_PUBLIC_LOCAL_WORKER_BASE_URL="${NEXT_PUBLIC_LOCAL_WORKER_BASE_URL:-http://127.0.0.1:8000}"

npm install
exec npm run dev
