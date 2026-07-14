# ATLAS Merge-Safety Report (Gate A) - Phase 1 Rebase

> Review timestamp: 2026-06-04.
> Scope: `../atlas` (sibling directory of this repo) on `codex/atlas`, rebased onto
> local 明仓 / MingCang `main` at `423bb1d9338b85467a5e96cf5c9a96df15dd641c`.
> Question answered: can the rebased Atlas candidate proceed to architecture
> review without production/test2/scheduler drift?

Current answer: **CLEARED FOR ARCHITECTURE REVIEW AND PHASE 3-MIN L0 MEMORY
CONTRACT; NOT CLEARED FOR DIRECT MERGE WITHOUT A FRESH PHASE 5 PACK AND USER
APPROVAL.** Atlas is based on current local `main`, the first local Phase 5 pack
passed on 2026-06-04, and Phase 3-min L0 hardening passed on 2026-06-05.
`ATLAS_ENABLED=false` / `settings.atlas_enabled=False` is wired and tested as
the Atlas total dormant switch for Atlas-only HTTP/API routes/features. Because
the 2026-06-04 Phase 5 parity pack predates the L0 implementation, direct merge
still requires final re-sync, a fresh Phase 5 parity pack, and explicit user
approval.

## Snapshot

| Item | Evidence | Result |
|---|---|---|
| Atlas branch | `git status --short --branch` | clean `codex/atlas` after final report commit |
| Main baseline | `git rev-parse main` | `423bb1d9338b85467a5e96cf5c9a96df15dd641c` |
| Merge-base | `git merge-base HEAD main` | `423bb1d9338b85467a5e96cf5c9a96df15dd641c` |
| Branch divergence | `git rev-list --left-right --count main...HEAD` | `0` main-only, Atlas-only commits are replayed on top |
| Atlas diff shape | `git diff --stat main..HEAD` | research architecture, additive DB/schema, docs, tests, `jsonschema` |
| Conflict markers | conflict-marker scan across the worktree | none |
| Protected mainline files | `git diff --name-status main..HEAD` on M31/M41/M42/M43 surfaces | no deletes/overwrites observed |

## Preserved Mainline Boundaries

- M31 cache/freshness policy and rhythm surfaces remain main-owned.
- M41 global data, market capability catalog, and CN-only official-signal policy remain main-owned.
- M42 qfq/hfq price-quality guard and remediation CLI remain main-owned.
- M43 facade split remains in place: `backend.data.schema_runtime` owns baseline runtime schema patches, while `backend.data.database` remains a compatibility facade plus Atlas additive schema setup.
- Production decision/agent/scheduler/jobs paths do not directly import Atlas research modules, Gate-B, forward thesis, review loop, universe guard, or AI supply-chain template code.
- `/research/{symbol}` remains after static `/research/...` routes, so static Atlas routes are not shadowed by the dynamic symbol route.
- `pyproject.toml` keeps `version = "0.2.3"` and adds only `jsonschema>=4.0,<5.0`; `uv.lock` contains the matching lock entries.

## Rebase Resolution Notes

- Public docs (`CHANGELOG.md`, `PROJECT.md`, `README.md`, `README_EN.md`, `STATUS.md`, `docs/ROADMAP.md`) kept current `main` facts. Atlas architecture context lives in Atlas-specific docs instead of rolling main docs back to older M31/M33-M40 wording.
- `backend/data/database.py` kept the M43 `schema_runtime.py` split and accepted only Atlas additive runtime schema for `universe_snapshots`, `forward_theses`, `gate_b_observations`, and `theme_hypotheses.ai_supply_chain_json`.
- `backend/data/schema_runtime.py` now accepts an optional engine so Atlas migration tests can run against temporary SQLite engines without re-inlining the main runtime schema function into `database.py`.
- `ThemeHypothesis.ai_supply_chain_json` is mapped in the ORM and remains observe-only template metadata; it is not read by scoring, official signal, position sizing, or research-constraint paths.

## Verification

Focused checks run after the rebase:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_core_database.py \
  tests/test_runtime_schema_forward_theses.py \
  tests/test_m40_research_routes.py \
  tests/test_m40_routes_http.py \
  tests/test_ai_supply_chain_template.py
```

Result: `68 passed, 1 warning`.

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_m31_cache_policy.py \
  tests/test_m31_cache_and_freshness.py \
  tests/test_external_data_sources.py \
  tests/test_provider_universe.py \
  tests/test_market_signal_policy.py \
  tests/test_m42_price_quality_guard.py \
  tests/test_m42_remediation_cli.py \
  tests/test_market_data_boundaries.py \
  tests/architecture/test_boundaries.py \
  tests/test_m10_quality_scheduler.py \
  tests/test_m15_route_guards.py
```

Result: `105 passed`.

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_signal_policy.py \
  tests/test_decision_harness.py::test_deep_research_run_does_not_update_last_signal_summary \
  tests/test_stock_memory.py::test_research_dossier_keeps_deep_research_out_of_official_action \
  tests/test_research_copilot.py::test_copilot_ignores_deep_research_decision_for_official_context \
  tests/test_m40_routes_http.py::test_ai_supply_chain_case_view_is_display_only_no_signal_side_effects
