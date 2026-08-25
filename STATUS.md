# MingCang — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Start
> here for "what is true now"; read `docs/ROADMAP.md` for active sequencing and
> `CHANGELOG.md` only when release/history details are required.

MingCang is an agent-ready, local-first A/HK/US equity research workspace. It
supports research, backtests, local validation, memory/context inspection, and
code maintenance. It does not place real trades or provide financial advice.

Current release surface: package/API/frontend versions are `0.7.1`; the latest
documented release is `v0.7.1` — freshness fail-closed signal generation
(`expected_trade_date` gate, stale symbols excluded before persist),
timestamp-aware signal readers, persistent job-run ledger + runtime identity
handshake, and the M68 news-pyramid production mirror (see `CHANGELOG.md`).
Full-market promotion remains explicitly on HOLD (v0.7.0).

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
| completed history | v0.3.3–v0.7.0 and completed historical records: see `CHANGELOG.md` and Git history; the pre-One-Loop roadmap snapshot is stored outside the repo governance archive |
| paper trading test2 | v1 ended 2026-07-02 (10 trades, 60% win, +19.53% weighted); **v2 started 2026-07-03**: exit params unchanged per M21.4 decision C (single-variable), direction-only evidence as before. **Boundary override 2026-07-06 (owner directive)**: LLM treatment arm may exceed ALL hard boundaries — entry threshold 25, per-stock 15%, per-sector 30%, **and total 80% ceiling** — with mandatory per-crossing rationale logging; mechanical control arm (`test2_ab_models.py`) keeps 25/15/30/80 fixed. Scoped to test2 v2 LLM arm ONLY — `config.py` global 15/30/80, copilot shadow, real-position validation, `risk_manager.py` unchanged. No mechanical floor under ~20% drawdown target now; rationale in `paper_trading/test2.md` §规则. Note: this adds a variable to v2, so v2 is no longer a clean single-variable exit-only continuation |
| remote agent mode | opt-in only; read-only by default |
| active project program | **MingCang One Loop** implementation stages 0/1/3/4/5 are complete; the mandatory post-implementation evidence gate is **5/20 close-confirmed days**, so the governance cycle is not complete |
| repository structure | core and workflows have no implementation dependency on `backend.tools`; canonical domain owners and compatibility facades are enforced by architecture tests, while intentional compatibility entrypoints remain for a release-cycle review |
| One Loop runtime truth | immutable audit on 2026-08-25 counts 2026-08-19, 20, 21, 24 and 25 as five complete close-confirmed days. Each has one selected authoritative RunEnvelope, exact official signal batch and committed eight-card panel; the current status is `insufficient_days` at **5/20**, not a broken window. The 2026-08-25 official batch is the final 25/25 run; two earlier partial attempts remain visible as `superseded_signal_batches:2`. The daily runner now snapshots SQLite with `backup()` so committed WAL rows are included, and it only emits `PIPELINE_DONE` when the target day and every later step succeed |
| M68 news pyramid | **continuous mirror + independent test2-v2 C arm are wired, not production direction authority**: M63 and the local default-25 `test2_signal_runner` share one post-test2 follow-up (`M54 accrual → M68 shadow → A/B/C compare`). The test2 hook runs only after a 25/25 successful batch whose `data_date` is the current run date; stale/partial/custom/no-LLM batches fail closed. Original test2 A/B state, official `signals`, weights, stops and positions remain untouched. First real C day is pending the next complete close-confirmed test2 session; no historical pyramid backfill is allowed |
| memory outcome loop | **operationally repaired, then isolated as shadow-only on 2026-08-18**: 1,718 of 2,019 judgments have validated 1d/3d/5d/10d outcomes (85.09% raw coverage; 93.27% among resolvable judgments). Maintenance reversibly archived 177 mature judgments whose exact observation-day price does not exist. All 2,337 active rows match the recall index by exact ID set (missing 0, stale 0); mature unresolved judgments and automatic `trusted` atoms are both 0. Because corrected complete-batch PIT A/B did not show robust P&L/stop benefit, `MEMORY_DECISION_CONTEXT_ENABLED=false` is the fail-closed default: chat, stock/project context, postmarket aggregation, research constraints, watchtower, M59 and the long-term track analyst receive no memory text. Outcome accrual, health/index maintenance, explicit `mingcang_memory_context` lookup and PIT backtests remain operational. The switch is restart/env-only rather than Admin-editable; production weights/stops/positions/orders remain unchanged. |

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

