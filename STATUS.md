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
| M26 | 量化层重估（扩盘+Kronos评估） | ✅ M26.0/M26.1/M26.2 完成；M26.3 暂停待 M27 alpha 目标达标 |
| M27 | Alpha 根治工程 | ⏳ M27.1b/M27.1c/M27.3/M27.4 离线证据继续推进；仍未过 promotion gate，继续保持 quant 关闭 |
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
- M26.1 扩盘：707 支（HS300+CSI500），LightGBM 重训 IC=0.0208 / ICIR=0.187；仅通过 M26 诊断阈值（IC≥0.02 / ICIR≥0.15 / 不强制单调），未通过生产 promotion gate（IC≥0.04 / ICIR≥0.40 / monotonic=True）
- M26.2 Kronos 零样本评估：IC=-0.0017，不及 LightGBM，不接生产；Kronos Path A 微调进入 M27.4 计划
- M26.3 暂停：两路均未带来足够 IC 改善，等 M27 alpha 目标（IC ≥ 0.04 / ICIR ≥ 0.40 / monotonic=True）达标后重启
- 报告存档：M26 baseline / 扩盘诊断写入 `~/.stock-sage/m26_quant_baseline_report.{md,json}`，Kronos 零样本写入 `~/.stock-sage/m26_kronos_report.{md,json}`；历史 M26.0 小权重建议不再作为当前结论引用
- 生产：继续 `weight_quant=0.0`，`kronos_enabled=false`

