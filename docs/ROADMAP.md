# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

> 已完成里程碑（v0.3.3–v0.5.1、M44–M50 等）不再列在本活跃表，详见文末 Completed Milestones Index 与 `CHANGELOG.md`。本表只保留进行中 / 未启动 / 触发待命的工作线。

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M54 新闻层 v2（多源可插拔·正文级·多信号综合评分） | 阶段0–7 已建（token 金字塔 `661deaa`）+ **三轮预注册 OOS（06-29/06-30/07-02）**。**第三轮（100支，claude-sonnet-4-6）推翻第二轮乐观结论**：h3d legacy 反超 v2（Δ=-0.064，legacy IC+0.118 > v2 IC+0.054），仅 h5d 仍支持 v2（Δ=+0.081）——两 horizon 不一致，按预注册规则3 判**第二轮"v2胜出"为小样本假象**，v2 信号设计需回炉，生产维持 legacy。三轮一致证实 IC天(14/9)由非重叠时间窗口数决定、与横截面宽度无关（50→100支仅12/8→14/9）——**下一步不再扩股票数**。v2-pyramid 保真度未达标（两 horizon 均劣于 v2-full ≥0.01 门，幅度远超预期，疑不止阈值问题）。详见 `docs/dev/M54_OOS_PREREGISTER.md` §10 | ① 诊断第二轮为何未复现（是否为有利子样本／新增50支拖累信号）② 按规则2 改向前采集扩窗口（IC天是唯一瓶颈，已证与横截面无关）③ 独立诊断 pyramid 触发逻辑损伤幅度异常 | 未过独立预注册 OOS 即启用/接 live test2/改情感权重/外溢 official signal·仓位·scheduler；不再扩横截面掩盖 IC天瓶颈；weight_sentiment 由 OOS 重定、中途不手调；不事后挑解释掩盖方向消失 |
| M56 AI 产业预警雷达 | planned 2026-07-02 / observe-only / non-promoting：把 AI capex、算力租赁、HBM、AI 信贷、数据中心约束、repo leverage、AI 龙头估值杀等八类指标做成独立行业风险观察层，不是个股 alpha 或仓位引擎。**呈现为报告内观察章节，非首页一级卡**（历史校验前不上前端权重） | **Phase 0a 数据可得性前置门：先摸 8 指标可稳定获取的时序，能稳定拿到 ≥5 个才立项开工，否则砍成轻量版**；Phase 0b spec + schema；Phase 1 手动/周度报告；Phase 2 快照持久化 + Evidence Card；Phase 3 只在历史校验后接入 `market_regime` 轻度注释 | 数据可得性未过前置门即进入 Phase 1；不直接改 official signal / 个股 scoring / 情感权重 / 仓位 / scheduler / test2；不得把缺数据指标伪装成中性 0；不得在未有历史命中记录前作为买卖建议或首页一级卡 |
| M51 外部项目借鉴优化 | 已启动 / non-promoting：D1 已把 DSR/PBO/trial-count 作为 `m29_hypothesis_registry` 的过拟合防线合约；研究轨已落 `research_report_pack.v1` 前端归一 adapter + Reports Markdown copy。详案 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md` | 下一步深化 Report Viewer / Evidence Card（不重写 deep_research），再在明确 scoped 时做 MingCang-GAIA seed；M29 续作只在 readiness true 后跑 forward shadow | non-promoting；不新建平行回测/因子/审计/数据校验系统；不改 official signal/仓位/scheduler/test2/weights |
| M29 Forward Evidence | 2026-06-12：价格回填完成（100支×7天，700行），baseline 1d/3d/5d artifacts 已建；positive delta 9/11+8/10+8/10 windows，non-promoting。M51 D1 统计门合约已补强：DSR/PBO/trial-count 必须报告 | 先刷新/确认 2026-06-12 之后 close-complete 价格覆盖，再重跑 readiness；只有 readiness true 才追加下一窗口 1d/3d/5d shadow 和 residual attribution | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| M44 Atlas 合并 | complete / dormant：`9820143` 已在 `origin/main`；Atlas/test4 Stage 2b signal-overlay shadow starter 可用；`ATLAS_ENABLED=false` | 只用 `backend.tools.atlas_test4_stage2b_shadow` 做 non-promoting shadow accrual；M51 D3（paper-only 双解锁 + 审计审查）归口此处 | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5（M51 D2/D4 数据覆盖+披露日 PIT 归口 M12） | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M51 外部金融开源项目借鉴优化【已启动 / D1 + report-pack adapter done / non-promoting】

Goal: 把外部金融开源项目（FinGenius/FinRobot/FinGPT/FinGAIA 研究系 + QuantDinger/alpha101 量化系）的长处**嫁接进明仓既有模块**，**不新建平行轨**。完整详案 + 逐项目重复判定 + 四域归口表见 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md`，本节只保留承重点。

