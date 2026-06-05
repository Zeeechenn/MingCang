# StockSage — Public Status Snapshot

> Compact current-state snapshot for fresh agents and public readers. Detailed
> plans live in `docs/ROADMAP.md`; completed history lives in `CHANGELOG.md`.

Current release: `v0.2.3` (2026-06-04).

StockSage is an agent-ready, local-first A-share research workspace. It supports
research, backtests, local validation, memory/context inspection, and code
maintenance. It does not place real trades or provide financial advice.

## Current State

| Area | Status |
|---|---|
| production signal profile | `new_framework` |
| production quant weight | `WEIGHT_QUANT=0.0` |
| technical / sentiment weights | `0.6 / 0.4` |
| entry threshold | `NEW_FRAMEWORK_ENTRY_THRESHOLD=25.0` |
| Kronos | disabled for production |
| M29 | active: forward evidence and residual attribution remain non-promoting |
| M30 | complete: mypy, lockfile, CI/security, coverage, core tests, maintainability |
| M31 | complete: cache policy, provider fallback observability, rhythm CLI (premarket/intraday/postmarket/weekend), postmarket export with evidence cards + position review |
| M41 | complete: read-only A/HK/US seven-layer data/research facade; HK/US official signals remain observe-only |
| M42 | complete: qfq/hfq price-contamination write guard and dry-run-first remediation CLI |
| M43 | complete: architecture boundary hardening for market data, runtime schema, AI chat routes, and scheduler jobs |
| M44 / Atlas merge | active: local Phase 5 readiness pack complete at `1f198f1`; Atlas remains dormant architecture candidate pending user review / merge decision after confirming no `main` advance |
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
passes the project promotion gate:

- IC >= 0.04
- ICIR >= 0.40
- monotonic buckets
- non-overlapping / stride evidence
- sufficient fresh forward sample
- no cache, fallback, provenance, or data-quality blockers

Stop loss / take profit remain ATR-derived project rules, not LLM predictions.

## Active Work

| Milestone | Status | Next action |
|---|---|---|
| M29 Alpha Reset / Forward Evidence Engine | active | wait for complete fresh forward coverage, then rerun readiness -> forward shadow -> ledger |
| M29.5 Quant Residual Attribution | first pass complete, non-promoting | continue only if fresh evidence clears gates |
| M31 Product/Engineering Borrowings | complete | L1/L2/L3 policy, provider chains, dry-run rhythm commands (incl. weekend review), postmarket export with evidence cards + position review |
| M32 Forward Hypothesis Bridge | design stance set | start only after review data is thick enough |
| M41 A/HK/US Global Data/Research Buildout | complete | read-only three-market data facade, health ledger, normalization/PIT contracts, UX boundary, and CN-only production guardrails |
| M42 qfq/hfq Price-Contamination Guard | complete | write-time jump guard, dry-run-first remediation CLI, 33 hermetic tests; legacy full-series hfq rows remain a separate data cleanup item |
| M43 Architecture Boundary Hardening | complete | compatibility facades, behavior-characterization tests, and AST architecture guards are in place |
| M44 Atlas Merge / L0-L4 Architecture | active: Phase 5 readiness pack complete at `1f198f1`; L0 trust, recall, migration, memory-promotion guardrails, and read-only adapter wiring verified | Phase 5 readiness pack complete locally; awaiting user review / merge decision after confirming no `main` advance |

For detailed sequencing, read `docs/ROADMAP.md`; for the Atlas/M44 detailed
checklist, read `docs/ATLAS_MERGE.md`. For historical milestone details, read
`CHANGELOG.md`.

M44 update (2026-06-05): `docs/ATLAS_MERGE.md` remains the detailed Atlas
checklist. Phase 0/1/2 are complete, and Phase 3-min is now complete: L0 memory
atoms/scenarios/profiles, scope and trust-state contracts, legacy
`legacy_import_pending` boundaries, ReviewCase / memory-candidate promotion
bridge, remote trusted-write guards, and active-recall filtering for refuted,
archived, ttl_days, valid_from, and valid_to are in place. Verification after
the Phase 3-min hardening passed focused Phase 3 tests, official
signal/scheduler smoke, live DB copy-smoke, test2 raw parity for
`--end 2026-06-05`, and full `make verify`. Phase 3-full productization remains
separate: complete legacy adapters/backfill and native ResearchCase /
ActionProposal L0 wiring are not yet required for the minimal merge-safety
slice. Atlas behavior must remain dormant until engineering parity gates pass;
any investment-impact promotion requires later shadow/test4 evidence.

