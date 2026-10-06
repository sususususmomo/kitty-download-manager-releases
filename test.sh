#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$ROOT/tests/test-youtube-session.py"
python3 "$ROOT/tests/test-windows-audit.py"
if command -v node >/dev/null 2>&1; then
  node "$ROOT/tests/test-youtube-session-ui.js"
fi
exec python3 "$ROOT/tests/run-regression.py" "$@"
