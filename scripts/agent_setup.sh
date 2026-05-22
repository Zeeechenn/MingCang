#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

echo "== StockSage agent setup =="
echo "Project: $ROOT"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -e ".[agent]" >/dev/null
elif command -v uv >/dev/null 2>&1; then
  UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/stocksage-uv-cache}" \
    uv pip install --python "$PYTHON_BIN" -e ".[agent]" >/dev/null
else
  echo "Neither python -m pip nor uv is available. Install pip/uv, then rerun make agent-setup." >&2
  exit 1
fi
echo "Python agent dependencies are installed."

if ! command -v pi >/dev/null 2>&1; then
  echo "pi was not found on PATH."
  echo "Install it with one of the official pi commands, then rerun make agent:"
  echo "  npm install -g --ignore-scripts @earendil-works/pi-coding-agent"
  echo "  curl https://pi.dev/install.sh | sh"
else
  echo "pi is installed: $(command -v pi)"
fi

if ! grep -Eq '^AI_PROVIDER=(anthropic|openai|local_cli)' .env; then
  printf "Choose StockSage runtime provider [anthropic/openai/local_cli] (default: anthropic): "
  read -r provider
  provider="${provider:-anthropic}"
  printf "\nAI_PROVIDER=%s\n" "$provider" >> .env
fi

provider="$(grep -E '^AI_PROVIDER=' .env | tail -n 1 | cut -d= -f2-)"
case "$provider" in
  anthropic)
    current_key="$(grep -E '^ANTHROPIC_API_KEY=' .env | tail -n 1 | cut -d= -f2- || true)"
    if [[ -z "$current_key" || "$current_key" == your_* ]]; then
      printf "Enter Anthropic API key for pi + StockSage runtime (leave blank to skip): "
      read -rs key
      printf "\n"
      if [[ -n "$key" ]]; then
        printf "\nANTHROPIC_API_KEY=%s\n" "$key" >> .env
      fi
    fi
    ;;
  openai)
    current_key="$(grep -E '^OPENAI_API_KEY=' .env | tail -n 1 | cut -d= -f2- || true)"
    if [[ -z "$current_key" || "$current_key" == your_* ]]; then
      printf "Enter OpenAI/OpenAI-compatible API key for pi + StockSage runtime (leave blank to skip): "
      read -rs key
      printf "\n"
      if [[ -n "$key" ]]; then
        printf "\nOPENAI_API_KEY=%s\n" "$key" >> .env
      fi
    fi
    ;;
  local_cli)
    echo "Using AI_PROVIDER=local_cli. Ensure claude -p works in this shell if internal LLM workflows need it."
    ;;
  *)
    echo "Unknown AI_PROVIDER=$provider. Update .env before running agent workflows." >&2
    ;;
esac

PYTHONPATH=. "$PYTHON_BIN" backend/data/database.py >/dev/null
PYTHONPATH=. "$PYTHON_BIN" -m backend.agent.cli health --pretty

echo "Setup complete. Run: make agent"
