# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情优先见 `CHANGELOG.md`。本文件优先列当前未完成任务项（`[ ]`）、暂缓项和必要接手摘要；完成项只保留会影响后续执行边界的部分。
> 排序按当前接手优先级和风险边界组织，不严格按 M 编号递增；例如 M44 直接承接 M43 后的 Atlas 合并基准。

---

## ⭐ M29 Alpha Reset / Forward Evidence Engine【P0 当前最高优先】🔬

> M27 已形成完整离线证据闭环，但所有候选均未过生产 promotion gate。M29 不继续包装旧候选，而是把 M27 的失败证据与弱正向线索转成可积累、可复核、可预注册的新 alpha 研究机制。

### 启动目标与边界（2026-05-31）

**目标**：建立 forward evidence ledger 与新 alpha 假设注册流程，让 top-decile filter、pure polarity、event overlay、regime-conditioned alpha 等线索在未来窗口中持续积累证据；只有新证据通过完整 gate 后，才讨论 non-promoting train candidate 或 M26.3 重启。

**非目标**：不恢复 `weight_quant`，不修改 production signal profile，不接 Kronos checkpoint，不继续更长 Kronos training，不把 M27 已失败候选直接重命名为可晋升候选。

### M29.1 Forward Evidence Ledger（P0）

- [x] 新增 read-only evidence ledger：汇总已有 M27 artifact 与未来 forward shadow，输出统一 JSON/Markdown artifact。
- [x] Ledger 字段必须包含：candidate/variant、window、sample size、IC/ICIR、stride/non-overlap 指标、quantile monotonic、top-bottom、data-quality blockers、multiple-comparison warning、production_unchanged。
- [x] 首批纳入 M27 证据：top-decile forward shadow、pure polarity v2 gate、polarity+event v2 gate、short-cycle/regime candidates、Kronos failed checkpoints。
- [x] 所有 M29.1 工具默认只读：不写 DB、不调 LLM/API、不保存模型、不改配置；产物优先写 `/private/tmp` 或 `~/.stock-sage`，不新增通用 planning 文件。

**验收**：新 AI 只读 ledger 即可判断每条 M27/M29 alpha 线索为何未晋升、下一次 forward 更新该跑什么命令、何时必须停下找用户确认。

> 2026-05-31 M29.1 首版完成：新增 `backend.tools.m29_evidence_ledger`，默认聚合 `~/.stock-sage/m27_top_decile_forward_shadow_{1,3,5}d.json`、`/private/tmp/m27_forward_shadow_rolling_20260401_20260529_{1,3,5}d.json`、M27.3 event/polarity v2 gate、M27 label/objective gate 与 `~/.stock-sage/m26_kronos_report.json`。首轮只读验证输出 `/private/tmp/m29_evidence_ledger_test.{json,md}`，artifacts_parsed=11、entries=12、gate_pass_count=0、promotable_count=0、non_promoting_count=12，promotion contract 仍为 IC≥0.04 / ICIR≥0.40 / monotonic=True / fresh forward / no data-quality blockers / human confirmation；缺失 source side-effect 字段会标记为 `unknown_boundary_flags` blocker，event/polarity entry 显式记录 cache/fallback 覆盖，label/objective entry 显式记录 short-cycle / multi-exit / segment 子证据摘要；新增最小 provenance contract，逐条记录 artifact sha256/mtime、panel/window/cutoff 可得字段，并把缺失的 `data_source`、`fetched_at`、`adjustment`、`universe_hash`、`train_label_realized_end` 标为 `missing_provenance_*` blocker；ledger 同时输出下一次 M29.3 forward shadow 命令模板；不写 DB、不调 LLM/API、不保存模型、不改生产配置。
>
> 2026-05-31 M29.1 shadow validation 接入：`backend.tools.m29_evidence_ledger` 已支持读取 `backend.tools.m29_shadow_validation` 产物；最新只读 smoke `/private/tmp/m29_evidence_ledger_with_shadow_validation.{json,md}` 纳入 `top_decile_entry_timing_v1` 后 artifacts_parsed=12、entries=13、gate_pass_count=0、skipped_artifacts=0，仍全部 non-promoting，生产配置不变。
>
> 2026-06-01 M29.1 post-event shadow validation 纳入：`backend.tools.m29_evidence_ledger` 默认加入 `/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.json`；复跑输出 `/private/tmp/m29_evidence_ledger_with_post_event_shadow.{json,md}`，artifacts_parsed=13、entries=14、gate_pass_count=0、promotable_count=0、non_promoting_count=14、skipped_artifacts=0。新增 entry 记录 `post_event_drift_pure_polarity_v1` 的 IC=0.180828 / ICIR=0.549296、ic_days=29、top_bottom=0.018281、quantile_monotonic=false、candidate_count=2 与 multiple-comparison warning，仍为 non-promoting。

### M29.2 新 Alpha 假设预注册（P0）

- [x] 建立候选假设清单，优先从 M27 暴露出的结构性线索出发：regime-conditioned alpha、行业内相对强弱、流动性/换手状态、事件后 drift 路径、top-decile filter 的入场时机。
- [x] 每条假设必须先写清：动机、样本范围、训练/验证/OOS 切分、目标 horizon、候选特征、预期失败条件、最小样本门、production gate。
- [x] 明确多重比较规则：同一轮候选数量、Bonferroni/FDR 或至少 explicit warning；没有该字段的报告不能作为晋升证据。
- [x] 禁止直接把 M27 的 `raw_20d_top_decile_classifier`、pure polarity、event overlay 或 Kronos checkpoint 作为 production candidate；它们只能作为 shadow/research candidate。

**验收**：每个新实验在运行前已有可审计 hypothesis spec；实验失败后能沉淀为 ledger，而不是继续口头追线索。

> 2026-05-31 M29.2 首版完成：新增 `backend.tools.m29_hypothesis_registry`，默认生成 5 条预注册 shadow research candidate：`regime_low_vol_alpha_v1`、`intra_industry_relative_strength_v1`、`liquidity_turnover_state_v1`、`post_event_drift_pure_polarity_v1`、`top_decile_entry_timing_v1`。每条均包含 M27 source clues、sample gates、fresh OOS/forward split、non-overlapping stride 要求、multiple-comparison policy、stop conditions 与 forbidden actions；首轮只读验证输出 `/private/tmp/m29_hypothesis_registry_test.{json,md}`，validation_passed=true，生产继续 `weight_quant=0.0` / `kronos_enabled=false` / signal profile 不变。
>
> 2026-05-31 M29.2/M29.3 首条 shadow validation：新增 `backend.tools.m29_shadow_validation`，先支持 `top_decile_entry_timing_v1`，读取既有 1d rolling forward shadow `/private/tmp/m27_forward_shadow_rolling_20260401_20260529_1d.json` 并按 registry 样本门输出 `/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.{json,md}`。当前 filtered_trades=99、positive_rolling_windows=7，样本门通过；但因仍是 M29 预注册前旧 artifact，且缺 `data_source` / `fetched_at` / `adjustment` / `universe_hash` / `train_label_realized_end` provenance，报告保留 `post_registration_fresh_forward_missing`、`not_continuous_quant_score`、`shadow_validation_non_promoting` blockers，`gate_pass=false`、`promotable=false`、生产不变。
>
> 2026-06-01 M29.2/M29.3 第二条 shadow validation：`backend.tools.m29_shadow_validation` 支持 `post_event_drift_pure_polarity_v1`，默认读取 `/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.json` 并输出 `/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.{json,md}`。该只读包装确认 cache_miss_windows=0、rows_with_fallback_polarity=0、universe_symbols=100、validation_rows=1010，样本门通过；但 pure polarity 与 polarity+event 均不单调，且仍缺 post-registration fresh forward 与旧 source provenance，blockers 包含 `pure_polarity_not_monotonic`、`polarity_event_not_monotonic`、`post_registration_fresh_forward_missing`、`shadow_validation_non_promoting`，`gate_pass=false`、`promotable=false`、生产不变。

### M29.3 Forward Shadow 自动延长（P1）

- [x] 自动/半自动延长 forward shadow 的执行闭环已补齐：ledger 可发现最新 `/private/tmp/m29_forward_shadow_rolling_*_{1,3,5}d.json`，并可用 `--forward-end YYYY-MM-DD` 渲染下一轮 1d/3d/5d rolling 命令。
- [x] 新 forward artifact 的 provenance producer / audit 路径已补齐：后续新产物应写出 `universe_hash`、`train_label_realized_end` 与 price provenance；旧 artifact 不猜测回填，缺口继续作为 blocker。
- [x] 新增 read-only forward readiness guard：`backend.tools.m29_forward_readiness` 只判断完整交易日与 future-return 覆盖是否足以运行下一轮 1d/3d/5d bundle，不写 DB、不调 LLM/API、不训练、不运行 forward shadow。
- [x] 新增 close-confirmed price/provenance refresh：`backend.tools.m29_price_coverage_refresh` 默认 dry-run，必须 `--execute` 才写 `prices`，且默认拒绝写入今日 partial bar。
- [ ] 新增完整 forward evidence 尚未追加：当前 rolling 只延至本地最新 2026-05-29，本轮不把 2026-06-01 partial local data 当作新 forward evidence；等完整新增交易日与 future-return 覆盖后再跑 1d/3d/5d rolling。
- [x] pure polarity / event overlay 首轮只读复核已纳入 M29 shadow validation；后续需要真实 `sentiment_cache` 写入或 LLM 调用时仍先汇报。
- [ ] 样本门继续保守：filtered trades < 50 不引用 Sharpe，IC days 不足不引用 ICIR 稳定性，分位不单调不能晋升。

**验收**：forward shadow 延长机制已可执行；只有在完整新增交易日与 future-return 覆盖后，才追加新 forward evidence。每次更新都必须保持 non-promoting / production_unchanged，直到完整 promotion gate 与人工确认同时满足。

> 2026-05-31 M29.3 接手约束：当前 rolling forward shadow 已延至本地最新 2026-05-29；2026-05-31 为周日，尚无更新交易日可安全延长。下一次新增行情后，先用 `backend.tools.m29_evidence_ledger` 查看 `next_forward_commands`，再分别跑 1d/3d/5d rolling；新 artifact 必须进入 ledger，并优先补齐 data source / fetched_at / adjustment / universe hash / label realized cutoff provenance。若需要刷新行情、写 DB、真实写 `sentiment_cache` 或调用 LLM/API，先停下汇报。

> 2026-06-01 M29.3 执行闭环补强：`backend.tools.m29_evidence_ledger` 默认会自动发现 `/private/tmp/m29_forward_shadow_rolling_*_{1,3,5}d.json` 中每个 exit horizon 的最新 artifact，避免未来新 forward shadow 跑完后还要手工重复传 `--artifact`；新增 `--forward-end YYYY-MM-DD` 可把 `next_forward_commands` 中的日期占位符渲染成可直接执行的 1d/3d/5d 命令。本轮不把 2026-06-01 partial local data 当作新 forward evidence，等完整新增交易日与 future-return 覆盖后再跑。

> 2026-06-01 M29.3 readiness guard：新增 `backend.tools.m29_forward_readiness`，默认只读检查 latest forward artifact end、test3 universe 覆盖、完整交易日数量与 1d/3d/5d future-return 安全 end；只有三条 exit horizon 都具备完整新增覆盖时才输出下一轮 `next_forward_commands`，否则输出 blockers 且不运行 forward shadow。CLI smoke `/private/tmp/m29_forward_readiness_finish_smoke.{json,md}` 确认当前默认无 DB 参数时 `ready_to_run_forward_shadow=false`、commands=[]、生产不变。

> 2026-06-01 M29.3 live readiness check：使用真实 SQLite 只读跑 `backend.tools.m29_forward_readiness --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db`，输出 `/private/tmp/m29_forward_readiness_live.{json,md}`。结果仍为 `ready_to_run_forward_shadow=false`、commands=[]；latest_price_date=2026-06-01，但 test3 universe 当日仅 10/100 支有价格，2026-05-27~2026-05-29 为 94/100 支且仅 25 支具备完整 price provenance；blockers=`no_new_complete_1d_forward_coverage`、`no_new_complete_3d_forward_coverage`、`no_new_complete_5d_forward_coverage`、`partial_latest_trading_day_after_last_artifact`。本轮不运行 forward shadow；若要刷新行情或补齐 DB，需要先按 M29 stop condition 汇报/确认。

> 2026-06-01 M29.3 close-confirmed refresh：新增 `backend.tools.m29_price_coverage_refresh`，默认 dry-run，`--execute` 仅刷新显式日期窗口的 `prices` 行，并默认拒绝写入今日 partial bar。获准后执行 2026-05-27~2026-05-29 close-confirmed refresh，输出 `/private/tmp/m29_price_coverage_refresh_execute_20260527_20260529.{json,md}`：100 symbols attempted、0 errors、300 rows written，三天均达到 100/100 price provenance complete；复跑 readiness 到 `/private/tmp/m29_forward_readiness_after_price_refresh.{json,md}` 后仍 `ready_to_run_forward_shadow=false`、commands=[]，因为 2026-06-01 仍为 10/100 partial 且 1d/3d/5d future-return 覆盖尚未形成。本轮不运行 forward shadow、不追加 fresh evidence。
>
> 2026-06-01 M29.3 follow-up readiness：按接手目标继续只读跑 `backend.tools.m29_forward_readiness --db-url sqlite:////Users/zeeechenn/stock-sage/stock-sage.db`，输出 `/private/tmp/m29_forward_readiness_next_20260601.{json,md}`。结果仍为 `ready_to_run_forward_shadow=false`、commands=[]；latest_existing_forward_end=2026-05-29，latest_complete_price_date=2026-05-29，2026-06-01 仅 13/100 支有价格。blockers=`no_new_complete_1d_forward_coverage`、`no_new_complete_3d_forward_coverage`、`no_new_complete_5d_forward_coverage`、`recommended_forward_end_not_after_all_existing_artifacts`、`partial_latest_trading_day_after_last_artifact`。本轮不运行 forward shadow、不追加 fresh evidence。

> 2026-06-01 M29.3 pure polarity / event overlay 只读复核：在不新增真实 `sentiment_cache` 写入、不调 LLM/API 的前提下，用 `backend.tools.m29_shadow_validation --hypothesis-id post_event_drift_pure_polarity_v1` 包装既有 v2 gate artifact。结果写入 `/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.{json,md}`：cache/fallback 已清零、样本门通过，但 pure polarity 与 polarity+event 均 `monotonic=False`，且缺 fresh forward / old artifact provenance，不能晋升。

> 2026-05-31 M29.3 provenance producer 补强：`backend.tools.m27_top_decile_forward_shadow` 后续新产物会写出 `universe_hash` 与 `train_label_realized_end`，rolling 报告会汇总 `train_label_realized_end_range`；既有历史 artifact 未回写，ledger 会继续把旧产物的 provenance 缺口标为 blocker。`backend.data.qlib_data.build_training_data` 已把 price row 的 `_price_source` / `_price_fetched_at` / `_price_adjustment` 带入训练面板，`backend.tools.m27_label_objective_eval` 已把 panel cache 升到 version 2 并在 panel meta 输出 `price_provenance` 覆盖率；`backend.tools.m29_evidence_ledger` 会读取 `panel.price_provenance`，若未来新 artifact 仍有缺口则标记 `panel_price_provenance_incomplete`。旧 DB 行的来源仍不猜测回填。