`docs/ROADMAP.md` is the single source of truth for sequencing. Current program
state on 2026-08-25:

- Baseline/conflict inventory and the pre-One-Loop roadmap archive are complete;
  the production database was only audited through an immutable copy and its hash
  remained unchanged.
- Documentation now has one authority per topic. Closed plans and generated work
  material are outside the repository, while `docs_public/` is the public source.
- Scheduler, manual CLI and test2-compatible paths now emit an explicit
  `run_envelope.v1`; consumers and `/api/system/health` reject legacy, partial,
  ambiguous, stale, custom-DB and non-authoritative batches. The implementation is
  complete, and the real 20-day acceptance window is currently 5/20.
- Workflow-to-tool implementation dependencies are zero. Canonical domain modules,
  lifecycle registry metadata and compatibility facades are covered by boundary
  tests.
- Research/run-card/notification/event-risk/exit-adjudication integrations remain
  additive and shadow/read-only. The locked M58 holdout rejected every alternative:
  the current baseline returned +14.78% with -27.50% maximum drawdown, while all
  alternatives were worse and failed the drawdown gate. No variant was promoted.
- `/api/daily/panel/latest?mode=postmarket` and `#/daily` provide one eight-card
  operator surface with explicit stable/shadow/degraded states. Authoritative M63
  runs persist a row-bound panel artifact using a DB-commit-aware pending/committed
  protocol; the Stage-6 auditor rejects uncommitted or incomplete evidence.
- The continuity auditor is operational and immutable/read-only. Remaining work is
  temporal rather than another implementation batch: collect 20 qualifying
  close-confirmed days, investigate any recovery blockers, rerun the full gate, and
  obtain explicit user confirmation before declaring One Loop complete.

## Operational Follow-ups

The read-only `scripts/audit_runtime_followups.py` report separates operational
cleanup from the 20-day continuity contract. Against the 2026-08-25 immutable
snapshot it found:

- one `m63_postmarket` JobRun left `running` since 2026-08-20 (about 116 hours at
  the audit clock); it is diagnostic debt and was not rewritten or reconciled;
- 33 persisted `adjustment_basis_drift` events across 17 symbols, led by 601899
  (9) and 600547 (6); no price history or trading ledger was rebased;
- the 20-day continuity contract's `degradation_rate` metric itself now excludes
  the pipeline's own `--no-llm` / `--no-shadow` quota-discipline skips (see
  `INTENTIONAL_SKIP_MARKERS` / `_classify_degradations` in
  `backend/ops/one_loop_continuity.py`, and `CHANGELOG.md`); each day's
  `degradations` field stays the full unfiltered record, split into
  `intentional_skips` and `unexpected_degradations`, and only the latter counts
  toward the rate. Verified on 2026-08-25 against a fresh consistent snapshot of
  the production database: the rate reads `0.0` with evidence
  `{degraded_days: 0, intentional_skip_days: 4, close_confirmed_days: 5}`,
  where it previously read `0.8`. The five days' gate verdicts are unchanged
  (all `complete`, 5/20) — this batch changed a metric's meaning, not the gate;
- human review is 0/88 created-on-day observations. Review freshness is
  88 fresh / 546 stale / 634 total **cross-day backlog observations**, not 634
  unique queue items; both remain follow-up work and do not redefine a complete
  RunEnvelope or waive the 20-day gate.

The diagnostic requires an explicit immutable database copy and can optionally
consume the continuity JSON; it never repairs the ledger, queue or prices.

## Validation Snapshot

Canonical release-quality gate:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache \
RUFF_CACHE_DIR=/private/tmp/mingcang_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/mingcang_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Last recorded full-suite run (2026-07-16, v0.7.1 release gate): backend
pytest 1827 passed / 5 skipped; ruff, release hygiene (732 files scanned) and
mypy (333 source files, 0 errors) green; frontend typecheck, 32 Vitest checks
across 14 files, production build, zero-warning ESLint, and Playwright smoke
(desktop + mobile routes plus both live-source truth states, 32 checks) all
green with no console or page errors. Release tags are published only after
the matching GitHub CI jobs also pass on the exact release commit.

