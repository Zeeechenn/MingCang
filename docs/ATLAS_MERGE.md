# Atlas Merge Record

> Compact handoff for the Atlas -> 明仓 / MingCang `main` integration. Historical
> phase-by-phase evidence belongs in git history and `CHANGELOG.md`; this file
> keeps only the current state, live boundaries, verification anchors, and
> rollback/push rules that future agents need.

## Current State

| Item | Status |
|---|---|
| Local `main` | Contains M43 baseline merge `4882d49` and dormant Atlas merge `9820143` |
| Remote | `origin/main` contains dormant Atlas merge `9820143`; local `main` is aligned with `origin/main` as of the latest audit |
| Atlas default | Dormant: `ATLAS_ENABLED=false` / `settings.atlas_enabled=False` |
| Production profile | `new_framework`, `WEIGHT_QUANT=0.0`, technical/sentiment `0.6/0.4`, entry threshold `25.0`, Kronos off |
| Official market boundary | CN-only official signals; HK/US remain observe-only research context |
| Test boundary | test2 frozen; do not change replay state, runner inputs, sizing, stop/take, signal loading, or state JSON semantics |
| Push policy | Push / publish only after explicit user authorization |

## What Was Merged

Atlas entered local `main` as a dormant architecture upgrade:

- L0 memory / knowledge base with trust states (`raw`, `pending`, `trusted`, `refuted`, `archived`, `legacy_import_pending`) and active-recall filtering for refuted / archived / TTL / validity windows.
- L1/L2 adapter review that maps the existing dossier into read-only EvidenceCard rows, ResearchCase shape, and L0 memory-candidate preview.
- L4 review / memory-promotion surfaces that keep trusted memory behind human / ReviewCase gates.
- Research modules from the Atlas branch, including thesis, theme hypothesis, review loop, universe guard, forward thesis, and Gate-B tracking.
- Dormant route and context guards so Atlas-only behavior stays off unless explicitly enabled.

The engineering merge does **not** promote Atlas investment behavior. Test4 / forward shadow is the separate investment-effect gate.
M45 Stage 2b is a separate source-gated research-positioning shadow lane; the
Atlas/test4 Stage 2b lane measures Atlas investment-effect only.

## Live Principles

- Atlas is the next main architecture candidate, not a separate permanent side project.
- Dormant means code may exist on `main`, but official signal, test2/test3, 标的1, scheduler, postmarket, stop/take, sizing, and production scoring do not use Atlas behavior by default.
- The dormant switch does not protect shared infra. Database migrations, runtime schema, dependency/lockfile changes, scheduler helpers, API helpers, and shared data-loading helpers still require parity checks.
- First merge allowed additive / non-destructive migration only, with one user-approved exception: `forward_theses` may use the recorded data-preserving table rebuild for the symbol-aware unique key.
- Trusted memory cannot be written automatically by LLM/tool callers; raw/pending/legacy rows require review before promotion.

## Verification Anchors

The local readiness/merge package recorded these gates around 2026-06-05:

- `git diff --check` passed.
- `make verify` passed: ruff, mypy on 204 source files, backend pytest `1049 passed, 5 skipped`, frontend node tests `19 passed`, Vite build passed.
- Test2 fixed-end replay used `--end 2026-06-05`; raw JSON diff against the repository's `paper_trading/test2_ab_state.json` was zero.
- DB copy-smoke on `/private/tmp/mingcang_m44_after_l0_gate_copy.db` passed `init_db()`, `PRAGMA integrity_check`, Atlas table/index checks, `forward_theses` normalized unique index check, and protected `stocks` / `signals` row-count stability (`718` / `879`).
- `build_memory_context()` includes L0 memory by default only when `settings.atlas_enabled=True`; explicit memory API context can opt in with `include_l0=True`.
- Fixed official-signal fixture with `WEIGHT_QUANT=0.0`, technical `0.6`, sentiment `0.4`, Kronos off produced composites `66.0`, `36.0`, `86.0`.

Treat these as recorded evidence, not proof that the current checkout is still release-ready. Rerun the relevant subset before push, release, or any follow-up that touches shared infra.

## Push / Publish Gate

Before any user-authorized push or release:

1. Confirm branch and divergence: `git status --short --branch`, `git rev-list --left-right --count origin/main...HEAD`.
2. Confirm no local dirty files unrelated to the push.
3. Run `git diff --check origin/main..HEAD`.
4. Rerun focused parity smoke for dormant Atlas, official signal fixture, scheduler/postmarket, memory promotion guard, and test2 fixed-end replay.
5. Run full `make verify` for release-quality publication.
6. Push only after the user explicitly approves the publish step.

Stop if any official signal, test2, test3, 标的1, scheduler/postmarket, migration, dependency/lockfile, or shared-helper drift appears.

## Post-Merge Work

Still pending, all dormant / shadow unless explicitly promoted:

- Phase 3-full: legacy adapters/backfill for `decision_memory_layered`, research memory, track-analyst skill, long-term reports, and topic reports.
- Native ResearchCase / future ActionProposal recall to L0.
- Full long-term research / track-analyst / deep_research / copilot / debate migration.
- Full M29 ledger integration.
- Atlas/test4 Stage 2b forward shadow for investment effect: signal-overlay
  starter exists via `backend.tools.atlas_test4_stage2b_shadow`; exit-overlay
  and entry+exit arms remain registered but not started.

## Rollback Runbook

Rollback triggers:

- Destructive or unexpected schema drift.
- Existing production rows unexpectedly rewritten.
- Dependency/shared-helper drift in fixed-fixture official signal smoke.
- Official signal, test2 canonical parity, scheduler/postmarket, or position sizing drift.
- Unexpected trusted-memory writes.
- Production path calls Atlas behavior while the total switch is off.

Rollback actions:

1. Stop related scheduler / Atlas shadow jobs if any are running.
2. Revert Atlas merge commit `9820143`, or switch back to `pre-atlas-m43-baseline` (`4882d49`) for local diagnosis.
3. Do not restore the pre-merge SQLite copy for routine rollback; preserve live rows created during the rollback window.
4. Re-run health, official-signal smoke, and test2 replay.
5. Record the drift cause before attempting another merge/push path.

## Baseline Snapshot

Pre-Atlas baseline marker:

- `pre-atlas-m43-baseline` -> `4882d49`.
- Test2 state SHA-256 recorded before merge: `7b9742389329cb77053ee481aabf67807ecd7340c846bd2c93524b947935f8aa`.
- Live DB schema digest recorded before merge: `3c422e341c2538a067446b4e4b04041ead05442fd01745ff776b600abdf788ac`.
- Atlas lockfile delta: `jsonschema>=4.0,<5.0` added to `pyproject.toml` / `uv.lock`; all other lock entries were recorded as identical at merge-readiness time.
