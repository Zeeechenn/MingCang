---
name: mingcang-research
description: Use for MingCang terminal-agent workflows covering health checks, project memory, single-stock research, topic research, paper-trading reviews and confirmed local actions.
---

# MingCang Research Workflow

## Health Check

1. Run `python3 -m backend.agent.cli health --pretty`.
2. If database state is empty on a fresh clone, suggest `python3 backend/data/database.py`.
3. For data coverage, run `make coverage-snapshot` when the user asks about runtime readiness.
4. If native Pi tools are available, prefer `mingcang_health` for the same
   contract.

## Single Stock Research

1. Run `python3 -m backend.agent.cli project-context --symbol <symbol> --pretty`.
2. Run `python3 -m backend.agent.cli stock-context <symbol> --pretty`.
3. Read relevant `README.md`, `STATUS.md`, `PROJECT.md` or `docs/ROADMAP.md` only when needed.
4. Summarize signal, position, long-term label, memory, risks and missing evidence.
5. Keep conclusions framed as research support, not investment advice.
6. Keep MingCang's own recommendation language visible, especially
   `可小仓试错`, `可关注`, `观望` and `规避`.

## Memory Work

1. Run `python3 -m backend.agent.cli memory-snapshot --pretty`.
2. Write project memory only when the user explicitly says to remember a durable
   MingCang rule, preference, risk note or research fact.
3. Dry-run `memory.write` first, then execute with `--confirm` only after user confirmation.

## Paper Trading Review

1. Use `STATUS.md` for current profile and milestone context.
2. Inspect persisted decision runs or relevant local reports only when the user
   asks for paper-trading evidence.
3. Summarize performance, drawdown, exits, rule adherence and next checks.

## Confirmed Actions

For watchlist, position, memory, review or config mutations:

1. Dry-run the action with `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty`.
2. Explain the action, risk level and payload.
3. Ask for explicit confirmation.
4. Run the same command with `--confirm`.

Useful action names can be discovered with:

```bash
python3 -m backend.agent.cli actions --pretty
```

Heavy actions such as `research.copilot`, `research.deep.run` and
`long_term.run` may spend LLM/search quota and write local research state.