核心判断（已对代码核实）：

- **QuantDinger / alpha101 对明仓净增量≈0**：回测引擎（`backend/backtest/`）、统计门+预注册（`backend/tools/m29_hypothesis_registry.py`）、append-only 审计（`backend/memory/audit_log.py`）、Qlib 因子+Alphalens IC（`backend/data/qlib_data.py` / `backend/backtest/alphalens_qlib.py`）均已自建。最大风险是"照抄造出平行轨"。
- **指导原则**：所有借鉴一律 graft 到现有模块；任何 PR 新建 `backtest_v2/`、`factors_v2/`、第二个 audit/数据校验层，直接拒。
- 曾提议的"M29.6 Historical Backtest Lab"**取消**（80% 已存在），拆成下列小 graft。

承重交付：

- **研究轨（本里程碑主体）**：① Phase 1（P0）单股研究报告包 v1——`research_report_pack.v1` 前端归一 adapter 已落地，可从 legacy deep-research payload 生成稳定 schema + Markdown；Reports 页已显示 pack 覆盖度并支持复制报告包。下一步仍是深化 Report Viewer / Evidence Card（M50 后端纪律前台化，不重写分析器）；③ Phase 3（P1）MingCang-GAIA 本地金融 agent 评测集（净新，首批 20–30 任务，只作研发指标、不回流信号）。
- **量化轨（小 graft，归口现有 owner，不新建里程碑）**：D1（P1）已在 `m29_hypothesis_registry` 合约层补 Deflated Sharpe / PBO / trial-count（复用 `backend/backtest/statistics/` 既有实现，不改算法）；D2/D4（P2）真实披露日 PIT + 100–300×3–5y 规模化验证，**本质是数据覆盖里程碑**（瓶颈是 financial 10/70、news 0/70，非引擎），归口 M12，数据补全前禁止规模化回测；D3（P2）paper-only 双解锁 token + 审计审查，归口 ATLAS。
- **明确不做**：alpha101 遗传挖矿、QuantDinger 执行层、把 Alpha101 的 101 因子塞进 `FEATURE_COLS`（只可作一次性 null-benchmark 电池跑一遍 m29 注册表，不进生产特征）。
- **新增借鉴对象：AI Berkshire（2026-07-02，用户判定 7/10 值得借鉴、不整套搬）**——Claude Code/Codex 投研 skill 集（四视角并行研究/固定报告结构/财务交叉验证/报告抽检/论文追踪/新闻异动归因）。只取 4 个小 graft，落点均为现有模块：① **报告 checklist/章节骨架** → `research_report_pack.v1` + dossier（只借结构不搬代码）；② **财务双源交叉验证**（关键财务数据 ≥2 独立来源、误差超阈标记）→ `ResearchReportGate` warning 检查项 + `research_evidence_defs`（与 M55 定性/数字分轨同族）；③ **报告抽检** → 按比例触发 M55 已建的 `review_loop.run_independent_review`（零新建）；④ **新闻异动归因卡**（事件时间线+四路主因+是否触发论文重审）→ M54 输出形态 + `forward_thesis` 触发字段。**不进门**：其 70% 年化战绩（作者自述，不作可迁移 alpha 证据）、价格区间/建仓比例/投资建议（违反明仓边界）、整套安装（造第二研究流程，违反 graft-not-parallel）。
- **新增借鉴对象：小红书美股投研 skill-pack 形态（2026-07-03，observe-only，原 M57 并入此处 / 不单开里程碑）**——源帖《美股投资者必装的10个AI投研工具（附使用指南）》`https://www.xiaohongshu.com/explore/6a379a330000000008026078`。只借"把重复投研动作封装成可复用 skill、按用户类型组合成长线研究/交易观察/内容报告三套 pack"的**产品形态**，不装同名美股 skills、不另建平行投研栈。落点：① **产品形态** → Reports/dossier 前端提供三套 skill-pack 入口而非孤立工具名，输出统一落 `research_report_pack.v1` 并显示 evidence ledger / gate status / as-of / freshness（承接上文 Report Viewer/Evidence Card 深化，不重写 deep_research）；② **A 股适配卡（先做贴近 M54/M50/M55 且不引入新交易假设的三张）**：`disclosure-change`（公告/年报/会计政策/风险因素/订单披露变化，不照搬 SEC/EDGAR）、`earnings-delta`（收入/毛利/现金流/应收/存货变化解释）、`fact-check-card`（L1-L4 质检+来源层级+缺数/过期显式提示）；`valuation-scenario`（DCF 只做情景/敏感性、不出目标价或仓位）仅 observe-only。**不进门**：`CANSLIM/VCP`、sector-rotation、flow 类只能作 M29/M32 hypothesis inputs 先注册再 shadow，不进 official signal；不引入目标价/建仓比例/荐股话术；不把 SEC/13F/EDGAR 机械映射成 A 股信号；资金流不入研究层打分。

