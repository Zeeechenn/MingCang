# MingCang — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Start
> here for "what is true now"; read `docs/ROADMAP.md` for active sequencing and
> `CHANGELOG.md` only when release/history details are required.

MingCang is an agent-ready, local-first A-share research workspace. It supports
research, backtests, local validation, memory/context inspection, and code
maintenance. It does not place real trades or provide financial advice.

Current release surface: package/API/frontend versions are `0.4.1`; the latest
documented release is `v0.4.1` public-surface polish in
`CHANGELOG.md`.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| v0.4.1 | complete: favicon restored with the new glass-shell palette, GitHub homepage screenshot refreshed, release notes bilingualized |
| v0.4.0 | complete: frontend glass-shell refresh with live/demo data fallback and ATLAS ledger surfaces kept behind existing dormant backend gates |
| v0.3.4 | complete: non-promoting Serenity/ResearchReportGate foundation, `ai_supply_chain` source-tier fields, and research-positioning importer/scoreboard source gates |
| M50 | complete/released through Phase 3: Serenity/ResearchReportGate foundation, `ai_supply_chain` source-tier fields, and research-positioning importer/scoreboard source gates; non-promoting |
| v0.3.3 | complete: first-run wizard, data health page, per-signal provenance, reproducible evidence path, community provider example, API contract, and stricter CI/dependency gates |
| M49 | complete: retained backend tools classified with purpose/read-write boundaries; `mingcang tools` JSON entry added; request/export/memory-candidate correlation IDs wired |
| M46.5 | complete: one-time lookahead audit found warning-only gaps, no blockers; frontend key-number display tests added |
| M46 | complete: docs_public router/manual/feature map + no-key demo first-screen data |
| M47 | complete: `mingcang evidence lookahead-check` productized; coverage snapshot warnings/freshness/provider chain visible in API, UI, and export |
| M48 | complete: first API response types added; SignalCard/EvidenceCard migrated to TSX; StatusBadge primitive and full frontend-test gate wired |
| M45 | complete: source-gated research-positioning tools; future work is guardrail-only |
| M44 / Atlas | complete and dormant: `9820143` is in `origin/main`; Atlas/test4 Stage 2b signal-overlay shadow starter exists; `ATLAS_ENABLED=false` |
| M29 | routine read-only: forward evidence and residual attribution remain non-promoting |
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
| M50 research gate follow-up | Phase 0-3 is complete/released; only start next-batch quality gates or frontend evidence cards when explicitly scoped | Do not connect Serenity, source tiers, or importer metadata to official signals, labels, scheduler, test2, positions, or production weights |
| M29 forward evidence ops | First fix or diagnose readiness blockers: full 100-symbol coverage after 2026-06-02 and recognizable 1d/3d/5d baseline artifacts are missing | Stop if fresh coverage is incomplete, artifacts are partial, or a change would re-enable quant / Kronos / production scoring |
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

Last full recorded gate for v0.4.1 on 2026-06-12:
`make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'` passed
locally: ruff passed, mypy passed, backend pytest reported 1200 passed / 5
skipped, frontend Vite test/build passed, and frontend lint-summary build
passed. GitHub CI should still be checked after push before treating the
release as remote-green.

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
