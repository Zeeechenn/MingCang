# StockSage — Public Status Snapshot

> Public runtime and release snapshot. Detailed history lives in `CHANGELOG.md`; future work lives in `docs/ROADMAP.md`.

---

## 里程碑状态

| 里程碑 | 名称 | 状态 |
|---|---|---|
| M0 | 系统骨架 | ✅ 完成 |
| M1 | 严肃化与质量门槛 | ✅ 完成 |
| M2 | 本地验证材料 | 🏠 本地维护，不进入 GitHub |
| M3 | 可信度审计层 | ✅ 完成 |
| M4 | 多 Agent 决策深化 | 🟡 大部分完成，LangGraph / full FinMem 后置 |
| M5 | 自动化执行 | 🔲 后置 |
| M6 | 持续迭代与扩展 | ✅ M6.1 / M6.3 当前范围完成，Qlib 暂不恢复权重 |
| M7 | 工程化与开源就绪 | ✅ 完成 |
| M8 | 深度研究与来源审计层 | ✅ 完成，手动触发，不进入日常信号 |
| M9 | 记忆系统接入与治理 | ✅ 大部分完成 |
| M10 | 运行可靠性与产品化优化 | ✅ M10.0-M10.4 完成，M10.5 后置 |
| M11 | Agent-Ready 本地/远程双模式接口 | ✅ 初版完成，本地 agent 默认信任，远程模式显式启用 |
| M14 | 股票长期记忆与跨入口召回 | ✅ 初版完成，SQLite 结构化召回 |
| M26 | 量化层重估（扩盘+Kronos评估） | ✅ M26.0/M26.1/M26.2 完成；M26.3 暂停待 M27.1 |
| M27 | Alpha 根治工程 | ⏳ 工程接线完成；M27.1a 诊断指向 label/objective 重设计，继续保持 quant 关闭 |
| M28 | 调研模块整合与实时搜索接入 | ✅ 完成，deep_research / copilot / debate 信息流打通 |

---

## 信号权重（Decision Layer）

| Profile | quant | technical | sentiment | entry_threshold | 触发条件 |
|---|---|---|---|---|---|
| `test1_legacy_qlib` | 0.45 | 0.40 | 0.15 | 20 | 旧 Qlib 验证 profile |
| `new_framework` | 0.0 | 0.6 | 0.4 | 25 | 生产默认 |

综合评分范围：-100（规避）→ +100（可小仓试错）

日常/批量盘后信号默认不启用多 Agent，以控制 runtime LLM token 消耗；多 Agent 保留给显式单股研究、长期研究和实验复盘。

> Qlib 量化层已加入 point-in-time 基本面因子与可选 LambdaRank 训练入口；最近验证未通过 alpha 门槛，因此生产默认 quant 权重继续保持 0。

**M26 量化层重估（2026-05-30 完结）**
- M26.1 扩盘：707 支（HS300+CSI500），LightGBM 重训 IC=0.0208 / ICIR=0.187；仅通过 M26 诊断阈值（IC≥0.02 / ICIR≥0.15 / 不强制单调），未通过生产 promotion gate（ICIR≥0.30 且分位单调）
- M26.2 Kronos 零样本评估：IC=-0.0017，不及 LightGBM，不接生产；Kronos Path A 微调进入 M27.4 计划
- M26.3 暂停：两路均未带来足够 IC 改善，等 M27.1 因子工程使 IC ≥ 0.04 后重启
- 报告存档：`~/.stock-sage/m26_quant_baseline_report.{md,json}`、`~/.stock-sage/m26_kronos_report.{md,json}`
- 生产：继续 `weight_quant=0.0`，`kronos_enabled=false`

