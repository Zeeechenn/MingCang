# StockSage Agent Instructions

## Project Identity

StockSage is a personal A-share research and decision-support system. It is
allowed to assist with research, tests, local validation analysis, configuration
review, and code changes. It must not place real trades or present output as
financial advice.

When a user refers to this project by an informal alias (for example
`项目s`, `项目S`, `project s`, or `Project s`), treat that as this
repository root.

## Local-First Agent Mode

Local Codex and Claude Code sessions are trusted development sessions. In local
mode, agents may directly:

- read and write project files as requested;
- inspect SQLite data and project memory;
- run tests, local validation checks, data coverage snapshots, and verification
  commands;
- call the paid data or LLM APIs already configured in the local `.env` when the
  requested StockSage workflow needs them;
- trigger project research, reviews, backfills, and local validation analysis.

Do not add extra confirmation gates for normal local development or validation
workflows.

Hard local boundaries:

- do not execute real broker orders or automatic trading;
- do not delete important local data, reset the git tree, publish, push, deploy,
  or release unless the user explicitly asks;
- do not commit secrets, local databases, model files, or personal trading
  records.

## Remote Agent Mode

Remote exposure is opt-in only. Use remote mode only when the environment
explicitly sets `STOCKSAGE_AGENT_MODE=remote`.

Remote mode must require `STOCKSAGE_AGENT_API_KEY` at the hosting/API layer.
Remote tools are read-only by default. Mutating remote tools require an explicit
allowlist and `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=true`.
HTTP writes accept `X-StockSage-Agent-API-Key` or `Authorization: Bearer ...`;
when `STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS` is non-empty, the action name must
also be listed, for example `watchlist.add,memory.write,config.update`.

For the bundled stdio MCP bridge, remote-mode tool calls must pass the same key
as the optional `api_key` argument, for example
`stock_sage_health(api_key="...")`. Local mode does not require this argument.
If a future HTTP/SSE transport validates the `Authorization` header before
forwarding requests, keep that gateway check equivalent to
`backend.agent.security.require_agent_access()`.

Keep real keys out of Git. `.env.example` may contain placeholders only.

## LLM/API Boundary

Codex and Claude Code use their own model access for development assistance.
That does not consume StockSage `.env` LLM keys.

StockSage `.env` keys such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`TAVILY_API_KEY`, and `ANSPIRE_API_KEY` are project runtime keys. They are used
only when running StockSage workflows that call the internal LLM, search, or data
provider chains.

For local agent development, cloud LLM keys are optional. To let StockSage's
internal LLM workflows run through local Claude Code CLI instead, set
`AI_PROVIDER=local_cli` and ensure `claude -p` works in the shell. Only
`AI_PROVIDER=anthropic` or `AI_PROVIDER=openai` requires and consumes the
matching cloud API key.

## Project Memory First

Before making StockSage trading, testing, review, or research decisions, prefer
project-owned memory over assistant-only chat memory:

1. `PROJECT.md` and `STATUS.md`
2. current SQLite state: positions, watchlist, signals, labels, reviews
3. `ai_memory` rows for rules, preferences, research indexes, and risk notes
4. `decision_memory_layered` and `~/.stock-sage/memory/*.md`
5. recent `audit_log_fts` entries

## Single-Stock Research Output

When Codex, Claude Code, pi, Cursor or another local agent runs single-stock
research, include the research copilot shadow conclusion in the answer whenever
available. This applies to terminal or agent-driven research even when the Web
copilot card is not being used.

For one-stock research, first load the stock context with:

```bash
python3 -m backend.agent.cli stock-context <symbol> --pretty
```

If the context contains `copilot`, report both tracks:

- official rule conclusion;
- copilot stance and summary;
- shadow position;
- risks and validation questions;
- whether it is marked as a reverse-risk shadow suggestion.

If no copilot record exists, say that the stock currently has no copilot shadow
opinion. Do not invent a shadow conclusion from the main signal, and do not let
the copilot modify official signals, stop loss, take profit, or real positions.

## First-Run Checklist For External Agents

When Codex, Claude Code, pi, Cursor or another local agent opens this repository
for the first time:

1. Read `README.md`, this `AGENTS.md`, `STATUS.md` and `PROJECT.md`.
2. Run `python3 -m backend.agent.cli health --pretty`.
3. If the database is not initialized, run `python3 backend/data/database.py`.
4. For one-stock work, run
   `python3 -m backend.agent.cli project-context --symbol <symbol> --pretty`
   and `python3 -m backend.agent.cli stock-context <symbol> --pretty`.
5. For memory-sensitive work, run
   `python3 -m backend.agent.cli memory-snapshot --pretty`.
6. Use dry-run action metadata before mutating local state:
   `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty`.
7. Execute mutations only after explicit user confirmation by adding
   `--confirm`.

The terminal pi entrypoint is:

```bash
make agent-setup
make agent
```

`make agent-dev` starts the same pi shell with developer intent; use it for code
changes rather than trading research.

The local MCP entrypoint is:

```bash
PYTHONPATH=. python3 -m backend.agent.mcp_server
# or:
make agent-mcp
```

Install the optional MCP dependency with:

```bash
pip install -e ".[agent]"
```

Useful agent tools are:

- `stock_sage_project_context`
- `stock_sage_memory_snapshot`
- `stock_sage_stock_context`
- `stock_sage_health`

To generate a local MCP client config snippet:

```bash
make agent-mcp-config
```

On a fresh clone, run `python3 backend/data/database.py` before expecting live
positions, watchlist, signals or memory. The MCP health tool returns empty
counts instead of failing when the database schema has not been initialized.

## Trading And Risk Constraints

- Do not predict prices as certainty.
- Do not encourage "strong buy" behavior.
- Mention rule/profile version for trading or validation decisions.
- Respect configured position limits. Defaults trend toward 15% per stock, 30%
  per sector, and 80% total equity exposure.
- Position write paths are locked to positive quantities/costs/prices and reject
  duplicate close attempts from M22 onward.
- If long-term labels are missing, avoid stronger language than buy/watch-level
  suggestions.
- Stop loss / take profit are ATR-derived project rules, not LLM predictions.

## Memory Write Policy

Write to project memory when the user explicitly says to remember a StockSage
rule, risk preference, holding/test state, or durable research fact.

Do not write one-off questions, transient discussion, or normal coding
preferences into StockSage memory. Those belong in the local assistant context,
not the trading system.

## Documentation Workflow

Do not create generic planning files in this repository, including
`task_plan.md`, `progress.md`, `findings.md`, `review.md`, `notes.md`, or
`todo.md`.

Use existing durable docs:

- `PROJECT.md` for navigation and index updates.
- `STATUS.md` for the current operational snapshot.
- `docs/ROADMAP.md` for active or future milestone work using M-numbered
  sections.
- `CHANGELOG.md` for completed milestone history.

## Common Commands

```bash
PYTHONPATH=. pytest -q
PYTHONPATH=. python3 -m backend.tools.coverage_snapshot
PYTHONPATH=. python3 -m backend.agent.cli health --pretty
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm run dev
```
