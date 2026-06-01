# StockSage — Public Status Snapshot

> Public runtime and release snapshot. Detailed history lives in `CHANGELOG.md`; future work lives in `docs/ROADMAP.md`.

当前公开 release：`v0.2.0`（2026-05-31），聚合 M26/M27/M28/M29 agent-ready research runtime 与 alpha evidence 更新；生产量化层继续关闭。

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
| M26 | 量化层重估（扩盘+Kronos评估） | ✅ M26.0/M26.1/M26.2 完成；M26.3 暂停待 M29 新 alpha gate 达标 |
| M27 | Alpha 根治工程 | ✅ 证据闭环完成但未晋升；所有候选均未过 promotion gate，继续保持 quant 关闭 |
| M28 | 调研模块整合与实时搜索接入 | ✅ 完成，deep_research / copilot / debate 信息流打通 |
| M29 | Alpha Reset / Forward Evidence Engine | ⏳ 当前活跃：固化 M27 失败证据，建立 forward evidence 与新 alpha 假设机制 |

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
- M26.3 暂停：两路均未带来足够 IC 改善，等 M29 新 alpha gate（IC ≥ 0.04 / ICIR ≥ 0.40 / monotonic=True）达标后重启
- 报告存档：M26 baseline / 扩盘诊断写入 `~/.stock-sage/m26_quant_baseline_report.{md,json}`，Kronos 零样本写入 `~/.stock-sage/m26_kronos_report.{md,json}`；历史 M26.0 小权重建议不再作为当前结论引用
- 生产：继续 `weight_quant=0.0`，`kronos_enabled=false`