改动顺序纪律：先做最小 graft（D1、Phase 1）并跑 `make verify`（基线 backend 1214 passed / 5 skipped）转绿，再碰 D2/D4 这类数据层改动。

Stop conditions: 任何改动触及 official signal / 仓位 / scheduler / test2 / production weights；blocked 报告落盘；eval 或回测结果被用于自动提升信号或可信记忆；出现第二个回测/因子/审计/数据校验系统；数据覆盖未补全即启动规模化回测。

---

## M56 AI 产业预警雷达【planned 2026-07-02 / observe-only / non-promoting】

Goal: 建一个独立的 AI 产业风险雷达，把“AI 内存墙 / 算力投资周期 / 融资泡沫传导”放在宏观与产业观察层，而不是塞进单股买卖分。它回答的是：AI 繁荣是否仍由真实需求驱动，还是开始转向 capex 过热、算力价格松动、信用链条脆弱与估值杀扩散。

核心指标（八点紧盯）：

- Hyperscaler capex / revenue 是否继续抬升，且收入转化跟不上投资强度。
- AI lab ARR / revenue 是否追不上算力、云服务、芯片采购或融资承诺。
- GPU 租赁价格是否持续下滑，提示算力供需从短缺转向宽松。
- HBM 涨价是否开始挤压下游毛利，而不是全链共振。
- AI 相关公司债、CDS、私募信贷赎回或折价融资是否恶化。
- 数据中心项目是否被电力、地方反对、融资成本或审批卡住。
- Treasury repo haircut / basis trade 压力是否从低位回升，提示杠杆资金链收紧。
- 美股 AI 龙头是否出现“业绩还好但估值杀”的走势，并向 A 股 AI 链情绪传导。

边界：

- **观察章节，不是首页一级卡**：呈现为报告/dashboard 内的 AI 产业风险观察章节；历史校验（Phase 3）通过前不做首页一级风险卡、不上前端权重。Phase 1 不回写 official signal、不改个股 scoring、不调 sentiment/quant 权重、不碰仓位。
- **缺数据显式暴露**：每个指标必须带 source/as-of/freshness/confidence。没有可靠数据时标 `missing_or_proxy`，不得用 0 或“中性”掩盖。
- **周期节奏分层**：周度完整报告；日度轻量观察只看市场价格/信用/估值杀/重大新闻；重大事件触发临时刷新。不得一开始接生产 scheduler。
- **归口**：报告呈现可复用 M51 `research_report_pack.v1` / Evidence Card；新闻与事件材料可复用 M54 L0-L2 管线；若未来用于风险修正，只能作为 `market_regime` 的轻度注释/折扣层，并且 default-off。

