# ATLAS Merge-Safety Report (Gate A) - Current Review

> Review timestamp: 2026-06-04 01:01 +08.
> Scope: current Atlas candidate on `codex/atlas`, compared against local
> `main` in `/Users/zeeechenn/stock-sage`.
> Question answered: **Is the current Atlas branch safe to merge directly into
> `main` without changing production trading behavior?**
> Current answer: **NOT CLEARED for direct merge.** This is a current Gate-A
> review, not the stale 12-commit historical sign-off. The committed Atlas work
> still appears structurally isolated from the production decision/scheduler path
> in the checks below, but the branch has diverged from `main`, the Atlas
> candidate still requires owner review before any merge approval. The candidate
> has passed `make verify`; that does not remove the branch-divergence and review
> blockers.

## Snapshot

| Item | Evidence | Result |
|---|---|---|
| Atlas branch | `git status --short --branch`; `git rev-parse --abbrev-ref HEAD` | `codex/atlas` |
| Atlas HEAD | `git rev-parse HEAD` | current `codex/atlas` commit containing this report |
| main tip used for comparison | `git -C /Users/zeeechenn/stock-sage rev-parse main` | `a5fae3b921b04d4f20e2afb4dff988c465723fb8` |
| merge-base | `git merge-base HEAD main` | `de26530e6f03b88b8bfcf8e76ad47432077ff099` |
| branch divergence | `git rev-list --left-right --count main...HEAD` | `14` main-only commits, `28` Atlas-only commits |
| Atlas-only committed diff | `git diff --stat de26530..HEAD` | 45 files, about 10k insertions, about 700 deletions |
| main-only diff since base | `git diff --stat de26530..main` | 50 files, 5633 insertions, 526 deletions |
| Atlas worktree state after commit | `git status --short --branch` | clean `codex/atlas` worktree |
| new tracked support files | `git show --stat HEAD` | `m43_2_amihud_ic.py`, `tests/test_m43_2_factor_reproduction.py`, `tests/test_runtime_schema_forward_theses.py` |
| main worktree state | `git -C /Users/zeeechenn/stock-sage status --short --branch` | `main...origin/main [ahead 5]` |
| integrated verification | `make verify` | PASS: lint, mypy, 899 backend tests, 19 frontend tests, Vite build |

## Current Diff Shape

Atlas-only committed work since `de26530` adds the M33-M43 research and
governance layer: research case/stress/thesis/theme/review/universe/forward
modules, research API routes and schemas, additive DB tables/migrations,
Gate-B tracking, M43 experiment docs, tests, and the explicit `jsonschema`
dependency.

The target `main` is not the same base. Since `de26530`, main has M31/M41/M42
and other production-path work, including `backend/data/cache_policy.py`,
`backend/data/global_data.py`, `backend/data/market_capabilities.py`,
`backend/data/price_quality.py`, `backend/decision/market_policy.py`,
M31/M42 tools and tests, scheduler/API/frontend changes, and related docs.
Any direct merge plan must preserve and reconcile those main-only changes.

The current Atlas candidate includes API routes/schemas, DB schema setup and
runtime migration, Gate-B recorder/tracker logic, research modules, M43
reproduction, docs, and tests. These changes are now part of the candidate
commit rather than a dirty worktree.

## Gate-A Checks

| # | Criterion | Evidence | Status |
|---|---|---|---|
| A1 | Atlas-only committed work does not edit production decision/scheduler/agent code | `git diff --name-status de26530..HEAD -- backend/decision backend/agent backend/agents backend/scheduler.py` returned empty | PASS for committed Atlas-only range |
| A2 | Production path does not directly import Atlas research modules | `rg` over `backend/decision`, `backend/agent`, `backend/agents`, and `backend/scheduler.py` found no `backend.research.*`, `gate_b`, `review_loop`, `universe_guard`, or `forward_thesis` imports | PASS for checked tree |
| A3 | Branch is based on current merge target | merge-base is `de26530`, while local `main` is `a5fae3b`; `main...HEAD` is `14/28` | BLOCKED |
| A4 | Worktree is clean enough to review as a merge candidate | Candidate changes have been committed; `git status --short --branch` is clean after commit | PASS |
| A5 | API/schema/storage changes are reviewed as safe and additive | Tests cover response models, local-human memory gate, forward-thesis runtime migration, and normalised NULL uniqueness | PARTIAL: test-backed, owner review still required |
| A6 | Full implementation gate is green on the integrated candidate | `make verify` passed: lint, mypy, 899 backend tests, 19 frontend tests, Vite build | PASS |
| A7 | Gate-B/M43 value claims are separated from merge safety | M43 docs now include a three-factor script-backed harness; no decision wiring observed in production path grep | PASS as safety framing, not value proof |