**M27 Alpha 根治工程（2026-05-30 启动，2026-05-31 证据闭环未晋升）**
- M27.1（P1）：经典因子工程已接入；regression candidate IC=0.020217 / ICIR=0.176699 / monotonic=False，ranker candidate IC=0.029978 / ICIR=0.163796 / monotonic=False，均未达 M27 alpha 目标 / 生产 promotion 配置（`backend/config.py` 默认 IC≥0.04 / ICIR≥0.40 / monotonic=True）
- M27.1a（P1）：alpha 诊断报告已写入 `~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`；active 94 支、107270 行、2019-01-25~2026-05-22，5d 最强单因子 `roe` 仅 IC=0.015642 / ICIR=0.114032 / monotonic=False，M27 最强 `sector_rel_strength_20_z` 仅 IC=0.012131 / ICIR=0.076884；结论为先重设计 label/objective，再继续堆因子
- M27.1b（P1）：label/objective 离线评估已刷新到 `~/.stock-sage/m27_label_objective_eval_report.{md,json}`；best=`raw_20d_top_decile_classifier`，raw IC=0.108904 / ICIR=0.393701 / monotonic=True，stride ICIR=0.299587，top-decile lift=2.674922；因 raw gate 未过（ICIR 略低于 0.40，且 stride 更弱），结论仍为 `keep_quant_disabled`；sector-specific offline candidate 已接入且 non-promoting，半导体样本达标但 raw IC=0.112838 / ICIR=0.218514 / stride ICIR=0.279028、gate=False；`--segment-min-symbols 3` exploratory 报告写入 `~/.stock-sage/m27_label_objective_eval_exploratory_report.{md,json}`，通信设备仅 3 支样本且 raw IC=-0.125885 / ICIR=-0.178232、gate=False，不可晋升
- M27.1c（P1）：top-decile classifier 离散过滤器 offline candidate-pool A/B 工具已接入，报告写入 `~/.stock-sage/m27_top_decile_filter_ab_report.{md,json}`；validation 窗口 baseline 全候选 32852 行、filtered top-decile 3506 行，filtered mean forward return=0.064955 vs baseline=0.021177，non-overlapping stride delta daily equal-weight return=0.052722；test3 production-profile 交易级 A/B 已写入 `~/.stock-sage/m27_test3_production_profile_ab_report.{json,md}`，baseline 292 笔 vs filtered 36 笔，filtered avg net return=0.032771 vs baseline=0.005297，filtered Sharpe=1.563425 vs baseline=0.428561；forward shadow 工具 `backend.tools.m27_top_decile_forward_shadow` 已接入，避免用已过期 validation keys 判断 2026-05-15~2026-05-22，并收紧训练 cutoff 到 label realized date 早于 target start；报告输出 `~/.stock-sage/m27_top_decile_forward_shadow_{1,3,5}d.{json,md}`：1d filtered 19 笔，avg net return=0.240773 vs baseline=0.087168、Sharpe=4.021878 vs 2.534082；3d filtered 7 笔，avg=0.080748 vs 0.060377、Sharpe=7.825931 vs 7.042919；5d filtered 6 笔，avg=0.792643 vs 0.281036、Sharpe=3.765263 vs 2.186085；forward 结果支持过滤器有候选价值，但样本很小且复利总额仍因交易数下降低于 baseline。2026-04-01~2026-05-29 weekly rolling 已扩展到 `/private/tmp/m27_forward_shadow_rolling_20260401_20260529_{1,3,5}d.{json,md}`：1d baseline 691 / filtered 99、positive delta windows 7/9、trade-weighted avg net return delta=0.047711、样本门槛通过；3d baseline 237 / filtered 42、positive 6/9、delta=0.012785，样本仍不足；5d baseline 109 / filtered 25、positive 6/9、delta=0.027642，样本仍不足；新增 2026-05-27~2026-05-29 窗口 filtered=0（3d/5d 因 forward exit 不足 baseline=0），三者均为 non-promoting / production unchanged，只作为离线候选过滤诊断，不作为连续 quant score，不进入生产配置
- M27.1d（P1）：`backend.tools.m27_label_objective_eval` 已扩展为 multi-exit / short-cycle objective search：主 20d 候选补充 1/3/5/10/20d raw-return matrix，新增 1d/3d/5d regression/top-decile/ranker 短周期候选，并把 `volatility_regime` 纳入 segment-specific offline candidates；隔离报告写入 `/private/tmp/m27_label_objective_eval_m27_1d_multi_exit.{json,md}`。active-only 94 支仍为 `keep_quant_disabled`；最佳短周期候选 `raw_5d_top_decile_classifier_short_cycle` raw IC=0.046294 / ICIR=0.180649 / stride ICIR=0.130392，gate=False；active-only `low_vol` segment regression raw IC=0.126409 / ICIR=0.614230 / stride ICIR=0.873032，但分层不单调、gate=False。扩样本 `--include-inactive` 报告 `/private/tmp/m27_label_objective_eval_include_inactive_m27_1d_multi_exit.{json,md}` 覆盖 713 支 / 794648 行，仍为 `keep_quant_disabled`；最佳主候选 raw IC=0.043327 / ICIR=0.223696 / stride ICIR=0.283768，短周期候选均未过 gate。结论：1d rolling 过滤器不能直接转化为可晋升 label/objective；`low_vol` / `high_vol` regime 是下一轮研究线索，但当前仍不可生产晋升
- M27.2（P1）：`backend.tools.m27_build_test3_universe` 可复现生成本地 `paper_trading/test3_universe.json`（100 支，candidate_count=708，sector_count=64；该目录被 `.gitignore` 忽略，不作为 Git 交付）；signal runner 与 M26 baseline 支持显式 universe 参数，M26 默认仍保留 test2 基线口径
- M27.3（P2）：A 股事件分类与 `event_score` 已接入情感/信号合成；真实 `sentiment_cache` writer 已接入 `backend.tools.m27_sentiment_cache_backfill`，可恢复分批 runner 已接入 `backend.tools.m27_sentiment_cache_batch_runner`，默认 dry-run，真实写入必须显式 `--execute` / `--db-url` / 调用上限，并输出 per-batch audit 与 rollback manifest；本轮用 Codex-first `local_cli` 和 `LOCAL_CLI_TIMEOUT_SECONDS=180` 完成 batch18-batch25（合计 189-key、189 LLM call；最后 batch25 插入 14 key），当前计划内 exact cache key 命中 624 / 624，最终缺口计划 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch25_new_missing.{json,md}` 为 total_windows=0、deduped_cache_keys=0、invalid_windows=0；复跑 `m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json` 后，rows_with_cache_polarity=889、rows_with_fallback_polarity=0、cache_miss_windows=0，pure polarity IC=0.095070 / ICIR=0.311549，polarity+event IC=0.102256 / ICIR=0.324784，delta IC=0.007186；cache/fallback 已闭合但 ICIR 仍低于 0.40，M27 gate 未过。lookback sensitivity 已只读跑到 `/private/tmp/m27_alpha_event_ab_lookback{1,5}.{json,md}`：lookback=1 polarity+event ICIR=-0.017651 且新缺口 211 个去重 key；lookback=5 初筛 polarity+event ICIR=0.425622 但重新引入 203 个去重 cache key / fallback 92 行。获批后已完成 lookback=5 真实回填 9 批（203 key / 203 LLM call），summary 写入 `~/.stock-sage/m27_sentiment_cache_batch_runner_lookback5_20260531_summary.json`，最终缺口计划 `/private/tmp/m27_sentiment_cache_plan_lookback5_after_backfill_dbcheck_20260531.{json,md}` 为 total_windows=0、deduped_cache_keys=0、invalid_windows=0；复核报告 `/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531.{json,md}` rows_with_cache_polarity=1010、rows_with_fallback_polarity=0、cache_miss_windows=0，pure polarity IC=0.180828 / ICIR=0.549296，polarity+event IC=0.131126 / ICIR=0.410776，delta IC=-0.049702。新增 v2 gate 报告 `/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.{json,md}` 已补 quantile/top-bottom/monotonic/multiple-comparison 警告：pure polarity top-bottom=0.018281 但 monotonic=False，polarity+event top-bottom=0.014853 且 monotonic=False，两者 `passes_event_ab_gate=False` / `gate_blockers=["not_monotonic"]`，`variant_comparison.recommended_variant="none"`。结论：cache/fallback 已闭合，但 pure polarity 与 event overlay 均未过完整 gate，不能把事件化或纯 polarity signal profile 晋升；生产不变
- M27.4（P2）：Kronos Path A 数据准备、StockSage tracked ListMLE loss（`backend.analysis.kronos_losses`）、dry-run training plan、受控 launch config、StockSage-owned smoke training loop、real-finetuned launcher、`m26_kronos_eval --model kronos-finetuned` 入口完成；完整覆盖检查为 requested=713 / complete_symbols=679 / min_symbols=707，reviewed universe 已写入 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json`（679 支，排除 34 支 incomplete）；正式 reviewed 数据已生成到 `~/.stock-sage/m27_kronos_reviewed_data/`，coverage passed=true、symbol_count=679、train_windows=318065、valid_windows=132274；smoke checkpoint 隔离在 `~/.stock-sage/models/kronos_path_a_smoke/checkpoints/best_model/` 且仍会被评估入口拒绝；首个真实 Kronos-compatible fine-tuned checkpoint 曾写入 canonical `~/.stock-sage/models/kronos_finetuned/checkpoints/best_model/`，manifest `checkpoint_kind=stocksage_kronos_finetuned_model`、step=200、`production_config_changed=false`，同标尺评估 IC=0.006391 / ICIR=0.020976 / monotonic=False / m27_gate_pass=False；获批后按审查约定使用新隔离目录从头训练，不从 canonical step=200 resume，产物写入 `~/.stock-sage/models/kronos_finetuned_isolated/m27_4_kronos_long_20260531_204923/`，actual_device=mps、step=2000、observed best_loss=2.113054、`production_config_changed=false`，launch config 后验 eval command 已指向 `.venv_kronos/bin/python` 与该隔离 `output_dir`；代理核验发现本轮 `best_model` 指针仍等同 `step_000100`（这是 launcher best-checkpoint 选择缺陷，已修代码，未来按已保存 checkpoint loss 选择），因此补评已保存 checkpoint 中 loss 最低的 `step_001500` 和最终 `step_002000`。`step_001500` 为 IC=-0.036154 / ICIR=-0.125869 / IC>0=0.461538 / monotonic=False / m27_gate_pass=False；最新 `~/.stock-sage/m26_kronos_report.{json,md}` 加载 `step_002000`，IC=-0.047219 / ICIR=-0.195819 / IC>0=0.384615 / monotonic=False / m27_gate_pass=False，长训后 checkpoint 明确失败，仍不接生产
- M27 验证管线修复（2026-05-31 审查后）：`backend.tools.m27_label_objective_eval` 的晋升结论现在必须同时满足 raw gate 与非重叠 `stride_icir >= 0.40`，并输出 `n_candidates_tested`、Bonferroni alpha/ICIR 参考值与 `multiple_comparison_warning`；隔离重跑 `/private/tmp/m27_label_objective_eval_stage0_gate.{json,md}` 后仍为 `keep_quant_disabled`，best=`raw_20d_top_decile_classifier`，stride ICIR=0.299587，raw/stride gate pass count=0。`backend.tools.m27_top_decile_forward_shadow` 已输出 `sample_adequacy.insufficient_for_sharpe`，默认按 `exit_days` 写入 `~/.stock-sage/m27_top_decile_forward_shadow_{exit_days}d.{json,md}`；`backend.tools.m27_kronos_path_a_launch` 的后验 eval command 指向 `.venv_kronos/bin/python` 与本次 `output_dir`，避免未来新目录训练后误评 canonical 或误用缺少 Kronos 依赖的 `.venv`。
- M27 收口结论：M27.1d 已验证短周期 label/objective、扩样本 full universe、volatility regime 与 event lookback sensitivity，均不足以恢复 quant；M27.1c 只保留为 1d 入场过滤器 offline evidence，rolling 已扩展到本地最新 2026-05-29 且新增窗口未给出晋升证据；M27.3 lookback=5 真实回填和 v2 gate 后，pure polarity 只是探索性正向线索，因分位不单调不能晋升；M27.4 隔离 2000-step 长训的已保存 best-loss 与 final checkpoint 均未过 M27 gate 且弱于 LightGBM。当前 M27 结论为继续 `weight_quant=0.0`，不接 checkpoint，不改 signal profile；下一步不再继续烧 Kronos 或改事件 profile，除非另行批准新的研究假设或等待更多 forward 样本
- 当前规划见 `docs/ROADMAP.md § M29`；M27 历史证据见 `docs/ROADMAP.md § M27`