M44 Phase 4 update (2026-06-05): the minimal adapter review is complete using
the existing dossier as `dossier_readonly_v0`. The Atlas-only
`/api/research/{symbol}/adapter-review` route is dormant-guarded and returns
read-only L1 EvidenceCard-style mappings, an L2 ResearchCase, and an L0
memory-candidate preview. It does not create candidates or promote trusted
memory; promotion remains behind the existing M37/M40 local-human gate path.
Focused adapter regression passed with `44 passed, 1 warning`; expanded
M33/M37/M40/L0 regression passed with `159 passed, 1 warning`. Merge-day
equivalence remains a Phase 5 parity-pack requirement, not a Phase 4 claim.

M44 Phase 5 readiness note (2026-06-05): after commit `1f198f1`, local
readiness checks showed `main...HEAD = 0 / 35`, `merge-base main HEAD =
423bb1d9338b85467a5e96cf5c9a96df15dd641c`, `git diff --check main...HEAD`
passed, and read-only `git merge-tree main HEAD` returned a synthetic tree with
no conflict output. Full `make verify` passed with backend pytest
`1049 passed, 5 skipped`, frontend node tests `19 passed`, and Vite build.
Fixed-end test2 replay at `--end 2026-06-05` had zero raw JSON diff against the
main `paper_trading/test2_ab_state.json`; DB copy-smoke on
`/private/tmp/stocksage_m44_after_l0_gate_copy.db` passed `init_db()`,
`PRAGMA integrity_check`, Atlas table/index checks, and protected `stocks` /
`signals` row-count stability (`718` / `879`). `build_memory_context()` now
keeps L0 memory dormant by default unless `ATLAS_ENABLED=true`, while explicit
memory API context still opts into L0. This is a local merge-readiness package,
not a merge; if `main` advances before user approval, rerun conflict checks and
the parity pack.

M31 completion note (2026-06-02): `backend.data.cache_policy` defines L1/L2/L3
and the intraday zero-network contract; `/api/system/data-coverage` exposes
freshness contracts and provider fallback chains; `backend.tools.m31_cache_benchmark`
writes read-only latency reports under `/private/tmp`; `backend.agent.cli`
and `stocksage` expose `premarket` / `intraday` / `postmarket` dry-run rhythm
commands; `/api/export/postmarket-review.html` and `?format=word` export
postmarket review reports with the day's signal table, per-signal evidence cards
(score decomposition + stop/take + LLM rationale), a position-review section
(open holdings with unrealized P/L plus same-day closes), rule/profile version,
and non-advice disclaimers. The M31.3 weekend-review rhythm command
(`weekend` / `周末`) is also packaged, so M31 is now fully complete.

M41 seed note (2026-06-03): `backend.data.market` now registers
`yfinance_hk` for HK daily OHLCV and keeps `yfinance_us` for US daily OHLCV;
watchlist, research prepare, positions, and local agent action schemas accept
`HK` alongside `CN`/`US`. This is a daily-price bridge only; non-price layers
still need field normalization, PIT/freshness checks, and promotion gates before
becoming research or signal inputs.

M41 capability note (2026-06-03): `/api/system/data-coverage` now nests a
StockSage-owned A/HK/US seven-layer market capability catalog under
`summary.market_capability_catalog`, alongside per-market coverage and provider
fallback chains. `backend.decision.market_policy` keeps official signal
generation CN-only: HK/US may be prepared and viewed as read-only research
context, but postmarket batch, stop-loss checks, long-term constraint labels,
and `save_signal()` do not promote known HK/US stocks into official signals.

M41 probe note (2026-06-03): `/api/system/external-data-sources?probe=true`
now accepts `market=CN|HK|US`. CN keeps the existing ftshare/TickFlow/Tushare
qfq/iFinD probes; US adds read-only SEC submissions/companyfacts plus yfinance
basic/options-expiry probes; HK adds HKEXnews title-search reachability plus
yfinance basic-info probing. `probe=false` remains offline, and all probe
results keep `write_policy=no_database_writes` and `signal_impact=none`.
The same probe links are now attached to `summary.market_capability_catalog`,
so `/api/system/data-coverage` can show which read-only probe belongs to each
market/layer without running those probes.

M41 probe-summary note (2026-06-03): `/api/system/external-data-sources`
now returns `probe_summary`. With `probe=true`, the API keeps raw probe payloads
and adds normalized read-only health rows by market/layer/provider, including
sample size, fields present, required StockSage fields, missing-field gaps,
freshness status, and explicit `safe_for_research_scoring=false` /
`safe_for_production_signal=false`. With `probe=false`, the endpoint still does
not run network probes and reports `probed=false`. Field-complete rows are only
marked `required_fields_present`; they are not treated as normalized or
PIT-ready.

