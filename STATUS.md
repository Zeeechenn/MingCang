# MingCang — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Start
> here for "what is true now"; read `docs/ROADMAP.md` for active sequencing and
> `CHANGELOG.md` only when release/history details are required.

MingCang is an agent-ready, local-first A-share research workspace. It supports
research, backtests, local validation, memory/context inspection, and code
maintenance. It does not place real trades or provide financial advice.

Current release surface: package/API/frontend versions are `0.3.0`; the latest
documented patch is `v0.3.1` trust/onboarding cleanup in `CHANGELOG.md`.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
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
| M49 tooling observability | Classify backend tools into stable / maintenance / evidence / attic and add purpose/read-write boundaries | Do not change signal behavior, scheduler behavior, or memory write policy while documenting tools |
| M45 research-positioning follow-up | Use dry-run-first importer / scoreboard only with direct source fidelity | Do not promote trusted memory, official signals, production profile, scheduler, test2, stops, sizing, or positions |
| M29 forward evidence | Run readiness checks read-only before any shadow bundle | Stop if fresh coverage is incomplete or if a change would re-enable quant / Kronos / production scoring |
| M32 hypothesis bridge | Start only after review data is thick enough | Output falsifiable theses, not Strong Buy labels |
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

Last full recorded gate after the onboarding/demo cleanup on 2026-06-06:
ruff passed, mypy passed, backend pytest `1101 passed, 5 skipped`, frontend
node tests `19 passed`, Vite build passed, and ESLint summary passed.

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
