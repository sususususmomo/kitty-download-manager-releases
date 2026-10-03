#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--check" ]]; then
  shift
  exec python3 -B "$ROOT/native-host/maintenance.py" check "$@"
fi

exec python3 -B "$ROOT/native-host/maintenance.py" update --source "$ROOT" "$@"