> 2026-05-31 M29.3 provenance audit 首版：新增 `backend.tools.m29_provenance_audit`，只读检查 daily price / index price schema 与 M29 ledger artifact provenance；`backend.data.database.Price` / `IndexPrice` 已新增 nullable `source` / `fetched_at` / `adjustment`，`backend.data.market.fetch_daily` / `fetch_cn_index` 会把 provider provenance 写入 DataFrame attrs，`backfill_if_needed` / `sync_index_to_db` 会写入未来新增行情。已对本地 SQLite 执行轻量 runtime schema patch（只加 nullable 列，不回填旧数据、不刷新行情）。最新 smoke 输出 `/private/tmp/m29_provenance_audit_with_post_event_shadow.{json,md}`：`prices` / `index_prices` / `market_snapshots` schema blocker 已清零；当前 14 条 ledger entries 仍有历史 artifact provenance 缺口（artifact hash 与 generated_at 可证明，旧 daily source/fetched_at/adjustment 与旧 universe_hash 不可证明）。结论：M29 可以继续收集 forward evidence，但旧 artifact provenance blocker 清零前不得进入 promotion review；未来新增行情应自然带 provider provenance。

### M29.4 Promotion Contract（P1）

- [x] M29 所有候选沿用同一生产 gate：IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调。
- [x] 晋升前必须同时满足 fresh OOS/forward、非重叠稳定性、多重比较披露、data-quality blockers 清零、人工确认。
- [x] 任何恢复 `weight_quant`、修改 signal profile、接入 checkpoint、覆盖 checkpoint、继续更长 Kronos training、真实写 `sentiment_cache` 的动作都必须先停下汇报。
- [ ] 当前没有候选进入 promotion review：尚无 post-registration fresh forward 证据，历史 artifact provenance blocker 未清零，不能声明 production alpha success。

**验收**：promotion contract 与工具侧校验已固化；M29 当前只能产出 shadow / non-promoting research evidence，不能绕过生产 gate、人工确认，或声明 production alpha success。

> 2026-06-01 M29.4 contract hardening：`backend.tools.m29_hypothesis_registry.validate_registry` 现在会校验完整 promotion gate 字段：IC、ICIR、stride ICIR、monotonic、fresh OOS/forward、data-quality blockers 清零和人工确认；`backend.tools.m29_evidence_ledger` Markdown 也会渲染 Promotion Contract，避免只在 JSON 中可见。该补强不改变生产配置、不恢复 quant、不产生 promotable artifact。

### M29.5 Quant Residual Attribution / Interaction Audit（P0 下一步）

**目标**：回答“量化负向影响来自策略/label、数据不足，还是新闻/技术面交互”这个因果问题；只做 attribution 与 shadow evidence，不恢复 `weight_quant`，不修改 production signal profile。

- [ ] 先跑 readiness：每轮先用 `backend.tools.m29_forward_readiness --db-url ...` 确认完整新增交易日与 1d/3d/5d future-return 覆盖；未 ready 时不运行 forward shadow、不追加 fresh evidence。
- [x] 单变量 quant sweep：固定 entry threshold 与 tech:sent 比例，只改 `Q=0 / 0.225 / 0.45`，比较入场集合、收益、回撤、max positions 下的边缘持仓差异，避免把阈值变化误归因为量化。
- [x] 逐笔 attribution：对 quant_on 与 quant_off 差异交易记录 `composite_with_quant - composite_without_quant`、是否跨 entry threshold、后续 1d/3d/5d/10d 收益与相对沪深 300 超额收益。
- [x] 残差 IC：在同一 forward window 下分别评估 `technical only`、`sentiment/event only`、`T+S`、`quant only`、`T+S+quant`，再看 quant 对 `T+S` 残差收益是否有增量 IC / ICIR / monotonic。
- [x] 交互分桶：按强/弱技术面、正/负情绪、event/no event、low/high volatility 分桶测 quant IC、top-bottom 与分层单调；若只在特定状态有效，转入 M29 预注册的 regime-conditioned 或 post-event drift 假设。
- [x] 输出接入 ledger：所有 attribution/sweep/residual 结果必须写为 shadow artifact，并被 `m29_evidence_ledger` 纳入；未满足 fresh forward、stride ICIR、monotonic、provenance 与人工确认前，结论只能是 non-promoting。

**验收**：能把“量化是否有独立残差信息”与“融合/阈值是否放大噪声”分开判断；若 residual IC 仍弱或非单调，继续保持 `weight_quant=0.0`，并把 top-decile 只作为离散 entry filter 研究线索。

> 2026-06-01 代理团队结论落地：当前更支持“量化策略/label/objective 与连续 score 形态未站住”，数据不足是 forward readiness 与置信度 blocker，新闻/技术面不是压坏有效量化的主因。下一步不打开量化层，而是按 M29.5 做 fixed-threshold quant sweep、逐笔 attribution、residual IC 与交互分桶；只有证明 quant 对 `technical+sentiment/event` 残差有稳定正贡献，才进入后续 non-promoting train candidate 讨论。
>
> 2026-06-01 M29.5 首轮只读 attribution 完成：新增 `backend.tools.m29_quant_residual_attribution`，默认产物 `/private/tmp/m29_quant_residual_attribution_v1.{json,md}`，并扩展 `backend.tools.m29_evidence_ledger` 解析 `read_only_quant_residual_attribution` artifact。本轮使用当前 `lgbm_alpha_v1` 对 2025-11-01~2026-05-14 test3 universe 做 attribution-only quant score 重算（`lookahead_quant_warning=true`，不作为 PIT-safe promotion proof），signal_inputs=2600、rows_with_nonzero_quant=2596、1/3/5/10d forward/excess 覆盖均为 2600/2600。固定阈值 sweep：Q=0 trades=296、avg net=0.005543、Sharpe=0.450818、max drawdown=0.796891；Q=0.225 trades=70、avg net=0.004945、Sharpe=0.407800；Q=0.45 trades=31、avg net=0.008292、Sharpe=0.638303、但主要来自大幅减少交易数（dropped_by_quant=281、added_by_quant=16）。关键残差结果：5d `quant_residual_to_technical_sentiment` IC=0.018251 / ICIR=0.151156 / monotonic=False / gate_pass=False；ledger 复核 `/private/tmp/m29_evidence_ledger_with_quant_residual_v1.{json,md}` 为 entries=1、gate_pass_count=0、promotable_count=0，并保留 `historical_current_model_attribution_only`、`post_registration_fresh_forward_missing`、`stride_icir_missing`、`requires_human_confirmation`、`quant_residual_not_monotonic` 与 provenance 缺口 blockers。结论：量化可能有离散过滤价值，但未证明对 `technical+sentiment/event` 残差有可晋升的稳定连续 alpha；继续 `weight_quant=0.0`，等待 fresh forward 覆盖后再追加 evidence。

### 新对话执行交接（2026-06-01）

1. 先读 `STATUS.md § M29` 与本节，再运行 `git status --short`；不要回滚当前未提交的 M27/M29 工具、测试和文档更新。
2. 第一动作是 M29.3 readiness：只读检查完整新增交易日与 1d/3d/5d future-return 覆盖；未 ready 时停在等待状态，不把 partial local data 当 fresh evidence。
3. 第二动作是 M29.5：首轮 attribution artifact 已完成；fresh coverage ready 后在同一 forward window 上追加或复跑 fixed-threshold quant sweep、逐笔 attribution、residual IC 与交互分桶，再讨论任何小权重灰度。
4. 第三动作是把新增 shadow artifact 纳入 M29.1 ledger；若 ledger 仍有 `gate_pass_count=0` 或 provenance/data-quality blockers，保持 non-promoting。
5. 停止条件：任何步骤会改变生产信号、恢复 quant、接入 checkpoint、继续 Kronos 长训、真实写 `sentiment_cache`、下载新依赖或调用额外付费外部服务。

---

## M30 工程质量收敛【完成】🛠️

> 来源：2026-06-01 外部全栈评审二次核验。只纳入可复现、可定位、对后续开发有实际收益的发现；已判定为错误、过度表述或未证实的报告项不进入规划。

### M30.1 类型检查与 M29 工具收敛（P0）

- [x] 修复 `backend.tools.m29_evidence_ledger`、`backend.tools.m29_forward_readiness`、`backend.tools.m29_hypothesis_registry` 的 13 个 mypy 错误；验收命令显式使用可写 cache，例如 `--cache-dir /private/tmp/stocksage-mypy-cache`，避免把环境 cache 问题误判为代码问题。
- [x] 将 `make typecheck` / CI 的 mypy 输出保持为 0 error；若 mypy 版本升级导致行为变化，先固定工具版本或记录版本边界，再修业务类型问题。

> 2026-06-01 M30.1 完成：M29 ledger / readiness / registry 工具完成类型收窄；`PYTHONPATH=. .venv/bin/python -m mypy backend --ignore-missing-imports --no-incremental --cache-dir /private/tmp/stocksage-mypy-cache-main` 与 `make typecheck` 均为 0 error。

### M30.2 Python 依赖可复现（P0）

- [x] 引入 Python lock 流程（`uv lock` / `pip-compile` 二选一，按仓库实际工具链定），保留 `pyproject.toml` 作为声明源，CI 使用 frozen/sync 模式验证。
- [x] 对 akshare / efinance / tushare / yfinance 等易漂移数据源依赖设置可复现边界；升级依赖必须能通过 `make verify` 与关键数据源 smoke。

> 2026-06-01 M30.2 完成：新增 `uv.lock`；Makefile 增加 `python-sync`、`python-lock`、`python-lock-check`，CI 使用 `uv sync --frozen --extra dev` 与 `uv lock --check`。当前 lock 验证通过，后续数据源依赖升级仍必须走 `make verify` 与关键 smoke。

### M30.3 CI / 安全 / 覆盖率补强（P1）

- [x] 拆分 CI job：backend lint/typecheck、backend tests、frontend test/build；保留当前 `make verify` 已覆盖 `npm run build` 这一事实，不重复修一个不存在的 build 缺口。
- [x] 增加 pip cache、pytest coverage 输出与最小 coverage snapshot；先观察当前覆盖率，再决定阈值，避免一次性设置不可维护的硬门槛。
- [x] 增加依赖与安全扫描的低噪声入口：优先 `pip-audit` / `bandit` 或 `ruff --select S` 的分阶段策略；先用 per-file-ignore / noqa 处理确定误报，再把规则放进 CI。

> 2026-06-01 M30.3 主体完成：`.github/workflows/test.yml` 拆成 backend-quality、backend-tests、security、frontend 四个 job；Makefile 增加 cache-aware lint/typecheck/test、`coverage`、`security`、`dependency-audit`。当前 coverage snapshot 为 backend total 63%。`ruff --select S --exit-zero` 只作 advisory；`pip-audit` 已接入；历史 `efinance -> retry -> py` 链路在 2026-06-02 已通过 optional extra 与重锁解除，CI 暂设为 non-blocking 以保留分阶段观察。

### M30.4 核心路径专项测试（P1）

- [x] 不采用“9 个核心模块无直接单测”的原报告说法；现有 tests 已直接覆盖 `aggregator.py`、`pipeline.py`、`database.py`、`copilot.py` 等路径。M30 的真实目标是补更聚焦、更快反馈的专项测试。
- [x] 优先补 `backend/decision/aggregator.py`、`backend/agents/pipeline.py`、`backend/data/database.py` 三条核心路径的边界测试：信号聚合解释、pipeline 透传与降级、DB schema/runtime migration。
- [x] 次级补 `backend/api/routes/ai.py`、`backend/api/routes/system.py`、`backend/decision/memory_layered.py`、`backend/agents/researcher.py` 的 happy-path / auth-failed / degraded-input 测试。

> 2026-06-01 M30.4 完成：新增 `tests/test_core_aggregator.py`、`tests/test_core_pipeline.py`、`tests/test_core_database.py`、`tests/test_core_paths_worker_d.py`，覆盖 aggregator event override / quant blend、pipeline context merge / no-LLM trace、DB latest price isolation / session close、AI/system route auth/degrade、memory layered 与 researcher degraded input。

### M30.5 低噪声安全与代码气味修复（P1/P2）

- [x] 逐条处理当前可复现的 `ruff --select S608` 发现：`backend/agent/context.py` 的 table name 走白名单；动态 `IN (...)` 迁移到安全 bind 参数或补充精准 `noqa` 注释；不要把参数化 placeholder 误报升级为注入漏洞。
- [x] 处理当前可复现的 `S324` 非密码学 hash 使用：确认用途是 cache key / dedup 后，加说明性 `noqa`，或替换为 `blake2b(digest_size=16)`。
- [x] 处理当前可复现的 `S301` / `S310` 噪声：Qlib 模型持久化改为直接 `joblib` 依赖；非 CLI 外部探测与 Bark 通知改用 `requests`，保留超时、错误降级与响应大小限制。
- [x] 对非 CLI 库代码中的 `print()` 分批替换为 logger / 审计保留：当前剩余 `print()` 均在 `__main__`、agent CLI、tools、backtest 或手动报告输出路径，属于刻意的命令行输出，暂不为 lint 做 churn。
- [x] Python dependency audit debt：`efinance` 已从默认依赖移到 optional extra，CN 日线与指数 provider 仅在安装后注册；`pytest` 升至 9.0.3 并重锁 `uv.lock`，当前 `make dependency-audit` 无已知漏洞。
- [x] npm audit debt：Vite 已小步升到 6.4.3，避开 `vite <=6.4.1` / `esbuild <=0.24.2` advisory；`@vitejs/plugin-react` 约束同步到 v4.7，未使用 `npm audit fix --force` 跳 Vite 8。

> 2026-06-02 M30.5 首轮完成：Python 依赖已补上限并同步 `uv.lock`；`ruff check backend --select S301,S310,S324,S608` 通过；新增 focused tests 覆盖 external source requests size guard、Bark requests retry、market OHLCV normalize、CN news dedupe/CST、Qlib joblib roundtrip 与 stock memory bound params。`make verify` 通过，backend coverage snapshot 升至 64%。

> 2026-06-02 M30.5 依赖审计收口：`efinance` 改为 optional extra（默认安装不再带入 `retry -> py`），provider registry 在未安装时跳过 `efinance_cn` / `efinance_index_cn`，并补充 daily/index fallback focused tests；`pytest` 升至 9.0.3。当前 Python lock check 与 `make dependency-audit` 通过。前端随后小步升级到 Vite 6.4.3 / `@vitejs/plugin-react` 4.7，`npm audit` 为 0 vulnerabilities，未使用 force 跳 Vite 8。

### M30.6 可维护性拆分（P2）