**M27 Alpha 根治工程（2026-05-30 启动）** ← 当前活跃里程碑
- M27.1（P1）：经典因子工程已接入；regression candidate IC=0.020217 / ICIR=0.176699 / monotonic=False，ranker candidate IC=0.029978 / ICIR=0.163796 / monotonic=False，均未过 `IC≥0.04 / ICIR≥0.40 / monotonic=True`
- M27.1a（P1）：alpha 诊断报告已写入 `~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`；active 94 支、107270 行、2019-01-25~2026-05-22，5d 最强单因子 `roe` 仅 IC=0.015642 / ICIR=0.114032 / monotonic=False，M27 最强 `sector_rel_strength_20_z` 仅 IC=0.012131 / ICIR=0.076884；结论为先重设计 label/objective，再继续堆因子
- M27.1b（P1）：label/objective 离线评估工具已改为真实 top 10% 训练/评估口径，并加入 FEATURE_COLS cache 失效保护；旧 20% 口径报告不再作为结论引用，需刷新 `~/.stock-sage/m27_label_objective_eval_report.{md,json}` 后再进入 M27.1c 离散入场过滤器验证；生产 quant 继续关闭
- M27.2（P1）：`paper_trading/test3_universe.json` 已生成 100 支，candidate_count=708，sector_count=64；signal runner 与 M26 baseline 支持显式 universe 参数，M26 默认仍保留 test2 基线口径
- M27.3（P2）：A 股事件分类与 `event_score` 已接入情感/信号合成；test3 IC A/B 仍待足量事件样本验证
- M27.4（P2）：Kronos Path A 数据准备、ListMLE loss、dry-run training plan、`m26_kronos_eval --model kronos-finetuned` 入口完成；真实微调未长跑
- 完整规划见 `docs/ROADMAP.md § M27`

**M28 调研模块整合（2026-05-30 完成）**
- `ResearchSection` 升级为 IC Memo schema，deep_research 报告持久化结构化 `sections`
- `run_deep_research` 支持 Tavily 纯内存 `web_search` 与 `seed_queries`，末轮搜索结果会重新审计后进入报告，不写 DB，不进入日常信号
- 多轮辩论可注入 research_context；盘后路径可从 `research_pointer.sections` 恢复 catalysts/risks/evidence；copilot `validation_questions` 进入 dossier `pending_questions`

公开默认 LLM runtime 为 `AI_PROVIDER=local_cli`，通过本机 Claude / Codex CLI 调用；`anthropic` / `openai` 只有在配置真实 key 时才可用，空 key 和 `your_*` 占位值视为未配置。`GET /api/system/health` 与 `GET /api/system/status` 会返回非敏感 runtime readiness。

当前数据覆盖请以 `PYTHONPATH=. python3 -m backend.tools.coverage_snapshot` 或 `GET /api/system/data-coverage` 为准。

单股研究入口：`POST /api/research/{symbol}/prepare` 尽力回填数据并返回 dossier；`GET /api/research/{symbol}/dossier` 读取信号、长期标签、copilot、记忆、专题调研索引和缺失项。

长期专家团入口：`POST /api/long-term/{symbol}/run` 同步运行单股专家团，`POST /api/long-term/run` 后台批量刷新自选股。长期标签包含 `quality` / `constraint_eligible` / `quality_notes`；当前 `LONG_TERM_CONSTRAINTS_ENABLED=false`，长期标签默认只展示/留痕、不改官方动作；验证通过后再开启可信标签约束。

专题研究入口：`POST /api/research/deep/run` 或
`PYTHONPATH=. python3 -m backend.research.deep_research --topic "AI算力产业链" --symbols 300308,300394`。
专题研究只在明确触发时运行，不创建 `Signal`，不参与日常复盘信号。

---

## 止盈止损公式

```
初始止损价 = 收盘价 - ATR(14) × 2.0
固定止盈参考价 = 收盘价 + (收盘价 - 初始止损价) × 2.0   # 1:2 风险收益比
移动止损价 = max(当前止损价, 持仓最高收盘价 - ATR(14) × 2.5)
```

默认启用移动止损保护浮盈；固定止盈价作为提醒/分批决策参考，不默认强制平仓。

---

## 调度时间表

| 时间 | 任务 | 说明 |
|------|------|------|
| 08:30 工作日 | 盘前同步 | 行情回填 + 个股新闻 + 沪深 300 指数 |
| 14:30 工作日 | 止损预警 | 检查买入信号止损线，触及则 Bark 推送 |
| 16:00 工作日 | 盘后信号 | 三路信号聚合 → 写 Signal 表 → Bark 推送 |
| 周六 09:00 | 模型重训 | LightGBM Alpha 模型周训练 |
| 周一 09:00 / 周五 15:00 | 长期团 | 长期分析师团 label 生成；日期与时间可在配置页调整 |
| 周日 11:00 | 长期反思 | `weekly_long_term_reflect` 写入分层长期记忆 |
| 每日 01:00 | 记忆维护 | 清理过期 `ai_memory` 并为股票判断补 outcome / lesson |

