# Atlas Merge Plan

> Durable execution plan for merging Atlas into StockSage `main`. ROADMAP stays light and points here for the detailed checklist. This file replaces the external `/Users/zeeechenn/Downloads/PLAN (2).md` as the project-owned handoff surface.

## Current State

| Item | Status |
|---|---|
| Current phase | Phase 5 readiness pack complete locally at `1f198f1`; awaiting user review / merge decision after confirming no `main` advance |
| Main baseline | Phase 0 completed locally; `main` includes M43 at merge commit `4882d49` |
| Baseline marker | local tag `pre-atlas-m43-baseline` points to `4882d49` |
| Atlas worktree | `/Users/zeeechenn/Documents/项目s/atlas` on `codex/atlas` |
| Production boundary | `new_framework`, `WEIGHT_QUANT=0.0`, Kronos off, official signal markets `CN` only |
| Test boundary | test2 frozen baseline; do not change replay state, runner inputs, sizing, stop/take, signal loading, or state JSON semantics |
| Push policy | local work only until user explicitly asks to push |

## Gate Split

- **Engineering merge gate** decides whether Atlas architecture code can enter `main`: production behavior must be equivalent on merge day, dormant by default, and revertable.
- **Investment effect gate** decides whether Atlas behavior can influence official signals, positions, stops, or future execution: only shadow/test4 evidence can promote it.
- Engineering success never implies investment promotion.

## Merge Principles

- Atlas is not a permanent side project; it is the next-generation main architecture candidate.
- First Atlas merge must be a dormant merge: new code may exist on `main`, but official signal, test2, test3, 标的1, scheduler, and postmarket paths do not use Atlas behavior by default.
- `ATLAS_ENABLED=false` / `settings.atlas_enabled=False` is the Atlas total dormant switch: it disables Atlas-only M33-M40 routes/features by default while preserving legacy research routes and all official signal, test2, scheduler, and postmarket behavior.
- Module-level flags are secondary and cannot replace the total switch.
- The dormant switch does not protect shared infra. Database migrations, runtime schema, dependency/lockfile changes, scheduler helpers, API helpers, and shared data-loading helpers need their own parity gates.
- First merge allows only additive / non-destructive migration: new tables, nullable columns, non-destructive indexes, idempotent runtime schema patches. No dropping/renaming old tables or columns, no rewriting live old rows, no incompatible constraints on existing production tables, except the user-approved `forward_theses` data-preserving rebuild recorded in Phase 5.
- Do not use Atlas tip to overwrite `main`. Rebase/replay Atlas increments onto current `main` and preserve main-only M31/M41/M42/M43 capabilities.
- `Gate-B` remains the Atlas/M40 prospective tracker name. L4 is Review / Promotion / Calibration, not Gate-B.

## Target L0-L4 Architecture

| Layer | Name | Responsibility | Merge-time boundary |
|---|---|---|---|
| L0 | Memory / Knowledge Base | long-term knowledge, user rules, historical lessons, A-teacher methods, research memory | minimal memory contract; legacy defaults to pending / legacy_import_pending |
| L1 | Evidence Layer | source/time/PIT/quality-aware evidence | EvidenceCard / dossier read-only mapping |
| L2 | Thesis Layer | research cases, hypotheses, invalidation conditions, holding horizon | ResearchCase / Thesis skeleton |
| L3 | Action / Signal / Position Layer | entry, hold, sizing, stop, exit proposals and official signal explanations | ActionProposal only as proposal/shadow, not official path |
| L4 | Review / Promotion / Calibration Layer | outcome review, attribution, calibration, memory promotion | ReviewCase / PromotionGate; LLM cannot write trusted memory directly |

## Phase 0: Main Baseline First

Goal: make M43 the true `main` baseline before any Atlas rebase.