- [x] 新增前端 advisory lint/format 入口：`make frontend-lint` 与 `make frontend-format-check` 可单独运行，先不并入 `make verify`，避免大规模格式化 churn。
- [x] `frontend/src/pages/AdminPage.jsx` 可维护性拆分：2026-06-02 已抽出 `adminPageUi.jsx` / `adminPageConstants.js` / `adminPagePanels.jsx`，页面主体从 992 行降到约 391 行，`AdminSettingsPanel` 与 sidebar cards 保持展示职责，`AdminPage.jsx` 保留 state/API 容器职责；前端 lint、node tests 19 passed、Vite build 通过。
- [x] `paper_trading/test2_ab_runner.py` 是 A/B 验证核心：2026-06-02 已抽出 `test2_ab_models.py`（常量、dataclass、framework 与 composite），并按 data / stats / report / runner / cli 完成本地 ignored 材料拆分；runner 仍作为兼容入口且降到约 254 行，selftest 6 passed，固定 `--end 2026-06-01` 生成的 replay JSON 与 `paper_trading/test2_ab_state.json` 无差异。

### 不纳入 M30 的外部报告项

- `EVIDENCE.md` 路径错误：当前实际证据文件是 `/Users/zeeechenn/stock-sage-review/raw-data.md`；不把缺失路径写成项目问题。
- “CI 没跑 `npm run build`”为错误结论；当前 `.github/workflows/test.yml` 跑 `make verify`，而 `make verify` 包含 frontend build。
- “9 个核心模块无直接单元测试”为过度表述；改为 M30.4 的专项覆盖补强。
- “agent_mode decorator / kwargs symbol XSS”未找到对应代码，不作为修复项；若未来发现真实渲染风险，再以具体 file:line 建任务。
- “S324 有 58 处 sha1”与当前复现不符；按实际 `ruff --select S324` 结果处理。
- “docs/reviews 有 16 篇”与当前仓库不符；不基于这个数字建立整理任务。
- “pre-commit 只有 ruff”不准确；当前已有基础 pre-commit hooks，M30 只补 mypy/安全等缺口。

**主体验收（2026-06-01 / 2026-06-02 更新）**：M30.1-M30.4 已完成；M30.5 已完成低噪声安全修复、Python / npm dependency audit debt 与非 CLI print 审计；M30.6 已完成前端 advisory lint/format 入口、AdminPage 展示组件拆分，以及本地 test2 A/B runner 的 data / stats / report / runner / cli 拆分。最新 `make verify` 后端与前端测试通过，frontend build 在沙盒外写入 Vite temp config 后通过；mypy、Python lock/frozen install、核心路径专项测试、coverage、低噪声安全扫描、Python dependency audit、npm audit、前端 lint/test/build 与 test2 固定日期 replay diff 都能复现。M30 当前无剩余规划项；后续优先级回到 M29 fresh forward evidence。

---

## M31 工程化与产品化借鉴（StockInsight 对标）🧰

> 来源：2026-06-02 评估小红书博主 @我在偷偷学AI 的周末项目 StockInsight v3.0（50 模块 / 16k 行 / 5,220 只 A 股）。
> 仅借鉴其**工程表达与产品化**长处，**明确不引入**其预测型卖点（AI 预测涨跌方向、Strong Buy/Sell 评级、ML 集成投票当作预言）——后者与 `AGENTS.md` 的"不把价格当确定性预测、不鼓励 strong buy"约束冲突，且本项目 promotion gate（M26/M27）已主动否决该类候选（`WEIGHT_QUANT=0.0`）。
> 优先级低于 M29（forward evidence）/ M30（工程收敛），按 P2/P3 排期。

### M31.1 显式三级缓存与延迟基准（P2）

- [x] 把当前散落在 `backend/data/database.py` / `external_sources.py` 的缓存读路径抽象成命名的三层：L1 进程内内存 → L2 本地 SQLite → L3 远端 API 增量，单一入口、命中层可观测。
- [x] 给出"盘中零网络调用"的显式保证：盘中分析只读 L1/L2，L3 仅在盘后/增量补齐时触发。
- [x] 新增只读 benchmark 脚本（`backend.tools.*_benchmark`），产出全市场扫描耗时、单股分析耗时、各层命中延迟，写 `/private/tmp` 或 `~/.stock-sage`，并在 README 公布一组实测 SLA。

> 2026-06-02 M31.1 完成：新增 `backend.data.cache_policy`，统一输出 L1/L2/L3 cache layer、交易时段 workflow policy、盘中 zero-network contract 与 freshness contract；`backend.tools.m31_cache_benchmark` 默认只读、默认不触发 L3 远端 API，输出 `/private/tmp/m31_cache_benchmark*.{json,md}`。live baseline（20 iterations，本地 SQLite）为 L1 p50≈0.0001ms、L2 单股 latest price p50≈0.0982ms、L2 全市场 count scan p50≈18.8607ms；README / README_EN 已同步 SLA。沙盒不能打开 SQLite WAL 时，benchmark 会把 L2 标为 `measured=false` 而不是误触发远端。

### M31.2 数据源有序容灾链 + 按数据类型分新鲜度层（P2）

- [x] 在 `backend/data/providers.py` 把多源 fallback 显式编码为**有序优先级链**（含每条源的失败降级与 observe-only 标记）。
- [x] 为每类数据声明刷新频率 / TTL / staleness 容忍度（实时行情秒级、资金流 T+1、基本面季报、行业板块季度），并在 health/coverage 快照里暴露"某类数据当前新鲜度"。

> 2026-06-02 M31.2 完成：`DailyProvider` / `IndexProvider` 增加 `data_type`、`observe_only` 与 chain metadata，observe-only provider 会被 fallback 跳过并计入 skipped；`register_default_market_providers()` 可在不发网络请求时注册默认 chain；`build_data_coverage_snapshot()` / `/api/system/data-coverage` 通过 schema 暴露 `cache_policy`、`freshness_contract`、`intraday_zero_network_policy` 与按 market 展开的 `provider_fallback_chains`。

### M31.3 按交易节奏的命令 UX（P2）

- [x] 把现有 Pi 终端 / CLI 能力按"盘前 / 盘中 / 盘后 / 周末"打包成少数几条一句话命令（如盘前自检、盘中快速个股、盘后全市场入库 + 复盘报告、周末长期标签刷新 + 周度反思），降低入口心智负担。
- [x] 命令只做编排，复用现有 `backend.agent.cli` 子命令，不新增分析逻辑。

> 2026-06-02 M31.3 完成：`backend.agent.cli` 新增 `premarket` / `intraday` / `postmarket` / `weekend`（含中文 alias `盘前` / `盘中` / `盘后` / `周末`），默认只输出 dry-run orchestration JSON，列出 reused entrypoints、side effects、confirmation_required 与 cache policy，不执行重型 job；`weekend` 复用 `job_weekly_longterm` / `job_weekly_long_term_reflect` 并按 maintenance 口径允许 L3（`REMOTE_REFRESH_PHASES` 增加 `weekend`）；`scripts/stocksage_launcher.sh` 同步支持 `stocksage premarket|intraday|postmarket|weekend` 薄封装。

### M31.4 一键多端报告输出（P3）

- [x] 扩展 `backend/api/routes/exports.py`：盘后一条命令生成可分享的复盘报告（Word-compatible / HTML），证据卡 / 信号 / 持仓复盘随报告导出。
- [x] 报告显式标注 rule/profile 版本与"研究复盘，非投资建议、非价格预测"声明。

> 2026-06-02 M31.4 完成：`/api/export/postmarket-review.html?as_of=YYYY-MM-DD`（含 `?format=word` 的 Word-compatible `.doc` HTML）导出 report_version、rule/profile version、当日信号表、**逐信号证据卡**（量化/技术/情感分解 + 止损/止盈 + LLM rationale，按综合分取前 10）、**持仓复盘段**（当前持仓含现价与浮动盈亏 + 当日平仓的已实现盈亏）与“研究复盘，非投资建议、非价格预测”声明。report_version 升至 `m31_postmarket_review_v2`；未引入 `python-docx` 或新依赖。新增 `test_export_postmarket_review_html_includes_evidence_cards_and_positions` 覆盖。

---

## M42 价格复权口径(qfq/hfq)污染防护与修复【complete】🧹

> 来源：ATLAS Gate-B 前瞻跟踪发现约 30% 的 5 日前瞻收益不可信（|net|>1.5）。根因：2026-05-25/26 有约 52 个标的的后复权(hfq)收盘价被写入 prices 表且 `adjustment=NULL`，与 qfq 行无法区分，导致 qfq 入场价 / hfq 退出价产生 100–330x 伪收益。`adjustment` 列历史上 99.94% 为 NULL，无法按标签过滤。

- [x] 写入时护栏：`backend/data/price_quality.py:check_adjustment_basis_jump`（close > 3×前10中位数即判为污染）+ `PriceQualityPolicy.adjustment_jump_ratio`；接入 `backend/data/market.py:backfill_if_needed`，写库前跳过污染行（下次 backfill 以 qfq 重抓）。`evaluate_price_quality` 与打分逻辑不变。
- [x] 一次性修复 CLI：`backend/tools/m42_remediate_hfq_contamination.py`（dry-run 默认、删前 `shutil.copy2` 备份、拒绝生产路径、原生 sqlite3、跑到 0 行；级联需 2 遍收敛）。
- [x] 线上修复：删除 2026-05-25/26 共 84 行混合口径污染行（恢复备份 `~/.stock-sage/backups/stock-sage.db.bak.20260603_174914`）；真实判据复检 0 残留；周边日期 (05-22/05-27) 行数不变。新增 33 个 hermetic 测试，全量 754 passed。
- [x] 整条 hfq 标的修复（2026-06-04）：600519(茅台)/600601/600602 三只整条序列为 hfq（茅台 ¥9,108、600601 ¥151,341、600602 ¥10,767），删整条 + 经项目 backfill 链 qfq 重抓（years=6，源 tickflow_cn，adjustment 标签已填）。修后茅台 ¥1,268、600601 ¥12.62、600602 ¥18.35；全库 max close>10000 清零；OHLC 自洽；备份 `~/.stock-sage/backups/stock-sage.db.bak.20260604_203532`。

> 编号说明：M33–M40 属 ATLAS 研究架构分支（codex/atlas），主线 M32→M41 跳过了 M33–M40；M42 衔接 M41 之后，两分支编号无冲突。

---

## M43 架构边界硬化与行为等价重构【complete】🧱

> 来源：2026-06-04 代码架构复盘。项目整体不是单文件式“屎山”，但 `market.py`、`database.py`、`api/routes/ai.py`、`scheduler.py` 已经开始变厚；M43 采用兼容 facade + characterization tests，而不是推倒重写或拆微服务。

- [x] Market facade：`backend.data.market` 保留 public imports、provider 注册顺序、fallback、adjustment attrs、M42 写入 guard；实际 helper 拆到 `market_utils.py`、`market_sources.py`、`market_persistence.py`。
- [x] Runtime schema / seed：`database.py` 保留 ORM models、session、`get_db`、`init_db` 与兼容私有入口；启动时 schema patch 和默认 seed 分别落到 `schema_runtime.py` / `seed.py`。
- [x] News cycle cleanup：`RawNews` 迁到 `news_models.py`，`news.py` 与 `news_audit.py` 不再形成真实双向依赖。
- [x] AI route split：`api/routes/ai.py` 保留 HTTP/SSE、pending/confirm 和旧测试 wrapper；自然语言 action 解析、chat store、确定性回答构建分别落到 `agent/action_parser.py`、`memory/chat_store.py`、`agent/chat_responder.py`。
- [x] Scheduler split：`scheduler.py` 保留 scheduler 生命周期、job state、tracked jobs、kill-switch guard、cron schedule 与旧 monkeypatch 接缝；实际 job workflows 拆到 `backend/jobs/`。
- [x] Architecture guard：新增 AST 级 `tests/test_architecture_boundaries.py`，硬门禁只检查顶层 backend import graph、API routes 顶层 heavy-provider imports、核心 facade 行数，避免误伤有意 lazy import。

> 2026-06-04 M43 完成：`market.py` 从约 659 行降到 179 行，`api/routes/ai.py` 从约 657 行降到 344 行，`scheduler.py` 从约 858 行降到 352 行，`database.py` 从约 718 行降到 452 行。生产信号、provider 优先级、API URL/response、SSE 顺序、scheduler job id/时间表、`WEIGHT_QUANT=0.0` 均未改变。
> 验证：ruff、mypy、759 个 backend tests、19 个 frontend node tests 通过；集成 `make verify` 到 Vite build 步骤时因沙盒无法写 `frontend/node_modules/.vite-temp` 报 `EPERM`，随后在正常文件权限下单独 rerun `npm --prefix frontend run build` 通过。

---

## M44 Atlas 合并与 L0-L4 主架构升级【active / Phase 0】🧭

> 来源：2026-06-04 Atlas 合并规划。Atlas 不是主项目旁边的独立功能区，而是 `main` 的下一代架构候选；首个合并目标是工程安全落地，不是让新策略行为立刻影响正式信号。外部 `PLAN (2).md` 已被压缩进本节，后续 AI 以本节和 `STATUS.md` 为接手入口。
>
> 当前入口事实（执行前必须重新核验）：主仓计划先让 `codex/m43-architecture-boundaries` 合入 `main` 并建立 `pre-atlas-m43-baseline`；Atlas worktree 为 `/Users/zeeechenn/Documents/项目s/atlas` 的 `codex/atlas`；测试2保持 frozen baseline，不中途改口径。

### M44.0 合并原则与已锁定决策

- **工程合并 gate**：判断 Atlas 架构代码能否进入 `main`。合并当天必须生产行为等价、默认休眠、可回滚。
- **投资效果 gate**：判断 Atlas 新行为能否影响正式信号、仓位、止损或未来自动交易；只看 shadow/test4 数据，不用工程合并结果替代投资证据。
- 首次 Atlas 合并必须是 dormant merge：总闸默认关闭，例如 `ATLAS_ENABLED=false` / `atlas_research_enabled=false`；official signal、test2、test3、标的1、scheduler/postmarket 不经过 Atlas 新逻辑。
- 分模块 flag 只能是二级开关，不能替代 Atlas 总闸；总闸也不能替代 migration、runtime schema、依赖、共享 helper 的单独 gate。
- 首次合并只允许 additive / non-destructive migration：新增表、nullable 新列、非破坏性 index、idempotent runtime schema patch；禁止删除/重命名旧表旧列、重写 live 旧行、改变既有字段语义或加不兼容约束。
- Atlas 不能用 tip 覆盖主线，只能在 M43 后的 `main` 上 rebase/重放增量；每次 `main` 有 test2、scheduler、database、official signal、M31/M41/M42/M43 相关非琐碎提交都要 re-sync。
- `Gate-B` 保留给现有 Atlas/M40 prospective tracker；L4 命名为 Review / Promotion / Calibration。
- 合并前范围只保留最小闭环：L0 最小 memory contract、L1/L2 case skeleton、一个只读 adapter/case view、memory promotion gate、Atlas 总休眠开关、行为等价验证和回滚 runbook。

### M44.1 Phase 0：固定主线基准，先合 M43（P0 当前入口）

目标：让 `main` 先拥有 M43 架构边界硬化，成为 Atlas rebase 的唯一真实基准。

