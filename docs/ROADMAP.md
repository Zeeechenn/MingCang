# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情优先见 `CHANGELOG.md`。本文件只列当前未完成任务项（`[ ]`）、暂缓项和少量摘要指针。

---

## ⭐ M27 Alpha 根治工程【P0 当前最高优先】🔬

> M27 alpha 目标与真实生产 promotion 配置已统一为：IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调；未达门槛前生产继续 `weight_quant=0.0`。

### 本轮变动总结与下一步计划（2026-05-31）

**本轮总结**：M27.1c 已完成 test3 production-profile 交易级离线 A/B，top-decile 离散入场过滤器在当前历史窗口上表现优于 baseline，但仍只作为 non-promoting offline diagnostic；M27.3 已接入受控 `sentiment_cache` writer 并完成 60 / 624 个计划内 exact cache key 回填，复跑 event A/B 后 delta IC 提升到 0.038168，但仍有 564 个 deduped key 缺口；M27.4 已写出 reviewed dataset training plan，但当前入口仍不是可直接长跑的真实训练 launcher。生产继续 `weight_quant=0.0`，不改 signal profile，不接 Kronos checkpoint。

**下一步计划**：
- M27.3：把剩余 564 个 deduped cache key 改为可恢复后台/分批 runner，或继续以 25-key batch 逐批回填；每批保留 audit / rollback manifest，完成后复跑 test3 event A/B，只有真实 cache/persisted polarity 对齐后才判断 M27.3 验收。
- M27.4：补 StockSage Path A 专用真实训练 launcher/config，明确设备、dataset、checkpoint、loss、日志和中断恢复；只有生成 `~/.stock-sage/models/kronos_finetuned` 可读 checkpoint 后，才运行 `m26_kronos_eval --model kronos-finetuned` 做同标尺评估。
- M27.1c：将 top-decile filter 保持为离线候选过滤证据，继续做更长窗口或 forward shadow 验证；未通过 M27 production gate 前，不接连续 quant score，不恢复生产量化权重。

### M27.1 经典因子工程（P1）

**目标**：达到 M27 alpha 目标（IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调），再讨论恢复量化权重。

- [x] 新增因子（`backend/analysis/alpha_factors.py`）：反转动量（12-1）/ 换手率异常（z-score）/ 量价背离 / 板块相对强弱
- [x] rolling z-score 标准化，防量级差异淹没小因子
- [ ] 重训 LightGBM，达到 M27 alpha 目标；生产晋升按 `backend/config.py` 的同一 promotion 配置执行
- [x] 用 M26.0 同标尺重跑 `python3 -m backend.tools.m26_quant_baseline`，对比前后
- [x] M27.1a alpha 诊断：单因子 IC/ICIR、3/5/10/20d horizon、行业/波动 regime、ranker label 分布（`backend/tools/m27_alpha_diagnostic.py`）
- [x] M27.1b label/objective 离线评估工具：行业/市值中性标签、20d horizon、真实 top-decile classification / LambdaRank（`backend/tools/m27_label_objective_eval.py`）
- [x] M27.1c top-decile classifier 离散入场过滤器验证：只作为候选股票过滤/加权，不作为连续 quant score；用 test3 universe 做 profile A/B 与交易级收益回测