- [x] Confirm M43 branch is `codex/m43-architecture-boundaries` and worktree is clean.
- [x] Confirm M43 branch only contains M43 / documentation-related commits over `main`.
- [x] Run full gate on M43 branch: `make verify`.
- [x] Run fixed-end test2 replay to `/private/tmp` without modifying `paper_trading/test2_ab_state.json`.
- [x] Confirm replay JSON equals `paper_trading/test2_ab_state.json`.
- [x] Merge M43 into local `main` with a traceable merge commit.
- [x] Create local baseline marker `pre-atlas-m43-baseline`.
- [x] Re-run `make verify` on post-merge `main`.
- [x] Re-run fixed-end test2 replay on post-merge `main` and confirm zero diff.
- [x] Confirm production boundary: active profile `new_framework`, quant/technical/sentiment `0.0/0.6/0.4`, entry threshold `25.0`, multi-agent off, Kronos off.
- [x] Confirm official signal markets remain `CN`, with HK/US observe-only.

Evidence:

- `main` merge commit: `4882d49`.
- Local baseline tag: `pre-atlas-m43-baseline` -> `4882d49`.
- M43 branch and post-merge `main` `make verify`: ruff, mypy, 759 backend tests, 19 frontend node tests, Vite build passed.
- test2 replay command pinned `--end 2026-06-04`; post-merge state artifact `/private/tmp/stocksage_test2_ab_state_20260604_postmerge.json` matched `paper_trading/test2_ab_state.json` with SHA-256 `3ad1af227d3767d27720122df8303d5afa84bc7b89415e69e9f60b68c298cdcd`.

## Phase 1: Rebase Atlas To M43/Main

Goal: turn Atlas from an old long-lived branch into a candidate based on current `main`.

- [x] In `/Users/zeeechenn/Documents/项目s/atlas`, verify branch is `codex/atlas` and worktree is clean before starting.
- [x] Rebase/replay Atlas onto `main` after `pre-atlas-m43-baseline`.
- [x] Preserve M31/M41/M42/M43 mainline modules; do not let Atlas delete or overwrite them.
- [x] Protect main-only surfaces: cache policy, global data, market capabilities, price quality, M43 facades/jobs/architecture guards.
- [x] Resolve known conflict areas only as integration work: project docs, `backend/data/database.py`, API/schema, `pyproject.toml`, `uv.lock`, scheduler and shared data helpers.
- [x] Do not expand Atlas functionality during conflict resolution.
- [x] Rebuild Gate-A merge-safety report from current code. Old `ATLAS_MERGE_SAFETY.md` is historical reference only.
- [x] Run focused migration tests.
- [x] Run M43 reproduction / architecture-boundary focused tests.
- [x] Run `make verify` in the rebased Atlas worktree.
- [x] Confirm Atlas no longer appears to delete M31/M41/M42/M43 mainline files.

Acceptance:

- [x] Atlas worktree clean after rebase.
- [x] Gate-A says “ready for architecture review” or gives concrete blockers.
- [x] `make verify` passes.
- [x] No production/test2/test3/official signal behavior changes are introduced merely by rebase.

Stop if:

- Atlas conflicts require destructive migration or shared-infra semantic rewrites.
- Rebase would alter test2 replay truth, official signal path, scheduler/postmarket defaults, or M43 public facades.
- Main has advanced with non-trivial test2/scheduler/database/official-signal changes before the rebase finishes; re-sync first.

## Phase 2: L0-L4 Architecture Contract

Goal: make the target main architecture explicit before implementing more behavior.

- [x] Update project-owned Atlas architecture docs to describe L0-L4 as the future main architecture, not a side feature.
- [x] State that merge-time behavior must remain dormant by default.
- [x] State that test2, test3, 标的1, and official signal behavior do not change on merge day.
- [x] Define current roles: Researcher enabled, Portfolio Manager proposal enabled, Execution Trader shadow/interface only.
- [x] Clarify that `ActionProposal` is a future object and does not equal the current runtime action registry.
- [x] Clarify that early `ActionProposal` output is shadow/proposal only and does not connect to official paths.
- [x] Keep `Gate-B` reserved for the current prospective tracker.

Acceptance:

- [x] L0 is named as the priority implementation layer.
- [x] test2 frozen baseline is explicit.
- [x] dormant merge contract is explicit.
- [x] No generic temporary planning files are created.

## Phase 3: L0 Memory / Knowledge Base First

