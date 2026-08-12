#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

docker compose --project-directory "$project_dir" -f "$project_dir/compose.yaml" \
  run --rm --no-deps app sh -c '
    set -eu
    umask 077
    lock=/data/.backup.lock
    if ! mkdir "$lock" 2>/dev/null; then
      echo "Backup already in progress" >&2
      exit 1
    fi
    cleanup() {
      rmdir "$lock" 2>/dev/null || true
    }
    trap cleanup EXIT HUP INT TERM
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    python -m backend.app.cli backup \
      --output "/data/backups/finance-${timestamp}.sqlite3"
  '