```

Result: `16 passed, 1 warning`.

Test2 replay:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache \
PYTHONPATH=.:<repo-root> \
.venv/bin/python -m paper_trading.test2_ab_cli \
  --db <repo-root>/mingcang.db \
  --universe <repo-root>/paper_trading/test2_universe.json \
  --end 2026-06-04 \
  --out /private/tmp/mingcang_m44_phase1_test2_ab.md \
  --state-out /private/tmp/mingcang_m44_phase1_test2_ab_state.json
diff -u <repo-root>/paper_trading/test2_ab_state.json \
  /private/tmp/mingcang_m44_phase1_test2_ab_state.json
```

Result: replay wrote `/private/tmp/mingcang_m44_phase1_test2_ab.md`; raw JSON
state diff was zero.

Final implementation gate:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mingcang_pycache \
RUFF_CACHE_DIR=/private/tmp/mingcang_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/mingcang_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Result after dormant-switch wiring: ruff passed, mypy passed on 203 source
files, backend pytest `1027 passed, 5 skipped`, frontend node tests `19 passed`,
and Vite build passed.

## Phase 5 Local Parity Update

Additional local checks run on 2026-06-04 after the architecture-contract review:

- `make verify` passed again: ruff, mypy on 203 source files, backend pytest
  `1027 passed, 5 skipped`, frontend node tests `19 passed`, and Vite build
  passed.
- Test2 fixed-end replay used Atlas code with main's protected DB and universe:
  `/private/tmp/mingcang_m44_phase5_test2_ab_state.json` had zero raw JSON diff
  against `<repo-root>/paper_trading/test2_ab_state.json`.
- Canonical test2 parity passed with stable key ordering and explicit ignored
  non-semantic timestamp fields.
- Official-signal, scheduler/postmarket, API route, memory-promotion,
  dormant-flag, runtime-schema, M31/M42, and architecture focused tests passed
  across the Phase 5 smoke set.
- Live DB migration copy-smoke used `/private/tmp/mingcang_m44_phase5_copy.db`;
  `init_db()` completed, required Atlas tables/columns existed, and
  `PRAGMA integrity_check` returned `ok`.
- `git diff --check` passed and conflict-marker scan returned no matches.

Review notes from the architecture and infra pass:

- `docs/dev/ATLAS.md` now records L0-L4 as the future main architecture, the current
  Researcher / Portfolio Manager / Execution Trader roles, the `ActionProposal`
  shadow/proposal boundary, and the Gate-B versus L4 naming boundary.
- The dormant switch is documented as an HTTP/API and default-runtime contract.
  Internal Python storage helpers remain importable for tests and explicit local
  tooling; they are not wired into production paths while Atlas is disabled.
- `forward_theses` runtime schema has a compatibility table-rebuild path for old
  unique indexes, so it is not purely additive in implementation mechanics. The
  `/private/tmp` copy-smoke is the merge-day guard for duplicate normalized keys
  or startup blocking.

## Phase 3 L0 Memory Update

Additional local checks run on 2026-06-05 after the L0 memory implementation and
Phase 3-min guard hardening:

- `backend.memory.l0_memory` now filters active recall by `refuted`, `archived`,
  `ttl_days`, `valid_from`, and `valid_to`; invalid timestamps remain visible
  rather than being silently dropped.
- M37 `/research/memory-candidates/{id}/promote|reject` now keeps the local
  human gate and also carries standard `agent_write_guard` dependencies for
  `research.memory.promote` and `research.memory.reject`.
- Focused Phase 3 regression passed: `141 passed, 1 warning`.
- Official-signal and scheduler/postmarket focused smoke passed:
  `23 passed, 1 warning`.
- Test2 fixed-end replay used `--end 2026-06-05`; raw JSON diff against
  `<repo-root>/paper_trading/test2_ab_state.json` was zero.
- Live DB copy-smoke used
  `/private/tmp/mingcang_phase3_l0_copy_20260605_afterguard.db`; `init_db()`
  completed, `memory_atoms`, `memory_scenarios`, and `memory_profiles` existed,
  `memory_promotion_candidates.memory_atom_id` existed, `PRAGMA integrity_check`
  returned `ok`, and protected `stocks` / `signals` row counts were stable.
- Full `make verify` passed after Phase 3-min hardening: ruff passed, mypy
  passed on 204 source files, backend pytest `1045 passed, 5 skipped`, frontend
  node tests `19 passed`, and Vite build passed.

This update clears the Phase 3-min memory contract. It does not clear a direct
merge by itself; Phase 4 minimal adapter review and a fresh Phase 5 parity pack
remain required.

## Remaining Blockers Before Direct Merge

1. Final re-sync check against `main` must be repeated immediately before any
   merge decision if `main` advances.
2. Merge, push, publish, or release still requires explicit user instruction.
3. Keep investment-effect validation separate. Atlas research/Gate-B/test4
   evidence must not alter official signals, positions, stops, sizing, or
   scheduler behavior without later shadow/test4 evidence and user confirmation.
4. If any merge-day copy-smoke finds duplicate normalized `forward_theses` keys
   or DB integrity drift, stop and attribute before merging.

## Recommendation

Proceed to a user-owned merge decision only after confirming `main` has not
advanced. Do not merge directly into `main` without explicit approval.