Goal: build a safe memory foundation before connecting more research or proposal behavior.

Merge-safety scope: Phase 3-min is the required pre-Phase-4 slice. It creates
the L0 storage, trust-state, recall, and promotion guardrails needed before a
minimal adapter is wired. Phase 3-full productization remains separate.

- [x] Review L0 design before irreversible schema decisions.
- [x] Inventory memory sources: `stock_memory_items`, `decision_memory_layered`, research memory, A-teacher skill, long-term reports, topic reports, ReviewCase candidates, and user-explicit rules/preferences.
- [x] Define memory scope: stock, theme, sector, market/global, user preference, methodology/skill.
- [x] Define trust state: raw, pending, trusted, refuted, archived, legacy_import_pending.
- [x] Define legacy backfill policy: legacy rows do not become trusted by default.
- [x] Default current legacy adapter rows to pending / legacy_import_pending.
- [x] Allow LLM/tool callers to generate raw/pending/legacy_import_pending only.
- [x] Require human gate or ReviewCase promotion for trusted memory.
- [x] Prevent remote agent from promoting trusted memory, including M37 memory-candidate promote/reject routes.
- [x] Expose current L0 recall with trusted and pending/raw memory separated for existing memory context and review-loop promotion surfaces.
- [x] Add expiration / refutation policy for thesis-like memory: refuted, archived, ttl_days, valid_from, and valid_to are excluded from active recall.
- [ ] Phase 3-full: implement full legacy adapters/backfill for `decision_memory_layered`, research memory, A-teacher skill, long-term reports, and topic reports.
- [ ] Phase 3-full: wire native ResearchCase and future ActionProposal recall to L0 instead of only the current context/review-loop bridge.

Acceptance:

- [x] L0 supports stock/theme/sector/global research.
- [x] L0 distinguishes pending from trusted.
- [x] L0 serves the current memory context and ReviewCase / memory-candidate promotion bridge.
- [ ] Phase 3-full: L0 serves native ResearchCase and ActionProposal adapters.
- [x] Legacy memory is not accidentally trusted.
- [x] LLM cannot automatically write trusted memory.
- [x] L0 does not change official signal or test2 behavior.

Evidence:

- Base L0 implementation: `5008699 feat(atlas): add l0 memory system`.
- Phase 3-min hardening on 2026-06-05 added M37 standard `agent_write_guard`
  coverage for trusted/refuted memory writes and `valid_from` / `valid_to`
  active-recall filtering.
- Focused Phase 3 regression: `141 passed, 1 warning`.
- Official signal / scheduler smoke: `23 passed, 1 warning`.
- Live DB copy-smoke on `/private/tmp/stocksage_phase3_l0_copy_20260605_afterguard.db`:
  `memory_atoms`, `memory_scenarios`, and `memory_profiles` exist,
  `memory_promotion_candidates.memory_atom_id` exists, `PRAGMA integrity_check`
  returned `ok`, and protected row counts for `stocks` and `signals` were stable.
- Test2 fixed-end replay used `--end 2026-06-05`; raw JSON diff against
  `/Users/zeeechenn/stock-sage/paper_trading/test2_ab_state.json` was zero.
- Full gate after Phase 3-min hardening: ruff passed, mypy passed on 204 source
  files, backend pytest `1045 passed, 5 skipped`, frontend node tests
  `19 passed`, and Vite build passed.

## Phase 4: Minimal Core Adapter

Goal: prove one old module can enter the new architecture safely without migrating everything before merge.

- [x] Implement or wire one read-only `ResearchCase` / case view.
- [x] Implement one minimal `EvidenceCard` mapping.
- [x] Implement one memory candidate / promotion gate path.
- [x] Pick one adapter, preferably deep_research or existing dossier, because it can stay read-only and avoid official signal impact.
- [x] Confirm/wire `settings.atlas_enabled` as the Atlas total dormant switch; module-level flags remain secondary.
- [x] With dormant switch off, Atlas HTTP/API routes return disabled, empty, or manual-only behavior; internal storage helpers remain importable for tests and explicit local tooling.

