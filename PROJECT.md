# MingCang — Architecture and Navigation

用户掌控的研究决策台：数据/证据 → 研究 → 决策/风险 → 组合/复盘，由稳定 workflow 和
RunEnvelope 连接到唯一日常面板。Research Lab 单独过晋升门；Archive 只作历史查询。
规则 AGENTS；当前运行 STATUS；唯一计划 ROADMAP；实现合同 Developer Guide；历史 CHANGELOG。
本页是路径/所有权地图，代码存在和分组名称不证明运行活跃。

| Authority | Owner |
|---|---|
| `AGENTS.md` / local CLAUDE/Pi wrappers | 共享行为规则；wrapper 只路由 |
| `STATUS.md` | 当前有日期的状态与证据限制 |
| `docs/ROADMAP.md` | 下一步、依赖、开工/验收/晋升门 |
| `docs_public/` | 公开唯一文档源；README 中英只导航 |
| `docs_public/DEVELOPER_GUIDE.md` | 实现与验证合同 |
| `docs/data-sources/`, `docs/evidence/` | 活来源手册、证据摘要/归档 hash 索引 |
| `docs/dev/` allowlist | 尚被代码/测试引用的维护契约，按需读 |
| `CHANGELOG.md` | 已完成/发布历史；非默认上下文 |

研究/复盘/日志/历史规划原文存仓库外，不能靠 gitignore 当作归档。
`docs/ARCHITECTURE.md` / `docs/WHY_NOT_AI_STOCK_PICKER.md` 是一个发布周期的兼容 stub。
`docs/ATLAS_MERGE.md` 只保留 dormant 边界；详版见历史与外部档案。

## Repository Map

Use this as a navigation map, not a full file inventory. For symbol-level
questions, use CodeGraph first; for literal strings, use `rg`.

| Area | Path | Notes |
|---|---|---|
| Runtime config | `backend/config.py` | env vars, paths, scheduling, profile knobs |
| Database/runtime schema | `backend/data/database.py`, `backend/data/schema_runtime.py`, `backend/data/seed.py` | ORM/session/init compatibility, runtime patches, memory seeds |
| Market data | `backend/data/market*.py`, `backend/data/providers.py`, `backend/data/flow_floor.py`, `backend/data/tavily_news.py` | A/HK/US read-only facades, provider fallback, flow/news acquisition, M41 envelopes, M42 write guard |
| News pyramid mirror | `backend/data/news_shadow.py`, `backend/data/models/news_shadow.py`, `backend/api/routes/news_shadow.py`, `backend/tools/m68_news_shadow.py`, `backend/tools/m68_test2_compare.py`, `frontend/src/services/news-shadow.ts`, `frontend/src/page-news-shadow.tsx` | M68 production-shaped observe-only dual run, event-risk review queue, independent test2-v2 C comparison, counterfactual API/UI and evidence-bound feedback; never writes official signals or original A/B state |
| Decision layer | `backend/decision/` | aggregation, harness, signal policy, decision memory |
| Research and memory | `backend/research/`, `backend/memory/`, `backend/agents/` | dossier/deep research, outcome-backed calibration (`experience.py`), reversible health/compaction (`maintenance.py`), layered memory, multi-agent pipelines |
| Portfolio and risk | `backend/portfolio/`, `backend/ops/kill_switch.py` | sizing, trailing stops, kill switch, exit-shadow adjudication and panel-domain compatibility |
| API routes | `backend/api/routes/`, `backend/api/schemas.py`, `backend/main.py` | FastAPI app and REST surfaces, including the read-only daily panel API |
| Scheduler and workflows | `backend/scheduler.py`, `backend/jobs/`, `backend/workflows/`, `backend/ops/run_envelope.py`, `backend/ops/job_ledger.py` | scheduled/manual jobs plus stable orchestration facades and the explicit completed-run contract; API/jobs depend on workflows, not tool implementations |
| Agent bridge | `backend/agent/` | local CLI, action registry, MCP/tool context |
| Analysis, backtests and evidence | `backend/analysis/`, `backend/backtest/`, `backend/evidence/`, `backend/ops/one_loop_continuity.py` | quant/statistics, PIT replay, independent cash NAV with explicit execution/action boundaries, run cards, committed daily-panel artifacts and immutable continuity audit |
| Tools registry | `backend/tools/registry.py`, `backend/tools/`, `python3 -m backend.agent.cli tools` | CLI, maintenance, experiment and compatibility adapters, including manual-only P0-R evidence and price-rebase planning; stable business modules must not depend on tool implementations |
| M31/M41/M42/M45 tools | `backend/tools/m31_*`, `backend/tools/m41_*`, `backend/tools/m42_*`, `backend/tools/m45_*` | cache benchmark, probe health, qfq/hfq remediation, source-gated import/scoreboard |
| Frontend | `frontend/src/main.tsx`, `frontend/src/page-*.tsx`, `frontend/src/features/`, `frontend/src/services/` | hash-routed pages, feature-owned Daily/Debate views and canonical API/live service boundaries; pages must not import other page implementations |
| Public docs | `README.md`, `README_EN.md`, `docs_public/`, `mkdocs.yml` | GitHub entrypoints and the canonical public documentation site; checked by `make doc-check` |
| Internal evidence docs | `docs/data-sources/`, `docs/evidence/`, `docs/dev/` allowlist | live data/source contracts, reproducibility evidence, and minimal active maintainer contracts |