- [ ] 确认主仓当前分支为 `codex/m43-architecture-boundaries` 或等价 M43 分支，worktree 干净，且相对 `main` 只有 M43/文档相关提交。
- [ ] 跑完整主仓 gate：`make verify`，并记录结果；若环境 cache 或 Vite temp 权限导致假失败，使用 `/private/tmp` cache 或正常文件权限复跑对应步骤。
- [ ] 固定 `--end` 重跑 test2 replay 到 `/private/tmp`，要求与 `paper_trading/test2_ab_state.json` 零 diff；不要改 `paper_trading/test2_ab_state.json`。
- [ ] 将 M43 合入 `main`，保留可追溯历史，不 push。
- [ ] 合并后建立 `pre-atlas-m43-baseline` 或同义 tag/branch。
- [ ] 合并后确认：production profile 仍是 `new_framework`，`WEIGHT_QUANT=0.0` 不变，test2 replay、test3 universe、标的1文件、official signal 行为不变。

停止条件：`make verify` 失败、test2 JSON diff 非零、`main` 有未纳入判断的反向提交、或 M43 分支出现非 M43 范围改动时，先停下归因，不进入 Atlas rebase。

### M44.2 Phase 1：Atlas rebase 到 M43/main

目标：把 Atlas 从过期分支变成基于当前主线的架构候选。

- [ ] 在 Atlas worktree 内 rebase/重放到 M43 后的 `main`，不让 Atlas 删除或覆盖 M31/M41/M42/M43 主线能力。
- [ ] 明确保护 main-only 文件：cache policy、global data、market capabilities、price quality、M43 facade/jobs/architecture guard 等。
- [ ] 重点处理冲突：项目文档、`backend/data/database.py`、`docs/ROADMAP.md`、API/schema、`pyproject.toml`、`uv.lock`。
- [ ] 重做 Gate-A merge-safety；旧 `ATLAS_MERGE_SAFETY.md` 只能作历史参考。
- [ ] 跑 `make verify`、migration focused tests、M43 reproduction focused tests；Gate-A 只表示可进入架构审查，不等于批准合并。

### M44.3 Phase 2-3：定稿 L0-L4 contract，并优先完成 L0

目标：先把“合并后主项目是什么”定死，再完成最小记忆/知识底座。

| 层级 | 名称 | 职责 | 首次合并边界 |
|---|---|---|---|
| L0 | Memory / Knowledge Base | 长期知识、用户规则、历史教训、A老师方法、专题研究沉淀 | 最小 memory contract；legacy 默认 pending / legacy_import_pending |
| L1 | Evidence Layer | 带来源、时间、PIT、质量状态的证据 | EvidenceCard / Dossier 只读映射 |
| L2 | Thesis Layer | 研究命题、主题假设、失效条件、持有周期 | ResearchCase / Thesis skeleton |
| L3 | Action / Signal / Position Layer | 入场、持有、仓位、止损、退出建议 | ActionProposal 只做 proposal/shadow，不接 official path |
| L4 | Review / Promotion / Calibration Layer | 结果复盘、归因、校准、记忆晋升 | ReviewCase / PromotionGate；LLM 不得自动写 trusted memory |

- [ ] L0 设计复审前不做不可逆 schema 决策。
- [ ] 梳理 `stock_memory_items`、`decision_memory_layered`、research memory、A老师 skill、专题研究报告、ReviewCase candidates、用户明确要求记住的规则/偏好。
- [ ] 定义 memory scope：stock、theme、sector、market/global、user preference、methodology/skill。
- [ ] 定义 trust 状态：raw、pending、trusted、refuted、archived、legacy_import_pending。
- [ ] ResearchCase 和 ActionProposal 召回 memory 时必须区分 trusted 与 pending；trusted 只走 human gate / ReviewCase promotion。

### M44.4 Phase 4-5：最小 adapter 与 dormant merge

目标：用一个最小 adapter 证明旧模块可进入新架构，然后把 Atlas 合入 `main` 但保持默认休眠。

- [ ] 首个 adapter 优先选择 deep_research 或已有 dossier，只读接入 `ResearchCase` / `EvidenceCard` / memory candidate，不影响 official signal。
- [ ] 实现 Atlas 总休眠开关；总闸关闭时新 routes/modules 返回 disabled/empty/manual-only 行为。
- [ ] 合并前必须通过：final re-sync、final Gate-A、`make verify`、test2 replay zero diff、canonical parity、official signal parity smoke、scheduler/postmarket parity smoke、additive migration review、DB migration copy-smoke、dependency/lockfile shared-infra review、API route smoke、memory promotion gate smoke、architecture import guard、Atlas dormant flag smoke、`git diff --check`。
- [ ] 行为等价标准：official signal、`WEIGHT_QUANT=0.0`、test2 replay、test3 口径、标的1、stop/take/position sizing、daily/postmarket 自动流程均不变；ActionProposal 只能 shadow/proposal，不自动执行。

### M44.5 Phase 6：合并后启动 Atlas shadow/test4

目标：用投资效果数据验证 Atlas 新行为，不污染测试2。

- [ ] 测试2继续 frozen baseline：原规则、原状态、原 A/B 目标、原 dependency path；Atlas 合并后的普通 PR 也不得改变 test2 replay、runner 输入、退出/入场规则、position sizing、signal loading 或 state JSON 口径。
- [ ] test4 指标、阈值、样本窗口、失败条件必须预注册；同窗口回放只能 diagnostic，不能作为 promotion proof。
- [ ] 第一阶段可用 test2 universe / 日期窗口 / 价格数据 / 基础 signal，Atlas 只生成 shadow overlay。
- [ ] 建议三臂：`test2_baseline`、`atlas_exit_overlay`、`atlas_entry_exit_overlay`。
- [ ] 指标至少包括收益、回撤、卖飞率、误杀趋势率、重新入场质量、proposal 命中率、机会成本、额外回撤和尾部风险；proposal 命中率必须预定义 horizon、label source、判定规则和样本不足处理。

### M44 回滚 runbook 摘要

- 合并前打 `pre-atlas-m43-baseline` 或同义 tag/branch，记录 production profile、`WEIGHT_QUANT`、scheduler job ids、test2 state hash、schema digest、关键 production table row counts、lockfile hash、fixed-fixture official signal 输出。
- Atlas merge 保留为可 revert 的 merge commit；不要 squash 成难以回滚的散乱提交。
- 常规回滚优先 revert merge commit 或切回 baseline；SQLite copy 只作灾难恢复，不作为常规 rollback，避免丢失回滚窗口内新增 live 数据。
- 触发回滚：schema drift、旧 production row 非预期重写、official signal drift、test2 canonical parity drift、scheduler/postmarket drift、trusted memory 非预期写入、总闸关闭时 production path 仍调用 Atlas 行为模块。

---

## M41 A/HK/US Global Data/Research Buildout【complete】🌐

> 来源：2026-06-03 评估“Global Stock Data / 港美市场数据 Agent Skill”参考视频。视频的可借鉴点不是单一接口，而是把分散入口封装成 agent 可调用的数据能力：quote / kline / fundamental / capital / options / filings / fallback，并明确数据源边界、字段与失效策略。本项目先接 daily price seed，不把未验证的 fundamentals/options/filings 直接并入研究或生产信号。

### M41.1 Daily Price Seed（P2）

- [x] HK daily OHLCV：`backend.data.market` 新增 `hk_yfinance_ticker()` 与 `fetch_hk_daily()`，并在 provider chain 注册 `yfinance_hk`（`auto_adjust`）。
- [x] US daily OHLCV：保留既有 `yfinance_us` provider，并用同一 fallback/provenance attrs 入口暴露。
- [x] API / agent / frontend 入口：watchlist、research prepare、positions 与本地 action schema 接受 `HK` alongside `CN` / `US`；A 股 fundamentals sync 仍只在 `market == "CN"` 时触发。
- [x] 验证：focused backend/API tests 与 frontend tests/build 通过；live read-only smoke 显示 `700 HK -> yfinance_hk`、`AAPL US -> yfinance_us`。

### M41.2 Provider Catalog And Probe Layer（P2）

- [x] 将参考视频的七层映射成 StockSage-owned catalog：`quote`、`kline`、`fundamentals`、`capital_flow`、`derivatives`、`filings`、`tools_fallback`，每层写明 market support、required fields、provider/stage、signal impact 与是否 production / seeded / observe-only / planned。
- [x] 在 `/api/system/data-coverage` 嵌入 A/HK/US per-market coverage、provider fallback chain、`summary.market_capability_catalog` 与 `production_signal_policy`；Admin 数据源面板展示三市场能力矩阵。
- [x] 加入 CN-only 官方信号边界：HK/US 可做 read-only research context，但 `research.prepare` 不把新 HK/US 标的激活为生产宇宙；postmarket batch、stop-loss check、long-term constraint label 与 `save_signal()` 都阻止已知 HK/US 进入官方信号链。
- [x] 为 HK/US 候选源先做 side-effect-free probes，不写 DB、不进入 production signal：US 覆盖 SEC submissions / companyfacts、yfinance basic info / options expiries；HK 覆盖 HKEXnews title-search reachability 与 yfinance basic info；CN 保留既有 ftshare / TickFlow / Tushare qfq / iFinD probe。
- [x] `/api/system/external-data-sources?probe=true&market=CN|HK|US&symbol=...` 返回 read-only probe results；默认 `probe=false` 仍不联网，所有新 probe payload 带 `write_policy=no_database_writes` 与 `signal_impact=none`。
- [x] 将 probe links 与 `/api/system/data-coverage` 的 `summary.market_capability_catalog` 做只读关联：每个 market/layer 能显示对应的 `probe_id`、`source_id`、默认 symbol、`write_policy` 与 `signal_impact`，但不自动运行 probe。
- [x] 将显式 probe 结果汇总为 `probe_summary`：按 market/layer/provider 输出 health、sample size、fields_present、required_fields、missing_fields、freshness_status；即使 required fields 已出现，也只标记 `required_fields_present`，并固定 `safe_for_research_scoring=false` / `safe_for_production_signal=false`。
- [x] 积累连续 health/freshness 样本的只读 ledger 入口已建立；字段归一化 / PIT/freshness gate 以 canonical schema 和 envelope 形式暴露，通过前不进入 research scoring 或 production signal。

### M41.3 Agent-Facing Skill Facade（P3）

- [x] catalog 先暴露 agent facade contract：routing keys、required output fields 与 fallback rule，作为后续 route/CLI 的稳定规格。
- [x] 新增只读 agent-facing route/CLI：`GET /api/system/global-data` 与 `python3 -m backend.agent.cli global-data` 按 `market + symbol + intent` 返回 quote/kline/fundamentals/filings/options/capital_flow/tools_fallback envelope。
- [x] 输出带 source、fetched_at、currency / timezone / symbol namespace、freshness_status、field_status 与 missing-field 说明。
- [x] 未通过 provider health、field normalization、PIT/freshness gates 前，不把 HK/US 非价格数据并入 composite_score、position sizing 或 production signal profile。

### 后续总规划（执行顺序）

> 目标：把 A 股现有体系升级成三市场通用的数据/研究工作台，同时让港股、美股先成为可审计的 read-only research context。任何进入交易评分、仓位、生产信号的动作，都必须先过数据质量、PIT、freshness、forward evidence 与人工确认。

#### M41.4 Probe Health Ledger（P1）

- [x] 为 `/api/system/external-data-sources?probe=true` 增加只读/低副作用 health snapshot 工具：`backend.tools.m41_probe_health_ledger` 按 market/source/layer/symbol 输出 ok rate、latency、sample size、field gaps、error class、checked_at。
- [x] 默认产物写 `/private/tmp` 或显式指定输出；若要写 DB 表、scheduler 自动跑、长期留存样本，仍先单独评估 schema 与调度影响。
- [x] 覆盖 CN/HK/US 代表 symbol：默认 probe target 为 CN `600519`，HK `700`/`9988`，US `AAPL`/`MSFT`；`--run-probes` 显式触网，默认可聚合已有 probe JSON。
- [x] 验收：能回答“哪个 market/layer/source 连续可用、字段缺什么、是否新鲜、是否只是偶发成功”；仍不产生 research score 或 signal input。

#### M41.5 Field Normalization And PIT Gates（P1）

- [x] 为七层分别定义 StockSage canonical schema：quote、kline、fundamentals、capital_flow、derivatives、filings、tools_fallback。
- [x] 为 HK/US 非价格层先做 parser/adapter contract，不直接写生产表：SEC filings/companyfacts、HKEX filings、yfinance basic/options 只输出标准字段与缺失说明。
- [x] 每个 envelope 带 source、fetched_at、market timezone、currency、symbol namespace、as_of/disclosure/published date、staleness、missing_fields。
- [x] PIT gate：任何 fundamentals/filings/capital_flow 在 decision date 之后披露的数据不得回填成当日可见信息；缺披露时间时只能作为 observe-only evidence。
- [x] 验收：adapter/context tests 覆盖 happy path、缺字段、时区/币种、provider error；未通过前不接入 scoring。

#### M41.6 Agent-Facing Global Data Route（P2）

- [x] 新增只读 route/CLI：按 `market + symbol + intent` 路由到 quote/kline/fundamentals/filings/options/fallback，不让 agent 临时拼外部接口。
- [x] 输出统一 envelope：`market`、`symbol`、`intent`、`source`、`fetched_at`、`freshness_status`、`field_status`、`missing_fields`、`write_policy`、`signal_impact`。
- [x] 对不可用数据返回 `unavailable` / `observe_only_unavailable` 和原因，不返回编造字段或 neutral 值。
- [x] 验收：agent 可以问“给我 AAPL filings context / 700 HK 基本面可用性 / 600519 资金面 probe”，系统返回可审计结果；仍为 read-only。

#### M41.7 A-Share Seven-Layer Upgrade（P1）

- [x] 把 A 股也按同一七层 facade 暴露，避免 A 股与港美股形成两套不可比接口。
- [x] 现有 CN production 层保持不变：daily/kline/technical/fundamentals/filings 按既有 provider 和 DB 运行；capital_flow/外部 evidence 先只读。
- [x] 给 A 股补同样的 field/freshness summary：让 Admin 与 agent 能看到每层数据是否 production、observe-only、planned、blocked。
- [x] A 股现有 composite_score 不因为七层 facade 自动改变；新增数据层若要进入评分，必须走 M29/M41.10 evidence gate。
- [x] 验收：A 股研究报告能引用统一 data envelope；旧 watchlist、postmarket、test2 replay 不变。

#### M41.8 HK/US Read-Only Research Context（P2）

- [x] 先做港股/美股单股 read-only context，而不是交易建议：daily bars、basic info、filings/options availability、source health、missing fields、currency/timezone caveats。
- [x] `research.prepare` 对 HK/US 继续保持 observe-only stock，不自动 active，不进入 postmarket batch。
- [x] 前端展示：港股/美股观察标的标明“观察”；缺数据通过 global-data envelope 明确显示缺口。
- [x] 验收：可以分析 HK/US 标的的数据可用性和研究问题，但不会给 official buy/sell、position sizing、stop/take。

#### M41.9 Global Portfolio/Watchlist UX（P2）

