"""Static governance registry for retained MingCang tool entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CATEGORIES = ("stable", "maintenance", "evidence", "attic")

_TOOL_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "module": "backend.tools.coverage_snapshot",
        "category": "stable",
        "purpose": "Print the current data coverage snapshot as JSON.",
        "read_write_boundary": "Read-only; opens the configured database and does not write rows.",
        "recommended_entrypoint": "python3 -m backend.tools.coverage_snapshot",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.check_sensitive_paths",
        "category": "stable",
        "purpose": "Guard commits from including runtime data, secrets, and sensitive local paths.",
        "read_write_boundary": "Read-only filesystem path check; exits non-zero on blocked paths.",
        "recommended_entrypoint": "python3 -m backend.tools.check_sensitive_paths <paths...>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.gate_b_tracker",
        "category": "stable",
        "purpose": "Record, realize, and report Gate-B prospective observations.",
        "read_write_boundary": "report is read-only; record/realize write GateBObservation rows only through the gated tracker flow.",
        "recommended_entrypoint": "python3 -m backend.tools.gate_b_tracker report --pretty",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.long_term_constraint_impact",
        "category": "stable",
        "purpose": "Compare latest daily signals with active long-term labels under shadow and enforced modes.",
        "read_write_boundary": "Read-only report; does not promote long-term constraints or write signals.",
        "recommended_entrypoint": "python3 -m backend.tools.long_term_constraint_impact",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m59_panel",
        "category": "stable",
        "purpose": "Build the M59 postmarket operation panel as postmarket_panel.v1 JSON or Markdown.",
        "read_write_boundary": "Read-only; opens the configured SQLite database in mode=ro and never writes tables.",
        "recommended_entrypoint": "python3 -m backend.tools.m59_panel",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m59_discretion",
        "category": "stable",
        "purpose": "Build observe-only M59 LLM discretion reference cards for candidate selection and holding decisions.",
        "read_write_boundary": "Reads M59 panel/context packs and writes only the m59_discretion_cards table; never mutates official signals, stops, targets, or positions.",
        "recommended_entrypoint": "python3 -m backend.tools.m59_discretion --json",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m52_flow_floor",
        "category": "stable",
        "purpose": "M61 B7 资金流地基:news_fusion flow 腿的 PIT 数据读取(fetch_flow_data_pit)与 s_flow 计算(compute_s_flow_data,tanh 自归一 v1)。打分路径只读 DB,绝不打外部 API。",
        "read_write_boundary": "Read-only against fund_flows; emits DegradationEvent rows when PIT data is absent; no CLI entrypoint (library imported by backend.data.news_fusion).",
        "recommended_entrypoint": "python3 -c 'from backend.tools.m52_flow_floor import fetch_flow_data_pit'  # library, no CLI",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m61_backfill",
        "category": "stable",
        "purpose": "M61 品类数据回填/滴灌 CLI:announcements/research_reports/lhb/corporate_events/holders/fund_flow/overseas 按 universe+日期窗口拉取入库,逐股降级续跑,幂等。",
        "read_write_boundary": "Writes the M61 category tables (announcements/research_reports/lhb_records/corporate_events/holder_snapshots/fund_flows/overseas_snapshots) idempotently; reads external providers via category_registry; emits DegradationEvent on failures.",
        "recommended_entrypoint": "python3 -m backend.tools.m61_backfill --category fund_flow --universe paper_trading/biaodi1_universe.json --start 2026-01-01 --end 2026-07-04",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_render",
        "category": "stable",
        "purpose": "M63 shared human-readable report layer: plain-Chinese glossary, semantic notes, number formatting, section rendering, and premarket/intraday language guard.",
        "read_write_boundary": "Library only; no database, filesystem, network, or LLM side effects.",
        "recommended_entrypoint": "python3 -c 'from backend.tools.m63_render import render_report'  # library",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_daily",
        "category": "stable",
        "purpose": "M63 daily touchpoints CLI: 盘前看/盘中记/盘后决 reports, trigger router, and research queue writing.",
        "read_write_boundary": "Reads configured SQLite; writes paper_trading/m63_out reports and ~/.mingcang/m63_research_queue.json / m63_trigger_history.json; postmarket may call bounded data/LLM steps unless --no-llm is used.",
        "recommended_entrypoint": "python3 -m backend.tools.m63_daily --mode postmarket --no-llm",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_research",
        "category": "stable",
        "purpose": "M63-2 随时式 full-stack research CLI: resolve a symbol/theme, run bounded category backfill, labels, deep research, copilot refresh, watchlist upsert, and consolidated report rendering.",
        "read_write_boundary": "Writes M61 category tables, paper_trading/watchlists/*.json, paper_trading/m63_out/research_*.md, and optionally marks ~/.mingcang/m63_research_queue.json entries done; LLM stages are skipped with --no-llm and deep research requires --auto or interactive confirmation.",
        "recommended_entrypoint": "python3 -m backend.tools.m63_research --target 300604 --no-llm",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_opinion",
        "category": "stable",
        "purpose": "M63-2 喂观点 CLI: archive raw user opinions, compare them against watchlist theses, and enqueue R4_opinion_change research tasks when stance changes.",
        "read_write_boundary": "Always appends ~/.mingcang/m63_opinions.jsonl; with LLM available it may append deduped R4 entries to ~/.mingcang/m63_research_queue.json; --no-llm archives only.",
        "recommended_entrypoint": "python3 -m backend.tools.m63_opinion --text '<观点内容>' --source manual --no-llm",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_weekly",
        "category": "stable",
        "purpose": "M63-3 固定式周末体检 CLI: one optional LLM attribution call plus zero-LLM trigger audit, staleness/drift scan, R5 weekly-sweep queue escalation, and weekly report rendering.",
        "read_write_boundary": "Reads configured SQLite, watchlist JSON, trigger history, and research queue; writes paper_trading/m63_out/weekly_<date>.md and deduped R5 entries to ~/.mingcang/m63_research_queue.json; --no-llm skips the only attribution LLM call.",
        "recommended_entrypoint": "python3 -m backend.tools.m63_weekly --no-llm",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m63_wiring",
        "category": "stable",
        "purpose": "M63-4 explicit wiring disposition map from retained tools registry modules to daily/research/weekly/trigger/manual buckets.",
        "read_write_boundary": "Static library only; no database, filesystem, network, or LLM side effects.",
        "recommended_entrypoint": "python3 -c 'from backend.tools.m63_wiring import WIRING_MAP; print(len(WIRING_MAP))'",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m61_source_health",
        "category": "evidence",
        "purpose": "M61 P1 源体检 harness:对(源×数据类别)矩阵做只读探针,输出六维打分卡(覆盖/回溯/完整率/时延/稳定/PIT),发牌表依据。",
        "read_write_boundary": "Read-only probes against external providers (bounded calls, throttled); writes JSON scorecards under paper_trading/m61_out/ only, never the database.",
        "recommended_entrypoint": "python3 -m backend.tools.m61_source_health --list",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.blind_adjudication",
        "category": "evidence",
        "purpose": "判断门 A/B 产出的代理盲裁 harness(沉淀自 2026-07-04 M61 P4):双臂盲化为甲/乙(sha256 定序,answer_key 独立落盘),N 独立裁判按'事前推理质量+事后结局对照+泄漏检查' rubric 出结构化票。",
        "read_write_boundary": "Reads judgment-gate JSON + DB as-of-later outcome data; calls local claude/codex CLI as judges (single-layer); writes adjudication JSON artifacts under paper_trading/m61_out/ only.",
        "recommended_entrypoint": "python3 -m backend.tools.blind_adjudication --help",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m61_quant_features",
        "category": "evidence",
        "purpose": "M61 §7.5 量化富特征矩阵 v2 构建器:价格块(复用 qlib_data)+龙虎榜/事件/研报修正/财务/资金流块,全特征严格 PIT,缺数据保留 NaN(禁 fillna(0),D3 假特征教训)。",
        "read_write_boundary": "Read-only against prices and the M61 category tables; returns DataFrame, writes nothing; no LLM, no network.",
        "recommended_entrypoint": "python3 -c 'from backend.tools.m61_quant_features import build_feature_matrix_v2'  # library",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m61_quant_walkforward",
        "category": "evidence",
        "purpose": "M61 §7.5 富特征 LGBM walk-forward(预注册假设 m61_quant_v2_enriched_features,门=IC 0.04/ICIR 0.40):与旧 LGBM 关门口径同法,新特征空间新假设,不推翻旧证伪。",
        "read_write_boundary": "Read-only DB; trains LightGBM in-memory; writes JSON results under paper_trading/m61_out/ only; zero LLM.",
        "recommended_entrypoint": "python3 -m backend.tools.m61_quant_walkforward --universe paper_trading/biaodi1_universe.json --start 2026-01-01 --end 2026-07-04",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m61_judgment_gate",
        "category": "evidence",
        "purpose": "M61 P4 判断门盲对照 harness:四个历史案例×双臂(改造前starved vs 改造后full context)同题同模型出裁量,as_of 截断,不自评,盲评留人工。",
        "read_write_boundary": "Reads DB as-of snapshots; calls local claude CLI (forced non-codex) for LLM arms; writes markdown/JSON reports under paper_trading/m61_out/ only.",
        "recommended_entrypoint": "python3 -m backend.tools.m61_judgment_gate --dry-run",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m60_watchtower",
        "category": "stable",
        "purpose": "M60 Phase 1 postmarket watchtower: scan the Phase 0 observation watchlist for price/volume anomaly, sector resonance, and M54 news-L1 triggers (zero LLM, deterministic).",
        "read_write_boundary": "Read-only against prices/news via the configured SQLite database in mode=ro; writes only the requested JSON/Markdown artifacts under --output-dir (default /private/tmp), never the database.",
        "recommended_entrypoint": "python3 -m backend.tools.m60_watchtower",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m60_second_entry",
        "category": "stable",
        "purpose": "M60 Phase 2b observe-only second-entry shadow ledger: register V1 immediate, V2 MA5 pullback, and V3 volume-confirmed new-high variants from watchtower triggers.",
        "read_write_boundary": "Read-only against prices via the configured SQLite database in mode=ro; writes only paper_trading/m60_out/second_entry_ledger.json and optional M29 preregistry JSON backup/update when explicitly requested.",
        "recommended_entrypoint": "python3 -m backend.tools.m60_second_entry",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m60_thesis_sync",
        "category": "maintenance",
        "purpose": "Sync M60 watchlist thesis text and validation conditions into ForwardThesis authority rows.",
        "read_write_boundary": "Writes forward_theses rows only when settings.forward_thesis_enabled is true; never writes signals, scores, positions, or watchlist JSON.",
        "recommended_entrypoint": "python3 -m backend.tools.m60_thesis_sync --json",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m31_cache_benchmark",
        "category": "stable",
        "purpose": "Measure M31 cache-layer latency for L1/L2 and describe L3 policy without calling it.",
        "read_write_boundary": "Read-only benchmark by default; does not call paid or remote L3 providers.",
        "recommended_entrypoint": "python3 -m backend.tools.m31_cache_benchmark",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m41_probe_health_ledger",
        "category": "stable",
        "purpose": "Build the M41 probe health ledger from existing probe artifacts or explicit probes.",
        "read_write_boundary": "Default reads existing JSON; --run-probes performs side-effect-free external probes and writes only the ledger artifact.",
        "recommended_entrypoint": "python3 -m backend.tools.m41_probe_health_ledger",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m54_content_probe",
        "category": "evidence",
        "purpose": "M54 feasibility probe: report 东财/Anspire raw article-content coverage and history reach before ingestion drops it.",
        "read_write_boundary": "Read-only: performs external news fetches and prints a summary; never writes the DB or any artifact.",
        "recommended_entrypoint": "python3 -m backend.tools.m54_content_probe",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m54_content_backfill",
        "category": "evidence",
        "purpose": "Backfill historical M54 news content through existing 东财/Anspire fetchers and report content coverage.",
        "read_write_boundary": "Writes only deduplicated news rows through save_news_to_db; report-only mode is read-only and no LLM/scoring path is called.",
        "recommended_entrypoint": "python3 -m backend.tools.m54_content_backfill --start <YYYY-MM-DD> --end <YYYY-MM-DD>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m54_news_v2_oos",
        "category": "evidence",
        "purpose": "Run the M54 news_layer_v2 clean OOS harness with isolated cache namespace and IC gate diagnostics.",
        "read_write_boundary": "Reads local news/prices and writes only the requested JSON artifact; --mock avoids live LLM/provider calls.",
        "recommended_entrypoint": "python3 -m backend.tools.m54_news_v2_oos --mock --start <YYYY-MM-DD> --end <YYYY-MM-DD>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m54_daily_accrual",
        "category": "evidence",
        "purpose": "Daily M54 news_layer_v2 forward accrual: idempotent same-day content fetch + pyramid scoring + v2 score-cache write, plus cumulative IC-day gate progress toward the 20-day门 (M54_OOS_PREREGISTER §12-13).",
        "read_write_boundary": "Writes deduplicated news rows and m54_oos_score_cache rows only; --report-only is fully read-only (no fetch/scoring/LLM spend).",
        "recommended_entrypoint": "python3 -m backend.tools.m54_daily_accrual",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.backfill_coverage",
        "category": "maintenance",
        "purpose": "Backfill missing financial rows, fresh news rows, and short price history coverage gaps.",
        "read_write_boundary": "Writes data coverage gaps when run; intentionally does not start scheduler jobs.",
        "recommended_entrypoint": "python3 -m backend.tools.backfill_coverage",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m26_expand_universe",
        "category": "maintenance",
        "purpose": "Expand the M26 training universe and optionally refresh/retrain supporting data.",
        "read_write_boundary": "--dry-run previews; normal execution can write stocks/prices and optional retraining artifacts.",
        "recommended_entrypoint": "python3 -m backend.tools.m26_expand_universe --dry-run",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_build_test3_universe",
        "category": "maintenance",
        "purpose": "Build the M27 test3 universe from the local MingCang SQLite database.",
        "read_write_boundary": "Reads local database and writes the requested universe JSON artifact.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_build_test3_universe",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_kronos_finetune_data",
        "category": "maintenance",
        "purpose": "Prepare index-backed M27.4 Kronos Path A fine-tuning datasets.",
        "read_write_boundary": "Reads price data and writes dataset/report artifacts; does not train or promote a model.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_kronos_finetune_data",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_kronos_path_a_launch",
        "category": "maintenance",
        "purpose": "Create guarded Kronos Path A launch config, smoke training plan, and optional training run.",
        "read_write_boundary": "Plan/config generation writes artifacts; explicit training flags can write model outputs only.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_kronos_path_a_launch",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_sentiment_cache_backfill",
        "category": "maintenance",
        "purpose": "Conservatively backfill M27.3 sentiment_cache entries.",
        "read_write_boundary": "Dry-run by default; real LLM/API calls and database writes require --execute with explicit --db-url.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_sentiment_cache_backfill",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_sentiment_cache_batch_runner",
        "category": "maintenance",
        "purpose": "Run resume-safe bounded batches around the M27.3 sentiment_cache backfill writer.",
        "read_write_boundary": "Dry-run by default; --execute delegates bounded writes to the sentiment cache backfill tool.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_sentiment_cache_batch_runner",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_sentiment_cache_plan",
        "category": "maintenance",
        "purpose": "Build a dry-run M27.3 sentiment_cache backfill plan from exported cache misses.",
        "read_write_boundary": "Reads exported misses and optionally a read-only cache recheck; writes only plan artifacts.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_sentiment_cache_plan --input <misses.json>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_price_coverage_refresh",
        "category": "maintenance",
        "purpose": "Refresh close-confirmed M29 price coverage for the test3 universe.",
        "read_write_boundary": "Narrow helper that writes prices rows for coverage preparation; does not promote alpha evidence.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_price_coverage_refresh",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m42_remediate_hfq_contamination",
        "category": "maintenance",
        "purpose": "Detect and remediate M42 hfq-contaminated price rows idempotently.",
        "read_write_boundary": "Dry-run/report modes are safe; explicit remediation writes repaired price rows and audit artifacts.",
        "recommended_entrypoint": "python3 -m backend.tools.m42_remediate_hfq_contamination --dry-run",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m58_remediate_adjustment_splice",
        "category": "maintenance",
        "purpose": "Detect (and, once confirmed safe, remediate) adjustment-basis-splice price rows idempotently.",
        "read_write_boundary": "Dry-run by default and always safe; --execute backs up the target SQLite file before deleting flagged rows.",
        "recommended_entrypoint": "python3 -m backend.tools.m58_remediate_adjustment_splice --db-url <sqlite-url>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m45_track_hook_update",
        "category": "maintenance",
        "purpose": "Adapt structured track-analyst hook updates into the M45 ForwardThesis import path.",
        "read_write_boundary": "Dry-run by default; --execute writes only ForwardThesis and L0 pending atoms via the M45 importer path.",
        "recommended_entrypoint": "python3 -m backend.tools.m45_track_hook_update --input <updates.json>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m45_falsification_scoreboard",
        "category": "maintenance",
        "purpose": "Record M45 falsification scoreboard events for review-loop state.",
        "read_write_boundary": "Dry-run by default; --execute writes ReviewCase rows and optional pending candidates only.",
        "recommended_entrypoint": "python3 -m backend.tools.m45_falsification_scoreboard --input <scoreboard.json>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m45_import_track_theses",
        "category": "maintenance",
        "purpose": "Import track-analyst-class thesis records into M45 shadow research state.",
        "read_write_boundary": "Dry-run by default; --execute writes ForwardThesis rows and L0 pending atoms only.",
        "recommended_entrypoint": "python3 -m backend.tools.m45_import_track_theses --input <theses.json>",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.atlas_test4_stage2b_shadow",
        "category": "evidence",
        "purpose": "Start the Atlas test4 Stage 2b forward shadow lane without promoting Atlas behavior.",
        "read_write_boundary": "Reads source DB/universe; writes only isolated Gate-B observation DB rows and optional evidence artifacts.",
        "recommended_entrypoint": "python3 -m backend.tools.atlas_test4_stage2b_shadow --print",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.atlas_stage2b_strict_gate",
        "category": "evidence",
        "purpose": "Run the one-command Atlas Stage 2b strict gate from shadow replay plus Gate-B realization/report evidence.",
        "read_write_boundary": "Reads source DB/universe; writes only isolated Gate-B DB rows and requested evidence artifacts, never production DB/test2/scheduler/config state.",
        "recommended_entrypoint": "python3 -m backend.tools.atlas_stage2b_strict_gate --print",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m26_kronos_eval",
        "category": "evidence",
        "purpose": "Evaluate Kronos model integration against MingCang data and validation windows.",
        "read_write_boundary": "Reads local data/model inputs and writes evaluation artifacts; does not alter production weights.",
        "recommended_entrypoint": "python3 -m backend.tools.m26_kronos_eval",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m26_quant_baseline",
        "category": "evidence",
        "purpose": "Build the M26 quant baseline validation report for the current LightGBM model.",
        "read_write_boundary": "Local read-only validation by default; writes JSON/Markdown report artifacts only.",
        "recommended_entrypoint": "python3 -m backend.tools.m26_quant_baseline",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m58_grid_backtest",
        "category": "evidence",
        "purpose": "M58 function-slot grid backtest (T/M families, weight lattice + rule forms, holdout locked).",
        "read_write_boundary": "Read-only against prices; writes JSON/Markdown report artifacts under /private/tmp only.",
        "recommended_entrypoint": "python3 -m backend.tools.m58_grid_backtest --grid",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m58_exit_sweep",
        "category": "evidence",
        "purpose": "M58 exit-parameter sweep (trailing ATR grid x floating take-profit variants, portfolio-level, plus test2 ledger replay comparison).",
        "read_write_boundary": "Read-only against prices and test2 ledger inputs; writes JSON/Markdown report artifacts under /private/tmp only.",
        "recommended_entrypoint": "python3 -m backend.tools.m58_exit_sweep --full-test2-grid",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m58_exit_shadow",
        "category": "evidence",
        "purpose": "M58 exit-parameter shadow arm for test2 v2 (owner option B, 2026-07-03): replays the v2 ledger window with the current exit rule (trailing x2.5/none) vs the holdout-winning shadow candidate (trailing x3.5/drawdown_10) via the same m58_exit_sweep simulate_exit, for 4-6 weeks without changing production.",
        "read_write_boundary": "Read-only against mingcang.db (mode=ro&immutable=1) and test2_universe.json; never opens test2_ab_state.json or any test2 ledger file for writing; writes only JSON/Markdown report artifacts and the append-only shadow-history JSONL under /private/tmp.",
        "recommended_entrypoint": "python3 -m backend.tools.m58_exit_shadow",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m58_lgbm_walkforward",
        "category": "evidence",
        "purpose": "M58 LGBM walk-forward closing test for the price-alpha quant family (rolling 250d train / 60d retrain).",
        "read_write_boundary": "Read-only against prices; trained models stay in memory only and are never written to a serving model path; writes JSON/Markdown report artifacts only.",
        "recommended_entrypoint": "python3 -m backend.tools.m58_lgbm_walkforward",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_alpha_diagnostic",
        "category": "evidence",
        "purpose": "Diagnose current alpha weakness before changing labels, factors, or production quant weight.",
        "read_write_boundary": "Reads features/signals/artifacts and writes diagnostic reports; does not promote model changes.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_alpha_diagnostic",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_kronos_preflight",
        "category": "evidence",
        "purpose": "Check reviewed M27.4 data and local environment readiness for separate Kronos fine-tuning.",
        "read_write_boundary": "Read-only preflight; emits report artifacts without training or promotion.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_kronos_preflight",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_label_objective_eval",
        "category": "evidence",
        "purpose": "Evaluate alpha label/objective alternatives before adding factors.",
        "read_write_boundary": "Local-only evaluation; writes report artifacts and never promotes a model.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_label_objective_eval",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_test3_production_profile_ab",
        "category": "evidence",
        "purpose": "Run offline test3 production-profile entry-filter A/B diagnostics.",
        "read_write_boundary": "Reads local artifacts/data and writes A/B reports; does not change production filters.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_test3_production_profile_ab",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_top_decile_filter_ab",
        "category": "evidence",
        "purpose": "Compare validation-window baseline candidates with a top-decile entry filter.",
        "read_write_boundary": "Read-only local diagnostic; writes JSON/Markdown reports only.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_top_decile_filter_ab",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m27_top_decile_forward_shadow",
        "category": "evidence",
        "purpose": "Run read-only forward shadow evidence for the top-decile entry filter.",
        "read_write_boundary": "Trains only on realized prior labels for shadow evidence; writes reports without promotion.",
        "recommended_entrypoint": "python3 -m backend.tools.m27_top_decile_forward_shadow",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_evidence_ledger",
        "category": "evidence",
        "purpose": "Build a read-only M29 alpha evidence ledger from local M27/M29 artifacts.",
        "read_write_boundary": "Artifact index only; reads existing reports and writes ledger artifacts, never promotes decisions.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_evidence_ledger",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_forward_readiness",
        "category": "evidence",
        "purpose": "Guard readiness for the next M29.3 forward-shadow run.",
        "read_write_boundary": "Read-only coverage check; writes readiness artifacts but does not run shadow validation.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_forward_readiness",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_hypothesis_registry",
        "category": "evidence",
        "purpose": "Pre-register M29 alpha hypotheses before running another experiment.",
        "read_write_boundary": "Writes only JSON/Markdown registry artifacts; never opens promotion or write paths.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_hypothesis_registry",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_provenance_audit",
        "category": "evidence",
        "purpose": "Audit M29 price and artifact provenance readiness.",
        "read_write_boundary": "Read-only audit; writes provenance report artifacts without side effects.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_provenance_audit",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_quant_residual_attribution",
        "category": "evidence",
        "purpose": "Audit residual quant contribution after technical and sentiment/event signals.",
        "read_write_boundary": "Read-only attribution audit; writes reports and does not alter quant weights.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_quant_residual_attribution",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m29_shadow_validation",
        "category": "evidence",
        "purpose": "Validate pre-registered M29 hypotheses against existing artifacts in shadow mode.",
        "read_write_boundary": "Reads existing artifacts and registry gates; writes validation reports only.",
        "recommended_entrypoint": "python3 -m backend.tools.m29_shadow_validation",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.m46_5_lookahead_one_time_audit",
        "category": "evidence",
        "purpose": "Run the M46.5 one-time lookahead audit behind the standing M47 productized check.",
        "read_write_boundary": "Read-only audit; emits pass/warn/fail evidence and does not wire into public CLI.",
        "recommended_entrypoint": "python3 -m backend.tools.m46_5_lookahead_one_time_audit",
        "still_runnable": True,
    },
    {
        "module": "backend.tools.attic.backfill_and_run",
        "category": "attic",
        "purpose": "Archived one-off script for batch backfilling stocks and running LongTermTeam analysis.",
        "read_write_boundary": "Archived and not recommended; historical script can backfill data and run long-term analysis if restored.",
        "recommended_entrypoint": "archived: move out of backend/tools/attic before any reuse",
        "still_runnable": False,
        "archived": True,
    },
    {
        "module": "backend.tools.attic.rerun_failed_6",
        "category": "attic",
        "purpose": "Archived one-off script for rerunning six quota-limited AI/semiconductor LongTermTeam analyses.",
        "read_write_boundary": "Archived and not recommended; historical script can rerun LongTermTeam analysis if restored.",
        "recommended_entrypoint": "archived: move out of backend/tools/attic before any reuse",
        "still_runnable": False,
        "archived": True,
    },
)


def list_tool_entries(category: str | None = None) -> list[dict[str, Any]]:
    """Return static tool registry entries, optionally filtered by category."""
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown tool category: {category}")
    entries = [dict(item) for item in _TOOL_REGISTRY]
    if category is None:
        return entries
    return [item for item in entries if item["category"] == category]


def build_tool_registry_payload(category: str | None = None) -> dict[str, Any]:
    """Return the M49 tools registry payload used by the agent CLI."""
    entries = list_tool_entries(category)
    counts = {name: 0 for name in CATEGORIES}
    for entry in entries:
        counts[entry["category"]] += 1
    return {
        "ok": True,
        "schema_version": "m49_tools_registry.v1",
        "category": category or "all",
        "categories": list(CATEGORIES),
        "counts": counts,
        "counts_by_category": counts,
        "total": len(entries),
        "tools": entries,
    }


def tools_registry_payload(category: str | None = None) -> dict[str, Any]:
    """Compatibility wrapper for the M49 CLI naming."""
    return build_tool_registry_payload(category)


def retained_tool_modules() -> set[str]:
    """Return retained backend.tools modules, excluding package initializers."""
    tools_dir = Path(__file__).resolve().parent
    modules = {
        f"backend.tools.{path.stem}"
        for path in tools_dir.glob("*.py")
        if path.name not in {"__init__.py", "registry.py"}
    }
    modules.update(
        f"backend.tools.attic.{path.stem}"
        for path in (tools_dir / "attic").glob("*.py")
        if path.name not in {"__init__.py", "registry.py"}
    )
    return modules


def missing_retained_tools() -> set[str]:
    """Return retained tool modules missing registry metadata."""
    registered = {entry["module"] for entry in _TOOL_REGISTRY}
    return retained_tool_modules() - registered