**M29 Alpha Reset / Forward Evidence Engine（2026-05-31 启动）** ← 当前活跃里程碑
- M29 目标：把 M27 的失败/弱正向线索转为可持续积累的 forward evidence 与预注册新 alpha 假设；不再把 M27 旧候选反复包装成晋升候选。
- M29.1（P0）：`backend.tools.m29_evidence_ledger` 已接入 read-only evidence ledger，默认聚合 M27 top-decile forward shadow、rolling shadow、event/polarity v2 gate、label/objective gate、Kronos failed checkpoint 与 M29 shadow validation 证据；最新只读输出 `/private/tmp/m29_evidence_ledger_with_shadow_validation.{json,md}` 为 artifacts_parsed=12、entries=13、gate_pass_count=0、promotable_count=0、non_promoting_count=13，统一记录窗口、样本量、IC/ICIR、stride/non-overlap、monotonic、top-bottom、data-quality blockers、multiple-comparison warning 与 production_unchanged；缺失 source side-effect 字段保守标记为 `unknown_boundary_flags` blocker，event/polarity entry 显式记录 cache/fallback 覆盖，label/objective entry 显式记录 short-cycle / multi-exit / segment 子证据摘要；新增最小 provenance contract，逐条记录 artifact sha256/mtime、panel/window/cutoff 可得字段，并把缺失的 `data_source`、`fetched_at`、`adjustment`、`universe_hash`、`train_label_realized_end` 标为 `missing_provenance_*` blocker；ledger 同时输出下一次 M29.3 forward shadow 命令模板；工具不写 DB、不调 LLM/API、不保存模型、不改配置。
- M29.2（P0）：`backend.tools.m29_hypothesis_registry` 已接入预注册清单，默认生成 5 条 shadow research candidate：regime-conditioned alpha、行业内相对强弱、流动性/换手状态、事件后 drift、top-decile entry timing；首轮只读输出 `/private/tmp/m29_hypothesis_registry_test.{json,md}`，validation_passed=true；每条均含 M27 source clue、样本门、fresh OOS/forward、non-overlapping stride、multiple-comparison、promotion gate 与停止条件，明确禁止把 M27 旧候选或 Kronos checkpoint 作为 production candidate。
- M29.2/M29.3 shadow validation：`backend.tools.m29_shadow_validation` 已接入首条预注册验证包装器，优先验证 `top_decile_entry_timing_v1` 的 1d rolling forward shadow；只读 smoke 输出 `/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.{json,md}`，source=`/private/tmp/m27_forward_shadow_rolling_20260401_20260529_1d.json`，filtered_trades=99 ≥ 50、positive_windows=7/9，样本门通过但 `gate_pass=False` / `promotable=False`，blockers=`missing_source_data_source/fetched_at/adjustment/universe_hash/train_label_realized_end`、`post_registration_fresh_forward_missing`、`not_continuous_quant_score`、`shadow_validation_non_promoting`；生产不变。
- M29.3（P1）：自动/半自动延长 forward shadow；当前 rolling 已延至本地最新 2026-05-29，2026-05-31 为周日，暂无新交易日可安全追加；下一次新增行情后先读取 ledger 的 `next_forward_commands` 跑 1d/3d/5d rolling，再把新 artifact 纳入 ledger；只有样本充足、非重叠 ICIR 稳定、分层单调且无 cache/fallback/data-quality/provenance blocker 时，才允许进入 non-promoting train candidate。
- M29.3 执行闭环补强（2026-06-01）：`backend.tools.m29_evidence_ledger` 默认会自动发现 `/private/tmp/m29_forward_shadow_rolling_*_{1,3,5}d.json` 中每个 exit horizon 的最新 M29 forward artifact，并支持 `--forward-end YYYY-MM-DD` 输出可直接执行的 1d/3d/5d rolling 命令；本轮未追加新的 partial forward evidence，等完整新增交易日与 future-return 覆盖后再跑。
- M29.3 readiness guard（2026-06-01）：`backend.tools.m29_forward_readiness` 已接入，只读判断 test3 universe 是否具备完整新增交易日与 1d/3d/5d future-return 覆盖；只有三条 exit horizon 同时 ready 才输出下一轮命令，否则输出 blockers 且不运行 forward shadow。CLI smoke `/private/tmp/m29_forward_readiness_finish_smoke.{json,md}` 为 `ready_to_run_forward_shadow=false`、commands=[]、`runs_forward_shadow=false`；live DB 只读检查 `/private/tmp/m29_forward_readiness_live.{json,md}` 显示 latest_price_date=2026-06-01，但 test3 universe 当日仅 10/100 支有价格，2026-05-27~2026-05-29 为 94/100 支且仅 25 支具备完整 price provenance，blockers=`no_new_complete_{1,3,5}d_forward_coverage`、`partial_latest_trading_day_after_last_artifact`；当前状态为 tooling/provenance-ready、fresh-forward-blocked。
- M29.3 provenance producer 补强：`backend.tools.m27_top_decile_forward_shadow` 后续新产物会写出 `universe_hash` 与 `train_label_realized_end`，rolling 报告会汇总 `train_label_realized_end_range`；既有历史 artifact 未回写，ledger 会继续把旧产物的 provenance 缺口标为 blocker。`backend.data.qlib_data.build_training_data` 已把 price row 的 `_price_source` / `_price_fetched_at` / `_price_adjustment` 带入训练面板，`backend.tools.m27_label_objective_eval` 已把 panel cache 升到 version 2 并在 panel meta 输出 `price_provenance` 覆盖率；`backend.tools.m29_evidence_ledger` 会读取 `panel.price_provenance`，若未来新 artifact 仍有缺口则标记 `panel_price_provenance_incomplete`。旧 DB 行的来源仍不猜测回填。
- M29.3 provenance audit 首版：`backend.tools.m29_provenance_audit` 已接入只读检查；`backend.data.database.Price` / `IndexPrice` 已新增 nullable `source` / `fetched_at` / `adjustment`，`backend.data.market.fetch_daily` / `fetch_cn_index` 会把 provider provenance 写入 DataFrame attrs，`backfill_if_needed` / `sync_index_to_db` 会写入未来新增行情。已对本地 SQLite 执行轻量 runtime schema patch（只加 nullable 列，不回填旧数据、不刷新行情）。最新 smoke 输出 `/private/tmp/m29_provenance_audit_with_shadow_validation.{json,md}`：`prices` / `index_prices` / `market_snapshots` schema blocker 已清零；当前 13 条 ledger entries 均仍有历史 artifact provenance 缺口（artifact hash 与 generated_at 可证明，旧 daily source/fetched_at/adjustment 与旧 universe_hash 不可证明）。结论：M29 可以继续收集 forward evidence，但旧 artifact provenance blocker 清零前不得进入 promotion review；未来新增行情应自然带 provider provenance。
- M29.4（P1）：promotion contract 继续沿用生产 gate：IC≥0.04 / ICIR≥0.40 / monotonic=True，并要求 stride ICIR、multiple-comparison warning、fresh OOS/forward 证据、data-quality blockers 清零和人工确认；`backend.tools.m29_hypothesis_registry` 会校验完整 gate 字段，`backend.tools.m29_evidence_ledger` Markdown 会显式渲染 promotion contract；当前状态为 contract-enforced、promotion-not-started，没有候选满足 fresh OOS/forward、provenance blockers 清零和人工确认；未过 gate 前 `weight_quant=0.0`、`kronos_enabled=false`、signal profile 不变。

