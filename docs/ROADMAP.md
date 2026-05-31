# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情优先见 `CHANGELOG.md`。本文件只列当前未完成任务项（`[ ]`）、暂缓项和少量摘要指针。

---

## ⭐ M29 Alpha Reset / Forward Evidence Engine【P0 当前最高优先】🔬

> M27 已形成完整离线证据闭环，但所有候选均未过生产 promotion gate。M29 不继续包装旧候选，而是把 M27 的失败证据与弱正向线索转成可积累、可复核、可预注册的新 alpha 研究机制。

### 启动目标与边界（2026-05-31）

**目标**：建立 forward evidence ledger 与新 alpha 假设注册流程，让 top-decile filter、pure polarity、event overlay、regime-conditioned alpha 等线索在未来窗口中持续积累证据；只有新证据通过完整 gate 后，才讨论 non-promoting train candidate 或 M26.3 重启。

**非目标**：不恢复 `weight_quant`，不修改 production signal profile，不接 Kronos checkpoint，不继续更长 Kronos training，不把 M27 已失败候选直接重命名为可晋升候选。

### M29.1 Forward Evidence Ledger（P0）

- [ ] 新增 read-only evidence ledger：汇总已有 M27 artifact 与未来 forward shadow，输出统一 JSON/Markdown artifact。
- [ ] Ledger 字段必须包含：candidate/variant、window、sample size、IC/ICIR、stride/non-overlap 指标、quantile monotonic、top-bottom、data-quality blockers、multiple-comparison warning、production_unchanged。
- [ ] 首批纳入 M27 证据：top-decile forward shadow、pure polarity v2 gate、polarity+event v2 gate、short-cycle/regime candidates、Kronos failed checkpoints。
- [ ] 所有 M29.1 工具默认只读：不写 DB、不调 LLM/API、不保存模型、不改配置；产物优先写 `/private/tmp` 或 `~/.stock-sage`，不新增通用 planning 文件。

**验收**：新 AI 只读 ledger 即可判断每条 M27/M29 alpha 线索为何未晋升、下一次 forward 更新该跑什么命令、何时必须停下找用户确认。

### M29.2 新 Alpha 假设预注册（P0）

- [ ] 建立候选假设清单，优先从 M27 暴露出的结构性线索出发：regime-conditioned alpha、行业内相对强弱、流动性/换手状态、事件后 drift 路径、top-decile filter 的入场时机。
- [ ] 每条假设必须先写清：动机、样本范围、训练/验证/OOS 切分、目标 horizon、候选特征、预期失败条件、最小样本门、production gate。
- [ ] 明确多重比较规则：同一轮候选数量、Bonferroni/FDR 或至少 explicit warning；没有该字段的报告不能作为晋升证据。
- [ ] 禁止直接把 M27 的 `raw_20d_top_decile_classifier`、pure polarity、event overlay 或 Kronos checkpoint 作为 production candidate；它们只能作为 shadow/research candidate。

**验收**：每个新实验在运行前已有可审计 hypothesis spec；实验失败后能沉淀为 ledger，而不是继续口头追线索。

### M29.3 Forward Shadow 自动延长（P1）

- [ ] 基于 `backend.tools.m27_top_decile_forward_shadow` 延长未来窗口；新增行情积累后优先补 1d/3d/5d rolling evidence。
- [ ] pure polarity / event overlay 只在 cache/fallback 清零、无新增真实写入需求时做只读复核；需要真实 `sentiment_cache` 写入或 LLM 调用时先汇报。
- [ ] 样本门继续保守：filtered trades < 50 不引用 Sharpe，IC days 不足不引用 ICIR 稳定性，分位不单调不能晋升。

**验收**：forward 样本持续更新，但每次更新都保持 non-promoting / production_unchanged。

### M29.4 Promotion Contract（P1）

- [ ] M29 所有候选沿用同一生产 gate：IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调。
- [ ] 晋升前必须同时满足 fresh OOS/forward、非重叠稳定性、多重比较披露、data-quality blockers 清零、人工确认。
- [ ] 任何恢复 `weight_quant`、修改 signal profile、接入 checkpoint、覆盖 checkpoint、继续更长 Kronos training、真实写 `sentiment_cache` 的动作都必须先停下汇报。

**验收**：M29 可以提出新的 non-promoting train candidate，但不能绕过生产 gate 或人工确认。

### 新对话执行交接（2026-05-31）

1. 先读 `STATUS.md § M29` 与本节，再运行 `git status --short`；不要回滚当前未提交的 M27/M29 工具、测试和文档更新。
2. 第一动作是 M29.1：实现或细化 read-only evidence ledger，聚合已有 M27 artifact 和未来 forward shadow 结果。
3. 第二动作是 M29.2：把新 alpha 假设写成预注册候选清单，先定义 gate/样本/OOS/停止条件，再跑实验。
4. 停止条件：任何步骤会改变生产信号、恢复 quant、接入 checkpoint、继续 Kronos 长训、真实写 `sentiment_cache`、下载新依赖或调用额外付费外部服务。

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
| M29.0–M29.4 | 进行中 | Alpha Reset / Forward Evidence Engine，当前最高优先 |
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