Deferred until after first merge:

- [ ] Full long-term research / A-teacher adapter.
- [ ] Full deep_research migration.
- [ ] Full copilot migration.
- [ ] Full debate refactor.
- [ ] Full M29 ledger integration.
- [ ] Complete ActionProposal influence path.
- [ ] test4 overlay investment promotion.

Acceptance:

- [x] Focused tests cover the minimal adapter.
- [ ] Unfinished modules have owners / migration notes.
- [x] Atlas total switch off means Atlas-only routes/features are dormant and no official path impact is introduced.
- [ ] Merge-day behavior remains equivalent.

Evidence:

- Phase 4 minimal adapter uses the existing dossier as `dossier_readonly_v0`.
- `GET /api/research/{symbol}/adapter-review` is Atlas-only and dormant-guarded.
- The adapter maps legacy dossier data into read-only L1 evidence-card rows,
  an L2 `ResearchCase`, and an L0 memory-candidate preview. It does not create
  memory candidates or promote trusted memory; promotion remains gated by the
  existing local-human M37/M40 route path.
- Focused adapter regression passed `44 passed, 1 warning`.
- Expanded M33/M37/M40/L0 regression passed `159 passed, 1 warning`.
- Full merge-day equivalence is intentionally not claimed here; it remains a
  Phase 5 parity-pack requirement.

## Phase 5: Behavior-Equivalent Atlas Merge

Goal: make Atlas the new main architecture while keeping strategy behavior dormant.

Required gates before merge:

- [ ] Final re-sync onto current `main`.
- [ ] Final Gate-A merge-safety report.
- [ ] `make verify`.
- [ ] test2 replay zero diff.
- [ ] canonical test2 parity.
- [ ] official signal parity smoke.
- [ ] scheduler/postmarket parity smoke.
- [ ] additive/non-destructive migration review.
- [ ] DB migration copy-smoke.
- [ ] dependency / lockfile shared-infra review.
- [ ] API route smoke.
- [ ] memory promotion gate smoke.
- [ ] architecture import guard.
- [ ] Atlas dormant flag smoke.
- [ ] `git diff --check`.

Migration decision:

- [x] User-approved exception on 2026-06-05: `forward_theses` may use the
  existing data-preserving table rebuild to replace the legacy unique key with
  the symbol-aware contract. This remains a migration exception, not a general
  permission to drop or rename production tables. Merge-day copy-smoke must pass,
  and duplicate normalized `forward_theses` keys must fail loudly before any live
  schema run.

Phase 5 readiness evidence at `1f198f1` (local only; not merged):

- Latest Atlas commit: `1f198f1 fix(atlas): keep l0 memory dormant by default`.
- Read-only branch checks: Atlas worktree clean; `merge-base main HEAD` =
  `423bb1d9338b85467a5e96cf5c9a96df15dd641c`; `main...HEAD = 0 / 35`.
- Read-only merge simulation: `git merge-tree main HEAD` returned synthetic tree
  `785b63b519f9d572242f86f19d28dace7c0ee0ad` with no conflict output.
- `git diff --check main...HEAD` passed.
- Focused L0 / route / runtime / postmarket tests after the dormant-context fix
  passed with `161 passed, 1 warning`.
- Full `make verify` passed: ruff passed, mypy passed on 204 source files,
  backend pytest `1049 passed, 5 skipped`, frontend node tests `19 passed`, and
  Vite build passed.
- Test2 fixed-end replay used `--end 2026-06-05`; raw JSON diff against
  `/Users/zeeechenn/stock-sage/paper_trading/test2_ab_state.json` was zero.
- Live DB copy-smoke used `/private/tmp/stocksage_m44_after_l0_gate_copy.db`;
  `init_db()` completed on the copy, `PRAGMA integrity_check` returned `ok`,
  required Atlas tables and indexes existed, `memory_promotion_candidates.memory_atom_id`
  existed, `forward_theses` normalized unique index existed, and protected
  `stocks` / `signals` row counts stayed `718` / `879`.
