# MingCang — Project Index

个人 A 股研究循环工作台。核心目标不是造一个更聪明的 AI，而是建立一个可审计的判断循环：进口假设 → 证伪 → 归因 → 记忆更新。

Alpha 来自人的判断；AI 负责广度扫描、证伪和短期风险纪律；最终决策始终由用户负责。

**核心约束**：止盈止损由 ATR 公式计算；默认用 ATR 2.5 移动止损保护浮盈；LLM 不做价格预测，不做自动交易；记忆促进需要 outcome 结果和人工确认，且当前 `MEMORY_DECISION_CONTEXT_ENABLED=false`，只记录、显式查询和影子回测。

---

## 快速导航

| 文件 | 何时读取 |
|------|------|
| [AGENTS.md](AGENTS.md) | 默认 agent 规则、任务路由和安全边界 |
| [STATUS.md](STATUS.md) | 当前状态、生产权重、验证快照和下一步入口 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 唯一活跃的 MingCang One Loop 治理与执行计划 |
| [CHANGELOG.md](CHANGELOG.md) | 版本、历史变更、历史验证记录；不要默认读取 |
| [README.md](README.md) | GitHub 门面、安装、配置和公开说明 |
| [docs/ATLAS_MERGE.md](docs/ATLAS_MERGE.md) | Atlas dormant merge 的详细核验记录 |
| [docs/dev/](docs/dev/) | 尚未归口到代码/测试的活维护契约；关闭计划将迁出仓库 |

---

## Agent-Ready Boundary

MingCang can be used as regular software and as an agent-ready codebase. Public
agent instructions belong in `AGENTS.md`; private local notes, generated
reports, runtime databases and personal trading records stay outside Git
tracking.

---

## 项目级计划

当前唯一活跃计划是 **MingCang One Loop**。执行顺序、阶段门、六个外部项目的处理决定、
能力生命周期与文档治理见 `docs/ROADMAP.md`；已完成历史见 `CHANGELOG.md`；生产权重、
运行新鲜度和当前结论见 `STATUS.md`。

旧 M 编号只作为历史、证据标签和兼容入口，不再组织新模块、新工作线或产品概念。

## One Loop Operating Model

MingCang uses one modular-monolith production core, one daily orchestration
surface, one operator-facing daily panel, and an isolated research lab:

```text
data/evidence → research → decision/risk → portfolio/review
       │              one complete RunEnvelope              │
       └────────────── daily orchestration ──────────────────┘
                              │
                    authoritative daily panel

research lab ── explicit promotion gate ──▶ production core
archive ── no imports / no default context ──▶ history only
```

Capabilities use the lifecycle states `proposed`, `experimental`, `shadow`,
`stable`, `dormant`, `rejected`, and `archived`. A module is not active merely
because code exists; active use requires a canonical owner, real consumer,
tracked run, fresh output, evidence status, and rollback path.

## Documentation Authority

| Truth | Authority |
|---|---|
| agent rules, safety, governance | `AGENTS.md` |
| architecture, ownership, canonical paths | `PROJECT.md` |
| current runtime and production truth | `STATUS.md` |
| active ordering, gates, blockers | `docs/ROADMAP.md` |
| completed releases and historical verification | `CHANGELOG.md` |
| public documentation site | `docs_public/` |
| data-source live manuals | `docs/data-sources/` |
| reproducibility evidence | `docs/evidence/` |
| active maintainer contracts not yet encoded in code/tests | `docs/dev/` allowlist only |

The same topic must not have independent authority in both `docs/` and
`docs_public/`. Local research, reviews, logs, generated reports, and historical
planning archives stay outside the repository directory.

Current public docs authority lives in `docs_public/`; `docs/ARCHITECTURE.md`
and `docs/WHY_NOT_AI_STOCK_PICKER.md` are one-release compatibility stubs only.
Historical `docs/research/`, `docs/reviews/`, and closed `docs/dev/` plans are
kept in the external One Loop governance archive, not in the repo.

---

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
| daily panel evidence | `backend.evidence.daily_panel`, `backend.api.routes.daily`, `frontend/src/features/daily/` | `backend.portfolio.daily_panel` compatibility facade |
| continuity acceptance | `backend.ops.one_loop_continuity`, `scripts/audit_one_loop_continuity.py` | none; explicit immutable DB path is required |
| independent cash NAV evidence | `backend.backtest.nav_replay` | `backend.tools.p0r_nav_replay` manual-only snapshot CLI; no scheduler or production-ledger consumer |
| price-history rebase/write safety | none; maintenance-only | `backend.tools.rebase_price_history` dry-run plus opt-in strict write guard; routine callers keep the guard disabled until separately activated |

## 研究模块地图

精确消费者和调用关系容易随代码变化，不在本文件维护逐文件长表；架构任务应先查
CodeGraph，再以 `rg`/AST 和 registry 复核。稳定分组如下：

| 分组 | Canonical paths | 状态与边界 |
|---|---|---|
| 深研入口 | `backend/research/deep_research.py`, `dossier.py`, `copilot.py` | active；日常经 `backend.tools.m63_research` 路由 |
| 论点与证据门 | `case.py`, `thesis_ledger.py`, `review_loop.py`, `research_report_gate.py` | gate-guarded；主观清单不直接改短线分数 |
| 前瞻观察 | `forward_thesis.py`, `watchlist.py`, `watchtower_confirm.py` | active/gate-guarded；事件和确认结果只进入受控证据路径 |
| 主题与压力测试 | `theme_hypothesis_engine.py`, `stress_test.py`, `universe_guard.py` | gate-guarded；必须保留 PIT/universe provenance |
| dormant 模板 | `ai_supply_chain_template.py`, `serenity_chokepoint.py` | dormant 或 type-only；新功能不得依赖 |
| 多智能体决策 | `backend/agents/` | active；由 pipeline 编排，RiskManager 保持最终机械风险边界 |

新增、移除或晋升研究模块时，更新本分组、`backend.tools.registry`、对应测试和
`CHANGELOG.md`；不要恢复动态消费者清单作为长期手工维护负担。
