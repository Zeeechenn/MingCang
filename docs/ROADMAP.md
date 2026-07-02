# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

> 已完成里程碑（v0.3.3–v0.5.1、M44–M50 等）不再列在本活跃表，详见文末 Completed Milestones Index 与 `CHANGELOG.md`。本表只保留进行中 / 未启动 / 触发待命的工作线。

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M54 新闻层 v2（多源可插拔·正文级·多信号综合评分） | 阶段0–5b 已建 + 两轮预注册 OOS（06-29/06-30）。**第二轮同窗三腿：v2 相对排序显著胜 legacy（h3d Δ=+0.074 / h5d Δ=+0.099，均超 +0.02 门；v2 正 IC、legacy 负）——「读正文≫读标题」首次正向支持**；但 IC天 12/8<20 绝对门未过 → 规则3 不晋级，生产维持 legacy。唯一硬门=横截面薄（50 支）。2026-07-02 增补 token 经济学约束（L0-L3 金字塔/域共享/预算护栏/前端推送模型，见 M54 节）。spec `docs/dev/M54_NEWS_LAYER_V2_DESIGN.md` + `docs/dev/M54_OOS_PREREGISTER.md` §7-8 | ① 先落地金字塔 L0/L1/L2 + 预算护栏（扩样本前置）② 扩 universe ~100-300 支采集/回填 ③ 再预注册第三轮同窗三腿 | 未过独立预注册 OOS 即启用/接 live test2/改情感权重/外溢 official signal·仓位·scheduler；金字塔未落地前不开正文级全量扩样本；weight_sentiment 由 OOS 重定、中途不手调；探索性 IC 当裁决 |
| M51 外部项目借鉴优化 | 已启动 / non-promoting：D1 已把 DSR/PBO/trial-count 作为 `m29_hypothesis_registry` 的过拟合防线合约；研究轨已落 `research_report_pack.v1` 前端归一 adapter + Reports Markdown copy。详案 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md` | 下一步深化 Report Viewer / Evidence Card（不重写 deep_research），再在明确 scoped 时做 MingCang-GAIA seed；M29 续作只在 readiness true 后跑 forward shadow | non-promoting；不新建平行回测/因子/审计/数据校验系统；不改 official signal/仓位/scheduler/test2/weights |
| M55 Serenity 收敛进 ATLAS + s-skill 优点归口 | **Phase 0-3 done 2026-07-02（`e45bbb1`，1274 passed / 生产 diff=0）** / observe-only·non-promoting：M50 的 `serenity_chokepoint.analyze()` 事实休眠（default-off + 零 CLI/web/pipeline 入口，仅 tests/gate 类型注解引用），SKILL.md 生产影响≈0。按 M51 graft-not-parallel 原则收敛进 ATLAS 脊柱（theme_hypothesis_engine/forward_thesis/review_loop/dossier），并把 ZadAnthony/muxuuu/fadewalk 三个外部 Serenity skill 优点归口 ATLAS 各模块。详案 `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md` | Phase 0 spec：优点→ATLAS 归口映射 + serenity 六步 vs ATLAS 逐条边界比对 + README 诚实口径修正 | 层纯度红线（fadewalk 资金流禁入研究层）；不改 official signal/仓位/scheduler/test2/weights；blocked 报告不落盘；不新建平行轨；生产 signal diff=0 |
| M50 Serenity 瓶颈 skill + 强制报告门 | Phase 0-3 complete/released；non-promoting | 下一步只在明确需要时开下一批质量门或前端 evidence card（已并入 M51 Phase 2）；否则回到 M29 evidence ops / 用户反馈 | 不接长期标签加权、不改 official signal/仓位/scheduler/test2、blocked 报告不落盘 |
| M29 Forward Evidence | 2026-06-12：价格回填完成（100支×7天，700行），baseline 1d/3d/5d artifacts 已建；positive delta 9/11+8/10+8/10 windows，non-promoting。M51 D1 统计门合约已补强：DSR/PBO/trial-count 必须报告 | 先刷新/确认 2026-06-12 之后 close-complete 价格覆盖，再重跑 readiness；只有 readiness true 才追加下一窗口 1d/3d/5d shadow 和 residual attribution | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| M44 Atlas 合并 | complete / dormant：`9820143` 已在 `origin/main`；Atlas/test4 Stage 2b signal-overlay shadow starter 可用；`ATLAS_ENABLED=false` | 只用 `backend.tools.atlas_test4_stage2b_shadow` 做 non-promoting shadow accrual；M51 D3（paper-only 双解锁 + 审计审查）归口此处 | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5（M51 D2/D4 数据覆盖+披露日 PIT 归口 M12） | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M50 Serenity 瓶颈研究 skill + UZI 强制报告门【Phase 0-3 released / next batch optional / non-promoting】

Goal: 补两块研究方法真空 —— Serenity 风格供应链瓶颈拆解 + 证据分层纪律（借鉴 赛道研究员"SKILL.md + 结构化 LLM 输出"的工程模式，但**不接入长期标签聚合**），以及 UZI 风格的**输出侧强制报告门**（检查不过的报告物理上写不出）。两者配套：Serenity 产检查项，Gate 负责强制执行。全程 observe-only / source-gated / non-promoting。来源是两份外部 skill 学习报告（Serenity 系列 S1–S8 + UZI）。

Key design constraints（已对代码核实）:

- **Serenity 不复用 `role="track"`、不返回 `LongTermReport`、不进 `LongTermTeam._aggregate_score`**。`LongTermReport` 强制带 `score`/`label_vote`，且 `team.py` 把 track(赛道研究员)/quality(piotroski)/boom(jingqi)/flow(QFII) 加权合成长期标签——Serenity 一旦走 track 槽就会污染长期标签，违背 non-promoting。改出独立 `SerenityChokepointReport`：`chokepoint_layer` / `chain_layers[]` / `evidence_tier` / `source_refs[]` / `substitute_risk` / `quick_filter_pass` / `falsification_questions[]` / `bear_case` / `research_priority_band`（枚举 `够查`/`暂缓`/`证据不足`，**非数字**）。不出 score/vote。
- **ResearchReportGate** 落 `backend/research/research_report_gate.py`，沿用 M46.5/M47 的 `pass/warning/blocked` 口径。必须在 `deep_research.py` 的 `write_text()` **之前**执行（当前顺序 `_render_report()`→`write_text()`→`_persist_report()`；放 persist 前文件已落盘，达不到"物理上发不出"）。blocked 时不 `write_text` / 不 `record_decision_run` / 不 `remember_deep_research` / 不建 memory candidate。
- **Gate 作用域 = 所有 deep research 报告**：以 `DeepResearchReport` + audits 为基线检查，Serenity 字段有则加严、无则按现有字段判（不假设 Serenity 一定跑过）。
- **共享 module**：`source_tier` 枚举 + forbidden-wording 词表，被 Serenity 与 Gate 同时 import。与输入侧 `FORBIDDEN_TEMPLATE_KEYS` 职责切开——前者查输入字段名，后者查最终文本措辞，同一检查不两处写。
- Serenity 调用方：主入口在 `deep_research.py` 内 `write_text()` 前；旁路入口为独立 CLI/tool 供单主题人工试跑，结果只回显不写 DB。

Phases:

0. ✅ done — 纯文档/prompt，零代码：`serenity-chokepoint/SKILL.md`（瓶颈分层 / quick filter 分层 / source tier / A股 source playbook / 贝叶斯追踪 / 反方先行 QA）+ Gate 检查清单 spec + 共享定义；固态电池主题人工试跑通过（证据/叙事/风险分清、零买卖语气、媒体-only 判 blocked）。
1. ✅ done — 独立 Serenity 结构化器（flag 默认 False，不写 DB，不接 LongTermTeam）+ `research_evidence_defs.py` + `research_report_gate.py` + `deep_research` 写前挂点；50 M50 测试 green（schema 不生成 score/vote、Gate blocked 不落盘、聚合隔离均覆盖）。
   - ✅ Phase 1 收尾 done：① 数据覆盖最终定为 **warning（永不 blocked）**——gate 接真实 prices/financials，纯主题(symbols=[])不罚，理由见 spec §3；② blocked 报告经新增 `DeepResearchReport.gate_status` 字段区分（不靠 path.exists）。70 M50 测试 green、lint/mypy clean。
2. ✅ done — 扩 `ai_supply_chain_template.py`：加 `chain_layers` / `source_tier` / `substitute_risk` / `source_freshness`；新合法字段**不得进** `FORBIDDEN_TEMPLATE_KEYS`；`observe_only/signal_impact/not_a_buy_score` 仍不可覆盖。
3. ✅ done — M45 importer 现有 source gate **增强（非重写）**：加 `source_tier`（execute 不能只有 social）、`evidence_level != needs_check`；`source_kind=derived_summary`/`handoff_context` 仍只能 dry-run。`m45_track_hook_update` 继承 importer gate；`m45_falsification_scoreboard` 同步相同 source-tier / evidence-level guard，避免 M45 旁路漂移。

Not in this batch: research_priority 数字分（用档位防漂移）、TradingAgents 多 agent/checkpoint（重、撞 dormant Atlas、ReviewCase 已覆盖闭环）、QuantDinger action scope 细分（audit 字段加厚/可复现快照留 P2 顺手）、UZI 评委团人格、前端 evidence cards（P2）、Buffett 质量门（P1 下一批，做时须与 piotroski 交叉引用防双重扣分）。

Stop conditions: 不改 official signal / 仓位 / 止盈止损 / scheduler / test2 / production weights；不进长期标签加权；不写 trusted memory（除非 ReviewCase + 人工确认）；blocked 报告不得落盘或 promotion；本地开发不加多余确认门。

> 完整 S1–S7 协同 / C1–C6 冲突矩阵与逐 Phase 验收在工作规划文档维护，本节只保留里程碑级承重点。

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

改动顺序纪律：先做最小 graft（D1、Phase 1）并跑 `make verify`（基线 backend 1214 passed / 5 skipped）转绿，再碰 D2/D4 这类数据层改动。

Stop conditions: 任何改动触及 official signal / 仓位 / scheduler / test2 / production weights；blocked 报告落盘；eval 或回测结果被用于自动提升信号或可信记忆；出现第二个回测/因子/审计/数据校验系统；数据覆盖未补全即启动规模化回测。

---

## M55 Serenity 收敛进 ATLAS 研究脊柱 + s-skill 优点归口【planned 2026-07-02 / observe-only / non-promoting】

Goal: M50 交付的 `serenity_chokepoint.analyze()` **事实休眠**——`long_term_serenity_enabled=False` 且全仓无 CLI/web/pipeline 入口调用它（仅 tests + gate 类型注解引用），`.pi/skills/serenity-chokepoint/SKILL.md` 生产影响≈0。同时 `backend/research/`（18 模块）已有成熟 ATLAS 脊柱（theme_hypothesis_engine / forward_thesis / review_loop / dossier / thesis_ledger / stress_test），其证据分层 / 证伪 / 假设追踪与 serenity 六步高度重叠。本里程碑按 **M51「graft-not-parallel」** 原则：把 serenity 六步降级为跑在 ATLAS 脊柱上的**方法论透镜**（不再是独立平行 analyzer），消除重复；并把三个外部 Serenity skill（ZadAnthony / muxuuu / fadewalk，对比结论见 `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md`）的优点**归口到 ATLAS 各模块**，而非堆进即将退役的独立分析器。

Key constraints（对代码核实）:

- **README 诚实口径先修**：公开面「Serenity 灰度中」与代码（default-off + 零入口）不符，踩自定诚实红线（[[project_mingcang_growth]]）。Phase 1 先修为与代码一致的表述（方法论就绪 / 待激活）。
- **保留 M50 真资产**：`research_report_gate.py`（已接 `deep_research.py:838` 写前、default ON）+ `research_evidence_defs.py`（SourceTier / 禁词，已被 M45 tools 复用）继续做共享地基，本里程碑不动其对外契约。
- **serenity_chokepoint.analyze() 瘦身 / 退役**：必须保持 `test_serenity_chokepoint` 隔离不变量——no score/vote 字段、不 import backend.decision/LongTermTeam、非 LongTermReport 子类。
- **层纯度红线**：fadewalk 的资金流维度（龙虎榜 / 主力净流入 / 北向 / 筹码）**禁入研究层**——属信号 / 择时层，`qfii_flow_analyst` 已管；如用只作 observe-only 事件线索且强制 source-gating，不给分、不进档。
- **弃**：zad 的估值引擎（A/B 法 + PT + 仓位 + 预期空间数字）违反 observe-only，不引入。

优点归口映射（spec 逐条展开）:

| 来源优点 | 归口 ATLAS 模块 | 处理 |
|---|---|---|
| zad 独立 reviewer sub-agent | `review_loop.py` | 合并强化，不重造 |
| zad 中文表达规范（禁黑话 / 加粗≤25） | `dossier` 全局输出规范 | 所有研报受益 |
| zad 发现硬门 + 定性/数字分轨 | `research_report_gate` 检查项 | 从 SKILL.md 文字劝导 → 门强制（additive） |
| zad 14 判据 / 10 红旗颗粒度 | `theme_hypothesis_engine` / `forward_thesis` | 选择性吸收 |
| muxuuu 工程打包（refs/validate/evals） | ATLAS 自有 test 套件 | 转化可测性，不做独立 skill 包 |
| fadewalk 资金流维度 | —— | 弃 / 隔离（层纯度） |

Phases:

0. spec（纸面 / `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md`）：优点→ATLAS 归口映射 + serenity 六步 vs ATLAS 逐条边界比对（合 / 退役 / 保留独立）+ observe-only 边界。
1. 无悔：README 诚实口径修正；发现硬门 / 定性数字分轨从 SKILL.md 下沉为 gate 检查项（additive、default-safe）。
2. 归口 landing：中文表达规范 → dossier；reviewer → review_loop；serenity `analyze()` 瘦身 / 退役；SKILL.md 转方法论文档。
3. 回归：`PYTHONPATH=. pytest -q` 转绿 + 确认生产 signal diff=0（`git diff --name-only` 不含 signal/decision/scheduler/test2/weights）。

Stop conditions: 同 M50/M51（不改 official signal / 仓位 / 止盈止损 / scheduler / test2 / production weights；不进长期标签加权；blocked 报告不落盘；不新建平行轨）+ 层纯度红线（资金流不入研究层）+ 生产 signal diff=0。

---

## M29 Alpha Reset / Forward Evidence Engine【active / non-promoting】

Production remains `new_framework`, `WEIGHT_QUANT=0.0`, Kronos disabled. No candidate has passed the promotion gate:

- IC >= 0.04
- ICIR >= 0.40
- monotonic buckets
- non-overlapping / stride evidence
- sufficient fresh forward sample
- no cache, fallback, provenance, or data-quality blockers
- human confirmation

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

## M54 新闻层 v2（多源可插拔 · 正文级 · 多信号综合评分）【阶段0–5b 已建 / 两轮预注册 OOS：方向胜出·样本不足 / observe-only】

> **状态刷新（2026-07-02）**：阶段0–5b 代码全部建完（正文入库/适配器 seam/聚类/分级抽取/确定性融合/端到端编排/OOS harness+预注册），iFinD+Tavily 适配器已接（阶段6 partial）。两轮干净 OOS 已跑（判据先落盘）：
> - **第一轮 06-29**（东财内容独力）：IC天 12/8 « 20，gate_blocked，规则3 不晋级。
> - **第二轮 06-30**（+iFinD 正文，同窗同样本同模型三腿对照）：**v2 相对排序显著胜 legacy——h3d Δ=+0.074、h5d Δ=+0.099（均远超 +0.02 显著门），v2 正 IC、legacy 负 IC**。这是「读正文 ≫ 读标题」核心假设的首次正向支持（对比 M52 标题级全负）。但 IC天 12/8 < 20、非单调 → 绝对门未过，**规则3 强形态：方向确立、样本不足、不晋级，生产维持 legacy**。
> - **唯一硬门 = 横截面薄**（50 支 → IC天 8-12，与内容覆盖无关）。**下一步：扩 universe 至 ~100-300 支 → 再预注册 → 同窗三腿重跑**；过绝对门后按预注册规则1 走用户显式授权 + epoch-reset 才可上 live。详见 `docs/dev/M54_OOS_PREREGISTER.md` §7-8。

### Token 经济学约束（2026-07-02 增补 · 扩样本前必须先落地）

**问题**：当前成本模型 = 每股 × 每天 × 同深度均匀处理；正文级(数千 token/篇)若直接铺到 100-300 支，OOS 与未来生产成本均爆炸（naive 估算 ~200 万 token/天量级）。**新闻的信息结构不均匀：大盘/政策/行业新闻共享、个股真有料的日子是少数**——均匀处理 = 大部分 token 花在"今天没事"的股票与重复分析同一条政策上。

**四层金字塔（在 spec「分级读正文」基础上扩成全链路设计）**：
- **L0 确定性层（零 LLM，永远全量）**：多源拉取、去重、`event_taxonomy` 关键词事件分类（已有）、source_diversity、资金流数字、政策关键词命中。
- **L1 触发层（规则，决定谁配吃 LLM）**：仅命中触发器的股票升级——新公告/财报落地、价量异动、政策关键词、source_diversity 突增、L0 事件分≥阈值。**未触发 = 复用昨日结果 + as-of 戳，不调 LLM**。
- **L2 共享域层（LLM 按域不按股）**：大盘 1 份/天 + 政策 1 份/天 + 行业按板块 ~20 份/天 + 个股仅 L1 触发者。**成本从 O(股票数) 变 O(板块数+触发数)，对关注列表规模亚线性**（金字塔后估算 ~24 万 token/天，约省 8 倍，200 支时几乎不涨）。
- **L3 深研层（贵，仅按需）**：deep_research/dossier 仅用户点击或论题触发重审时跑，走 gate；加增量更新（复用未过期章节），不整篇重写。

**配套**：① 预算护栏——`llm_usage.py` 已有按桶统计，加日预算阈值，sentiment 桶超限自动降级（只跑 L0/L1 + 显式"今日 LLM 降级"flag，与降级铁律同构）；② 前端放弃 100 支实时，改**推送模型**——夜间批量 + 盘中仅异动刷新，每卡带 as-of 时间戳与新鲜度标记（旧数据标旧，不装实时）。

**输出形态增补（借 AI Berkshire news-pulse，归 M51 borrowing）**：个股触发 L2 时产出「**异动归因卡**」——事件时间线 + 主因判断（公司事件/监管政策/行业对手/市场情绪四路）+ **是否触发论题重审**（接 forward_thesis 触发字段）。只借输出形态，不借其 web-only 流程。

承接 M52 收口（标题级新闻情感干净 OOS 证伪——sonnet 三腿全负 IC、无显著差异、无一过门；详见工作分支 `codex/m52-news-sentiment-on-m51` 的 `docs/dev/M52_NEWS_FINISH_PLAN.md` 与 `paper_trading/m52_oos_preregister.md`）+ 决定性新发现：**东财/Anspire 正文一直被入库口丢弃**（东财 `backend/data/news.py:146`、Anspire `:411`），M52 全程建立在「26 字纯标题、零正文」上。库内 96% 是 Anspire 财经媒体、Tavily 仅 4%、iFinD MCP 已是第一兜底——问题不是「只用 Tavily」，而是「全链路只留标题」。

**目标（两者并重）**：① 基建——多源可插拔 + 统一 evidence schema + 拉正文 + 用户自选/自接源；"源无关" = **处理源无关**（换/加源不改评分逻辑），非输出相同。② alpha——正文级 + 多信号综合评分跑赢 legacy，default-off 靠独立 OOS 挣启用资格。

**核心设计**：5 层架构（适配器只取数不评分 → 归一/聚类 → 分级抽取 → 确定性融合+降级 → v2 候选）。关键机制：(a) **分级读正文**（全部存、materiality 高的才用强模型啃全文）；(b) **source_diversity（不同源数而非文章数）做置信**——结构上修兆易 whipsaw（一事件 50 转载≠信号）；(c) **确定性可审计融合**：news_score(簇加权) ⊕ flow_score(真实资金流,独立通道)；(d) **降级铁律**：某类缺失显式降 confidence + 打 flag，绝不塞冒充信号的中性 0。信号分期：一期=正文情感+资金流，二期=公告/龙虎榜(接 M53,可能最高价值)，延后=研报。

**完整 spec**：`docs/dev/M54_NEWS_LAYER_V2_DESIGN.md`（架构/schema/管线/融合/降级/路线A·B·C/验证门控/回填可行性/实施6阶段/开放决策）。

**第一动作（2026-07-02 刷新）**：~~阶段0 可行性验~~（已完成）→ 现为：① 先落地 L0/L1/L2 金字塔与预算护栏（扩样本的前置，防 OOS 第三轮成本爆炸）；② 扩 universe 至 ~100-300 支做内容采集/回填；③ 再预注册第三轮，同窗三腿重跑。

**停止条件**：未过独立预注册 OOS 门即启用 v2 / 接 live test2 / 改情感权重 / 外溢到 official signal·仓位·scheduler；不机械堆源充数（无 dedup/materiality 的多源放大 whipsaw）；把探索性 IC 当统计裁决；**顺序纪律：金字塔触发层/域共享未落地前不得开正文级全量扩样本**（顺序反了成本先爆）；`weight_sentiment=0.4` 系 stock-sage 初始快照继承默认、从未被推导——**由 M54 OOS 结果重定，中途不手调**（保测试可比性）。

---

## Completed Milestones Index

Detailed history is intentionally not repeated here. Read `CHANGELOG.md` for:

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
