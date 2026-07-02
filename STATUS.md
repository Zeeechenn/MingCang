# MingCang — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Start
> here for "what is true now"; read `docs/ROADMAP.md` for active sequencing and
> `CHANGELOG.md` only when release/history details are required.

MingCang is an agent-ready, local-first A-share research workspace. It supports
research, backtests, local validation, memory/context inspection, and code
maintenance. It does not place real trades or provide financial advice.

Current release surface: package/API/frontend versions are `0.5.2`; the latest
documented release is `v0.5.2` track-analyst de-personalization and M51 plan
archive in `CHANGELOG.md`.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| recent completed (v0.3.3–v0.5.1, M45–M50) | complete: productization, frontend glass-shell + TypeScript migration, MingCang naming finalization, context sanitization, M45 source-gated research positioning, M46–M48 correctness/discovery/reliability floor, M49 tools registry, M50 Serenity + ResearchReportGate. Detail in `docs/ROADMAP.md` Completed Index and `CHANGELOG.md` |
| paper trading test2 v1 | ended 2026-07-02 by explicit user close-out; treatment ledger: 10 trades, 60% win rate, +19.53% position-weighted net return; direction-only evidence, not a statistical promotion gate |
| M51 external borrowing | started, non-promoting: D1 overfit guard is grafted into `m29_hypothesis_registry` (DSR/PBO/trial-count contract); report-pack v1 adapter exists in frontend and Reports can copy normalized Markdown. Remaining: fuller Report Viewer/Evidence Card, MingCang-GAIA, D2-D4 data/PIT work |
| M44 / Atlas | complete and dormant: `9820143` is in `origin/main`; Atlas/test4 Stage 2b signal-overlay shadow starter exists; `ATLAS_ENABLED=false` |
| M29 | baseline 1d/3d/5d forward artifacts created 2026-06-12; positive delta 9/11 + 8/10 + 8/10 windows; non-promoting; DSR/PBO/trial-count registry guard added; next: refresh/confirm post-06-12 price coverage, then rerun readiness before any forward shadow |
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
passes all promotion gates:

- IC >= 0.04
- ICIR >= 0.40
- monotonic buckets
- non-overlapping / stride evidence
- sufficient fresh forward sample
- no cache, fallback, provenance, or data-quality blockers
- explicit user confirmation

Stop loss / take profit remain ATR-derived project rules, not LLM predictions.

## Active Work

| Workstream | First action | Stop condition |
|---|---|---|
| M51 external borrowing | Continue from the small graft now in place: deepen the report-pack viewer/Evidence Card from `research_report_pack.v1`, then seed MingCang-GAIA only when scoped. D1 overfit guard is done at registry-contract level; D2/D4 remain data/PIT work under M12 | Graft into existing modules only; never build a parallel backtest/factor/audit/data-validation system; do not touch official signal, positions, scheduler, test2, or production weights |
| M50 research gate follow-up | Phase 0-3 is complete/released; only start next-batch quality gates or frontend evidence cards when explicitly scoped (folded into M51 Phase 2) | Do not connect Serenity, source tiers, or importer metadata to official signals, labels, scheduler, test2, positions, or production weights |
| M29 forward evidence ops | Refresh/confirm close-complete post-2026-06-12 price coverage, run `backend.tools.m29_forward_readiness`, then extend the next 1d/3d/5d shadow window only if readiness is true | Stop if fresh coverage is incomplete, artifacts are partial, or a change would re-enable quant / Kronos / production scoring |
| M45 research-positioning follow-up | Use dry-run-first importer / scoreboard only with direct source fidelity | Do not promote trusted memory, official signals, production profile, scheduler, test2, stops, sizing, or positions |
| M32 hypothesis bridge | Start only after review data is thick enough; current local DB has only a small seed set (`review_cases=2`, `forward_theses=2` as of 2026-06-09) | Output falsifiable theses, not Strong Buy labels |
| M44 Atlas | Use `backend.tools.atlas_test4_stage2b_shadow` only for non-promoting signal-overlay shadow accrual | Stop on any official-signal / test2 / scheduler / shared-infra drift |

For detailed current sequencing, read `docs/ROADMAP.md`. For Atlas/M44 detail,
read `docs/ATLAS_MERGE.md`. For older milestone history, read `CHANGELOG.md`
only when the task actually asks for releases, audit trail, or historical
verification.

## Validation Snapshot

Canonical release-quality gate:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache \
RUFF_CACHE_DIR=/private/tmp/mingcang_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/mingcang_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Last full recorded gate for v0.5.2 on 2026-06-15:
`make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
RUFF_CACHE_DIR=/private/tmp/mingcang_ruff_cache
MYPY_CACHE_DIR=/private/tmp/mingcang_mypy_cache` passed locally: ruff passed,
mypy passed, backend pytest reported 1214 passed / 5 skipped, frontend
typecheck/Vite test/build passed, and frontend lint-summary passed. GitHub CI
should still be checked after push before treating the release as remote-green.

For release-quality work, treat `make verify` as the canonical gate.

## Fresh-Agent Reading Rule

Do not read every project document by default. Start with `AGENTS.md`, then load
only the file that matches the task:

| Task | Read |
|---|---|
| current state, tests, trading/research status | `STATUS.md` |
| architecture or file navigation | `PROJECT.md` |
| onboarding, install, public wording | `README.md` |
| next step, continuation, milestone sequencing | `docs/ROADMAP.md` |
| release notes, version history, old verification claims | `CHANGELOG.md` |
| paper trading test truth | `paper_trading/*_state.json` first, then matching `.md` |

`CHANGELOG.md` is not a routine startup file. Use it only to answer "what
changed in version X", to audit a historical claim, or to prepare a release.

## Runtime Truth Order

For trading, testing, review, or research decisions, prefer runtime/project
truth over chat recap:

1. current SQLite state: positions, watchlist, signals, labels, reviews
2. `ai_memory` rows for rules, preferences, research indexes, and risk notes
3. `decision_memory_layered` and `~/.mingcang/memory/*.md`
4. recent `audit_log_fts` entries

## Agent Boundary

Local agents may run project checks, inspect SQLite state, and make requested
code/docs changes. They must not place broker orders, delete important local
data, push/publish/release without explicit user request, or commit secrets,
local databases, model files, and personal trading records.
