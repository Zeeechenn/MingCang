#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v pi >/dev/null 2>&1; then
  echo "pi was not found on PATH. Run make agent-setup and install pi first." >&2
  exit 1
fi

profile="${1:-research}"
export MINGCANG_PI_PROFILE="$profile"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ "$profile" == "dev" ]]; then
  echo "Starting MingCang native Pi developer session. Read AGENTS.md before editing."
else
  echo "Starting MingCang native Pi research session. Confirm mutating actions before running them."
fi
echo "Project .env stays private to MingCang Python runtime; it is not bulk-exported into Pi."

exec pi