> 所有任务跑在 FastAPI 进程内（APScheduler），服务不运行则任务不触发。
> M3.4 kill switch 激活时，premarket / postmarket / stoploss_check 自动跳过。

---

## 验证摘要

历史 M1.3 公开摘要为 **N=2 单股回测逐股均值**，不是组合级权益曲线指标，也不再作为系统级验收结论单独引用。当前固化复现以 2026-05-27 重跑输出为准。

| 指标 | 当前固化复现 | 口径 |
|------|-------------|------|
| Sharpe | **2.50** | N=2 单股均值 |
| 最大回撤 | **15.69%** | N=2 单股均值 |
| 净盈亏比 | **3.13** | profit factor 均值 |

固定复现范围：`300308, 688008`，区间 `2025-11-01 ~ 2026-05-14`，命令：
`PYTHONPATH=. python3 backend/backtest/backtrader_eval.py --symbols 300308 688008 --start 2025-11-01 --end 2026-05-14 --legacy`。
当前回测脚本已显式建模 0.20% 往返手续费/印花税与每次成交 0.10% 滑点；最新数值以重跑输出为准。

---

## 测试套件

- M22 数据完整性修复后，持仓写入路径已锁定正数数量/成本/价格与 CN/US 市场枚举；重复平仓返回 409，不再覆盖首次 realized PnL。
- 非默认 SQLite 初始化默认跳过本机 `~/.stock-sage/memory` 迁移；确需导入时设置 `STOCKSAGE_MIGRATE_LOCAL_MEMORY=1`。
- `python3 -m pytest -q -p no:cacheprovider tests/test_llm_runtime_provider.py tests/test_long_term_team.py tests/integration/test_long_term_pipeline.py tests/test_stage_a_fixes.py tests/test_frontend_expansion_api.py tests/test_stock_memory.py` → **70 passed**（2026-05-27 public research readiness focused suite）。
- `python3 -m pytest -q -p no:cacheprovider tests/test_backfill_signals.py tests/test_compare_paths.py tests/test_sweep_threshold.py tests/test_exit_sweep.py` → **32 passed**（2026-05-27 backfill look-ahead guard）。
- `python3 -m pytest -q -p no:cacheprovider tests/test_qlib_ranker.py tests/test_m6_backtest_report.py tests/test_qlib_validation_panel.py` → **8 passed**（2026-05-27 Qlib promotion/offline gate）。
- `python3 -m pytest -q -p no:cacheprovider tests/test_cross_entry_contracts.py tests/test_agent_cli.py tests/test_agent_context.py tests/test_m10_quality_scheduler.py tests/test_m6_api.py` → **24 passed**（2026-05-27 cross-entry contract regression）。
- `PYTHONPATH=. python3 backend/backtest/alphalens_qlib.py --walk-forward --json-output /private/tmp/stocksage_qlib_offline_m25_5.json` → 通过；single split `IC=0.0372` / `ICIR=0.229` 且分层非单调，walk-forward `IC=-0.0058` / `ICIR=-0.025` 且分层非单调，继续保持 `weight_quant=0.0`。
- `PYTHONPATH=. .venv/bin/python -m backend.tools.m26_quant_baseline --start 2025-11-01 --end 2026-05-14 --every-n-days 5` → 通过；输出本地 M26 报告到 `~/.stock-sage/`，结论继续保持 `weight_quant=0.0`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m6_backtest_report.py tests/test_qlib_ranker.py tests/test_backfill_signals.py tests/test_m26_quant_baseline.py tests/test_stage_a_fixes.py tests/integration/test_long_term_pipeline.py tests/test_portfolio_eval.py tests/test_backtrader_eval.py` → **44 passed**（2026-05-30 M26 quant baseline / Kronos optional interface）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider tests/test_m27_alpha_diagnostic.py tests/test_qlib_ranker.py` → **10 passed**（2026-05-30 M27.1a alpha diagnostic）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m backend.tools.m27_alpha_diagnostic --active-only` → 通过；输出 `~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`，建议 `redesign_label_objective_before_more_feature_work`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_deep_research.py tests/test_m26_quant_boundary.py tests/test_m26_quant_baseline.py tests/test_qlib_feature_engineering.py tests/test_m27_alpha_event_universe.py tests/test_m27_m28_integration.py tests/test_m26_kronos_eval.py tests/test_qlib_ranker.py tests/test_qlib_validation_panel.py tests/test_m6_backtest_report.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_multi_round_debate.py tests/test_stock_memory.py tests/test_m27_kronos_finetune_data.py tests/test_stocksage_kronos_losses.py` → **102 passed, 2 skipped**（2026-05-30 M26/M27/M28 pre-commit repair suite）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m backend.tools.m27_label_objective_eval --active-only --horizon 20 --n-estimators 120` → **待刷新**；旧报告使用修复前 top-decile 口径，不再作为当前结论引用。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.analysis.qlib_engine --validate-production --json-output /private/tmp/stocksage_m26_prod_validation.json` → 通过；`status=ok`，legacy production feature cols 25 维验证，current candidate 29 维，production gate 未过，继续 `keep_quant_disabled`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider` → **546 passed, 2 skipped**（2026-05-30 M26/M27/M28 repair full suite）。
- `python3 -m compileall backend tests` → 通过
- `cd frontend && node --test src/*.test.js src/components/*.test.js src/pages/*.test.js` → **19 passed**（2026-05-27 StockDetail progressive loading）
- `cd frontend && npm run build` → 通过（62 modules，约 470 KB / gzip 146 KB）

## 环境准备

```bash
cp .env.example .env                   # 默认 AI_PROVIDER=local_cli；云 provider 才填对应 API key
pip install ".[dev]"                   # 含 dev/test/agent 工具链
pip install -e ".[agent]"              # 可选：只安装本地 MCP agent 工具桥
python3 backend/data/database.py       # 初始化 DB
cd frontend && npm install
```

### 启动

```bash
PYTHONPATH=. uvicorn backend.main:app --reload   # 后端（根目录执行）
cd frontend && npm run dev                        # 前端（另开终端）
```

### 常用命令

```bash
PYTHONPATH=. python3 -m backend.analysis.qlib_engine --train
PYTHONPATH=. python3 -m backend.analysis.qlib_engine --train --ranker
PYTHONPATH=. python3 -m backend.backtest.walk_forward --start 2024-01-01 --end 2026-05-15
PYTHONPATH=. python3 -m backend.agent.mcp_server
curl http://localhost:8000/api/system/health
curl -X POST "http://localhost:8000/api/research/300308/prepare?name=中际旭创&market=CN"
curl -X POST http://localhost:8000/api/long-term/300308/run
curl -X POST http://localhost:8000/api/system/kill-switch/reset
curl http://localhost:8000/api/signals/eval/600519?days=60
```

## Agent-Ready Snapshot

- 本地 Codex / Claude Code 使用 StockSage 时默认信任，可直接跑测试、查 DB、运行验证和项目研究流程。
- 远程 agent 暴露必须显式设置 `STOCKSAGE_AGENT_MODE=remote`，并配置 `STOCKSAGE_AGENT_API_KEY`；stdio MCP 工具调用需传入 `api_key` 参数，远程写操作默认关闭。
- 项目记忆入口在 `backend/agent/context.py`，MCP 启动入口为 `PYTHONPATH=. python3 -m backend.agent.mcp_server`；未初始化数据库时 health/context 返回空状态，不抛出缺表错误。
- 盘后批处理已接入 Portfolio Manager：单股信号先生成，再统一做组合层裁剪；最终仓位写入 `position_pct`，原始单股仓位保留在 `trader_position_pct`，裁剪原因进入 `portfolio_decision` / evidence。
- Chat action 已统一走 Action Registry；远程 HTTP 写操作复用 agent guard，支持 API key、写开关和 action allowlist。
- Runtime LLM/API key 边界见 README 的 "注意事项" 与 `AGENTS.md`；公开默认 local CLI，云服务额度仍以各平台控制台为准。