- [x] Watchlist / Positions / Admin 数据源面板支持三市场筛选、货币/交易所/时区提示、market-specific data coverage。
- [x] 持仓展示支持 HKD/USD/CNY 原币字段；涉及汇率、总资产折算、跨币种 P/L 时先停下单独评估，不在本阶段自动合并。
- [x] 增加 evidence cards/envelope：每个 HK/US context 展示 source、freshness、missing_fields、observe-only policy。
- [x] 验收：用户能把 HK/US 放进观察与手动持仓记录，但不会被误认为 A 股同等级生产信号。

#### M41.10 Research Evidence And Promotion Gates（P0/P1）

- [x] 所有新增层若想影响评分，必须先注册成 hypothesis/evidence candidate：定义 horizon、样本、non-overlap、multiple-comparison、失败条件。
- [x] 对 A 股新增 evidence、港股/美股非价格 evidence 统一走 M29 ledger：fresh forward、IC/ICIR、monotonic、stride、PIT/provenance blockers 全部可见。
- [x] HK/US 若未来要从 read-only 升级，先做 shadow research report，不做 official signal；只有长期稳定 evidence 才讨论 small-scope gray release。
- [x] 验收：没有任何 provider 因“可抓到数据”直接进入 composite_score；只有 evidence gate 通过且人工确认后，才可能改 signal policy。

#### M41.11 Production Boundary Review（P1）

- [x] 在 M41.4-M41.10 完成后，做一次全仓库 blast-radius review：scheduler、aggregator、watchlist、research、positions、exports、tests、docs。
- [x] 明确三市场最终等级：
  - CN：当前 production signal market。
  - HK/US：默认 read-only research context。
  - 任何升级：必须单独确认 market_policy、risk rules、currency/PIT/schema/test2 impact。
- [x] 跑完整 gate：backend full tests、frontend tests/build、ruff、mypy、test2 replay diff、必要时 `make verify`。
- [x] 验收：项目可以清楚回答“哪些市场能拉数据、哪些能研究、哪些能产生官方信号、为什么”。

### 停止条件

- [ ] 会写生产 DB schema、迁移、定时任务、长期 health 表、真实外部付费 API 批量调用时，先单独评估影响。
- [ ] 会影响 official signal、composite_score、position sizing、stop/take、scheduler、test2 replay truth 时，先做只读验证和用户确认。
- [ ] HK/US 非价格数据未通过 field normalization、PIT、freshness、provider health 前，不进入 research scoring 或 production signal。
- [ ] 任何“强买/强卖/确定预测涨跌”的输出不纳入项目路线。

---

## M32 Forward 预测层 / 复盘 → 假设桥【设计立场 + 启动路径】🧭

> 记录于 2026-06-02。背景：评估小红书 StockInsight v3.0 的"AI 预测 + Strong Buy 评级"卖点后，确立本项目对"预测"的立场，并把"想像 A 老师一样提前判断赛道方向"这个目标落到可执行路径上。供未来开发参考，**不要重复讨论要不要做价格预测**。

### 立场：两种"预测"，只做一种

- **不做（明确拒绝）**：个股短期涨跌方向的 ML 分类 + 置信度 + Strong Buy/Sell 评级。理由：
  1. 违反 `AGENTS.md`「不把价格当确定性预测、不鼓励 strong buy」与 `PROJECT.md` 核心约束；
  2. M26/M27 已用完整 gate（DSR/PBO/walk-forward）否决该类候选，生产 `WEIGHT_QUANT=0.0`——系统已如实证明该 edge 不显著；
  3. 周末速成式 ML（多股 × 多技术特征）是过拟合 + 未来函数标本，输出"假确定性"比没有更危险。
  - 评级分数可保留，但定位为**多因子体检快照 / 5000 股分诊工具**，显式标注"非预测"。
- **要做（正路）**：赛道级、基本面/供应链驱动、**可证伪**的前瞻论点。这才是 A 老师"半年前判断存储牛市"的真实方法（供应链锁单 / 海外领先指标 / 周期 vs 结构性升维 / 盯边际变化），与 ML-on-price 无关。本项目已有的 M29 forward evidence + `/a-teacher` skill 就是它的载体。

### 复盘 → Forward 的三步桥（启动前提：复盘数据足够厚）

- [ ] **第 1 步 — 复盘攒"信号→结果"数据集**：用测试1/测试2 + `audit_log_fts` 沉淀"哪些信号在自有历史里真正领先行情"，作为 forward 假设的训练与校准基准。（与现有复盘工作合流，非新坑）
- [ ] **第 2 步 — 把验证过的信号注册成 forward 假设**：扩展 `backend.tools.m29_hypothesis_registry`，新增"赛道级前瞻论点"类型——动机用供应链/海外领先指标证据、horizon、证伪条件、最小样本门、多重比较规则齐全；接入 `/a-teacher` 五层框架（供应链核查 / 海外领先指标 / 周期升维 / 炒作过滤 / 高位过滤）作为论点的证据模板。
- [ ] **第 3 步 — forward 跟踪与回溯打分**：论点进入 M29 forward shadow / evidence ledger，事后按是否兑现做校准；输出形态是"带证据、可证伪、置信度被回溯打分的论点"，不是 Strong Buy 标签。

### 边界

- 启动时机：等第 1 步复盘数据更厚再正式开 M32.2/M32.3；当前保持 M29（forward evidence）为 P0。
- 不恢复 `weight_quant`、不接 Kronos checkpoint、不改生产 signal profile——M32 是研究/论点层，与生产信号解耦，遵循 M29 的 non-promoting / production_unchanged 纪律。

---

## M27 Alpha 根治工程【证据闭环，未晋升】🔬

> M27 alpha 目标与真实生产 promotion 配置已统一为：IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调；未达门槛前生产继续 `weight_quant=0.0`。

### 本轮证据闭环总结（2026-05-31）

**本轮总结**：M27.1c 已完成 test3 production-profile 交易级离线 A/B，并补上 2026-05-15~2026-05-22 forward shadow 与 2026-04-01~2026-05-29 rolling 扩展；旧 production-profile 工具在该 forward 窗口 filtered=0 是 stale validation keys 导致，不作为模型真实拒绝证据，新 `backend.tools.m27_top_decile_forward_shadow` 已收紧训练 cutoff 到 label realized date 早于 target start，结果为 positive-but-small-sample，只作为 non-promoting offline diagnostic；M27.1d 已补 multi-exit / short-cycle objective search、volatility regime 分段与 include-inactive 扩样本检查，全部仍为 `keep_quant_disabled`；M27.3 已接入可恢复 `sentiment_cache` batch runner，主线 cache/fallback 闭合后 polarity+event IC=0.102256 / ICIR=0.324784，lookback=5 获批回填 203 个新增 cache key 后 rows_with_cache_polarity=1010、fallback/cache_miss=0；v2 gate 报告显示 pure polarity IC=0.180828 / ICIR=0.549296 但 monotonic=False，polarity+event IC=0.131126 / ICIR=0.410776 且 monotonic=False，recommended_variant=none，事件化和纯 polarity 均不晋升；M27.4 已完成隔离目录 2000-step Kronos 训练，代理核验发现本轮 `best_model` 指针仍等同 `step_000100`，因此补评已保存 best-loss checkpoint `step_001500` 与 final checkpoint `step_002000`，两者 IC/ICIR 均为负、monotonic=False / m27_gate_pass=False，仍未过 gate。生产继续 `weight_quant=0.0`，不改 signal profile，不接 Kronos checkpoint。

**M27 收口结论**：
- M27.3：主线 cache 对齐已完成，最终缺口计划为 total_windows=0 / deduped_cache_keys=0 / invalid_windows=0；lookback=5 真实回填后也已清零 fallback/cache_miss，但 v2 gate 显示 pure polarity 与 event overlay 均分位不单调，因此 M27.3 只能固化为 non-promoting offline evidence，生产不恢复 quant、不改 signal profile。
- M27.1c：forward shadow 1d/3d/5d 已补齐并扩展到本地最新 2026-05-29，weekly rolling 2026-04-01~2026-05-29 显示 1d filtered trades=99、positive delta windows=7/9、trade-weighted avg net return delta=0.047711，3d filtered=42、5d filtered=25 仍低于 50 笔样本门槛；新增 2026-05-27~2026-05-29 窗口 filtered=0，过滤器有候选价值但仍不接连续 quant score，不恢复生产量化权重。
- M27.1d：short-cycle objective、multi-exit matrix、volatility regime 分段、include-inactive 扩样本均未产生可晋升候选；active-only `low_vol` regression 过 IC/ICIR/stride 但分层不单调，include-inactive 后也未稳定，保留为下一轮研究线索。
- M27 验证管线：已将 label/objective 晋升 decision 收紧为 raw gate + 非重叠 stride ICIR 双门槛，并输出多重比较警告；当前隔离重跑仍为 `keep_quant_disabled`，没有候选过 stride gate。
- M27.3 lookback sensitivity：lookback=1 明显变差；lookback=5 已完成 203-key 真实 cache 回填并复核，polarity+event ICIR=0.410776 表面过 0.40，但 pure polarity ICIR=0.549296 更强且 delta IC=-0.049702；v2 gate 进一步显示 pure polarity top-bottom=0.018281 但 monotonic=False，polarity+event top-bottom=0.014853 且 monotonic=False，两者 gate_blockers 均为 `not_monotonic`，不要把任何 variant 当成 gate pass。
- M27.4：真实 Kronos-compatible checkpoint 已生成并完成同标尺评估；隔离 2000-step 训练未污染 canonical/production，但已保存 best-loss checkpoint `step_001500` 为 IC=-0.036154 / ICIR=-0.125869，最终 `step_002000` 为 IC=-0.047219 / ICIR=-0.195819，均分层不单调且未过 M27 gate，不接生产。继续更长训练属于新的长跑预算，应重新确认，不从 canonical step=200 中断品 resume。

### M27 收口交接（历史参考，不作为当前入口）

**收口目标**：M27 已用真实离线证据判断当前只能继续保持 quant 关闭，不恢复 quant，不接 Kronos finetuned，不改 production signal profile。新的当前入口是 M29。

**接手顺序**：
1. 先运行 `git status --short`，确认当前未提交变更应包含 `backend/tools/m27_sentiment_cache_batch_runner.py`、`backend/tools/m27_kronos_path_a_launch.py`、`backend/tools/m27_top_decile_forward_shadow.py`、对应测试、`STATUS.md` 和本文件；这些是本轮 M27 交付的一部分，不要回滚。
2. M27.1d 已完成 short-cycle / multi-exit / regime / include-inactive 检查：报告在 `/private/tmp/m27_label_objective_eval_m27_1d_multi_exit.{json,md}` 与 `/private/tmp/m27_label_objective_eval_include_inactive_m27_1d_multi_exit.{json,md}`，两者结论均为 `keep_quant_disabled`；不要把 1d forward shadow 过滤器解释为可晋升连续 quant score。
3. M27.3 已完成主线 cache 对齐：最终 exact cache key 命中 624 / 624、fallback/cache_miss 清零，但 polarity+event ICIR=0.324784 仍低于 0.40。lookback=5 已获批完成 203-key 真实 LLM 回填，复核后 rows_with_cache_polarity=1010、fallback/cache_miss=0；v2 gate 后 pure polarity IC=0.180828 / ICIR=0.549296 但 monotonic=False，polarity+event IC=0.131126 / ICIR=0.410776 且 monotonic=False，recommended_variant=none，event overlay 和 pure polarity 均不晋升。
4. M27.1c 已补 forward shadow：单窗口用 `backend.tools.m27_top_decile_forward_shadow --universe-path paper_trading/test3_universe.json --start 2026-05-15 --end 2026-05-22 --exit-days {1,3,5}` 复现；rolling 最新扩展用同工具加 `--rolling --start 2026-04-01 --end 2026-05-29 --rolling-window-days 7 --rolling-stride-days 7`，报告为 `/private/tmp/m27_forward_shadow_rolling_20260401_20260529_{1,3,5}d.{json,md}`。当前结论：1d rolling 样本已够且正向但新增末端窗口 filtered=0，3d/5d 样本仍不足；只能继续累积更长 forward 样本，不接生产。
5. M27.4 历史 canonical checkpoint：`~/.stock-sage/models/kronos_finetuned/checkpoints/best_model` 是 step=200 CPU 中断品，仅作为离线失败证据；不要从它 resume 或接生产。
6. M27.4 隔离长训已跑完：`~/.stock-sage/models/kronos_finetuned_isolated/m27_4_kronos_long_20260531_204923/`，actual_device=mps、step=2000、observed best_loss=2.113054、`production_config_changed=false`；本轮 `best_model` 指针核验为 step_000100，代码已修正未来选择逻辑。本轮最终结论以显式 checkpoint 评估为准：`step_001500` IC=-0.036154 / ICIR=-0.125869，`step_002000` IC=-0.047219 / ICIR=-0.195819，monotonic=False / m27_gate_pass=False。评估必须按 M27 production gate，而不是旧 M26 diagnostic gate。
7. 聚合文档写入规则：并行子 agent 不直接改 `STATUS.md` / `docs/ROADMAP.md`；Lead 收齐结构化结果后串行更新一次。

**停机/汇报条件**：继续更长 Kronos training、覆盖 checkpoint、需要下载/安装新依赖、需要恢复 quant 权重、需要接入 checkpoint、或任何步骤会改变生产信号配置。遇到这些情况先停下汇报，不要硬推生产。

### M27.1 经典因子工程（P1）

**目标**：达到 M27 alpha 目标（IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调），再讨论恢复量化权重。

- [x] 新增因子（`backend/analysis/alpha_factors.py`）：反转动量（12-1）/ 换手率异常（z-score）/ 量价背离 / 板块相对强弱
- [x] rolling z-score 标准化，防量级差异淹没小因子
- [ ] 重训 LightGBM，达到 M27 alpha 目标；生产晋升按 `backend/config.py` 的同一 promotion 配置执行
- [x] 用 M26.0 同标尺重跑 `python3 -m backend.tools.m26_quant_baseline`，对比前后
- [x] M27.1a alpha 诊断：单因子 IC/ICIR、3/5/10/20d horizon、行业/波动 regime、ranker label 分布（`backend/tools/m27_alpha_diagnostic.py`）
- [x] M27.1b label/objective 离线评估工具：行业/市值中性标签、20d horizon、真实 top-decile classification / LambdaRank（`backend/tools/m27_label_objective_eval.py`）
- [x] M27.1c top-decile classifier 离散入场过滤器验证：只作为候选股票过滤/加权，不作为连续 quant score；用 test3 universe 做 profile A/B 与交易级收益回测
- [x] M27.1d multi-exit / short-cycle objective search：1d/3d/5d short-cycle 候选、1/3/5/10/20d raw-return matrix、volatility regime 分段与 include-inactive 扩样本，全部 non-promoting