- Dormant-context fix: `build_memory_context()` now includes L0 memory by
  default only when `settings.atlas_enabled=True`; explicit memory API context
  still opts into L0 with `include_l0=True`.
- This clears the local Phase 5 readiness pack for current `main` `423bb1d`,
  but it is not a merge approval and not investment-effect promotion. Canonical
  test2 parity, official-signal parity smoke, scheduler/postmarket smoke,
  API/memory/dormant/import guards, and DB copy-smoke remain merge-day checks to
  rerun before any user-approved merge. If `main` advances before merge,
  recompute conflict checks and rerun the parity pack.

Behavior equivalence:

- [ ] official signal output unchanged.
- [ ] `WEIGHT_QUANT=0.0` unchanged.
- [ ] test2 replay unchanged.
- [ ] test3 universe / diagnostic semantics unchanged.
- [ ] 标的1 unchanged.
- [ ] stop/take/position sizing unchanged.
- [ ] daily/postmarket automation unchanged.
- [ ] trusted memory not written automatically by LLM.
- [ ] ActionProposal can generate shadow/proposal only.
- [ ] With Atlas total switch off, production path does not import or call Atlas behavior modules.
- [ ] Migration/runtime schema/dependency/shared-helper changes do not drift fixed-fixture official signal smoke.

Test2 parity standard:

- [ ] Primary: raw current JSON equals `/private/tmp` replay JSON.
- [ ] Secondary: canonical parity with stable ordering, ignored run timestamp, explicit float tolerance, and explicit ignored fields.
- [ ] If raw diff fails but canonical parity passes, require recorded human waiver with non-semantic diff explanation.
- [ ] If canonical parity fails, stop merge.

## Phase 6: Atlas Shadow / Test4

Goal: validate investment effect without contaminating test2.

- [ ] Keep test2 frozen: original rules, state, A/B objective, runner inputs, signal loading, position sizing, exit/entry rules, and state JSON semantics.
- [ ] Pre-register test4 metrics, thresholds, sample windows, and failure conditions before running.
- [ ] Prefer forward/OOS data. Same-window replay is diagnostic only, not promotion proof.
- [ ] First stage may use test2 universe, same date window, same price data, same base signal, with Atlas only as shadow overlay.
- [ ] Suggested arms: `test2_baseline`, `atlas_exit_overlay`, `atlas_entry_exit_overlay`.
- [ ] Track return, drawdown, missed-upside rate, false trend-kill rate, re-entry quality, proposal hit rate, opportunity cost, extra drawdown, and tail risk.
- [ ] Define proposal hit rate horizon, label source, adjudication rule, and small-sample handling before evaluation.

Acceptance:

- [ ] test4 never changes official signal by itself.
- [ ] Atlas promotion to official path is discussed only after test4 / forward evidence passes and user confirms.

## Rollback Runbook

Before Atlas merge:

- [ ] Keep `pre-atlas-m43-baseline` or equivalent tag/branch.
- [ ] Record production profile, `WEIGHT_QUANT`, scheduler job ids, test2 state hash, schema digest, key production table row counts, lockfile hash, and fixed-fixture official signal output.
- [ ] Keep Atlas merge as a revertable merge commit; do not squash into hard-to-revert scattered commits.
- [ ] Back up live SQLite for disaster recovery only, not routine rollback.

Rollback triggers:

- [ ] destructive or unexpected schema drift.
- [ ] old production rows unexpectedly rewritten.
- [ ] dependency/shared-helper drift in fixed-fixture official signal smoke.
- [ ] official signal parity drift.
- [ ] test2 canonical parity drift.
- [ ] scheduler/postmarket drift.
- [ ] unexpected trusted-memory writes.
- [ ] production path calls Atlas behavior while total switch is off.

Rollback actions:

- [ ] Stop related scheduler / Atlas shadow jobs.
- [ ] Revert Atlas merge commit or switch back to `pre-atlas-m43-baseline`.
- [ ] Do not restore pre-merge SQLite copy for routine rollback; preserve live rows created during rollback window.
- [ ] Re-run health, official signal smoke, and test2 replay.
- [ ] Record drift cause; do not re-merge before attribution.

