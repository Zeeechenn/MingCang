#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${STOCKSAGE_APP_DIR:-$HOME/.stock-sage/app}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "StockSage app directory was not found: $APP_DIR" >&2
  echo "Install with: curl -fsSL https://raw.githubusercontent.com/Zeeechenn/stock-sage/main/scripts/install.sh | sh" >&2
  exit 1
fi

cd "$APP_DIR"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

command_name="${1:-agent}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command_name" in
  agent|start|"")
    bash scripts/agent_run.sh research "$@"
    ;;
  dev)
    bash scripts/agent_run.sh dev "$@"
    ;;
  configure|setup)
    bash scripts/agent_setup.sh "$@"
    ;;
  doctor)
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli health --pretty
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli actions --pretty
    ;;
  premarket|intraday|postmarket)
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli "$command_name" --pretty "$@"
    ;;
  update)
    if command -v git >/dev/null 2>&1; then
      git pull --ff-only
    fi
    bash scripts/agent_setup.sh "$@"
    ;;
  help|-h|--help)
    cat <<'USAGE'
StockSage native Pi launcher

Usage:
  stocksage             Start native Pi in StockSage research mode
  stocksage dev         Start native Pi in developer mode
  stocksage configure   Re-run StockSage setup/configuration
  stocksage doctor      Run health and action catalog checks
  stocksage premarket   Show the premarket workflow contract (dry-run)
  stocksage intraday    Show the intraday local-cache workflow contract (dry-run)
  stocksage postmarket  Show the postmarket review/export workflow contract (dry-run)
  stocksage update      Pull latest code and refresh setup
USAGE
    ;;
  *)
    echo "Unknown stocksage command: $command_name" >&2
    echo "Run: stocksage help" >&2
    exit 2
    ;;
esac