> 2026-05-30 结果：regression candidate IC=0.020217 / ICIR=0.176699 / monotonic=False；ranker candidate IC=0.029978 / ICIR=0.163796 / monotonic=False。两者均未达 M27 alpha 目标 / 真实生产 promotion 配置（默认 IC≥0.04 / ICIR≥0.40 / monotonic=True），生产模型不晋升，`weight_quant=0.0` 继续保持。
>
> 2026-05-30 M27.1a 诊断：active 94 支、107270 行、2019-01-25~2026-05-22；5d 最强单因子 `roe` 仅 IC=0.015642 / ICIR=0.114032 / monotonic=False，M27 新因子最强 `sector_rel_strength_20_z` 仅 IC=0.012131 / ICIR=0.076884。20d horizon 的 `log_market_cap` 达到 abs IC/ICIR（IC=-0.043831 / ICIR=-0.324008），但这是市值暴露，不应直接作为 alpha 推广。报告：`~/.stock-sage/m27_alpha_diagnostic_report.{md,json}`；下一步：先重设计 label/objective，再继续特征工程。
>
> 2026-05-30 M27.1b 刷新：`raw_20d_top_decile_classifier` 是当前 best raw candidate，raw IC=0.108904 / ICIR=0.393701 / monotonic=True，stride IC=0.093662 / ICIR=0.299587，top-decile precision=0.285470 / lift=2.674922；但 raw gate 未过（ICIR 低于 0.40，且 stride 稳定性不足），报告决策仍为 `keep_quant_disabled`，推荐先做事件条件化或行业分组 objective，再决定是否进入 M27.1c。
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
- [ ] A/B 验证：test3 universe 对比「纯极性」vs「极性+事件」IC（diagnostic-only fallback 已能计算 delta；仍需真实持久化 polarity 或 sentiment cache 对齐）

**验收**：分类体系落地，pipeline 可跑，IC 对比有明确结论。

> 2026-05-30 M27.3 推进：`m27_alpha_diagnostic --event-ab --universe-path paper_trading/test3_universe.json` 可离线生成 A/B 报告；本地 test3 news_items=1498，rows_with_news=889，rows_with_event_override=290，event_type_hits=484。polarity 来源优先级已改为 `news.sentiment_score > sentiment_cache_exact_match > offline_title_lexicon_fallback`；当前 exact title-window cache 命中为 0，`news.sentiment_score` 也无持久化样本，因此仍由 transparent diagnostic-only 标题词典 fallback 覆盖 rows_with_polarity=275。pure polarity IC=-0.010695 / ICIR=-0.044183，polarity+event IC=0.023102 / ICIR=0.092584，delta IC=0.033797。结论：事件化方向有离线线索，但验收前仍需真实 polarity 持久化或 sentiment cache 对齐。
>
> 2026-05-31 M27.3 cache-miss 对齐：`m27_alpha_diagnostic --event-ab` 已新增 `--event-ab-cache-missing-output`，可导出 exact title-window 级别的 `sentiment_cache` 缺口。当前 test3 复跑仍为 rows_with_cache_polarity=0 / rows_with_persisted_polarity=0，cache_miss_windows=889，明细写入 `~/.stock-sage/m27_event_ab_cache_missing.json`；`backend.tools.m27_sentiment_cache_plan` 可基于该明细生成 dry-run 回填计划，当前输出 `~/.stock-sage/m27_sentiment_cache_plan.{json,md}`，total_windows=889、deduped_cache_keys=624、duplicate_windows=265、invalid_windows=0、estimated_batches=25。该工具只生成待回填计划和统计，不写 `sentiment_cache`、不触发 LLM/API；真实 polarity 补齐仍需单独批准写入与调用。
>
> 2026-05-31 M27.3 真实 writer 与部分回填：新增 `backend.tools.m27_sentiment_cache_backfill`，真实写入需显式限额并输出 audit/rollback；已执行 10-key smoke、一次 full run 中断恢复 manifest（首批 25 key 已 commit）和后续 25-key batch，当前计划内 exact cache key 命中 60 / 624。用真实 cache 复跑 event A/B 后，rows_with_cache_polarity=187、rows_with_fallback_polarity=235、cache_miss_windows=702，pure polarity IC=-0.009624 / ICIR=-0.033792，polarity+event IC=0.028544 / ICIR=0.092007，delta IC=0.038168。由于仍有 564 个去重 key 待回填，且当前同步 full backfill 速度约数分钟/25 key，M27.3 A/B 验证 checklist 暂不勾；生产 signal profile 不变。

### M27.4 Kronos 微调 Path A（P2，基于 M27.2，待 M27.1 新基线后决策）