### Canonical / compatibility map

New code imports the canonical path. Compatibility paths remain available for at least one release cycle and may still
be used by CLI commands or external callers.

| Capability | Canonical path | Compatibility path |
|---|---|---|
| flow data floor | `backend.data.flow_floor` | `backend.tools.m52_flow_floor` |
| lookahead audit | `backend.evidence.lookahead_audit` | `backend.tools.m46_5_lookahead_one_time_audit` |
| quant baseline | `backend.backtest.quant_baseline` | `backend.tools.m26_quant_baseline` |
| cross-sectional IC | `backend.backtest.statistics.cross_sectional` | exports retained by `backend.tools.m27_alpha_diagnostic` |
| M63 orchestration | `backend.workflows.m63_daily` | `backend.tools.m63_daily` |
| M63 report rendering | `backend.workflows.render` | `backend.tools.m63_render` |
| frontend API/live | `frontend/src/services/api.ts`, `frontend/src/services/live.ts` | `frontend/src/api.ts`, `frontend/src/live.ts` |
| M68 news mirror | `backend.data.news_shadow` | `backend.tools.m68_news_shadow` (CLI) |
| test2-compatible replay | `backend.backtest.test2_replay`, `backend.backtest.test2_models` | `backend.tools.m68_test2_compare` (derived A/B/C evaluator) |
| completed-run contract | `backend.ops.run_envelope`, `backend.ops.job_ledger` | scheduler/manual/test2 entrypoint adapters |
| human research choices | `backend.research.daily_review`, `backend.api.routes.daily`, `frontend/src/features/daily/HumanReview.tsx` | existing `pending_ai_actions`; non-executable reviewed records only |
| daily panel evidence | `backend.evidence.daily_panel`, `backend.evidence.daily_panel_sources`, `backend.api.routes.daily`, `frontend/src/features/daily/` | `backend.portfolio.daily_panel` compatibility facade |
| continuity acceptance | `backend.ops.one_loop_continuity`, `scripts/audit_one_loop_continuity.py` | none; explicit immutable DB path is required |
| independent cash NAV evidence | `backend.backtest.nav_replay` | `backend.tools.p0r_nav_replay` manual-only snapshot CLI; no scheduler or production-ledger consumer |
| price-history rebase/write safety | none; maintenance-only | `backend.tools.rebase_price_history` dry-run plus opt-in strict write guard; routine callers keep the guard disabled until separately activated |

## 研究模块地图

精确消费者和调用关系容易随代码变化，不在本文件维护逐文件长表；架构任务应先查
CodeGraph，再以 `rg`/AST 和 registry 复核。稳定分组如下：

| 分组 | Canonical paths | 用途与边界（不宣称实时活跃） |
|---|---|---|
| 深研入口 | `backend/research/deep_research.py`, `dossier.py`, `copilot.py` | 日常入口；日常经 `backend.tools.m63_research` 路由 |
| 论点与证据门 | `case.py`, `thesis_ledger.py`, `review_loop.py`, `daily_review.py`, `research_report_gate.py` | gate-guarded；主观清单不直接改短线分数 |
| 前瞻观察 | `forward_thesis.py`, `watchlist.py`, `watchtower_confirm.py` | 受证据门约束；事件和确认结果只进入受控证据路径 |
| 主题与压力测试 | `theme_hypothesis_engine.py`, `stress_test.py`, `universe_guard.py` | gate-guarded；必须保留 PIT/universe provenance |
| dormant 模板 | `ai_supply_chain_template.py`, `serenity_chokepoint.py` | dormant 或 type-only；新功能不得依赖 |
| 多智能体决策 | `backend/agents/` | 日常入口；由 pipeline 编排，RiskManager 保持最终机械风险边界 |

新增、移除或晋升研究模块时，更新本分组、`backend.tools.registry`、对应测试和
`CHANGELOG.md`；不要恢复动态消费者清单作为长期手工维护负担。

## Post-loop ownership

| Capability | Owner / canonical entry | Consumer and boundary |
|---|---|---|
| Daily source binding | evidence, `daily_panel_sources` | existing JobRun/finalizer/panel; new-date contract only |
| Human choices | research, `daily_review` | daily-page research section via `/api/daily/reviews` and outcomes route; existing PendingAIAction, `daily.research_review`, reviewed/non-executable; no new table |
| Four gates/window/memory filter | evidence, `decision_desk_readiness` | explicit `run_decision_desk_checks.py` and module window CLI; no scheduler/default memory consumer |
| Model observation/session | evidence, `decision_desk_recording`, `decision_desk_session`, `decision_desk_manifest` | injected provider and explicit offline freeze/reservation/folds/holdout; no second trading ledger or production activation |
| Bounded diagnostic process | evidence, `decision_desk_process` | only explicit `run_decision_desk_model_smoke.py`; local byte/time/filesystem bounds, not billing/remote cancellation guarantees |
| Warmup/write safety | data, `market_persistence.backfill_if_needed` | opt-in `factor_warmup_rows`, strict provenance and preceding rows; routine caller defaults preserved |

Human opinions/outcomes preserve panel bytes and are separate from queue completion,
positions and memory promotion. Remote writes retain the agent guard. Removing the
page/API entry stops new writes while keeping records. These boundaries do not certify
future quality, full isolation, correct data or returns; exact acceptance is in ROADMAP.
