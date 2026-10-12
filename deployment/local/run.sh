#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ ! -f .env.worker.local ]; then
  echo "Run deployment/local/configure.py first; see deployment/local/README.md" >&2
  exit 1
fi
exec docker compose --env-file .env.worker.local up --build --detach --wait worker
