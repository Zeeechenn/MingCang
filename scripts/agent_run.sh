#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v pi >/dev/null 2>&1; then
  echo "pi was not found on PATH. Run make agent-setup and install pi first." >&2
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

profile="${1:-research}"
export STOCKSAGE_PI_PROFILE="$profile"
if [[ "$profile" == "dev" ]]; then
  echo "Starting StockSage pi developer session. Read AGENTS.md before editing."
else
  echo "Starting StockSage pi research session. Confirm mutating actions before running them."
fi

exec pi