Global data/research roadmap note (2026-06-03): `docs/ROADMAP.md` now records
the full A-share/HK/US buildout under one M41 milestone instead of spreading
the same work across multiple milestones: M41.4 probe health ledger, M41.5 field
normalization and PIT gates, M41.6 agent-facing global data route, M41.7
A-share seven-layer uplift, M41.8 HK/US read-only research context, M41.9
global watchlist/portfolio UX, M41.10 evidence and promotion gates, and M41.11
production-boundary review. HK/US remain read-only research context until these
gates pass and human confirmation explicitly changes `market_policy`.

M41 completion note (2026-06-03): `backend.data.global_data` now provides the
read-only `market + symbol + intent` envelope used by
`GET /api/system/global-data` and `python3 -m backend.agent.cli global-data`.
Every envelope carries source, fetched_at, currency/timezone/namespace,
freshness status, missing fields, canonical schema, PIT gate status,
`write_policy=no_database_writes`, and explicit scoring/signal safety flags.
`backend.tools.m41_probe_health_ledger` aggregates explicit probe summaries into
a `/private/tmp` health ledger and only runs network probes with
`--run-probes`. Production coverage checks and portfolio allocation weights now
use the CN production denominator; HK/US watchlist/position rows remain
observe-only and are not allowed to dilute A-share official decisions. HKD/USD
/CNY position summaries are displayed by market without automatic FX merging.

M42 completion note (2026-06-04): `backend.data.price_quality` now includes a
write-time qfq/hfq jump guard that flags close prices more than 3x the recent
history median before `backfill_if_needed` writes rows to `prices`.
`backend.tools.m42_remediate_hfq_contamination` provides a dry-run-first,
backup-protected sqlite remediation path for the 2026-05-25/26 hfq rows found
in ATLAS follow-up analysis. The production decision layer is unchanged:
`WEIGHT_QUANT=0.0`, CN-only official signals, and HK/US observe-only boundaries
all remain intact.

M43 completion note (2026-06-04): architecture hardening split the thick
market-data, runtime-schema, AI chat, and scheduler modules into focused helpers
while preserving compatibility facades. `backend.data.market` remains the public
market entrypoint but delegates provider helpers and DB writes to
`market_utils`, `market_sources`, and `market_persistence`; `database.py` keeps
ORM/session/init entrypoints while `schema_runtime.py` and `seed.py` own startup
patches and seed routines; `api/routes/ai.py` delegates action parsing, chat
storage, and deterministic response building; `scheduler.py` delegates job
workflows to `backend.jobs.*`. `tests/test_architecture_boundaries.py` now
guards top-level import cycles, API/provider layering, and facade size limits.
M43 verification passed with ruff, mypy, 759 backend tests, 19 frontend node
tests, and Vite build; the first integrated `make verify` run reached Vite build
and then hit a sandbox-only `frontend/node_modules/.vite-temp` write `EPERM`, so
the build step was rerun under normal filesystem permissions and passed.

## Validation Snapshot

Last recorded full gate for the current release:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache \
RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache \
MYPY_CACHE_DIR=/private/tmp/stocksage_mypy_cache \
make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'
```

Recorded result after M44 Phase 3-min hardening: ruff passed, mypy passed on
204 source files, backend pytest `1045 passed, 5 skipped`, frontend node tests
`19 passed`, and Vite build passed.

M41 verification update (2026-06-03): full `make verify` passed with ruff,
mypy, 714 backend tests, 19 frontend node tests, and Vite build. A read-only
`paper_trading.test2_ab_cli --end 2026-06-03` replay written to `/private/tmp`
had zero JSON diff against `paper_trading/test2_ab_state.json`.

For release-quality work, treat `make verify` as the canonical gate.

## Fresh-Agent Reading Rule

Do not read every project document by default. Start with `AGENTS.md`, then load
only the file that matches the task:

| Task | Read |
|---|---|
| current state, tests, trading/research status | `STATUS.md` |
| architecture or file navigation | `PROJECT.md` |
| onboarding, install, public wording | `README.md` |
| next step, continuation, planning | `docs/ROADMAP.md` |
| releases or historical changes | `CHANGELOG.md` |
| paper trading test truth | `paper_trading/*_state.json` first, then matching `.md` |

## Runtime Commands

```bash
python3 -m backend.agent.cli health --pretty
python3 backend/data/database.py
PYTHONPATH=. python3 -m backend.agent.mcp_server
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm run dev
```

For one-stock research:

```bash
python3 -m backend.agent.cli project-context --symbol <symbol> --pretty
python3 -m backend.agent.cli stock-context <symbol> --pretty
```

## Agent Boundary

- Local Codex / Claude Code sessions are trusted development sessions.
- Remote exposure requires `STOCKSAGE_AGENT_MODE=remote` and
  `STOCKSAGE_AGENT_API_KEY`.
- Remote writes require both `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=true` and an
  explicit action allowlist.
- Real broker orders, destructive git operations, publishing, pushing, and
  releases require explicit user instruction.
- Do not commit `.env`, local databases, model files, or personal trading
  records.