Current M68 worktree verification (2026-07-15): an initialized isolated DB
produced backend `1730 passed / 12 skipped`; ruff, release hygiene and mypy
(315 source files) are green. Frontend typecheck, 26 Vitest checks, production
build and zero-warning ESLint are green; Playwright smoke covered 14 desktop
and 11 mobile routes including `/news-shadow`, with no console/page errors.
This is worktree evidence, not a published release or GitHub CI claim.

Current memory-loop worktree verification (2026-08-18): backend
`1870 passed / 5 skipped`; ruff, release hygiene (735 files) and mypy
(338 source files, 0 errors) are green. Frontend typecheck, 32 Vitest checks
across 14 files, production build and zero-warning ESLint are green; Playwright
smoke passed 18 desktop/live-state checks and 14 mobile checks with no
console/page errors. This is worktree evidence, not a published release claim.

Current One Loop worktree verification (2026-08-19): the canonical `make verify`
gate used an isolated SQLite database and caches under `/private/tmp`. Backend
pytest passed `1938 / 5 skipped`; Ruff, release hygiene (708 present tracked
files), document authority and mypy (363 source files, 0 errors) are green.
Frontend typecheck and 37 Vitest checks across 15 files passed; production build
and zero-warning ESLint are green. Browser smoke passed 18 desktop/live-source
checks and 14 mobile checks, including the Daily entry, with zero console or page
errors. Strict MkDocs, release consistency and diff checks also passed. This is
worktree evidence, not a published release or a substitute for the open 20-day
continuity gate.

Current daily-pipeline hardening verification (2026-08-25) used an isolated
worktree, temporary SQLite database/caches, and a temporary copy of local-only
paper-trading Python fixtures. Backend pytest passed `1983 / 5 skipped`; Ruff,
release hygiene (764 present tracked files), document authority and mypy (364
source files, 0 errors) are green. Frontend TypeScript, 37 Vitest checks across
15 files, production build and zero-warning ESLint passed. Browser smoke passed
18 desktop/live-source checks and 14 mobile checks with no console or page
errors. The live database hash was unchanged across the immutable SQLite backup
and operational audits. This is local worktree evidence, not a published release
or a substitute for the open 5/20 continuity gate.

Memory P&L follow-up (2026-08-18): immutable-snapshot PIT replay over the 25-name
test2 pool now selects one latest **complete 25/25 batch** per close-confirmed
`data_timestamp` day; partial reruns are never mixed into a synthetic batch. It
requires every 10-session outcome to mature before reuse, retains original
stops/targets, and checks stops on every available session. Historically operated
outcome memory was zero because all validated rows were first created on 2026-08-18,
the same day as the latest selected signal. In the corrected through-2026-07-24
counterfactual, the primary guard changed `A_quant_on` return by -0.34pp and
`B_quant_off` by -6.15pp; maximum drawdown worsened by 0.31pp / 1.97pp and neither
arm reduced stops. Extending the frozen replay through 2026-08-18 produced +0.29pp
for A but worse drawdown by 0.31pp from a single veto/substitution, while B remained
-3.51pp with drawdown worse by 1.97pp and no stop reduction. This is not robust
evidence of improved profitability or stop discipline; no promotion.
The separate exit experiment then consumed its pre-registered locked holdout over
707 eligible symbols / 39,099 entries. The current baseline returned +14.78% with
-27.50% maximum drawdown; all four locked alternatives were worse and failed the
drawdown gate. The baseline is retained, new variants remain frozen, and no
production exit rule was promoted.

For release-quality work, treat `make verify` as the canonical gate.

## Runtime Truth Order

For trading, testing, review, or research decisions, prefer runtime/project
truth over chat recap:

1. current SQLite state: positions, watchlist, signals, labels, reviews
2. validated `stock_memory_items` outcomes/lessons and compact calibration
3. `ai_memory` rows for rules, preferences, research indexes, and risk notes
4. `decision_memory_layered`; legacy `~/.mingcang/memory/*.md` is fallback/cold history only
5. recent `audit_log_fts` entries

## Agent Boundary

Local agents may run project checks, inspect SQLite state, and make requested
code/docs changes. They must not place broker orders, delete important local
data, push/publish/release without explicit user request, or commit secrets,
local databases, model files, and personal trading records.