Phases:

0a. **数据可得性前置门（blocking）**：先对八指标逐一摸底可稳定获取的时序/代理源（可得性、频率、滞后、成本）。**能稳定拿到 ≥5 个才立项进 Phase 0b/1**；否则砍成只覆盖可靠指标的轻量版，或暂缓。缺失 3 个以上不得开工，避免建成常态化半空、信噪比低的"雷达"。
0b. spec（纸面）：定义 `AIIndustryWarningReport` / `AIWarningIndicator` schema、八指标数据源清单（含 0a 的可得性结论）、代理指标、刷新频率、风险等级（green/yellow/orange/red）和缺数口径。
1. 手动报告：实现本地 CLI/tool 手动跑周报，输出整体风险等级、八指标证据表、变化项、对 A 股 AI 链的 watch implications；只写报告/快照，不写 signal。
2. Evidence Card：把最近一次报告接到 Reports / dashboard，显示 as-of、source freshness、confidence、missing 指标和风险变化。
3. 历史校验：保留每期快照，评估预警等级与 AI 链指数/代表股票后续 1d/5d/20d 回撤、波动、估值收缩的关系；未通过历史校验不得接入交易判断。
4. 可选 regime overlay：仅在 Phase 3 有足够命中记录后，default-off 接入 `market_regime`，对 AI 链正向信号加“宏观拥挤/泡沫风险”注释或轻度风险折扣；启用必须用户显式确认。

Stop conditions: 直接生成买卖建议；直接调仓或改 position sizing；改 official signal / scheduler / test2 / production weights；把海外 AI 龙头或宏观融资指标机械映射成 A 股个股结论；没有 source/as-of/confidence 的指标进入总分；用新闻热度替代真实价格/信用/财务证据。

---

## M29 Alpha Reset / Forward Evidence Engine【active / non-promoting】

Production remains `new_framework`, `WEIGHT_QUANT=0.0`, Kronos disabled. No candidate has passed the promotion gate — **the canonical gate list is `STATUS.md` → Active Decision Layer** (single source of truth; not restated here to avoid drift). Additionally, per M51 D1 every candidate must report DSR/PBO/trial-count before promotion review.

Current execution:

1. Read `STATUS.md` and this section, then run `git status --short`.
2. First action is read-only: `backend.tools.m29_forward_readiness --db-url ...`.
3. **2026-06-12 state**: baseline 1d/3d/5d forward artifacts created. Price coverage
   backfilled through 2026-06-11 (100 symbols, 700 rows). Artifacts at
   `/private/tmp/m29_forward_shadow_rolling_20260401_20260610_1d.json`,
   `…_20260606_3d.json`, `…_20260604_5d.json`. Evidence: trade-weighted delta
   +0.89%/+1.67%/+2.80% for 1d/3d/5d; positive windows 9/11, 8/10, 8/10.
   Gate status: non-promoting (expected blockers: unknown_source_trains_model,
   not_continuous_quant_score, non_promoting_offline_diagnostic). Next: wait for
   fresh price coverage for 2026-06-12+, re-run readiness (primary blocker
   missing_existing_forward_artifacts now resolved), extend 1d/3d/5d window.
   2026-07-02 update: M51 D1 is now part of the preregistration contract, so
   every M29 candidate must report DSR/PBO/trial-count before promotion review.
4. If not ready, stop and wait. Do not treat partial local data as fresh evidence.
5. If ready, run 1d/3d/5d forward shadow bundle and add artifacts to `m29_evidence_ledger`.
6. Update M29.5 residual attribution in the same forward window. If still non-promoting, keep quant off.

Stop before any production change, checkpoint wiring, Kronos long training, true `sentiment_cache` writes, new dependency download, or extra paid external service.

---

## Other Open Items

