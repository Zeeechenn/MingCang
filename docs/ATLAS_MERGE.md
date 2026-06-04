# Atlas Merge Plan

> Durable execution plan for merging Atlas into StockSage `main`. ROADMAP stays light and points here for the detailed checklist. This file replaces the external `/Users/zeeechenn/Downloads/PLAN (2).md` as the project-owned handoff surface.

## Current State

| Item | Status |
|---|---|
| Current phase | Phase 1 complete; Atlas total dormant switch wired; next: Phase 5 parity pack and architecture-owner review before direct merge |
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
- First merge allows only additive / non-destructive migration: new tables, nullable columns, non-destructive indexes, idempotent runtime schema patches. No dropping/renaming old tables or columns, no rewriting live old rows, no incompatible constraints on existing production tables.
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

- [ ] Update project-owned Atlas architecture docs to describe L0-L4 as the future main architecture, not a side feature.
- [ ] State that merge-time behavior must remain dormant by default.
- [ ] State that test2, test3, 标的1, and official signal behavior do not change on merge day.
- [ ] Define current roles: Researcher enabled, Portfolio Manager proposal enabled, Execution Trader shadow/interface only.
- [ ] Clarify that `ActionProposal` is a future object and does not equal the current runtime action registry.
- [ ] Clarify that early `ActionProposal` output is shadow/proposal only and does not connect to official paths.
- [ ] Keep `Gate-B` reserved for the current prospective tracker.

Acceptance:

- [ ] L0 is named as the priority implementation layer.
- [ ] test2 frozen baseline is explicit.
- [ ] dormant merge contract is explicit.
- [ ] No generic temporary planning files are created.

## Phase 3: L0 Memory / Knowledge Base First

Goal: build a safe memory foundation before connecting more research or proposal behavior.

- [ ] Review L0 design before irreversible schema decisions.
- [ ] Inventory memory sources: `stock_memory_items`, `decision_memory_layered`, research memory, A-teacher skill, long-term reports, topic reports, ReviewCase candidates, and user-explicit rules/preferences.
- [ ] Define memory scope: stock, theme, sector, market/global, user preference, methodology/skill.
- [ ] Define trust state: raw, pending, trusted, refuted, archived, legacy_import_pending.
- [ ] Define legacy backfill: old `stock_memory_items`, `decision_memory_layered`, and research memory do not become trusted by default.
- [ ] Default unverifiable legacy rows to pending / legacy_import_pending.
- [ ] Allow LLM to generate raw/pending only.
- [ ] Require human gate or ReviewCase promotion for trusted memory.
- [ ] Prevent remote agent from promoting trusted memory.
- [ ] Ensure ResearchCase and ActionProposal recall trusted and pending memory separately.
- [ ] Add expiration / refutation policy for thesis-like memory.

Acceptance:

- [ ] L0 supports stock/theme/sector/global research.
- [ ] L0 distinguishes pending from trusted.
- [ ] L0 serves ResearchCase and ActionProposal.
- [ ] Legacy memory is not accidentally trusted.
- [ ] LLM cannot automatically write trusted memory.
- [ ] L0 does not change official signal or test2 behavior.

## Phase 4: Minimal Core Adapter

Goal: prove one old module can enter the new architecture safely without migrating everything before merge.

- [ ] Implement or wire one read-only `ResearchCase` / case view.
- [ ] Implement one minimal `EvidenceCard` mapping.
- [ ] Implement one memory candidate / promotion gate path.
- [ ] Pick one adapter, preferably deep_research or existing dossier, because it can stay read-only and avoid official signal impact.
- [x] Confirm/wire `settings.atlas_enabled` as the Atlas total dormant switch; module-level flags remain secondary.
- [x] With dormant switch off, Atlas routes/modules return disabled, empty, or manual-only behavior.

Deferred until after first merge:

- [ ] Full long-term research / A-teacher adapter.
- [ ] Full deep_research migration.
- [ ] Full copilot migration.
- [ ] Full debate refactor.
- [ ] Full M29 ledger integration.
- [ ] Complete ActionProposal influence path.
- [ ] test4 overlay investment promotion.

Acceptance:

- [ ] Focused tests cover the minimal adapter.
- [ ] Unfinished modules have owners / migration notes.
- [x] Atlas total switch off means Atlas-only routes/features are dormant and no official path impact is introduced.
- [ ] Merge-day behavior remains equivalent.

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
