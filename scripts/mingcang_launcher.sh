#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${MINGCANG_APP_DIR:-${STOCKSAGE_APP_DIR:-$HOME/.mingcang/app}}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "MingCang app directory was not found: $APP_DIR" >&2
  echo "Install with: curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh" >&2
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
  demo)
    make demo
    ;;
  project|project-context)
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli project-context "$@" --pretty
    ;;
  memory|memory-snapshot)
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli memory-snapshot "$@" --pretty
    ;;
  stock|stock-context)
    if [[ $# -lt 1 ]]; then
      echo "Usage: mingcang stock <symbol>" >&2
      exit 2
    fi
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli stock-context "$@" --pretty
    ;;
  evidence)
    PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli evidence "$@" --pretty
    ;;
  premarket|intraday|postmarket|weekend)
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
MingCang native Pi launcher

Usage:
  mingcang             Start native Pi in MingCang research mode
  mingcang dev         Start native Pi in developer mode
  mingcang configure   Re-run MingCang setup/configuration
  mingcang demo        Seed mock data and start backend + frontend demo
  mingcang doctor      Run health and action catalog checks
  mingcang project     Read watchlist/positions/memory startup context
  mingcang memory      Read the project memory snapshot
  mingcang stock 300308
                        Read one stock's signal/news/label/copilot context
  mingcang evidence lookahead-check
                        Run the standing read-only lookahead trust check
  mingcang premarket   Show the premarket workflow contract (dry-run)
  mingcang intraday    Show the intraday local-cache workflow contract (dry-run)
  mingcang postmarket  Show the postmarket review/export workflow contract (dry-run)
  mingcang weekend     Show the weekend review/calibration workflow contract (dry-run)
  mingcang update      Pull latest code and refresh setup

Legacy alias: stocksage still calls this launcher during the transition.
USAGE
    ;;
  *)
    echo "Unknown mingcang command: $command_name" >&2
    echo "Run: mingcang help" >&2
    exit 2
    ;;
esac