| Item | Trigger | Action |
|---|---|---|
| M32 Forward Hypothesis Bridge | Review data becomes thick enough | Register sector / supply-chain theses as forward hypotheses; output falsifiable thesis, not Strong Buy labels |
| M24.3 Long-term constraint reconnect | Suggested checkpoint 2026-06-10 and later test2 freeze end >= 2026-07-18 | Still wait for the original freeze/sample horizon; early 2026-07-02 test2 close-out is not enough to reconnect long-term constraints |
| M25 product/community leftovers | Low priority / actual need | README demo, verified quickstart, mobile core paths, virtual list only after watchlist >200 causes lag |
| M21.4 ATR narrow-stop analysis | Test2 v1 closed 2026-07-02; production-rule analysis remains after broader sample/freeze review | Can draft a v1 false-stop postmortem and v2 hypothesis, but do not change production stop rules from the 10-trade test2 sample alone |
| M12 external data governance | Any new endpoint | Add provider health, PIT timestamp, field normalization, and tests before DB writes |
| M10.5 migrations | SQLite runtime patch becomes bottleneck | Consider Alembic baseline |
| M4 / M5 automation | Strong validated evidence and explicit user intent | LangGraph / FinMem / broker automation stay deferred; no real trades |

---

## M54 新闻层 v2（多源可插拔 · 正文级 · 多信号综合评分）【阶段0–7 已建 / 三轮预注册 OOS：第三轮推翻第二轮乐观结论 / observe-only】

> **状态刷新（2026-07-02，第三轮后）**：阶段0–7 代码全部建完（正文入库/适配器 seam/聚类/分级抽取/确定性融合/端到端编排/OOS harness+预注册/token 金字塔 `661deaa`）。三轮干净 OOS 已跑（判据先落盘，不事后改）：
> - **第一轮 06-29**（东财内容独力，50支）：IC天 12/8 « 20，gate_blocked，规则3 不晋级。
> - **第二轮 06-30**（+iFinD 正文，50支，同窗同样本同模型codex三腿对照）：v2 相对排序显著胜 legacy——h3d Δ=+0.074、h5d Δ=+0.099，v2 正 IC、legacy 负 IC。规则3 强形态：方向确立、样本不足、不晋级，生产维持 legacy。
> - **第三轮 07-02（100支，claude-sonnet-4-6，扩容后）：结论反转**——h3d 上 **legacy 反超 v2**（Δ=-0.064，legacy IC+0.118 vs v2 IC+0.054），仅 h5d 仍支持 v2（Δ=+0.081）。两 horizon 不一致，按预注册规则3 字面判定：**第二轮"v2胜出"判为小样本假象**，v2 信号设计需回炉，生产继续维持 legacy。v2-pyramid 保真度也未达标（两 horizon 均劣于 v2-full，幅度远超 -0.01 门，疑不止阈值问题）。
> - **横截面扩容三轮一致证伪**：IC天由 12/8（50支）→14/9（100支，第三轮三腿一致），扩了一倍股票数只挪 2 天——**确定性结论：IC天由非重叠时间窗口数决定，与横截面宽度基本无关，下一步不再扩股票数**。详见 `docs/dev/M54_OOS_PREREGISTER.md` §9-10。

### Token 经济学约束（2026-07-02 增补 · 扩样本前必须先落地）

**问题**：当前成本模型 = 每股 × 每天 × 同深度均匀处理；正文级(数千 token/篇)若直接铺到 100-300 支，OOS 与未来生产成本均爆炸（naive 估算 ~200 万 token/天量级）。**新闻的信息结构不均匀：大盘/政策/行业新闻共享、个股真有料的日子是少数**——均匀处理 = 大部分 token 花在"今天没事"的股票与重复分析同一条政策上。

