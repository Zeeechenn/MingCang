# StockSage — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Detailed
> plans live in `docs/ROADMAP.md`; completed history lives in `CHANGELOG.md`.

Current release: `v0.2.1` (2026-06-02).

StockSage is an agent-ready, local-first A-share research workspace. It supports
research, backtests, local validation, memory/context inspection, and code
maintenance. It does not place real trades or provide financial advice.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| M29 | active: forward evidence and residual attribution remain non-promoting |
| M30 | complete: mypy, lockfile, CI/security, coverage, core tests, maintainability |
| M31 | M31.1–31.3 complete; M31.4 partial: cache policy, provider fallback observability, rhythm CLI, signal/review export (position-review + evidence cards pending) |
| remote agent mode | opt-in only; read-only by default |

Daily/batch post-market signals do not enable multi-agent research by default,
to keep runtime LLM token use bounded. Multi-agent research remains available
for explicit one-stock, long-term, deep-research, and review workflows.

## Active Decision Layer

| Profile | quant | technical | sentiment | entry threshold | Use |
|---|---:|---:|---:|---:|---|
| `new_framework` | 0.0 | 0.6 | 0.4 | 25 | production default |
| `test1_legacy_qlib` | 0.45 | 0.40 | 0.15 | 20 | legacy validation only |

Current decision: keep production quant disabled until a new alpha candidate
passes the project promotion gate:

- IC >= 0.04
- ICIR >= 0.40
- monotonic buckets
- non-overlapping / stride evidence
- sufficient fresh forward sample
- no cache, fallback, provenance, or data-quality blockers

Stop loss / take profit remain ATR-derived project rules, not LLM predictions.

## Active Work

| Milestone | Status | Next action |
|---|---|---|
| M29 Alpha Reset / Forward Evidence Engine | active | wait for complete fresh forward coverage, then rerun readiness -> forward shadow -> ledger |
| M29.5 Quant Residual Attribution | first pass complete, non-promoting | continue only if fresh evidence clears gates |
| M31 Product/Engineering Borrowings | M31.1–31.3 done; M31.4 partial | L1/L2/L3 policy, provider chains, dry-run rhythm commands, HTML/Word-compatible postmarket export; pending: position-review + evidence-card sections in export |
| M32 Forward Hypothesis Bridge | design stance set | start only after review data is thick enough |

For detailed sequencing, read `docs/ROADMAP.md`. For historical milestone
details, read `CHANGELOG.md`.

M31 completion note (2026-06-02): `backend.data.cache_policy` defines L1/L2/L3
and the intraday zero-network contract; `/api/system/data-coverage` exposes
freshness contracts and provider fallback chains; `backend.tools.m31_cache_benchmark`
writes read-only latency reports under `/private/tmp`; `backend.agent.cli`
and `stocksage` expose `premarket` / `intraday` / `postmarket` dry-run rhythm
commands; `/api/export/postmarket-review.html` and `?format=word` export
postmarket review reports with the day's signal table, review summary,
rule/profile version, and non-advice disclaimers. Position-holding review and
per-signal evidence cards are not yet in the export, so M31.4 remains partial.

## Validation Snapshot

Last recorded full gate for the current release:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache \
RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/stocksage_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Recorded result: ruff passed, mypy passed, backend pytest passed, frontend node
tests passed, and Vite build passed after using a sandbox-compatible writable
path.

For release-quality work, treat `make verify` as the canonical gate.

## Fresh-Agent Reading Rule

Do not read every project document by default. Start with `AGENTS.md`, then load
only the file that matches the task:

| Task | Read |
|---|---|
| current state, tests, trading/research status | `STATUS.md` |
| architecture or file navigation | `PROJECT.md` |
| onboarding, install, public wording | `README.md` |
| next step, continuation, planning | `docs/ROADMAP.md` |
| releases or historical changes | `CHANGELOG.md` |
| paper trading test truth | `paper_trading/*_state.json` first, then matching `.md` |

## Runtime Commands

```bash
python3 -m backend.agent.cli health --pretty
python3 backend/data/database.py
PYTHONPATH=. python3 -m backend.agent.mcp_server
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm run dev
```

For one-stock research:

```bash
python3 -m backend.agent.cli project-context --symbol <symbol> --pretty
python3 -m backend.agent.cli stock-context <symbol> --pretty
```

## Agent Boundary

- Local Codex / Claude Code sessions are trusted development sessions.
- Remote exposure requires `STOCKSAGE_AGENT_MODE=remote` and
  `STOCKSAGE_AGENT_API_KEY`.
- Remote writes require both `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=true` and an
  explicit action allowlist.
- Real broker orders, destructive git operations, publishing, pushing, and
  releases require explicit user instruction.
- Do not commit `.env`, local databases, model files, or personal trading
  records.