## Production-Path Risk Notes

1. **Main integration risk is the largest blocker.** Comparing `main..HEAD`
   shows files that exist only on current main as deletions from the Atlas tip
   perspective, including M31/M41/M42 data-quality and market-capability files.
   That does not mean Atlas commits deleted them; it means Atlas is behind a
   materially changed main and must be reconciled before any approval.

2. **Storage/schema risk is test-backed but still review-worthy.** The
   `backend/data/database.py` change modifies `forward_theses` uniqueness from
   `(statement, horizon_date)` to symbol-scoped uniqueness, adds a runtime helper
   that rebuilds legacy inline-unique SQLite tables without dropping visible
   columns/data, and creates a normalised unique index so `NULL` symbol or
   horizon values cannot bypass direct-SQL duplicate checks. The migration now
   preflights existing normalized duplicates and raises an actionable error with
   conflicting row ids instead of failing later with a generic SQLite index
   error.
   `tests/test_runtime_schema_forward_theses.py` covers the old-schema path and
   the direct-SQL NULL duplicate and preflight-error paths. Reviewer should
   still confirm the migration policy for any non-standard manual unique index,
   trigger, or private index on a user's persistent DB.

3. **Human-gate/API risk remains open.** The research route changes replace the
   `agent_write_guard` dependency for memory promote/reject with
   `local_human_memory_gate`, which blocks remote agent mode. That is
   conservative in intent, but the security semantics and local-only write path
   still need owner review before merge.

4. **Gate-B tracker/report behavior changed after the old report.** The
   `gate_b_recorder.py` changes update return realization horizon handling,
   data-quality accounting, ABORT precedence, and make PROMOTE impossible unless
   Stage-2 stability/coverage gates are supplied. This is conservative, and it
   is covered by focused tests, but it remains a behavior change in the research
   validation layer.

5. **M43 reproducibility is script-backed, but historical values were not
   refreshed on this machine.** `m43_2_amihud_ic.py` now supports
   `amihud_20`, `sector_rel_strength_20_z`, and `rev_mom_12_1_z`, with smoke
   coverage in `tests/test_m43_2_factor_reproduction.py`. The repo-local
   harness is ready, but the real `~/.stock-sage/m43_work.db` was not present
   in this run, so the table in `docs/M43_RETROSPECTIVE_EXPERIMENT.md` remains
   a historical 2026-06-03 work-DB note until rerun.

## Required Before Any Merge Approval

1. Decide the merge target: local `main` at `a5fae3b` versus `origin/main` at
   `3004cfe`. Local `main` is currently ahead of `origin/main` by 5 commits.
2. Bring Atlas onto the chosen current main inside the Atlas worktree only, then
   re-run the Gate-A diff checks on the integrated candidate.
3. Keep the Atlas worktree clean after any follow-up review fixes; do not merge
   a dirty candidate.
4. Review DB migration behavior for the `forward_theses` uniqueness change,
   especially any non-standard unique indexes/triggers outside the tested inline
   legacy table shape.
5. Review memory promote/reject human-gate semantics and confirm the intended
   local/remote write policy.
6. Keep `make verify` green after rebasing the integrated candidate onto the
   chosen current main.
7. Re-run route registration and schema/migration smoke checks if the API/DB
   changes remain in scope.

## Recommendation

**Do not merge the current Atlas branch directly into `main` yet.** The current
review supports a narrower finding: the committed Atlas-only research layer does
not appear to import into the production decision/scheduler/agent path. That is
not enough for merge approval because `main` has moved materially, Atlas has
merge-relevant API/DB/Gate-B/M43 changes that still need owner review, and the
clean candidate has not yet been rebased onto the chosen current main even
though it has passed `make verify`.