**四层金字塔（在 spec「分级读正文」基础上扩成全链路设计）**：
- **L0 确定性层（零 LLM，永远全量）**：多源拉取、去重、`event_taxonomy` 关键词事件分类（已有）、source_diversity、资金流数字、政策关键词命中。
- **L1 触发层（规则，决定谁配吃 LLM）**：仅命中触发器的股票升级——新公告/财报落地、价量异动、政策关键词、source_diversity 突增、L0 事件分≥阈值。**未触发 = 复用昨日结果 + as-of 戳，不调 LLM**。
- **L2 共享域层（LLM 按域不按股）**：大盘 1 份/天 + 政策 1 份/天 + 行业按板块 ~20 份/天 + 个股仅 L1 触发者。**成本从 O(股票数) 变 O(板块数+触发数)，对关注列表规模亚线性**（金字塔后估算 ~24 万 token/天，约省 8 倍，200 支时几乎不涨）。
- **L3 深研层（贵，仅按需）**：deep_research/dossier 仅用户点击或论题触发重审时跑，走 gate；加增量更新（复用未过期章节），不整篇重写。

**配套**：① 预算护栏——`llm_usage.py` 已有按桶统计，加日预算阈值，sentiment 桶超限自动降级（只跑 L0/L1 + 显式"今日 LLM 降级"flag，与降级铁律同构）；② 前端放弃 100 支实时，改**推送模型**——夜间批量 + 盘中仅异动刷新，每卡带 as-of 时间戳与新鲜度标记（旧数据标旧，不装实时）。

**输出形态增补（借 AI Berkshire news-pulse，归 M51 borrowing）**：个股触发 L2 时产出「**异动归因卡**」——事件时间线 + 主因判断（公司事件/监管政策/行业对手/市场情绪四路）+ **是否触发论题重审**（接 forward_thesis 触发字段）。只借输出形态，不借其 web-only 流程。

### 阶段7：token 金字塔实施（2026-07-02 列编 · 全部落在 v2 管线内，生产 legacy 打分链零接触）

> 铁律：`backend/analysis/sentiment.py`（legacy 生产打分链）本阶段一行不改；金字塔全部构件挂在 v2（本身 default-off），成本优化天然 observe-only。新 config 一律 default-safe。

- [ ] **7a L1 触发层**：确定性 `TriggerDecision`（无 LLM）——新公告/价量异动/政策关键词/source_diversity 突增/L0 事件分≥阈值，任一命中才升级吃 LLM；未触发=复用昨日+as-of 戳。附「异动归因卡」最小结构体（时间线/四路主因/是否触发论题重审），字段确定性生成、不靠 LLM 拍。
- [ ] **7b L2 域共享**：簇作用域分类（market/policy/sector/stock，确定性规则）+ 共享 digest 缓存（按 scope+date 键控）——非个股专属簇每域每天只打一次分、跨股复用；个股专属簇仅 L1 触发者打分。
- [ ] **7c 预算护栏**：基于 `llm_usage` 的日预算计量 + 阈值 config；v2 管线超限自动降级（显式 flag，与降级铁律同构）；legacy 侧最多加"仅告警不拦截"钩子（default-off）。
- [ ] **7d 前端推送模型**（后置，待 v2 挣到启用资格再做）：夜间批量+异动刷新+as-of 新鲜度标记。

验收：全量 pytest 绿；`git diff` 不含 sentiment.py/official signal/scheduler/test2/weights；新增检查项有测试；OOS 第三轮直接走金字塔管线跑（同时回答 alpha 与成本两个问题）。

承接 M52 收口（标题级新闻情感干净 OOS 证伪——sonnet 三腿全负 IC、无显著差异、无一过门；详见工作分支 `codex/m52-news-sentiment-on-m51` 的 `docs/dev/M52_NEWS_FINISH_PLAN.md` 与 `paper_trading/m52_oos_preregister.md`）+ 决定性新发现：**东财/Anspire 正文一直被入库口丢弃**（东财 `backend/data/news.py:146`、Anspire `:411`），M52 全程建立在「26 字纯标题、零正文」上。库内 96% 是 Anspire 财经媒体、Tavily 仅 4%、iFinD MCP 已是第一兜底——问题不是「只用 Tavily」，而是「全链路只留标题」。

**目标（两者并重）**：① 基建——多源可插拔 + 统一 evidence schema + 拉正文 + 用户自选/自接源；"源无关" = **处理源无关**（换/加源不改评分逻辑），非输出相同。② alpha——正文级 + 多信号综合评分跑赢 legacy，default-off 靠独立 OOS 挣启用资格。