> 2026-05-30 结果：regression candidate IC=0.020217 / ICIR=0.176699 / monotonic=False；ranker candidate IC=0.029978 / ICIR=0.163796 / monotonic=False。两者均未达 M27 alpha 目标 / 真实生产 promotion 配置（默认 IC≥0.04 / ICIR≥0.40 / monotonic=True），生产模型不晋升，`weight_quant=0.0` 继续保持。
>
> 2026-05-30 M27.1a 诊断：active 94 支、107270 行、2019-01-25~2026-05-22；5d 最强单因子 `roe` 仅 IC=0.015642 / ICIR=0.114032 / monotonic=False，M27 新因子最强 `sector_rel_strength_20_z` 仅 IC=0.012131 / ICIR=0.076884。20d horizon 的 `log_market_cap` 达到 abs IC/ICIR（IC=-0.043831 / ICIR=-0.324008），但这是市值暴露，不应直接作为 alpha 推广。报告：`~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`；下一步：先重设计 label/objective，再继续特征工程。
>
> 2026-05-31 M27.1b gate 修复：`backend.tools.m27_label_objective_eval` 的 `build_decision()` 已要求候选同时过 raw validation gate 与非重叠 `raw_return_stride_validation` ICIR gate（`stride_icir >= 0.40`），并写出 `n_candidates_tested`、Bonferroni alpha/ICIR 参考值和 `multiple_comparison_warning`。隔离重跑 `/private/tmp/m27_label_objective_eval_stage0_gate.{json,md}` 后，`raw_20d_top_decile_classifier` 仍是 best raw candidate，raw IC=0.108904 / ICIR=0.393701 / stride ICIR=0.299587，decision=`keep_quant_disabled`，raw/stride gate pass count=0；这说明此前“接近过 gate”的 A 线不能晋升。
>
> 2026-05-30 M27.1b 分段诊断：`~/.stock-sage/m27_label_objective_eval_report.{md,json}` 已加入 best raw candidate 行业 breakdown。早期 breakdown 曾提示通信设备 3 支小样本线索，但后续 2026-05-31 exploratory 复查已否定；半导体 IC=0.128475 / ICIR=0.269145；计算机设备 IC=0.145299 / ICIR=0.193137。结论：有 sector-specific objective 线索，但样本太小，不能替代全市场 gate。
>
> 2026-05-30 M27.1b sector-specific candidate：离线报告已新增 `sector_industry_specific_candidates`（non-promoting）。半导体进入正式样本门（5854 行 / 5 支 / validation 1452 行），raw IC=0.112838 / ICIR=0.218514 / stride ICIR=0.279028，gate=False；通信设备因仅 3 支未进入正式单独训练候选。结论：行业线索存在，但还不能晋升或进入生产量化。
>
> 2026-05-31 M27.1b 样本门参数化：`backend.tools.m27_label_objective_eval` 已支持 `--segment-min-rows` / `--segment-min-symbols` / `--segment-min-validation-rows`，默认仍保守要求 ≥4 支；低于默认门槛的运行会标记为 `exploratory_sample_limited`、`promotable=false`。使用 `--segment-min-symbols 3` 复查通信设备后，样本为 3391 行 / 3 支 / validation 681 行，raw IC=-0.125885 / ICIR=-0.178232、gate=False；因此旧的通信设备正向线索不能作为下一步训练依据。探索报告：`~/.stock-sage/m27_label_objective_eval_exploratory_report.{md,json}`。
>
> 2026-05-31 M27.1c 首轮 offline candidate-pool A/B：新增 `backend.tools.m27_top_decile_filter_ab`，复用 M27.1b raw 20d top-decile classifier，在 validation 窗口比较 baseline 全候选池与每日 predicted top-decile filtered pool。当前报告写入 `~/.stock-sage/m27_top_decile_filter_ab_report.{json,md}`：baseline 32852 行 / mean_forward_return=0.021177，filtered 3506 行 / mean_forward_return=0.064955，non-overlapping stride delta_daily_equal_weight_mean_return=0.052722。该结果为 non-promoting offline diagnostic：只评估候选过滤，不生成连续 quant score，不修改 `backend/config.py`，不改变生产 signal profile；生产继续 `weight_quant=0.0`。
>
> 2026-05-31 M27.1c test3 production-profile 交易级 A/B：新增 `backend.tools.m27_test3_production_profile_ab`，在 `paper_trading/test3_universe.json` 上用当前 `new_framework`（Q=0 / T=0.6 / S=0.4 / threshold=25）比较 baseline 入场与 top-decile eligibility filter 入场；报告写入 `~/.stock-sage/m27_test3_production_profile_ab_report.{json,md}`。当前固定 5d 退出口径：baseline 292 笔、avg net return=0.005297、Sharpe=0.428561；filtered 36 笔、avg net return=0.032771、Sharpe=1.563425。该结果仍为 non-promoting offline diagnostic：只证明离散过滤器在 test3 历史口径上有候选价值，不生成连续 quant score，不写 Signal 表，不改 `backend/config.py`，不改变生产 signal profile；生产继续 `weight_quant=0.0`。
>
> 2026-05-31 M27.1c forward shadow：旧 `m27_test3_production_profile_ab` 在 2026-05-15~2026-05-22 产生 filtered=0 的原因是 validation allow keys 只覆盖到 2026-04-21，不能代表模型在 forward 窗口真实拒绝；新增 `backend.tools.m27_top_decile_forward_shadow`，用 label realized date 早于 target start 的有标签样本训练，再对 target window 候选只用特征预测并生成 allow keys。默认输出已对齐为 `~/.stock-sage/m27_top_decile_forward_shadow_{exit_days}d.{json,md}`，报告新增 `sample_adequacy.insufficient_for_sharpe`（filtered trades < 50 时为 true）。现有 1d/3d/5d 单窗口报告：1d baseline 60 笔 / filtered 19 笔，avg net return 0.087168 → 0.240773、Sharpe 2.534082 → 4.021878；3d baseline 21 笔 / filtered 7 笔，avg 0.060377 → 0.080748、Sharpe 7.042919 → 7.825931；5d baseline 19 笔 / filtered 6 笔，avg 0.281036 → 0.792643、Sharpe 2.186085 → 3.765263。2026-04-01~2026-05-29 weekly rolling 报告写入 `/private/tmp/m27_forward_shadow_rolling_20260401_20260529_{1,3,5}d.{json,md}`：1d baseline 691 / filtered 99、positive delta windows 7/9、trade-weighted avg net return delta=0.047711、`insufficient_for_sharpe=false`；3d baseline 237 / filtered 42、positive 6/9、delta=0.012785、样本仍不足；5d baseline 109 / filtered 25、positive 6/9、delta=0.027642、样本仍不足；新增 2026-05-27~2026-05-29 窗口 filtered=0（3d/5d 因 forward exit 不足 baseline=0）。三组均标记 `writes_db=false` / `calls_llm_or_api=false` / `production_unchanged=true`；扩展后 DB 计数仍为 `signals=674`、`sentiment_cache=1033`、`positions=5`、`news=1519`。结论：过滤器有正向候选价值，但仍是 non-promoting offline diagnostic，不接生产。
>
> 2026-05-31 M27.1d multi-exit/short-cycle：`backend.tools.m27_label_objective_eval` 已新增 short-cycle 候选（1d/3d/5d regression/top-decile/ranker）、主候选 1/3/5/10/20d raw-return matrix 与 `volatility_regime` segment-specific offline candidate。active-only 报告 `/private/tmp/m27_label_objective_eval_m27_1d_multi_exit.{json,md}` 仍为 `keep_quant_disabled`；最佳短周期候选 `raw_5d_top_decile_classifier_short_cycle` raw IC=0.046294 / ICIR=0.180649 / stride ICIR=0.130392、gate=False；`low_vol` segment regression raw IC=0.126409 / ICIR=0.614230 / stride ICIR=0.873032 但分层不单调、gate=False。扩到 full universe 的 `/private/tmp/m27_label_objective_eval_include_inactive_m27_1d_multi_exit.{json,md}` 覆盖 713 支 / 794648 行仍为 `keep_quant_disabled`，最佳主候选 raw IC=0.043327 / ICIR=0.223696 / stride ICIR=0.283768；短周期候选均未过 gate。结论：1d 过滤器只能作为 candidate-entry diagnostic，不能直接恢复 continuous quant；regime-conditioned objective 是下一轮研究线索但当前不可晋升。

**验收**：新模型达到 M27 alpha 目标，并通过真实生产 promotion 配置；baseline 报告 IC ≥ 0.04 且分位单调。

### M27.2 交易池扩容 25 → 100 支（P1，已完成工程前置）

- [x] 从 707 支中筛出 ~100 支（历史 ≥ 500 bar / 近 60 日均换手率 ≥ 0.5% / 板块均匀）
- [x] 提供 `backend.tools.m27_build_test3_universe` 生成本地 `paper_trading/test3_universe.json`（`paper_trading/` 被 `.gitignore` 忽略，不作为 Git 交付）
- [x] 适配信号 runner（参数化 `--universe`，控制单日 LLM 调用量）
- [x] `m26_quant_baseline` 支持显式 universe 参数；M26 默认继续保留 test2 基线口径，M27/test3 诊断需显式传入 `--universe-path`

**验收**：≥ 90 支，baseline 基于 100 支截面。

> 2026-05-30 结果：`backend.tools.m27_build_test3_universe` 可复现生成本地 `paper_trading/test3_universe.json`，当前本地口径为 100 支、candidate_count=708、sector_count=64；`paper_trading/` 被 `.gitignore` 忽略，不作为 Git 交付。M26 baseline 默认仍指向 test2；test3 baseline 应使用显式 `--universe-path paper_trading/test3_universe.json` 和独立输出路径。生产旧 25 维模型验证已与 M27 29 维候选特征分离，结论仍为 `keep_quant_disabled`。

### M27.3 情感信号事件化（P2，基于 M27.2，与 M27.4 并行）

**目标**：事件标注后情感信号在 100 支 universe 上 IC ≥ 0.03

- [x] 定义 A 股事件分类体系 8~12 类（`backend/analysis/event_taxonomy.py`）：大合同/监管批文/管理层增持/股权激励/指数纳入/实控人减持/监管处罚/业绩预警
- [x] 升级情感 pipeline：在 Anspire/Tavily 新闻流上增加 LLM 事件抽取
- [x] 新增 `event_score` 字段进入信号合成，有事件覆盖极性分，无事件退回极性
- [x] 新增 `sentiment_cache` dry-run 回填计划工具：读取 cache-miss title-window，输出待回填规模、去重 cache key、样本窗口和批次建议；dry-run 不写 DB、不调用 LLM/API
- [x] 新增受控 `sentiment_cache` writer：默认 dry-run，真实写入必须显式 `--execute` / `--db-url` / `--max-keys` / `--max-llm-calls`，逐批输出 audit 与 rollback manifest，默认 skip existing、不覆盖
- [x] 新增可恢复 `sentiment_cache` batch runner：包装受控 writer，按 `max-batches` / `max-llm-calls-total` 小批推进，逐批保留 audit / rollback / summary，生产 signal profile 不变
- [x] A/B 验证：test3 universe 对比「纯极性」vs「极性+事件」IC；真实 `sentiment_cache` 已对齐，fallback/cache_miss 清零，结论明确但未过 M27 gate

**验收**：分类体系落地，pipeline 可跑，IC 对比有明确结论。