## Pre-Merge Rollback Snapshot (2026-06-05)

> This snapshot is the rollback comparison baseline, captured pre-merge (Phase 5 readiness pack complete at `1f198f1`, before any user-approved merge). It is **not** a merge approval.
> Rollback TARGET is `main` / `pre-atlas-m43-baseline` (`4882d49`).
> Where `main` and the Atlas candidate differ, both are labeled.

### Production Configuration (baseline = atlas-candidate; values identical)

| Item | Value |
|---|---|
| production profile | `new_framework` |
| `WEIGHT_QUANT` | `0.0` |
| technical weight | `0.6` |
| sentiment weight | `0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| official signal markets | `CN` only (HK/US observe-only) |

### Test2 Frozen State

| Item | Value |
|---|---|
| file | `paper_trading/test2_ab_state.json` |
| SHA-256 | `7b9742389329cb77053ee481aabf67807ecd7340c846bd2c93524b947935f8aa` |

### Dependency Lockfile Hashes

| File | SHA-256 |
|---|---|
| `main` `uv.lock` (baseline) | `6e80908df0a7b9368e246a01600bf14b40af300976fc888eeccd08742a467668` |
| Atlas `uv.lock` (atlas-candidate) | `fef3baff665a1f7999939e8b9929bdb393a3a5eb9d1db803864195fb19053931` |

Delta: Atlas adds a `jsonschema>=4.0,<5.0` pin to `pyproject.toml` / `uv.lock`; all other entries are identical.

### Schema Digest

Stable hash of `SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY tbl_name, type, name` on the live production DB (`stock-sage.db`) as of 2026-06-05:

```
3c422e341c2538a067446b4e4b04041ead05442fd01745ff776b600abdf788ac
```

### Key Production Table Row Counts (main / pre-merge baseline)

| Table | Row count |
|---|---|
| `positions` | 5 |
| `signals` | 879 |
| `stocks` (watchlist) | 718 |
| `prices` | 856 241 |
| `ai_memory` | 5 |
| `stock_memory_items` | 633 |
| `decision_memory_layered` | 89 |
| `research_states` | 94 |
| `market_snapshots` | 49 915 |
| `financial_metrics` | 1 878 |
| `index_prices` | 338 |
| `long_term_labels` | 169 |
| `sentiment_cache` | 1 240 |
| `news` | 1 863 |
| `pending_ai_actions` | 0 |

Note: Atlas adds `memory_atoms`, `memory_scenarios`, `memory_profiles`, and `memory_promotion_candidates` tables (all empty at merge time); `forward_theses` does not yet exist in the pre-merge main DB.

### Scheduler Job IDs

Registered via `backend.scheduler.start()`:

| Job ID | Schedule |
|---|---|
| `premarket` | configurable `schedule_premarket`, mon-fri |
| `postmarket` | configurable `schedule_postmarket`, mon-fri |
| `train_model` | Sat 09:00 |
| `stoploss_check` | mon-fri 14:30 |
| `daily_memory_backup` | daily 00:30 |
| `daily_memory_expire` | daily 01:00 |
| `weekly_longterm_monday` | conditional on `long_term_team_enabled` |
| `weekly_longterm_friday` | conditional on `long_term_team_enabled` |
| `weekly_long_term_reflect` | configurable `schedule_longterm_dow` |

### Fixed-Fixture Official Signal Output Fingerprint

Deterministic composite-score fixture (no LLM, no DB, fixed inputs: `WEIGHT_QUANT=0.0`, `technical=0.6`, `sentiment=0.4`, Kronos off):

| Input (tech_score / sentiment / quant) | Composite |
|---|---|
| 70 / 0.6 / 0.0 | 66.0 |
| 40 / 0.3 / 0.0 | 36.0 |
| 90 / 0.8 / 0.0 | 86.0 |

SHA-256 of fixture JSON: `54904c1fe3ea1e84ebf7a19566c134e60f52ca6806c07285847d847e304731ed`

### Baseline Marker

`pre-atlas-m43-baseline` tag -> commit `4882d49` (M43 merge into local `main`).
