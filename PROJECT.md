# MingCang — Project Index

个人 A 股研究循环工作台。核心目标不是造一个更聪明的 AI，而是建立一个可审计的判断循环：进口假设 → 证伪 → 归因 → 记忆更新。

Alpha 来自人的判断；AI 负责广度扫描、证伪和短期风险纪律；最终决策始终由用户负责。

**核心约束**：止盈止损由 ATR 公式计算；默认用 ATR 2.5 移动止损保护浮盈；LLM 不做价格预测，不做自动交易；记忆促进需要 outcome 结果和人工确认。

---

## 快速导航

| 文件 | 何时读取 |
|------|------|
| [AGENTS.md](AGENTS.md) | 默认 agent 规则、任务路由和安全边界 |
| [STATUS.md](STATUS.md) | 当前状态、生产权重、验证快照和下一步入口 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 当前/未来工作，使用 M-numbered 结构 |
| [CHANGELOG.md](CHANGELOG.md) | 版本、历史变更、历史验证记录；不要默认读取 |
| [README.md](README.md) | GitHub 门面、安装、配置和公开说明 |
| [docs/ATLAS_MERGE.md](docs/ATLAS_MERGE.md) | Atlas dormant merge 的详细核验记录 |
| [docs/dev/](docs/dev/) | 历史实验、旧计划、维护者参考；按名称需要时再读 |

---

## Agent-Ready Boundary

MingCang can be used as regular software and as an agent-ready codebase. Public
agent instructions belong in `AGENTS.md`; private local notes, generated
reports, runtime databases and personal trading records stay outside Git
tracking.

---

## 里程碑总览

不在本文件维护里程碑状态：活跃线与排序见 `docs/ROADMAP.md`，已完成历史见
`CHANGELOG.md`，生产权重/当前结论见 `STATUS.md`。

---

## Repository Map

Use this as a navigation map, not a full file inventory. For symbol-level
questions, use CodeGraph first; for literal strings, use `rg`.

| Area | Path | Notes |
|---|---|---|
| Runtime config | `backend/config.py` | env vars, paths, scheduling, profile knobs |
| Database/runtime schema | `backend/data/database.py`, `backend/data/schema_runtime.py`, `backend/data/seed.py` | ORM/session/init compatibility, runtime patches, memory seeds |
| Market data | `backend/data/market*.py`, `backend/data/providers.py`, `backend/data/flow_floor.py`, `backend/data/tavily_news.py` | A/HK/US read-only facades, provider fallback, flow/news acquisition, M41 envelopes, M42 write guard |
| News pyramid mirror | `backend/data/news_shadow.py`, `backend/data/models/news_shadow.py`, `backend/api/routes/news_shadow.py`, `backend/tools/m68_news_shadow.py`, `frontend/src/services/news-shadow.ts`, `frontend/src/page-news-shadow.tsx` | M68 production-shaped observe-only dual run, event-risk review queue, counterfactual API/UI and evidence-bound feedback; never writes official signals |
| Decision layer | `backend/decision/` | aggregation, harness, signal policy, decision memory |
| Research and memory | `backend/research/`, `backend/memory/`, `backend/agents/` | dossier/deep research, layered memory, multi-agent pipelines |
| Portfolio and risk | `backend/portfolio/`, `backend/ops/kill_switch.py` | sizing, trailing stops, kill switch |
| API routes | `backend/api/routes/`, `backend/api/schemas.py`, `backend/main.py` | FastAPI app and REST surfaces |
| Scheduler and workflows | `backend/scheduler.py`, `backend/jobs/`, `backend/workflows/` | scheduled jobs plus stable orchestration facades; API/jobs depend on workflows, not tool implementations |
| Agent bridge | `backend/agent/` | local CLI, action registry, MCP/tool context |
| Analysis and backtests | `backend/analysis/`, `backend/backtest/`, `backend/evidence/` | quant engine, statistics, backtests and audit/evidence contracts |
| Tools registry | `backend/tools/registry.py`, `backend/tools/`, `python3 -m backend.agent.cli tools` | CLI, maintenance, experiment and compatibility adapters; stable business modules must not depend on tool implementations |
| M31/M41/M42/M45 tools | `backend/tools/m31_*`, `backend/tools/m41_*`, `backend/tools/m42_*`, `backend/tools/m45_*` | cache benchmark, probe health, qfq/hfq remediation, source-gated import/scoreboard |
| Frontend | `frontend/src/main.tsx`, `frontend/src/page-*.tsx`, `frontend/src/services/` | hash-routed pages plus canonical API/live service boundary; feature grouping remains incremental M66 work |
| Public docs | `README.md`, `docs/WHY_NOT_AI_STOCK_PICKER.md`, `docs/assets/` | GitHub-facing product explanation and visuals |

### M66 canonical / compatibility map

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

## 研究模块地图

消费者来自 `rg`/AST import 查证；`dormant` 模块按 M57 记忆基础设施保留，勿在新功能中引用。