> 2026-05-30 M27.3 推进：`m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json` 可离线生成 A/B 报告；本地 test3 news_items=1498，rows_with_news=889，rows_with_event_override=290，event_type_hits=484。polarity 来源优先级已改为 `news.sentiment_score > sentiment_cache_exact_match > offline_title_lexicon_fallback`；当前 exact title-window cache 命中为 0，`news.sentiment_score` 也无持久化样本，因此仍由 transparent diagnostic-only 标题词典 fallback 覆盖 rows_with_polarity=275。pure polarity IC=-0.010695 / ICIR=-0.044183，polarity+event IC=0.023102 / ICIR=0.092584，delta IC=0.033797。结论：事件化方向有离线线索，但验收前仍需真实 polarity 持久化或 sentiment cache 对齐。
>
> 2026-05-31 M27.3 cache-miss 对齐：`m27_alpha_diagnostic --event-ab` 已新增 `--event-ab-cache-missing-output`，可导出 exact title-window 级别的 `sentiment_cache` 缺口。当前 test3 复跑仍为 rows_with_cache_polarity=0 / rows_with_persisted_polarity=0，cache_miss_windows=889，明细写入 `~/.stock-sage/m27_event_ab_cache_missing.json`；`backend.tools.m27_sentiment_cache_plan` 可基于该明细生成 dry-run 回填计划，当前输出 `~/.stock-sage/m27_sentiment_cache_plan.{json,md}`，total_windows=889、deduped_cache_keys=624、duplicate_windows=265、invalid_windows=0、estimated_batches=25。该工具只生成待回填计划和统计，不写 `sentiment_cache`、不触发 LLM/API；真实 polarity 补齐仍需单独批准写入与调用。
>
> 2026-05-31 M27.3 真实 writer 与部分回填：新增 `backend.tools.m27_sentiment_cache_backfill`，真实写入需显式限额并输出 audit/rollback；已执行 10-key smoke、一次 full run 中断恢复 manifest（首批 25 key 已 commit）和后续 25-key batch，当前计划内 exact cache key 命中 60 / 624。用真实 cache 复跑 event A/B 后，rows_with_cache_polarity=187、rows_with_fallback_polarity=235、cache_miss_windows=702，pure polarity IC=-0.009624 / ICIR=-0.033792，polarity+event IC=0.028544 / ICIR=0.092007，delta IC=0.038168。由于仍有 564 个去重 key 待回填，且当前同步 full backfill 速度约数分钟/25 key，M27.3 A/B 验证 checklist 暂不勾；生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch runner：新增 `backend.tools.m27_sentiment_cache_batch_runner`，dry-run 对齐 existing_cache_keys=60 / pending_before_batch=564 后，执行 1 个 25-key 真实 batch（llm_calls=25、inserted_cache_keys=25），per-batch audit/rollback 写入 `~/.stock-sage/m27_sentiment_cache_backfill_batches/`。batch3 后计划内 exact cache key 命中 85 / 624，新缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch3_new_missing.{json,md}`，total_windows=652、deduped_cache_keys=539、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=237、rows_with_fallback_polarity=225、cache_miss_windows=652，pure polarity IC=0.066592 / ICIR=0.225971，polarity+event IC=0.072677 / ICIR=0.225958，delta IC=0.006085；fallback 仍未清零，M27 production gate 仍未过，A/B 验证 checklist 暂不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch4：用 runner 再执行 1 个 25-key 真实 batch（llm_calls=25、inserted_cache_keys=25），audit/rollback 对齐且 rollback 仅按 `cache_key` 删除插入项。batch4 后计划内 exact cache key 命中 110 / 624，新缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch4_new_missing.{json,md}`，total_windows=602、deduped_cache_keys=514、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=287、rows_with_fallback_polarity=207、cache_miss_windows=602，pure polarity IC=0.038626 / ICIR=0.139958，polarity+event IC=0.059654 / ICIR=0.194807，delta IC=0.021028；fallback 仍未清零，ICIR 未过 M27 gate，A/B 验证 checklist 暂不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch5-batch7：继续用 runner 连续完成 3 个 25-key 真实 batch（合计 llm_calls=75、inserted_cache_keys=75），audit/rollback 均对齐且 rollback 仅按 `cache_key` 删除插入项。batch7 后计划内 exact cache key 命中 185 / 624，新缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch7_new_missing.{json,md}`，total_windows=452、deduped_cache_keys=439、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=437、rows_with_fallback_polarity=179、cache_miss_windows=452，pure polarity IC=0.076349 / ICIR=0.271813，polarity+event IC=0.064801 / ICIR=0.220827，delta IC=-0.011548；fallback 仍未清零，ICIR 未过 M27 gate，A/B 验证 checklist 暂不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch8-batch11：按 25-key 小批继续执行 4 个真实 batch（合计 llm_calls=100、inserted_cache_keys=100），runner summary、per-batch audit 与 rollback 均对齐，rollback 仍为 `delete_inserted_keys_only_no_overwrites` 且 SQL 仅按 `cache_key` 删除插入项。batch11 后计划内 exact cache key 命中 285 / 624，新缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch11_new_missing.{json,md}`，total_windows=339、deduped_cache_keys=339、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=550、rows_with_fallback_polarity=142、cache_miss_windows=339，pure polarity IC=0.060407 / ICIR=0.201861，polarity+event IC=0.064117 / ICIR=0.203814，delta IC=0.003710；fallback 仍未清零，ICIR 未过 M27 gate，A/B 验证 checklist 暂不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch12 stop：从 batch11 新缺口 plan 继续时，LocalCLI Claude 返回 `You've hit your session limit · resets 6:10am (Asia/Singapore)`；已终止 `m27_runner_batch12_20260531`，未产生 batch12 summary/audit/rollback。恢复探针使用 `m27_sentiment_cache_plan_after_runner_batch11_new_missing.json` 做 dry-run，确认 `existing_cache_keys=0`、`pending_cache_keys=339`、`selected_cache_keys=25`、`inserted_cache_keys=0`，即 batch12 无部分写入；下一次应从 batch11 新缺口 plan 恢复。
>
> 2026-05-31 M27.3 batch12-batch17：将 `local_cli` 默认改为 Codex-first 后继续小批回填，完成 6 个 25-key 真实 batch（合计 llm_calls=150、inserted_cache_keys=150），runner summary、per-batch audit 与 rollback 均对齐，rollback 仍为 `delete_inserted_keys_only_no_overwrites` 且 SQL 仅按 `cache_key` 删除插入项；期间 Codex CLI 出现数次 90s timeout 但成功重试。batch17 后计划内 exact cache key 命中 435 / 624，新缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch17_new_missing.{json,md}`，total_windows=189、deduped_cache_keys=189、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=700、rows_with_fallback_polarity=91、cache_miss_windows=189，pure polarity IC=0.060721 / ICIR=0.199560，polarity+event IC=0.083139 / ICIR=0.255496，delta IC=0.022418；fallback 仍未清零，ICIR 未过 M27 gate，A/B 验证 checklist 暂不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 batch18 stop：从 batch17 新缺口 plan 继续时，Codex CLI 连续多次 90s timeout，已终止 `m27_runner_batch18_20260531`，未产生 batch18 summary/audit/rollback。恢复探针使用 `m27_sentiment_cache_plan_after_runner_batch17_new_missing.json` 做 dry-run，确认 `existing_cache_keys=0`、`pending_cache_keys=189`、`selected_cache_keys=25`、`inserted_cache_keys=0`，即 batch18 无部分写入；下一次应从 batch17 新缺口 plan 恢复。
>
> 2026-05-31 M27.3 batch18-batch25 completion：将本轮命令的 `LOCAL_CLI_TIMEOUT_SECONDS` 提高到 180 后，继续完成 8 个真实 batch（batch18-batch24 各 25 key，batch25 为 14 key；合计 llm_calls=189、inserted_cache_keys=189），runner summary、per-batch audit 与 rollback 均对齐，rollback 仍为 `delete_inserted_keys_only_no_overwrites` 且 SQL 仅按 `cache_key` 删除插入项。batch25 后计划内 exact cache key 命中 624 / 624，最终缺口计划写入 `~/.stock-sage/m27_sentiment_cache_plan_after_runner_batch25_new_missing.{json,md}`，total_windows=0、deduped_cache_keys=0、invalid_windows=0。复跑 event A/B 后 rows_with_cache_polarity=889、rows_with_fallback_polarity=0、cache_miss_windows=0，pure polarity IC=0.095070 / ICIR=0.311549，polarity+event IC=0.102256 / ICIR=0.324784，delta IC=0.007186；cache/fallback 已闭合，但 ICIR 仍低于 0.40，M27 gate 未过，A/B 验证 checklist 不勾，生产 signal profile 不变。
>
> 2026-05-31 M27.3 lookback sensitivity：只读复跑 `/private/tmp/m27_alpha_event_ab_lookback1.{json,md}` 与 `/private/tmp/m27_alpha_event_ab_lookback5.{json,md}`。lookback=1 rows_with_cache_polarity=517 / fallback=57、polarity+event IC=-0.006020 / ICIR=-0.017651，明显变差；dry-run plan `/private/tmp/m27_sentiment_cache_plan_lookback1_dbcheck.{json,md}` 显示还需 211 个去重 cache key。lookback=5 rows_with_cache_polarity=791 / fallback=92、polarity+event IC=0.134892 / ICIR=0.425622，但 pure polarity ICIR=0.586046 更高，且 dry-run plan `/private/tmp/m27_sentiment_cache_plan_lookback5_dbcheck.{json,md}` 显示还需 203 个去重 cache key（约 9 批）真实 LLM 回填。该线索未闭合 cache/fallback，不能作为 gate pass；继续需要单独批准真实 `sentiment_cache` 写入。
>
> 2026-05-31 M27.3 lookback=5 completion：获批后使用 `m27_sentiment_cache_batch_runner` 完成 9 批真实回填（inserted_cache_keys=203、llm_calls=203，summary 为 `~/.stock-sage/m27_sentiment_cache_batch_runner_lookback5_20260531_summary.json`）；最终缺口计划 `/private/tmp/m27_sentiment_cache_plan_lookback5_after_backfill_dbcheck_20260531.{json,md}` 为 total_windows=0、deduped_cache_keys=0、invalid_windows=0。复核 `/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531.{json,md}`：rows_with_cache_polarity=1010、rows_with_fallback_polarity=0、cache_miss_windows=0，pure polarity IC=0.180828 / ICIR=0.549296，polarity+event IC=0.131126 / ICIR=0.410776，delta IC=-0.049702。结论：lookback=5 cache/fallback 已闭合，但事件 overlay 拉低 pure polarity，不改 production signal profile。
>
> 2026-05-31 M27.3 pure polarity gate v2：`backend.tools.m27_alpha_diagnostic` 已为 event A/B 增加 `event_ab_gate`、`pure_polarity_validation`、`polarity_event_validation`、`variant_comparison` 与 multiple-comparison warning；v2 报告写入 `/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.{json,md}`。coverage 仍闭合：rows_with_cache_polarity=1010、rows_with_fallback_polarity=0、cache_miss_windows=0。pure polarity 虽然 IC=0.180828 / ICIR=0.549296 / IC days=29 且 top-bottom=0.018281，但 quantile means 为 `[-0.002962, -0.009606, 0.004614, 0.021381, 0.015319]`，monotonic=False，`passes_event_ab_gate=False`、gate_blockers=`["not_monotonic"]`。polarity+event IC=0.131126 / ICIR=0.410776 / top-bottom=0.014853，同样 monotonic=False、gate_blockers=`["not_monotonic"]`。`variant_comparison.recommended_variant="none"`，生产继续不变。

### M27.4 Kronos 微调 Path A（P2，基于 M27.2，待 M27.1 新基线后决策）

**目标**：微调后 Kronos IC ≥ M27.1 LightGBM 新基线

- [x] 准备微调数据集（`backend/tools/m27_kronos_finetune_data.py`）：707 支 × 5 年 OHLCV，滑动窗口 `(context=400, pred_len=5)`；训练集 2020-01~2024-12，验证集 2025-01~2025-10
- [x] StockSage 自有训练目标（`backend/analysis/kronos_losses.py`）：加入 ListMLE 排序损失，`λ_rank=0.7` / `λ_recon=0.3`；`vendor/kronos/` 仅为本地 ignored 上游 checkout，不作为项目交付
- [x] StockSage Path A 受控 launch config：明确 reviewed dataset、Kronos-small/tokenizer、MPS 设备、日志、checkpoint、resume 与 M27 promotion gate；生成配置不启动训练、不写 checkpoint
- [x] StockSage-owned smoke training loop：显式 `--execute-training --ack-long-run --ack-model-write` 才启动，支持 MPS/CPU fallback、max-steps、checkpoint_interval、resume/skip-existing、已有 `best_model` 默认不覆盖、JSONL log 和 manifest；默认写入隔离的 `~/.stock-sage/models/kronos_path_a_smoke`，并拒绝把 smoke 写到 canonical `kronos_finetuned`；该 smoke artifact 仅证明 launcher 可执行，不等同于真实 Kronos-small 晋升
- [x] 微调 Kronos-small（`.venv_kronos/`，真实 Kronos `save_pretrained`，模型存 `~/.stock-sage/models/kronos_finetuned/`）
- [x] 打通 finetuned 评估入口（`m26_kronos_eval.py --model kronos-finetuned`）
- [x] 用真实 finetuned checkpoint 做 M26.0 同标尺验证，并与 LightGBM 同表对比

**决策门**：IC ≥ LightGBM 且通过完整 M27 production gate（IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调）→ 进 M26.3 重启评审；否则降级路径 B（特征融合）。

> 2026-05-30 结果：数据准备、tracked StockSage loss、dry-run training plan 和 `--model kronos-finetuned` 评估入口已完成；真实 Kronos-small 微调仍需单独长跑，未生成可验证 finetuned 模型。完整覆盖检查为 requested=713 / complete_symbols=679 / min_symbols=707，34 支缺 train 或 validation windows；`coverage_report.json` 已输出完整 `symbol_lists` 与推荐命令，并已固化 reviewed universe 到 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json`（679 支）。真实微调前应显式使用该 universe 并以 `--min-symbols 679` 生成正式数据；`--allow-partial` 只用于探索。
>
> 2026-05-31 reviewed 数据集：已用 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json` 和 `--min-symbols 679` 生成正式微调输入到 `~/.stock-sage/m27_kronos_reviewed_data/`；coverage passed=true，complete_symbols=679 / min_symbols=679，train_windows=318065，valid_windows=132274，hard_failures=[]。当前仍无 `~/.stock-sage/models/kronos_finetuned` checkpoint，下一步是真实 Kronos-small 微调长跑与同标尺验证。
>
> 2026-05-31 M27.4 preflight：新增 `backend.tools.m27_kronos_preflight`，只读检查 reviewed data、coverage、checkpoint、vendor/kronos、`.venv_kronos` 与 M27 gate 口径；报告写入 `~/.stock-sage/m27_kronos_preflight_report.{json,md}`。当前 decision=`ready_for_training_confirmation`，coverage passed=true，complete_symbols=679，checkpoint_exists=false，vendor/venv 存在；用户已批准继续推进后，下一层阻塞变为缺少可背书的 StockSage Path A 真实训练 launcher/config，最终判断仍必须使用 M27 production gate（IC≥0.04 / ICIR≥0.40 / monotonic=True），不能只看 M26 diagnostic gate。
>
> 2026-05-31 M27.4 training plan：`vendor/kronos/finetune/stocksage_path_a_train.py --ack-long-run` 已校验 reviewed dataset 并写出 `~/.stock-sage/models/kronos_finetuned/stocksage_path_a_training_plan.json`（complete_symbols=679、train_windows=318065、valid_windows=132274、Kronos-small / tokenizer base、ListMLE λ_rank=0.7）。但该入口只生成训练计划，不执行真实训练；上游 `train_predictor.py` 仍是 CUDA/DDP demo 配置且不等价于 StockSage Path A launcher，因此 `微调 Kronos-small` 与真实 checkpoint 同标尺验证仍未完成。
>
> 2026-05-31 M27.4 launch config：新增 tracked 入口 `backend.tools.m27_kronos_path_a_launch`，已用 reviewed dataset 写出隔离的 `~/.stock-sage/models/kronos_path_a_smoke/stocksage_path_a_launch_config.json`，配置包含 device=mps、epochs=1、batch_size=32、max_steps=500、learning_rate=1e-5、checkpoint_interval=100、log_dir、resume policy、`m26_kronos_eval --model kronos-finetuned` 后验命令和 M27 production gate（IC≥0.04 / ICIR≥0.40 / monotonic=True）。该配置 `starts_training=false`、`writes_checkpoint=false`、loss_wiring available=true、decision=`launch_config_ready`；真实写 smoke checkpoint 仍必须额外显式传入 `--execute-training --ack-long-run --ack-model-write`，并且已有 `best_model` 默认拒绝覆盖，canonical `kronos_finetuned` 输出被保留给真实 Kronos-compatible checkpoint。
>
> 2026-05-31 M27.4 smoke loop：`backend.tools.m27_kronos_path_a_launch` 已支持显式训练 smoke，不再依赖 ignored `vendor/kronos/` 入口作为交付面；聚焦测试用临时数据验证 checkpoint 写入、已有 checkpoint 拒绝覆盖、`--skip-existing`、`--resume-from`、MPS 不可用时 fallback CPU、日志和 manifest。为避免语义误接，smoke 默认输出目录已从 `kronos_finetuned` 隔离到 `kronos_path_a_smoke`，执行训练时若指定 canonical `kronos_finetuned` 会阻塞，`m26_kronos_eval --model kronos-finetuned` 也会拒绝 `checkpoint_kind=stocksage_path_a_smoke_model` 的 manifest。当前 canonical `~/.stock-sage/models/kronos_finetuned/checkpoints/best_model` 仍不存在；`微调 Kronos-small` 与同标尺验证仍未完成，生产继续 `weight_quant=0.0`。
>
> 2026-05-31 M27.4 reviewed-dataset smoke：已用 `backend.tools.m27_kronos_path_a_launch --execute-training --ack-long-run --ack-model-write --max-steps 10 --checkpoint-interval 5` 在 MPS 上跑通小步 smoke；summary 写入 `~/.stock-sage/logs/m27_kronos_path_a/stocksage_path_a_training_summary.json`，status=`training_completed`、wrote_checkpoint=true、step=10、best_loss=54.851444、actual_device=mps、production_config_changed=false。隔离 checkpoint 写入 `~/.stock-sage/models/kronos_path_a_smoke/checkpoints/best_model/`，manifest `checkpoint_kind=stocksage_path_a_smoke_model`，coverage complete_symbols=679 / train_windows=318065 / valid_windows=132274。canonical `~/.stock-sage/models/kronos_finetuned/checkpoints/best_model` 仍不存在；该 smoke 只证明 StockSage launcher/loss/log/checkpoint 边界可执行，不等同于真实 Kronos-small 微调，也不能进入 `m26_kronos_eval --model kronos-finetuned` 或生产。
>
> 2026-05-31 M27.4 real-finetuned checkpoint：`backend.tools.m27_kronos_path_a_launch` 已新增显式 `--artifact-kind real-finetuned --allow-canonical-finetuned` 路径，保留 smoke 默认不变；真实路径加载 `NeoQuasar/Kronos-small` 与 `NeoQuasar/Kronos-Tokenizer-base`，用 reviewed dataset 做 next-token predictor fine-tune，并通过 `Kronos.save_pretrained()` 写出可被 `Kronos.from_pretrained()` 读取的 checkpoint。500-step CPU 长跑在 step=200 后中断，已将真实 `step_000200` 复制为 canonical `~/.stock-sage/models/kronos_finetuned/checkpoints/best_model` 用于评估；manifest `checkpoint_kind=stocksage_kronos_finetuned_model`、best_loss=2.175277、production_config_changed=false。
>
> 2026-05-31 M27.4 finetuned 同标尺评估：`.venv_kronos/bin/python -m backend.tools.m26_kronos_eval --model kronos-finetuned --finetuned-model-path /Users/zeeechenn/.stock-sage/models/kronos_finetuned` 已跑通，模型路径为 canonical best_model。最新报告 `~/.stock-sage/m26_kronos_report.{json,md}`：IC=0.006391、ICIR=0.020976、IC>0=0.500000、monotonic=False、m27_gate_pass=False，低于 LightGBM IC=0.020811 / ICIR=0.186647，也未过 M27 gate（IC≥0.04 / ICIR≥0.40 / monotonic=True）。结论：不接生产，不恢复 quant；M27.4 当前真实路径降级为 failed offline evidence。
>
> 2026-05-31 M27.4 下一次训练约定：canonical best_model 是 step=200 CPU 中断品，不作为可 resume 的完整基线。若未来明确批准更长训练，必须使用新的隔离输出目录、从头训练（不传 `--resume-from`），并让后验 `m26_kronos_eval --model kronos-finetuned --finetuned-model-path` 指向该新目录；`backend.tools.m27_kronos_path_a_launch` 的 launch config 已改为按本次 `output_dir` 生成 eval command，避免误评 canonical。
>
> 2026-05-31 M27.4 isolated long training：获批后按上述约定使用新隔离目录从头训练，不从 canonical step=200 resume；产物写入 `~/.stock-sage/models/kronos_finetuned_isolated/m27_4_kronos_long_20260531_204923/`，日志写入 `~/.stock-sage/logs/m27_kronos_path_a/m27_4_kronos_long_20260531_204923/`。训练 summary：status=`training_completed`、actual_device=mps、step=2000、observed best_loss=2.113054、`production_config_changed=false`；launch config 的后验 eval command 已修正为 `.venv_kronos/bin/python -m backend.tools.m26_kronos_eval --model kronos-finetuned --finetuned-model-path /Users/zeeechenn/.stock-sage/models/kronos_finetuned_isolated/m27_4_kronos_long_20260531_204923`，避免误用缺少 Kronos 依赖的 `.venv`。代理核验发现本次 `best_model` 实际等同 `step_000100`，不是训练期间 observed best loss 对应权重；代码已修为未来按已保存 checkpoint loss 选择 best。为闭合本轮证据，显式补评已保存 checkpoint 中 loss 最低的 `step_001500`：IC=-0.036154、ICIR=-0.125869、IC>0=0.461538、monotonic=False、m27_gate_pass=False；显式补评 final `step_002000`（当前 `~/.stock-sage/m26_kronos_report.{json,md}`）：IC=-0.047219、ICIR=-0.195819、IC>0=0.384615、monotonic=False、m27_gate_pass=False。LightGBM baseline 为 IC=0.020811 / ICIR=0.186647。结论：隔离长训 checkpoint 未过 gate 且弱于 LightGBM，不接生产、不恢复 quant。

---

## M28 调研模块整合与实时搜索接入 ✅

> 历史背景：deep_research / copilot / 多轮辩论 三模块曾存在信息孤岛，辩论缺乏真实信息差，
> ResearchSection schema 曾为纯文本无结构；M28 已完成结构化接线。详细设计见 `docs/M28_RESEARCH_INTEGRATION_PLAN.md`。

### M28.1 ResearchSection IC Memo Schema 升级
**文件：** `backend/research/agents.py`
- [x] 扩展 `ResearchSection` 增加结构化字段（全部有默认值）：`catalysts / risks / valuation_anchor / evidence_snippets / stance / confidence`
- [x] 更新五个 builder 函数填充新字段
- [x] 更新 `_render_report` 展示结构化字段

### M28.2 Tavily 实时 Web 搜索补全 evaluator/planner 循环
**文件：** `backend/research/deep_research.py`
- [x] 新增 `_tavily_web_search(queries, ...)` — 纯内存路径，不写 DB，直调 Tavily REST API
- [x] 在 `_execute_plan` 补全 `next_action == "web_search"` 分支（当前已声明但未实现）
- [x] 报告中对 `source="tavily_web"` 条目展示来源 URL
- [x] 修复末轮 web_search 结果未重新审计的问题；空 seed query 不会提前耗尽 Tavily 通用重试机会

### M28.3 辩论注入结构化信息差
**文件：** `backend/agents/researcher.py` / `backend/agents/pipeline.py`
- [x] `multi_round_debate` 增加可选参数 `research_context: dict | None = None`（向后兼容）
- [x] bull 轮 prompt 注入 `catalysts + 正面 evidence_snippets`；bear 轮注入 `risks + 负面证据`
- [x] `pipeline.py`：若当日已有 deep_research 结果，自动提取并传入 `research_context`
- [x] 盘后路径可从持久化 `research_pointer.evidence_json.sections` 恢复结构化 research_context

### M28.4 建立 copilot → deep_research 信息流
**文件：** `backend/research/copilot.py` / `backend/research/deep_research.py` / `backend/research/dossier.py`
- [x] `run_deep_research` 增加可选 `seed_queries: list[str] | None = None`；CLI 支持 `--seed-queries`
- [x] `dossier.build_research_dossier` 新增 `pending_questions` 字段（从 copilot validation_questions 提取）

---

## M26 量化层重估 ✅ / M26.3 暂停

M26.0 基线 ✅ / M26.1 扩盘 ✅ / M26.2 Kronos 零样本 ✅（IC=-0.0017，不替换）

报告存档：M26 baseline / 扩盘诊断写入 `~/.stock-sage/m26_quant_baseline_report.{md,json}`，Kronos 零样本写入 `~/.stock-sage/m26_kronos_report.{md,json}`；当前决策口径以 M26.1/M26.2 后的 `keep_quant_disabled` 为准。

### M26.3 小权重 Paper Trading 验证（暂停）

> **重启条件**：M29 新 alpha gate（IC ≥ 0.04 / ICIR ≥ 0.40 / monotonic=True）达标后重新评估。

- [ ] 在 `test2_ab_runner.py` 新增第三臂 `quant_small`（Q=0.15, T=0.55, S=0.30, threshold=25）
- [ ] 跑满 4 周，按测试 2 汇报约定只汇报总结
- [ ] 决策门：`quant_small` 收益持续跑赢 `quant_off` ≥ 2pp 且最大回撤不高 → 进入生产权重恢复讨论

---

## M24.3 长期约束重新接入验证 ⏳

- [ ] **shadow forward outcome 观察**（从 2026-05-27 起）：每天保留只读报告输出，跟踪 `blocked_entry / position_reduced / score_capped` 样本的 1d/3d/5d/10d 表现；口径优先用相对沪深 300 超额收益。只观察，不开启约束。
- [ ] **中期检查点（建议 2026-06-10）**：汇总首批 shadow 样本，判断长期标签是否降低假阳性；不足或不稳定则继续观察。
- [ ] 测试 2 冻结期结束后（≥ 2026-07-18），用重建后的可信标签回放历史信号，严格按 PIT 口径对比「无约束」vs「有约束」；禁止使用未来生成的标签回改过去交易。
- [ ] 只有约束降低假阳性且不显著误杀有效入场时，才将 `LONG_TERM_CONSTRAINTS_ENABLED=true` 纳入下一轮测试架构。

---

## M25 综合改进路线图（剩余项）⏳

已完成：M25.0–M25.4 主体 / M25.2 统计口径补债 / M25.3 LLM 成本可观测性 + 跨入口契约回归测试

**M25.4 剩余（低优先）**
- [ ] 自选股 200+ 卡顿后再上虚拟列表；当前保留本地搜索/筛选
- [ ] 移动端先保障 Watchlist / StockDetail / Chat 三条核心路径可用，不急于完整复刻

**M25.5 Qlib 灰度（阻塞于 M27）**
- [ ] 只有多个窗口稳定通过 promotion gate 后，才允许小权重灰度（`quant=0.1`）；需配 kill switch 与复盘闭环

**M25.6 社区与战略（P3）**
- [ ] README demo 截图/GIF / release notes / 真实 quickstart 验证路径 / 典型研究案例
- [ ] PostgreSQL / pgvector：SQLite 成为真实瓶颈后再启动
- [ ] HK/US 多市场：A 股主线验证稳定后再做
- [ ] Tauri / 桌面客户端：Web 控制台稳定后再评估
- [ ] WebSocket：止损预警优先复用 scheduler + Bark，有多用户实时需求再引入

---

## M21.4 ATR 窄止损统计分析（触发条件：2026-07-18 后）

- [ ] 在 test1 + test2 全部 `closed` 仓位上统计 `ATR / 买入价` 分布，重点看 ATR 占比 < 0.5% 样本是否系统性触发假止损；如有问题评估：① 加 ATR 下限 `max(ATR×2, 买入价×3%)`；② 改用 trailing ATR×2.5。先出统计报告，不直接改测试 1（规则已冻结）。

---

## M12 外部数据源扩展治理（剩余）⏳

- [ ] 对任何新端点先补 provider health / PIT 时间戳 / 字段归一化 / 测试，再考虑写入 SQLite

---

## M10.5 长期工程基础（后置 / P3）

- [ ] 数据库迁移体系：先保留 `create_all + runtime patch`，中期引入 Alembic baseline
- [ ] 只有多个验证窗口通过后才允许小权重灰度；默认生产继续 `weight_quant=0.0`

---

## M4 多 Agent 决策深化（暂缓项）🟡

- [ ] **M4.4 LangGraph 重构 pipeline**：触发条件：本地验证 ≥ 10 笔样本 + path B Sharpe ≥ path A + 0.3
- [ ] **M4.5 FinMem 完整替换 `decision_memory.py`**：触发条件：≥ 30 笔样本证明"记忆深度 → Sharpe 改善"

---

## M5 自动化执行 🔲（后置，最不关键）

QMT/miniQMT 券商对接；盘中实时止损；半自动→全自动渐进。
**门槛**：本地验证通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

---

## M2 本地验证材料 🏠

本地验证材料、个人记录和临时统计不进入 GitHub。

---

## 里程碑摘要（详情见 CHANGELOG / PROJECT）

| 里程碑 | 完成时间 | 简述 |
|---|---|---|
| M30 | 2026-06-01 主体完成 | 工程质量收敛：mypy、Python lock、CI/安全/覆盖率、核心路径专项测试；安全债与可维护性拆分后置 |
| M29.0–M29.5 | 进行中 | Alpha Reset / Forward Evidence Engine，M29.5 首轮 attribution 已完成，等待完整 fresh forward 覆盖 |
| M27.0–M27.4 | 2026-05-31 | Alpha 根治工程证据闭环，未过 promotion gate，转入 M29 |
| M26.0 量化基线 | 2026-05-30 | 初始 test2 基线归档；后续以 M26.1/M26.2 的生产边界为准 |
| M26.1 训练盘扩容 | 2026-05-30 | 707 支，IC=0.021，仅过 M26 诊断阈值，未过生产 promotion gate |
| M26.2 Kronos 评估 | 2026-05-30 | 零样本 IC=-0.0017，不替换 |
| M25 综合改进主体 | 2026-05-27 | LLM 成本可观测性 / Chat SSE / 跨入口契约回归 |
| M24.0–M24.2 长期标签隔离 | 2026-05-26 | 测试 1/2 冻结期隔离 + 质量门 |
| M23 信号证据链 + 回测口径 | 2026-05-25 | M17.1 / M18.1 / 前端 EvidenceCard |
| M22 持仓完整性与状态隔离 | 2026-05-24 | 持仓 schema 锁定 / agent action 对齐 |
| M21 基础设施评审修复 | 2026-05-23 | 远程写守卫 / model_tier 分层 / runtime-config 校验 |
| M20 量化与分析层评审修复 | 2026-05-23 | RSRS 共线修复 / 涨跌停阈值板块差异 |
| M19 数据层与 PIT 修复 | 2026-05-23 | PIT 用 disclosure_date / 复权口径统一 / Q1/Q3 披露日 |
| M18 回测统计口径修复 | 2026-05-23 | 滑点建模 / Sharpe 年化统一 / DSR trial 语义 |
| M17 决策链评审修复 | 2026-05-23 | regime 不覆盖风控否决 / 证据仓位归属 / 幂等写 |
| M16 全项目分层评审 | 2026-05-23 | 六层评审完成，缺陷转入 M17–M21 |
| M15 记忆系统与影子副驾驶修复 | 2026-05-23 | judgment 去重 / vetter 接线 / 召回副作用降级 |
| M14 股票长期记忆与跨入口召回 | 2026-05-23 | `stock_memory_items` + 统一召回 `build_memory_context` |
| M13 pi Shell + Agent Kernel | 2026-05-23 | `backend/agent/cli.py` / `.pi/` 本地配置 |
| M11 Agent-Ready 本地/远程接口 | 2026-05-21 | AGENTS.md / MCP 工具桥 / PortfolioManager 闭环 |
| M10 运行可靠性与产品化优化 | 2026-05-20 | 覆盖快照 / scheduler 状态 / Bark 重试 / 前端渐进加载 |
| M9 记忆系统接入与治理 | 2026-05-19 | 分层 DB / AdminPage 记忆管理 / 摘要器 / 过期清理 |
| M8 深度研究与来源审计层 | 2026-05-17 | deep_research.py / news_audit / research_memory |
| M6 量化与前端升级 | 2026-05-19 | M6.1 PIT 基本面因子 / M6.3 前端操作台 |
| M7 工程化与开源就绪 | 2026-05-16 | README / CI / Docker / pyproject / Makefile |
| M4 多 Agent（已完成部分） | 2026-05-16 | 多轮辩论 / Director / Portfolio Manager / M4.6–M4.9 |
| M3 可信度审计层 | 2026-05-15 | DSR / PBO / Walk-Forward / PIT 拦截 / Kill Switch |
| M1 严肃化与质量门槛 | 2026-05-15 | Backtrader / regime 过滤 / 长期分析师团 / 双 profile |
| M0 系统骨架 | — | 数据/技术/情感/量化/Web/复盘全链路打通 |

---

## 历史决策点（不再阻塞）

**Qlib 归零**（M1.1）：IC=0.0228，分层非单调 → 权重归零；M26/M27 正在从训练盘广度不足的根因重建。

**跨市场信号（已移除）**：美股 ETF 作为领先指标，全板块回测无显著改善，已移除。