**核心设计**：5 层架构（适配器只取数不评分 → 归一/聚类 → 分级抽取 → 确定性融合+降级 → v2 候选）。关键机制：(a) **分级读正文**（全部存、materiality 高的才用强模型啃全文）；(b) **source_diversity（不同源数而非文章数）做置信**——结构上修兆易 whipsaw（一事件 50 转载≠信号）；(c) **确定性可审计融合**：news_score(簇加权) ⊕ flow_score(真实资金流,独立通道)；(d) **降级铁律**：某类缺失显式降 confidence + 打 flag，绝不塞冒充信号的中性 0。信号分期：一期=正文情感+资金流，二期=公告/龙虎榜(接 M53,可能最高价值)，延后=研报。

**完整 spec**：`docs/dev/M54_NEWS_LAYER_V2_DESIGN.md`（架构/schema/管线/融合/降级/路线A·B·C/验证门控/回填可行性/实施6阶段/开放决策）。

**第一动作（2026-07-02 第三轮后刷新）**：~~扩 universe 至 100-300 支~~（已做，证伪"扩横截面"路径）→ 现为：① 诊断第二轮为何未复现（是否第二轮50支恰为有利子样本、或新增50支拖累信号——需对比两轮子样本的具体差异，而非直接归因样本量）；② 按预注册规则2 改**向前采集扩窗口**（IC天是唯一瓶颈，三轮已证与横截面无关，不再扩股票数）；③ 独立诊断 v2-pyramid 触发逻辑损伤幅度异常（不只当阈值调参处理）。

**停止条件**：未过独立预注册 OOS 门即启用 v2 / 接 live test2 / 改情感权重 / 外溢到 official signal·仓位·scheduler；不机械堆源充数（无 dedup/materiality 的多源放大 whipsaw）；把探索性 IC 当统计裁决；**不再扩横截面掩盖 IC天瓶颈**（三轮已证无效）；`weight_sentiment=0.4` 系 stock-sage 初始快照继承默认、从未被推导——**由 M54 OOS 结果重定，中途不手调**（保测试可比性）；**不事后挑解释掩盖方向消失**（第三轮 h3d 反转是真实结果，不因模型/窗口差异找借口否定规则3 的触发）。

---

## Completed Milestones Index

Detailed history is intentionally not repeated here. Read `CHANGELOG.md` for:

- M55 Serenity 收敛进 ATLAS 研究脊柱 + s-skill 优点归口（Phase 0-3 done 2026-07-02 `e45bbb1`，1274 passed / 生产 diff=0；详见 `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md`）.
- M50 Serenity 瓶颈研究 skill + ResearchReportGate 强制报告门（Phase 0-3 released / non-promoting；详见 `docs/dev/m50_research_report_gate_spec.md`）.
- M46 onboarding/demo clarity and user-discovery follow-up.
- M46.5–M48 correctness floor (lookahead one-time audit + key-number display tests), standing `lookahead-check` + data-trust visibility, and frontend TS/API/primitive reliability.
- v0.5.1 context sanitization and status surface hardening.
- v0.5.0 MingCang naming finalization and transition compatibility removal.
- v0.4.3 frontend punctuation normalization and M29 forward baseline release.
- v0.4.2 frontend TypeScript module migration and visibility hardening.
- v0.4.1 public-surface polish.
- v0.4.0 frontend glass-shell refresh.
- v0.3.4 research source-gate hardening.
- v0.3.3 productization, reproducible evidence, community entry, and stability hardening.
- M49 tools registry / observability.
- M45 source-gated research positioning, importer, scoreboard, and Stage 2b shadow preregistration.
- M44 dormant Atlas L0-L4 merge.
- M30 engineering quality convergence.
- M31 cache / provider fallback / rhythm CLI / postmarket exports.
- M41 read-only A/HK/US global data and research facade.
- M42 qfq/hfq contamination guard and remediation.
- M43 architecture boundary hardening.
- M28 research integration.
- M27 alpha evidence closure, not promoted.
- M26 quant/Kronos reassessment, not promoted.
- M0-M25 historical buildout and cleanup.