**新对话接手目标（2026-05-31，M29）**
- 先读本节和 `docs/ROADMAP.md § M29`，再看 `git status --short`；当前预期未提交变更包含 M27/M29 交付文件，不要回滚 M27 工具、测试和文档更新。
- 第一动作：复核或扩展 M29.1 read-only evidence ledger；当前首版已聚合已有 `/private/tmp/m27_*`、`~/.stock-sage/m27_*` 报告，后续只允许追加 artifact 读取或未来 forward shadow 结果，不能写 DB、不调 LLM、不改生产配置。
- 第二动作：基于 M29.2 预注册清单挑一个 shadow hypothesis 设计只读验证；候选必须先满足 registry 的样本门、OOS/forward 窗口、gate 字段和 stop condition，避免事后筛选。
- 停止条件：任何步骤可能恢复 quant 权重、改变 production signal profile、接入/覆盖 checkpoint、继续更长 Kronos training、真实写 `sentiment_cache`、或需要新依赖/外部付费调用时，先停下汇报。

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
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_top_decile_forward_shadow --universe-path paper_trading/test3_universe.json --start 2026-05-15 --end 2026-05-22 --exit-days {1,3,5} --horizon 20 --n-estimators 120` → 通过；输出 `~/.stock-sage/m27_top_decile_forward_shadow_{1,3,5}d.{json,md}`，1d/3d/5d avg 和 Sharpe 均提升，但样本只有 19/7/6 笔且 compounded return 低于 baseline，结论为 positive-but-small-sample、non-promoting / 不写 DB / 不调用 LLM/API / 不保存模型。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_backfill --plan /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.json --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db --execute --max-keys 25 --max-llm-calls 25 --batch-size 25` → 通过；继 10-key smoke 与中断恢复批次后，再插入 25 个计划内 `sentiment_cache` key；batch2 后新缺口计划为 total_windows=702、deduped_cache_keys=564、invalid_windows=0。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. python3 -m backend.tools.m27_alpha_diagnostic --active-only --event-ab --universe-path paper_trading/test3_universe.json --event-ab-cache-missing-output /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing_after_batch2.json --json-output /Users/zeeechenn/.stock-sage/m27_event_ab_after_batch2_report.json --markdown-output /Users/zeeechenn/.stock-sage/m27_event_ab_after_batch2_report.md` → 通过；rows_with_cache_polarity=187，cache_miss_windows=702，polarity+event IC=0.028544 / ICIR=0.092007，delta IC=0.038168，仍为离线诊断。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_batch_runner --plan /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.json --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db --batch-size 25 --max-batches 1 --max-llm-calls-total 25 --audit-dir /Users/zeeechenn/.stock-sage/m27_sentiment_cache_backfill_batches --summary-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_batch_runner_dry_run_summary.json --run-id m27_runner_dry_20260531 --print` → 通过；dry-run only，existing_cache_keys=60，pending_before_batch=564，selected_cache_keys=25，不写 DB、不调用 LLM/API。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_batch_runner --plan /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan.json --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db --execute --batch-size 25 --max-batches 1 --max-llm-calls-total 25 --audit-dir /Users/zeeechenn/.stock-sage/m27_sentiment_cache_backfill_batches --summary-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_batch_runner_batch3_summary.json --run-id m27_runner_batch3_20260531 --print` → 通过；runner 真实 batch3 插入 25 个计划内 `sentiment_cache` key，llm_calls=25，audit/rollback 写入 `~/.stock-sage/m27_sentiment_cache_backfill_batches/`，生产配置不变。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json --event-ab-cache-missing-output /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing_after_runner_batch3.json --json-output /Users/zeeechenn/.stock-sage/m27_alpha_diagnostic_event_ab_after_runner_batch3.json --markdown-output /Users/zeeechenn/.stock-sage/m27_alpha_diagnostic_event_ab_after_runner_batch3.md` → 通过；rows_with_cache_polarity=237，rows_with_fallback_polarity=225，cache_miss_windows=652，pure polarity IC=0.066592 / ICIR=0.225971，polarity+event IC=0.072677 / ICIR=0.225958，delta IC=0.006085，仍为离线诊断。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_sentiment_cache_plan --input /Users/zeeechenn/.stock-sage/m27_event_ab_cache_missing_after_runner_batch3.json --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db --json-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan_after_runner_batch3_new_missing.json --markdown-output /Users/zeeechenn/.stock-sage/m27_sentiment_cache_plan_after_runner_batch3_new_missing.md` → 通过；batch3 后新缺口计划为 total_windows=652、deduped_cache_keys=539、invalid_windows=0。
- `.venv_kronos/bin/python vendor/kronos/finetune/stocksage_path_a_train.py --dataset-dir /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_data --output-dir /Users/zeeechenn/.stock-sage/models/kronos_finetuned --ack-long-run` → 通过；写出 `stocksage_path_a_training_plan.json`，但该入口只生成 training plan，不启动真实训练、不生成 checkpoint。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv_kronos/bin/python -m backend.tools.m27_kronos_path_a_launch --dataset-dir /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_data --output-dir /Users/zeeechenn/.stock-sage/models/kronos_finetuned --log-dir /Users/zeeechenn/.stock-sage/logs/m27_kronos_path_a --write-launch-config --ack-long-run --device mps --epochs 1 --batch-size 32 --max-steps 500 --learning-rate 0.00001 --checkpoint-interval 100` → 通过；写出 `stocksage_path_a_launch_config.json`，starts_training=false，writes_checkpoint=false，loss_wiring available=true，decision=`launch_config_ready`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv_kronos/bin/python -m backend.tools.m27_kronos_path_a_launch --dataset-dir /Users/zeeechenn/.stock-sage/m27_kronos_reviewed_data --output-dir /Users/zeeechenn/.stock-sage/models/kronos_finetuned --log-dir /Users/zeeechenn/.stock-sage/logs/m27_kronos_path_a/real_finetuned_20260531 --artifact-kind real-finetuned --allow-canonical-finetuned --device cpu --epochs 1 --batch-size 8 --max-steps 500 --checkpoint-interval 100 --learning-rate 0.00001 --ack-long-run --ack-model-write --execute-training` → 中断于 step=200 后停止；已写真实 Kronos-compatible step checkpoints，`step_000200` 复制为 canonical `~/.stock-sage/models/kronos_finetuned/checkpoints/best_model`，manifest `checkpoint_kind=stocksage_kronos_finetuned_model`、best_loss=2.175277、production_config_changed=false。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv_kronos/bin/python -m backend.tools.m26_kronos_eval --model kronos-finetuned --finetuned-model-path /Users/zeeechenn/.stock-sage/models/kronos_finetuned` → 通过；真实 checkpoint 可被 `Kronos.from_pretrained()` 读取，最新报告 `~/.stock-sage/m26_kronos_report.{json,md}` 为 IC=0.006391 / ICIR=0.020976 / IC>0=0.500000 / monotonic=False / m27_gate_pass=False，低于 LightGBM 且未过 M27 gate，不接生产。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_sentiment_cache_backfill.py tests/test_m27_sentiment_cache_plan.py tests/test_m27_test3_production_profile_ab.py tests/test_m27_top_decile_filter_ab.py tests/test_m27_kronos_preflight.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_m27_kronos_finetune_data.py` → **49 passed**（2026-05-31 M27.1c production-profile A/B + M27.3 writer + M27.4 planning focused suite）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.analysis.qlib_engine --validate-production --json-output /private/tmp/stocksage_m26_prod_validation.json` → 通过；`status=ok`，legacy production feature cols 25 维验证，current candidate 29 维，production gate 未过，继续 `keep_quant_disabled`。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache MYPY_CACHE_DIR=/private/tmp/stocksage_mypy_cache make verify PYTEST='.venv/bin/python -m pytest -p no:cacheprovider'` → ruff / mypy / backend **588 passed, 2 skipped** / frontend node **19 passed**；前端 build 首次被沙箱拦截 Vite 临时 config 写入，随后 `npm run build` 提权重跑通过（62 modules，约 475 KB / gzip 147 KB）。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m compileall -q backend tests` → 通过
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_top_decile_forward_shadow.py tests/test_m27_test3_production_profile_ab.py tests/test_m27_top_decile_filter_ab.py tests/test_m27_label_objective_eval.py tests/test_m27_sentiment_cache_backfill.py tests/test_m27_kronos_path_a_launch.py tests/test_m26_kronos_eval.py tests/test_llm_runtime_provider.py` → **49 passed, 3 skipped**（2026-05-31 M27 forward shadow / cache / Kronos / local_cli focused suite）。
- `RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache .venv/bin/python -m ruff check backend/tools/m27_top_decile_forward_shadow.py tests/test_m27_top_decile_forward_shadow.py backend/tools/m27_sentiment_cache_backfill.py backend/tools/m27_kronos_path_a_launch.py backend/tools/m26_kronos_eval.py tests/test_m27_sentiment_cache_backfill.py tests/test_m27_kronos_path_a_launch.py tests/test_m26_kronos_eval.py tests/test_llm_runtime_provider.py` → 通过；`git diff --check` → 通过；`PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache .venv/bin/python -m compileall -q backend tests` → 通过。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_kronos_path_a_launch.py tests/test_m26_kronos_eval.py tests/test_m27_top_decile_forward_shadow.py tests/test_m27_test3_production_profile_ab.py tests/test_m27_top_decile_filter_ab.py tests/test_m27_label_objective_eval.py tests/test_m27_sentiment_cache_backfill.py tests/test_llm_runtime_provider.py` → **51 passed, 3 skipped**（2026-05-31 M27.4 real-finetuned checkpoint + M27 focused suite）。
- `RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache .venv/bin/python -m ruff check backend/tools/m27_kronos_path_a_launch.py backend/tools/m26_kronos_eval.py backend/tools/m27_top_decile_forward_shadow.py tests/test_m27_kronos_path_a_launch.py tests/test_m26_kronos_eval.py tests/test_m27_top_decile_forward_shadow.py` → 通过；`git diff --check` → 通过；`PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache .venv/bin/python -m compileall -q backend tests` → 通过。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m backend.tools.m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json --event-lookback-days 5 --event-ab-cache-missing-output /private/tmp/m27_alpha_event_ab_lookback5_after_backfill_missing_20260531_v2.json --json-output /private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.json --markdown-output /private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.md` → 通过；pure polarity IC=0.180828 / ICIR=0.549296 但 monotonic=False、gate_blockers=`not_monotonic`；polarity+event IC=0.131126 / ICIR=0.410776 且 monotonic=False；recommended_variant=`none`，生产不变。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. MULTI_AGENT_ENABLED=false .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_alpha_diagnostic.py` → **12 passed**；`RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache .venv/bin/python -m ruff check backend/tools/m27_alpha_diagnostic.py tests/test_m27_alpha_diagnostic.py` → 通过。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. MULTI_AGENT_ENABLED=false .venv/bin/python -m backend.tools.m27_top_decile_forward_shadow --universe-path paper_trading/test3_universe.json --rolling --start 2026-04-01 --end 2026-05-29 --rolling-window-days 7 --rolling-stride-days 7 --exit-days {1,3,5}` → 通过；输出 `/private/tmp/m27_forward_shadow_rolling_20260401_20260529_{1,3,5}d.{json,md}`；1d baseline=691 / filtered=99 / positive=7/9 / delta=0.047711，3d baseline=237 / filtered=42 / positive=6/9 / delta=0.012785，5d baseline=109 / filtered=25 / positive=6/9 / delta=0.027642；三者均 non-promoting / production unchanged。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. MULTI_AGENT_ENABLED=false .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_m27_top_decile_forward_shadow.py tests/test_m27_kronos_path_a_launch.py tests/test_m26_kronos_eval.py tests/test_m27_sentiment_cache_backfill.py tests/test_m27_sentiment_cache_batch_runner.py tests/test_m27_sentiment_cache_plan.py tests/test_llm_runtime_provider.py` → **73 passed, 3 skipped**；`RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache .venv/bin/python -m ruff check backend/tools/m27_alpha_diagnostic.py backend/tools/m27_label_objective_eval.py backend/tools/m27_top_decile_forward_shadow.py backend/tools/m27_kronos_path_a_launch.py tests/test_m27_alpha_diagnostic.py tests/test_m27_label_objective_eval.py tests/test_m27_top_decile_forward_shadow.py tests/test_m27_kronos_path_a_launch.py` → 通过；`PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache .venv/bin/python -m compileall -q backend/tools/m27_alpha_diagnostic.py backend/tools/m27_label_objective_eval.py backend/tools/m27_top_decile_forward_shadow.py backend/tools/m27_kronos_path_a_launch.py` → 通过；`git diff --check` → 通过。
- `PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_provider_universe.py tests/test_m27_top_decile_forward_shadow.py tests/test_m27_label_objective_eval.py tests/test_m29_evidence_ledger.py tests/test_m29_hypothesis_registry.py tests/test_m29_provenance_audit.py tests/test_qlib_feature_engineering.py` → **55 passed**；`RUFF_CACHE_DIR=/private/tmp/stocksage_ruff_cache PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. .venv/bin/python -m ruff check backend/data/qlib_data.py backend/data/database.py backend/data/market.py backend/tools/m27_top_decile_forward_shadow.py backend/tools/m27_label_objective_eval.py backend/tools/m29_evidence_ledger.py backend/tools/m29_hypothesis_registry.py backend/tools/m29_provenance_audit.py tests/test_provider_universe.py tests/test_m27_top_decile_forward_shadow.py tests/test_m27_label_objective_eval.py tests/test_m29_evidence_ledger.py tests/test_m29_hypothesis_registry.py tests/test_m29_provenance_audit.py tests/test_qlib_feature_engineering.py` → 通过；M29 CLI 只读 smoke 输出 `/private/tmp/m29_evidence_ledger_test.{json,md}`、`/private/tmp/m29_hypothesis_registry_test.{json,md}` 与 `/private/tmp/m29_provenance_audit_test.{json,md}`；本地 SQLite runtime schema patch 已确认 `prices` / `index_prices` 均包含 `source`、`fetched_at`、`adjustment`。

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
