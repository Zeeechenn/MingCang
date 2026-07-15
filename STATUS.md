# MingCang — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Start
> here for "what is true now"; read `docs/ROADMAP.md` for active sequencing and
> `CHANGELOG.md` only when release/history details are required.

MingCang is an agent-ready, local-first A/HK/US equity research workspace. It
supports research, backtests, local validation, memory/context inspection, and
code maintenance. It does not place real trades or provide financial advice.

Current release surface: package/API/frontend versions are `0.7.0`; the latest
documented release is `v0.7.0` — A/HK/US market-scoped identity, independent
market rules, provider/research/scheduler integration, frontend adaptation, and
five-name HK/US shadow validation (see `CHANGELOG.md`). Full-market promotion is
explicitly on HOLD.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| market rollout | CN production unchanged; HK 2-name / US 3-name `gray/shadow`, position 0, no alerts or orders |
| market-specific gray weights | HK technical/sentiment `0.65/0.35`; US `0.75/0.25`; HK/US quant `0.0` |
| M67 promotion verdict | **HOLD** — replay `+127.97%` vs same-pool equal-weight hold `+1232.93%`; max single-stock contribution `50.77%` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| quant_score provenance | `placeholder_v0` momentum fallback serving deliberately (silent-degradation incident fixed 2026-07-03: explicit warning + per-signal `quant_model` provenance in `decision_runs`; regression `tests/test_quant_model_degradation.py`). Production composite unaffected (`WEIGHT_QUANT=0.0`). Saturday `job_train_model` now writes candidate + validation report only; production promotion is a separate explicit-human action with full contract revalidation and keeps `WEIGHT_QUANT=0.0` |
| completed history | v0.3.3–v0.7.0 and completed historical records: see `CHANGELOG.md` and the ROADMAP archive index |
| paper trading test2 | v1 ended 2026-07-02 (10 trades, 60% win, +19.53% weighted); **v2 started 2026-07-03**: exit params unchanged per M21.4 decision C (single-variable), direction-only evidence as before. **Boundary override 2026-07-06 (owner directive)**: LLM treatment arm may exceed ALL hard boundaries — entry threshold 25, per-stock 15%, per-sector 30%, **and total 80% ceiling** — with mandatory per-crossing rationale logging; mechanical control arm (`test2_ab_models.py`) keeps 25/15/30/80 fixed. Scoped to test2 v2 LLM arm ONLY — `config.py` global 15/30/80, copilot shadow, real-position validation, `risk_manager.py` unchanged. No mechanical floor under ~20% drawdown target now; rationale in `paper_trading/test2.md` §规则. Note: this adds a variable to v2, so v2 is no longer a clean single-variable exit-only continuation |
| M51 external borrowing | suspended 2026-07-03 (star-growth strategy deferred); landed pieces kept in service: D1 DSR/PBO/trial-count contract in `m29_hypothesis_registry`, report-pack v1 adapter |
| M44 / Atlas | **archived REJECT 2026-07-03**: Gate-B historical backfill verdict REJECT (delta -0.59pp), relaxed gate variants all worse, Stage 2b overlay 8.0% vs baseline 27.95%. Research-artifacts-as-signal-filter line falsified. L0-L4 memory / cases / review loop / evidence ledger kept as infrastructure for M57 (no scoring role); evidence accrual stopped; `ATLAS_ENABLED=false` permanent |
| M29 | mechanism (hypothesis registry / readiness / evidence ledger) folded into M58 as infrastructure; no standalone line |
| remote agent mode | opt-in only; read-only by default |
| repository structure | M66 first batch landed: stable core has no static `backend.tools` dependency; legacy CLI/import paths remain compatible |
| M68 news pyramid | **production-shaped mirror is trial-ready, not production direction authority**: M63 runs a bounded (default 20) holdings/test2/biaodi1 shadow step, writes only `news_shadow_*`, and exposes event-review priority plus legacy/pyramid counterfactuals. Official `signals`, weights, stops, positions and test2 are unchanged |

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

Per-workstream first action and stop condition live in `docs/ROADMAP.md` — the
single source of truth for sequencing. Live lines as of 2026-07-15:

- **M54 / M58 / M59 / M60 / M63** continue their existing forward-accrual,
  shadow, gray-release, watchtower and daily-orchestration duties.
- **M68** has completed its first trial slice: real DB evidence/price-volume inputs,
  explicit no-news/fetch/scoring states, a bounded M63 mirror step, three-bucket
  review queue, read-only API, `/news-shadow` trial UI and evidence-bound operator
  feedback. Its operating judgment is deliberately asymmetric: emotion/news is
  first used to surface event and volatility review risk; direction remains a
  shadow counterfactual until the existing M54 IC/ICIR/monotonicity/regime gates pass.
  Persistent extraction-cache replay, frozen-evidence reruns and a measured
  production v2-full token comparison remain open.
- **M66** has completed its first structural batch: stable core imports canonical
  data/backtest/evidence/research/workflow modules; eight related tests are grouped
  by domain; frontend API/live code is under `src/services/`. Remaining work is
  deliberately incremental: workflow tool adapters, the other root tests, feature
  grouping, then provider/data/docs cleanup.
- **M67** has completed its implementation and five-name shadow gray launch:
  market-scoped identity/schema, profiles, provider adapters, global research,
  close-aware scheduling, market-specific signals/costs, market-aware frontend
  routing/currency/PIT surfaces, UI and replay are live.
  Promotion remains HOLD pending US filing coverage, live two-source failover,
  exchange-calendar hardening and enough forward gray evidence.
- Quant v2 remains below promotion gates (IC 0.0215 / ICIR 0.098 vs 0.04 / 0.40)
  and waits for longer fund-flow history.

M57 and M65 are no longer active execution lines: both are archived with explicit
re-entry conditions in `docs/ROADMAP.md`. Older completed work stays in the ROADMAP
archive index and `CHANGELOG.md` rather than being repeated here.

For Atlas/M44 detail read `docs/ATLAS_MERGE.md`. For older milestone history read
`CHANGELOG.md` only when the task actually asks for releases, audit trail, or
historical verification.

## Validation Snapshot

Canonical release-quality gate:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache \
RUFF_CACHE_DIR=/private/tmp/mingcang_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/mingcang_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Last recorded full-suite run (2026-07-16, v0.7.0 release gate): backend
pytest 1757 passed / 5 skipped; ruff, release hygiene and mypy (321 source
files, 0 errors) green; frontend typecheck, 27 tests, build, zero-warning
ESLint, and 15 desktop / 13 mobile Playwright smoke routes plus live-source
truth checks all green with no console or page errors. A focused live-browser
check also verified HK 2/2 and US 3/3 market filters and visible shadow/no-order
badges. Release tags are published only after the matching GitHub CI jobs also
pass on the exact release commit.

Current M68 worktree verification (2026-07-15): an initialized isolated DB
produced backend `1730 passed / 12 skipped`; ruff, release hygiene and mypy
(315 source files) are green. Frontend typecheck, 26 Vitest checks, production
build and zero-warning ESLint are green; Playwright smoke covered 14 desktop
and 11 mobile routes including `/news-shadow`, with no console/page errors.
This is worktree evidence, not a published release or GitHub CI claim.

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
