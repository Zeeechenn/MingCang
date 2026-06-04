# ATLAS Merge-Safety Report (Gate A) - Phase 1 Rebase

> Review timestamp: 2026-06-04.
> Scope: `/Users/zeeechenn/Documents/项目s/atlas` on `codex/atlas`, rebased onto
> local StockSage `main` at `423bb1d9338b85467a5e96cf5c9a96df15dd641c`.
> Question answered: can the rebased Atlas candidate proceed to architecture
> review without production/test2/scheduler drift?

Current answer: **CLEARED FOR PHASE 1 ARCHITECTURE REVIEW; NOT CLEARED FOR
DIRECT MERGE.** Atlas is now based on current local `main` and focused parity
checks passed. `ATLAS_ENABLED=false` / `settings.atlas_enabled=False` is now
wired and tested as the Atlas total dormant switch for Atlas-only routes/features,
but final merge approval still requires the full Phase 5 official-signal,
scheduler/postmarket, DB migration, dependency, and human review gates from
`docs/ATLAS_MERGE.md`.

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
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_core_database.py \
  tests/test_runtime_schema_forward_theses.py \
  tests/test_m40_research_routes.py \
  tests/test_m40_routes_http.py \
  tests/test_ai_supply_chain_template.py
```

Result: `68 passed, 1 warning`.

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_m31_cache_policy.py \
  tests/test_m31_cache_and_freshness.py \
  tests/test_external_data_sources.py \
  tests/test_provider_universe.py \
  tests/test_market_signal_policy.py \
  tests/test_m42_price_quality_guard.py \
  tests/test_m42_remediation_cli.py \
  tests/test_market_data_boundaries.py \
  tests/test_architecture_boundaries.py \
  tests/test_m10_quality_scheduler.py \
  tests/test_m15_route_guards.py
```

Result: `105 passed`.

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. \
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
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache \
PYTHONPATH=.:/Users/zeeechenn/stock-sage \
.venv/bin/python -m paper_trading.test2_ab_cli \
  --db /Users/zeeechenn/stock-sage/stock-sage.db \
  --universe /Users/zeeechenn/stock-sage/paper_trading/test2_universe.json \
  --end 2026-06-04 \
  --out /private/tmp/stocksage_m44_phase1_test2_ab.md \
  --state-out /private/tmp/stocksage_m44_phase1_test2_ab_state.json
diff -u /Users/zeeechenn/stock-sage/paper_trading/test2_ab_state.json \
  /private/tmp/stocksage_m44_phase1_test2_ab_state.json
```

Result: replay wrote `/private/tmp/stocksage_m44_phase1_test2_ab.md`; raw JSON
state diff was zero.

Final implementation gate:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache \
RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/stocksage_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Result after dormant-switch wiring: ruff passed, mypy passed on 203 source
files, backend pytest `1027 passed, 5 skipped`, frontend node tests `19 passed`,
and Vite build passed.

## Remaining Blockers Before Direct Merge

1. `ATLAS_ENABLED=false` / `settings.atlas_enabled=False` is now wired as the
   Atlas total dormant switch for Atlas-only routes/features, with legacy
   research routes preserved. Keep it in the Phase 5 parity pack and confirm
   shared-infra behavior separately because module-level flags and the total
   switch do not protect database, dependency, scheduler, or shared helper
   changes by themselves.
2. Run the full Phase 5 parity pack before any merge into `main`: final Gate-A,
   `make verify`, test2 raw/canonical parity, official signal parity smoke,
   scheduler/postmarket smoke, DB migration copy-smoke, dependency/lockfile
   review, API route smoke, memory promotion gate smoke, Atlas dormant flag
   smoke, and `git diff --check`.
3. Keep investment-effect validation separate. Atlas research/Gate-B/test4
   evidence must not alter official signals, positions, stops, sizing, or
   scheduler behavior without later shadow/test4 evidence and user confirmation.
4. Do not push, publish, merge to `main`, or release without explicit user
   instruction.

## Recommendation

Proceed to the next M44 step: architecture-owner review of the rebased Atlas
candidate and dormant-switch contract. Do not merge directly into `main` yet.