**M27 Alpha 根治工程（2026-05-30 启动）** ← 当前活跃里程碑
- M27.1（P1）：经典因子工程已接入；regression candidate IC=0.020217 / ICIR=0.176699 / monotonic=False，ranker candidate IC=0.029978 / ICIR=0.163796 / monotonic=False，均未达 M27 alpha 目标 / 生产 promotion 配置（`backend/config.py` 默认 IC≥0.04 / ICIR≥0.40 / monotonic=True）
- M27.1a（P1）：alpha 诊断报告已写入 `~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`；active 94 支、107270 行、2019-01-25~2026-05-22，5d 最强单因子 `roe` 仅 IC=0.015642 / ICIR=0.114032 / monotonic=False，M27 最强 `sector_rel_strength_20_z` 仅 IC=0.012131 / ICIR=0.076884；结论为先重设计 label/objective，再继续堆因子
- M27.1b（P1）：label/objective 离线评估已刷新到 `~/.stock-sage/m27_label_objective_eval_report.{md,json}`；best=`raw_20d_top_decile_classifier`，raw IC=0.108904 / ICIR=0.393701 / monotonic=True，stride ICIR=0.299587，top-decile lift=2.674922；因 raw gate 未过（ICIR 略低于 0.40，且 stride 更弱），结论仍为 `keep_quant_disabled`；sector-specific offline candidate 已接入且 non-promoting，半导体样本达标但 raw IC=0.112838 / ICIR=0.218514 / stride ICIR=0.279028、gate=False；`--segment-min-symbols 3` exploratory 报告写入 `~/.stock-sage/m27_label_objective_eval_exploratory_report.{md,json}`，通信设备仅 3 支样本且 raw IC=-0.125885 / ICIR=-0.178232、gate=False，不可晋升
- M27.1c（P1）：top-decile classifier 离散过滤器 offline candidate-pool A/B 工具已接入，报告写入 `~/.stock-sage/m27_top_decile_filter_ab_report.{md,json}`；validation 窗口 baseline 全候选 32852 行、filtered top-decile 3506 行，filtered mean forward return=0.064955 vs baseline=0.021177，non-overlapping stride delta daily equal-weight return=0.052722；test3 production-profile 交易级 A/B 已写入 `~/.stock-sage/m27_test3_production_profile_ab_report.{json,md}`，baseline 292 笔 vs filtered 36 笔，filtered avg net return=0.032771 vs baseline=0.005297，filtered Sharpe=1.563425 vs baseline=0.428561；该路径仍为 non-promoting / production unchanged，只作为离线候选过滤诊断，不作为连续 quant score，不进入生产配置
- M27.2（P1）：`backend.tools.m27_build_test3_universe` 可复现生成本地 `paper_trading/test3_universe.json`（100 支，candidate_count=708，sector_count=64；该目录被 `.gitignore` 忽略，不作为 Git 交付）；signal runner 与 M26 baseline 支持显式 universe 参数，M26 默认仍保留 test2 基线口径
- M27.3（P2）：A 股事件分类与 `event_score` 已接入情感/信号合成；真实 `sentiment_cache` writer 已接入 `backend.tools.m27_sentiment_cache_backfill`，默认 dry-run，真实写入必须显式 `--execute` / `--db-url` / `--max-keys` / `--max-llm-calls`，并输出 audit 与 rollback manifest；本轮已执行 10-key smoke、一次中断后恢复记录和一个 25-key batch，当前计划内 exact cache key 命中 60 / 624，剩余 564 个 deduped key（`~/.stock-sage/m27_sentiment_cache_plan_after_batch2_new_missing.{json,md}`）；复跑 `m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json` 后，rows_with_cache_polarity=187、rows_with_fallback_polarity=235、cache_miss_windows=702，event 版相对 pure polarity 的 delta IC=0.038168（IC 0.028544 vs -0.009624）；该结果仍只作离线方向判断，不代表生产 polarity 已完全补齐，不改变生产 signal profile
- M27.4（P2）：Kronos Path A 数据准备、StockSage tracked ListMLE loss（`backend.analysis.kronos_losses`）、dry-run training plan、`m26_kronos_eval --model kronos-finetuned` 入口完成；完整覆盖检查为 requested=713 / complete_symbols=679 / min_symbols=707，reviewed universe 已写入 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json`（679 支，排除 34 支 incomplete）；正式 reviewed 数据已生成到 `~/.stock-sage/m27_kronos_reviewed_data/`，coverage passed=true、symbol_count=679、train_windows=318065、valid_windows=132274；preflight 报告写入 `~/.stock-sage/m27_kronos_preflight_report.{json,md}`，decision=`ready_for_training_confirmation`、checkpoint 不存在、vendor/venv 存在；`vendor/kronos/finetune/stocksage_path_a_train.py --ack-long-run` 已写出 `~/.stock-sage/models/kronos_finetuned/stocksage_path_a_training_plan.json`，但当前入口仍是 training plan 而非真实训练，且上游真实脚本仍是 CUDA demo 配置，本机不可安全直接启动 Kronos-small 微调
- 下一步计划：优先把 M27.3 剩余 564 个 deduped `sentiment_cache` key 改为可恢复后台/分批 runner 或继续按 25-key batch 回填，完成后再复跑不依赖 fallback 的 test3 event A/B；随后补 M27.4 StockSage Path A 专用真实训练 launcher/config，只有产出可读取 checkpoint 后才跑同标尺 `m26_kronos_eval --model kronos-finetuned`；M27.1c 只进入更长窗口/forward shadow 验证，不接生产评分
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
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_deep_research.py tests/test_m26_quant_boundary.py tests/test_m26_quant_baseline.py tests/test_qlib_feature_engineering.py tests/test_m27_alpha_event_universe.py tests/test_m27_m28_integration.py tests/test_m26_kronos_eval.py tests/test_qlib_ranker.py tests/test_qlib_validation_panel.py tests/test_m6_backtest_report.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_multi_round_debate.py tests/test_stock_memory.py tests/test_m27_kronos_finetune_data.py tests/test_stocksage_kronos_losses.py` → **103 passed, 2 skipped**（2026-05-30 M26/M27/M28 repair suite）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_label_objective_eval --active-only --horizon 20 --n-estimators 120 --refresh-panel-cache` → 通过；输出 `~/.stock-sage/m27_label_objective_eval_report.{md,json}`，best=`raw_20d_top_decile_classifier`，raw IC=0.108904 / ICIR=0.393701 / monotonic=True，stride ICIR=0.299587，decision=`keep_quant_disabled`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m backend.tools.m27_alpha_diagnostic --active-only --event-ab --universe-path paper_trading/test3_universe.json --event-ab-cache-missing-output /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing.json --json-output /Users/zeeechenn/.stock-sage/m27_event_ab_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_event_ab_report.md` → 通过；rows_with_cache_polarity=0，cache_miss_windows=889，diagnostic-only fallback 口径 rows_with_polarity=275，pure polarity IC=-0.010695 / ICIR=-0.044183，polarity+event IC=0.023102 / ICIR=0.092584，delta IC=0.033797。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_plan --input /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing.json --json-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.json --markdown-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.md` → 通过；dry-run only，total_windows=889，deduped_cache_keys=624，duplicate_windows=265，invalid_windows=0，estimated_llm_calls=624，estimated_batches=25，不写 `sentiment_cache`、不调用 LLM/API。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_sentiment_cache_plan.py tests/test_m27_alpha_diagnostic.py` → **16 passed**（2026-05-31 M27.3 cache-miss 导出 + dry-run plan；覆盖 exact key 校验、去重、只读 DB 检查、不默认连接 DB）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_label_objective_eval --active-only --horizon 20 --n-estimators 120 --segment-min-symbols 3 --json-output /Users/zeeechenn/.stock-sage/m27_label_objective_eval_exploratory_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_label_objective_eval_exploratory_report.md` → 通过；exploratory/sample-limited、non-promoting，通信设备 raw IC=-0.125885 / ICIR=-0.178232，gate=False。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_top_decile_filter_ab --horizon 20 --n-estimators 120 --json-output /Users/zeeechenn/.stock-sage/m27_top_decile_filter_ab_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_top_decile_filter_ab_report.md` → 通过；decision=`production_unchanged`，baseline mean_forward_return=0.021177，filtered mean_forward_return=0.064955，stride delta_daily_equal_weight_mean_return=0.052722，non-promoting / 不写 DB / 不调用 LLM/API / 不保存模型。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_kronos_finetune_data --universe-path /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_complete_universe.json --min-symbols 679 --output-dir /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_data` → 通过；coverage passed=true，complete_symbols=679，train_windows=318065，valid_windows=132274，尚未生成 finetuned checkpoint。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_kronos_preflight --json-output /Users/zeeechenn/.stock-sage/m27_kronos_preflight_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_kronos_preflight_report.md` → 通过；decision=`ready_for_training_confirmation`，coverage passed=true，complete_symbols=679，checkpoint_exists=false，vendor_kronos_exists=true，venv_kronos_exists=true，不启动训练、不写 checkpoint。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_top_decile_filter_ab.py tests/test_m27_kronos_preflight.py tests/test_m27_sentiment_cache_plan.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_m27_kronos_finetune_data.py` → **43 passed**（2026-05-31 M27.1c/M27.3/M27.4 focused gate）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_test3_production_profile_ab --universe-path paper_trading/test3_universe.json --start 2025-11-01 --end 2026-05-14 --exit-days 5 --horizon 20 --n-estimators 120` → 通过；输出 `~/.stock-sage/m27_test3_production_profile_ab_report.{json,md}`，baseline 292 笔 / filtered 36 笔，filtered avg net return=0.032771、Sharpe=1.563425，non-promoting / 不写 DB / 不调用 LLM/API / 不保存模型。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_backfill --plan /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.json --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db --execute --max-keys 25 --max-llm-calls 25 --batch-size 25` → 通过；继 10-key smoke 与中断恢复批次后，再插入 25 个计划内 `sentiment_cache` key；batch2 后新缺口计划为 total_windows=702、deduped_cache_keys=564、invalid_windows=0。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m backend.tools.m27_alpha_diagnostic --active-only --event-ab --universe-path paper_trading/test3_universe.json --event-ab-cache-missing-output /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing_after_batch2.json --json-output /Users/zeeechenn/.stock-sage/m27_event_ab_after_batch2_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_event_ab_after_batch2_report.md` → 通过；rows_with_cache_polarity=187，cache_miss_windows=702，polarity+event IC=0.028544 / ICIR=0.092007，delta IC=0.038168，仍为离线诊断。
- `.venv_kronos/bin/python vendor/kronos/finetune/stocksage_path_a_train.py --dataset-dir /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_data --output-dir /Users/zeeechenn/.stock-sage/models/kronos_finetuned --ack-long-run` → 通过；写出 `stocksage_path_a_training_plan.json`，但该入口只生成 training plan，不启动真实训练、不生成 checkpoint。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_sentiment_cache_backfill.py tests/test_m27_sentiment_cache_plan.py tests/test_m27_test3_production_profile_ab.py tests/test_m27_top_decile_filter_ab.py tests/test_m27_kronos_preflight.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_m27_kronos_finetune_data.py` → **49 passed**（2026-05-31 M27.1c production-profile A/B + M27.3 writer + M27.4 planning focused suite）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.analysis.qlib_engine --validate-production --json-output /private/tmp/stocksage_m26_prod_validation.json` → 通过；`status=ok`，legacy production feature cols 25 维验证，current candidate 29 维，production gate 未过，继续 `keep_quant_disabled`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache MYPY_CACHE_DIR=/private/tmp/stocksage_mypy_cache make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'` → ruff / mypy / backend **588 passed, 2 skipped** / frontend node **19 passed**；前端 build 首次被沙箱拦截 Vite 临时 config 写入，随后 `npm run build` 提权重跑通过（62 modules，约 475 KB / gzip 147 KB）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m compileall -q backend tests` → 通过

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