**目标**：微调后 Kronos IC ≥ M27.1 LightGBM 新基线

- [x] 准备微调数据集（`backend/tools/m27_kronos_finetune_data.py`）：707 支 × 5 年 OHLCV，滑动窗口 `(context=400, pred_len=5)`；训练集 2020-01~2024-12，验证集 2025-01~2025-10
- [x] StockSage 自有训练目标（`backend/analysis/kronos_losses.py`）：加入 ListMLE 排序损失，`λ_rank=0.7` / `λ_recon=0.3`；`vendor/kronos/` 仅为本地 ignored 上游 checkout，不作为项目交付
- [ ] 微调 Kronos-small（`.venv_kronos/`，MPS 加速，模型存 `~/.stock-sage/models/kronos_finetuned/`）
- [x] 打通 finetuned 评估入口（`m26_kronos_eval.py --model kronos-finetuned`）
- [ ] 用真实 finetuned checkpoint 做 M26.0 同标尺验证，并与 LightGBM 同表对比

**决策门**：IC ≥ LightGBM 且分位单调 → 进 M26.3 重启；否则降级路径 B（特征融合）。

> 2026-05-30 结果：数据准备、tracked StockSage loss、dry-run training plan 和 `--model kronos-finetuned` 评估入口已完成；真实 Kronos-small 微调仍需单独长跑，未生成可验证 finetuned 模型。完整覆盖检查为 requested=713 / complete_symbols=679 / min_symbols=707，34 支缺 train 或 validation windows；`coverage_report.json` 已输出完整 `symbol_lists` 与推荐命令，并已固化 reviewed universe 到 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json`（679 支）。真实微调前应显式使用该 universe 并以 `--min-symbols 679` 生成正式数据；`--allow-partial` 只用于探索。
>
> 2026-05-31 reviewed 数据集：已用 `~/.stock-sage/m27_kronos_reviewed_complete_universe.json` 和 `--min-symbols 679` 生成正式微调输入到 `~/.stock-sage/m27_kronos_reviewed_data/`；coverage passed=true，complete_symbols=679 / min_symbols=679，train_windows=318065，valid_windows=132274，hard_failures=[]。当前仍无 `~/.stock-sage/models/kronos_finetuned` checkpoint，下一步是真实 Kronos-small 微调长跑与同标尺验证。
>
> 2026-05-31 M27.4 preflight：新增 `backend.tools.m27_kronos_preflight`，只读检查 reviewed data、coverage、checkpoint、vendor/kronos、`.venv_kronos` 与 M27 gate 口径；报告写入 `~/.stock-sage/m27_kronos_preflight_report.{json,md}`。当前 decision=`ready_for_training_confirmation`，coverage passed=true，complete_symbols=679，checkpoint_exists=false，vendor/venv 存在；用户已批准继续推进后，下一层阻塞变为缺少可背书的 StockSage Path A 真实训练 launcher/config，最终判断仍必须使用 M27 production gate（IC≥0.04 / ICIR≥0.40 / monotonic=True），不能只看 M26 diagnostic gate。
>
> 2026-05-31 M27.4 training plan：`vendor/kronos/finetune/stocksage_path_a_train.py --ack-long-run` 已校验 reviewed dataset 并写出 `~/.stock-sage/models/kronos_finetuned/stocksage_path_a_training_plan.json`（complete_symbols=679、train_windows=318065、valid_windows=132274、Kronos-small / tokenizer base、ListMLE λ_rank=0.7）。但该入口只生成训练计划，不执行真实训练；上游 `train_predictor.py` 仍是 CUDA/DDP demo 配置且不等价于 StockSage Path A launcher，因此 `微调 Kronos-small` 与真实 checkpoint 同标尺验证仍未完成。

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

> **重启条件**：M27 alpha 目标（IC ≥ 0.04 / ICIR ≥ 0.40 / monotonic=True）达标后重新评估。

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
| M27.0–M27.4 | 进行中 | Alpha 根治工程，见本文件 M27 |
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
