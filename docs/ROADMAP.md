# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

> 已完成里程碑（v0.3.3–v0.5.1、M44–M50 等）不再列在本活跃表，详见文末 Completed Milestones Index 与 `CHANGELOG.md`。本表只保留进行中 / 未启动 / 触发待命的工作线。

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M54 新闻层 v2（多源可插拔·正文级·多信号综合评分） | 设计定稿 2026-06-28 / 路线A / observe-only 待实施。承接 M52 收口（标题级新闻情感干净 OOS 证伪，详见工作分支 `codex/m52-news-sentiment-on-m51`）+ 决定性发现：东财/Anspire 正文一直被入库口丢弃（`news.py:146`/`:411`），M52 全程只用 26 字标题；库内 96% 是 Anspire、Tavily 仅 4%、iFinD MCP 已是第一兜底。目标两者并重：多源可插拔统一 schema 拉正文（"源无关"=处理源无关）+ 正文级多信号综合评分跑赢 legacy（default-off 靠独立 OOS）。核心：分级读正文 + source_diversity 反兆易 whipsaw + 确定性可审计融合(新闻⊕真实资金流) + 缺失显式降级不污染。完整 spec `docs/dev/M54_NEWS_LAYER_V2_DESIGN.md` | 阶段0：实测东财/Anspire 能否取历史正文（定一期 OOS 时间线）+ `news` 表加 content/provider 列 + 入库口停止丢 content | 未过独立预注册 OOS 即启用/接 live test2/改情感权重/外溢 official signal·仓位·scheduler；不机械堆源放大 whipsaw；探索性 IC 当裁决 |
| M51 外部项目借鉴优化 | 已启动 / non-promoting：D1 已把 DSR/PBO/trial-count 作为 `m29_hypothesis_registry` 的过拟合防线合约；研究轨已落 `research_report_pack.v1` 前端归一 adapter + Reports Markdown copy。详案 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md` | 下一步深化 Report Viewer / Evidence Card（不重写 deep_research），再在明确 scoped 时做 MingCang-GAIA seed；M29 续作只在 readiness true 后跑 forward shadow | non-promoting；不新建平行回测/因子/审计/数据校验系统；不改 official signal/仓位/scheduler/test2/weights |
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

改动顺序纪律：先做最小 graft（D1、Phase 1）并跑 `make verify`（基线 backend 1214 passed / 5 skipped）转绿，再碰 D2/D4 这类数据层改动。

Stop conditions: 任何改动触及 official signal / 仓位 / scheduler / test2 / production weights；blocked 报告落盘；eval 或回测结果被用于自动提升信号或可信记忆；出现第二个回测/因子/审计/数据校验系统；数据覆盖未补全即启动规模化回测。

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

## M54 新闻层 v2（多源可插拔 · 正文级 · 多信号综合评分）【设计定稿 2026-06-28 / 路线A / observe-only 待实施】

承接 M52 收口（标题级新闻情感干净 OOS 证伪——sonnet 三腿全负 IC、无显著差异、无一过门；详见工作分支 `codex/m52-news-sentiment-on-m51` 的 `docs/dev/M52_NEWS_FINISH_PLAN.md` 与 `paper_trading/m52_oos_preregister.md`）+ 决定性新发现：**东财/Anspire 正文一直被入库口丢弃**（东财 `backend/data/news.py:146`、Anspire `:411`），M52 全程建立在「26 字纯标题、零正文」上。库内 96% 是 Anspire 财经媒体、Tavily 仅 4%、iFinD MCP 已是第一兜底——问题不是「只用 Tavily」，而是「全链路只留标题」。

**目标（两者并重）**：① 基建——多源可插拔 + 统一 evidence schema + 拉正文 + 用户自选/自接源；"源无关" = **处理源无关**（换/加源不改评分逻辑），非输出相同。② alpha——正文级 + 多信号综合评分跑赢 legacy，default-off 靠独立 OOS 挣启用资格。

**核心设计**：5 层架构（适配器只取数不评分 → 归一/聚类 → 分级抽取 → 确定性融合+降级 → v2 候选）。关键机制：(a) **分级读正文**（全部存、materiality 高的才用强模型啃全文）；(b) **source_diversity（不同源数而非文章数）做置信**——结构上修兆易 whipsaw（一事件 50 转载≠信号）；(c) **确定性可审计融合**：news_score(簇加权) ⊕ flow_score(真实资金流,独立通道)；(d) **降级铁律**：某类缺失显式降 confidence + 打 flag，绝不塞冒充信号的中性 0。信号分期：一期=正文情感+资金流，二期=公告/龙虎榜(接 M53,可能最高价值)，延后=研报。

**完整 spec**：`docs/dev/M54_NEWS_LAYER_V2_DESIGN.md`（架构/schema/管线/融合/降级/路线A·B·C/验证门控/回填可行性/实施6阶段/开放决策）。

**第一动作**：阶段0 可行性验——拿 1–2 支股票实测东财/Anspire **能否取历史正文**（决定一期 OOS 是「几天」还是「向前采集数周」）+ `news` 表加 `content`/`provider` 列 + 入库口停止丢 content。

**停止条件**：未过独立预注册 OOS 门即启用 v2 / 接 live test2 / 改情感权重 / 外溢到 official signal·仓位·scheduler；不机械堆源充数（无 dedup/materiality 的多源放大 whipsaw）；把探索性 IC 当统计裁决。

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