| 文件 | 代际 | 状态 | 消费者 | 一句话职责 |
|---|---|---|---|---|
| `backend/research/__init__.py` | M63 现役 | active | package import/export `DeepResearchReport`/`run_deep_research` | 研究包门面，透出手动深研入口。 |
| `backend/research/agents.py` | M63 现役 | active | `backend/research/deep_research.py` | 为手动深研生成确定性角色段落。 |
| `backend/research/ai_supply_chain_template.py` | ATLAS-dormant | dormant | `backend/api/routes/research.py`, `backend/research/theme_hypothesis_engine.py` | Atlas AI 供应链主题模板归 M57 记忆基础设施保留，勿在新功能中引用。 |
| `backend/research/case.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py`, `backend/research/dossier.py`, `backend/research/gate_b_recorder.py` | 把 dossier 派生成 ResearchCase、quality gate 和 validity card。 |
| `backend/research/case_view.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py` | 聚合 thesis/review/forward/theme 记录供 Case View 读取。 |
| `backend/research/copilot.py` | M63 现役 | active | `backend/api/routes/research.py`, `backend/tools/m63_research.py` | 生成单股研究副驾驶影子结论。 |
| `backend/research/deep_research.py` | M63 现役 | active | `backend/api/routes/research.py`, `backend/research/research_report_gate.py`, `backend/tools/m63_research.py` | 执行手动周末/主题深研并在写入前过报告门。日常入口经 `m63_research` 路由；模块直调属高级用法（R2 收敛）。 |
| `backend/research/dossier.py` | M63 现役 | active | `backend/api/routes/research.py` | 汇总单股研究 dossier 供 API 和 M63 研究上下文使用。 |
| `backend/research/forward_thesis.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py`, `backend/research/watchlist.py`, `backend/tools/m45_import_track_theses.py`, `backend/tools/m60_thesis_sync.py`, `backend/tools/m60_watchtower.py` | 存储前瞻 thesis、置信区间和证据清单。 |
| `backend/research/gate_b_recorder.py` | ATLAS-dormant | gate-guarded | `backend/tools/atlas_stage2b_strict_gate.py`, `backend/tools/atlas_test4_stage2b_shadow.py`, `backend/tools/gate_b_tracker.py` | Atlas Gate-B 前瞻观察记录和报告工具层。 |
| `backend/research/research_evidence_defs.py` | M39-M55 论点与门 | gate-guarded | `backend/research/ai_supply_chain_template.py`, `backend/research/research_report_gate.py`, `backend/tools/m45_*.py`, `backend/workflows/render.py` | 定义研究证据等级、禁用表述和报告扫描函数。 |
| `backend/research/research_report_gate.py` | M39-M55 论点与门 | gate-guarded | `backend/research/deep_research.py` | 在深研报告落盘前执行 M50 报告门。 |
| `backend/research/review_loop.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py`, `backend/research/case_view.py`, `backend/tools/m45_falsification_scoreboard.py` | 维护 review case、memory candidate 和独立复核结构门。 |
| `backend/research/serenity_chokepoint.py` | ATLAS-dormant | dormant | `backend/research/research_report_gate.py(type-only)` | Serenity 方法论形状归 M57 记忆基础设施保留，勿在新功能中引用。 |
| `backend/research/stress_test.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py` | 对 ResearchCase 做一次 evidence-bounded red-team stress test。 |
| `backend/research/theme_hypothesis_engine.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py`, `backend/research/case_view.py` | 存储主题和 hypothesis，并挂接前向证据。 |
| `backend/research/thesis_ledger.py` | M39-M55 论点与门 | gate-guarded | `backend/api/routes/research.py`, `backend/research/case_view.py` | 存储 thesis、状态流转、confidence 历史和 review 关联。 |
| `backend/research/universe_guard.py` | ATLAS-dormant | gate-guarded | `backend/api/routes/research.py` | 维护回测/前向验证用 universe snapshot 和 provenance 报告。 |
| `backend/research/watchlist.py` | M63 现役 | active | `backend/research/watchtower_confirm.py`, `backend/tools/m60_thesis_sync.py`, `backend/tools/m60_watchtower.py`, `backend/tools/m63_opinion.py`, `backend/tools/m63_research.py`, `backend/tools/m63_weekly.py` | 读取和校验观察哨主题，并用 ForwardThesis 作为 thesis 权威来源。 |
| `backend/research/watchtower_confirm.py` | M63 现役 | active | `backend/tools/m60_watchtower.py` | 对观察哨触发符号生成 LLM 确认卡。 |
| `backend/agents/director.py` | M63 现役 | active | `backend/agents/pipeline.py`, `backend/decision/aggregator.py` | 评估分析师报告质量并提出辩论议题。 |
| `backend/agents/trader.py` | M63 现役 | active | `backend/agents/pipeline.py`, `backend/agents/risk_manager.py` | 合成分析师和研究员结论，给出建议、仓位、止盈止损。 |
| `backend/agents/portfolio_manager.py` | M63 现役 | active | `backend/agents/__init__.py`, `backend/jobs/postmarket.py` | 盘后对候选信号做组合层仓位裁剪。 |
| `backend/agents/researcher.py` | M63 现役 | active | `backend/agents/pipeline.py`, `backend/agents/trader.py`, `backend/decision/aggregator.py` | 在分歧时执行多空辩论或快速共识。 |
| `backend/agents/analyst.py` | M63 现役 | active | `backend/agents/director.py`, `backend/agents/pipeline.py`, `backend/agents/researcher.py`, `backend/agents/trader.py`, `backend/decision/aggregator.py` | 将技术、量化、情绪、新闻结果包装为结构化 AnalystReport。 |
| `backend/agents/pipeline.py` | M63 现役 | active | `backend/agents/__init__.py`, `backend/decision/aggregator.py` | 编排 Analysts → Director → Researcher → Trader → RiskManager 决策流。 |
| `backend/agents/risk_manager.py` | M63 现役 | active | `backend/agents/pipeline.py` | 对 trader 提案执行风控否决、降级和执行约束提示。 |
