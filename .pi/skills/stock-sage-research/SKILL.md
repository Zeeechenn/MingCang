---
name: stock-sage-research
description: Use for StockSage terminal-agent workflows covering health checks, project memory, single-stock research, topic research, paper-trading reviews and confirmed local actions.
---

# StockSage Research Workflow

## Health Check

1. Run `python3 -m backend.agent.cli health --pretty`.
2. If database state is empty on a fresh clone, suggest `python3 backend/data/database.py`.
3. For data coverage, run `make coverage-snapshot` when the user asks about runtime readiness.

## Single Stock Research

1. Run `python3 -m backend.agent.cli project-context --symbol <symbol> --pretty`.
2. Run `python3 -m backend.agent.cli stock-context <symbol> --pretty`.
3. Read relevant `README.md`, `STATUS.md`, `PROJECT.md` or `docs/ROADMAP.md` only when needed.
4. Summarize signal, position, long-term label, memory, risks and missing evidence.
5. Keep conclusions framed as research support, not investment advice.

## Memory Work

1. Run `python3 -m backend.agent.cli memory-snapshot --pretty`.
2. Write project memory only when the user explicitly says to remember a durable
   StockSage rule, preference, risk note or research fact.
3. Dry-run `memory.write` first, then execute with `--confirm` only after user confirmation.

## Paper Trading Review

1. Run `make paper-stats`.
2. Use `STATUS.md` for current profile and milestone context.
3. Summarize performance, drawdown, exits, rule adherence and next checks.

## Confirmed Actions

For watchlist, position, memory, review or config mutations:

1. Dry-run the action with `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty`.
2. Explain the action, risk level and payload.
3. Ask for explicit confirmation.
4. Run the same command with `--confirm`.
