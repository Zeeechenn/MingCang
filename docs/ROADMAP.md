# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

> 已完成里程碑（v0.3.3–v0.5.1、M44–M50 等）不再列在本活跃表，详见文末 Completed Milestones Index 与 `CHANGELOG.md`。本表只保留进行中 / 未启动 / 触发待命的工作线。

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M51 外部项目借鉴优化 | 已立方案、未启动：研究轨（报告包 v1 / Evidence Card 前端 / MingCang-GAIA）+ 量化轨小 graft（D1-D4）。详案 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md` | 先做研究轨 Phase 1（报告包 schema 封装已有 deep_research/gate/falsification/supply-chain/research_case）；量化轨先做 D1 统计门补强 | non-promoting；不新建平行回测/因子/审计/数据校验系统；不改 official signal/仓位/scheduler/test2/weights |
| M50 Serenity 瓶颈 skill + 强制报告门 | Phase 0-3 complete/released；non-promoting | 下一步只在明确需要时开下一批质量门或前端 evidence card（已并入 M51 Phase 2）；否则回到 M29 evidence ops / 用户反馈 | 不接长期标签加权、不改 official signal/仓位/scheduler/test2、blocked 报告不落盘 |
| M29 Forward Evidence | 2026-06-12：价格回填完成（100支×7天，700行），baseline 1d/3d/5d artifacts 已建；positive delta 9/11+8/10+8/10 windows，non-promoting。可延伸 forward window | 重跑 readiness 确认 ready，再追加下一窗口的 1d/3d/5d shadow；可在此续作内插入 M51 D1（DSR/PBO/trial-count 补强 m29_hypothesis_registry） | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
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

## M51 外部金融开源项目借鉴优化【方案已立 / 未启动 / non-promoting】

Goal: 把外部金融开源项目（FinGenius/FinRobot/FinGPT/FinGAIA 研究系 + QuantDinger/alpha101 量化系）的长处**嫁接进明仓既有模块**，**不新建平行轨**。完整详案 + 逐项目重复判定 + 四域归口表见 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md`，本节只保留承重点。

核心判断（已对代码核实）：

- **QuantDinger / alpha101 对明仓净增量≈0**：回测引擎（`backend/backtest/`）、统计门+预注册（`backend/tools/m29_hypothesis_registry.py`）、append-only 审计（`backend/memory/audit_log.py`）、Qlib 因子+Alphalens IC（`backend/data/qlib_data.py` / `backend/backtest/alphalens_qlib.py`）均已自建。最大风险是"照抄造出平行轨"。
- **指导原则**：所有借鉴一律 graft 到现有模块；任何 PR 新建 `backtest_v2/`、`factors_v2/`、第二个 audit/数据校验层，直接拒。
- 曾提议的"M29.6 Historical Backtest Lab"**取消**（80% 已存在），拆成下列小 graft。

承重交付：

- **研究轨（本里程碑主体）**：① Phase 1（P0）单股研究报告包 v1——把 `deep_research`/`ResearchReportGate`/`falsification_scoreboard`/`ai_supply_chain`/`research_case` 封装成稳定 schema（封装与契约，不重写分析器）；② Phase 2（P1）前端 Evidence Card / Report Viewer（M50 后端纪律前台化，本里程碑最实打实的缺口）；③ Phase 3（P1）MingCang-GAIA 本地金融 agent 评测集（净新，首批 20–30 任务，只作研发指标、不回流信号）。
- **量化轨（小 graft，归口现有 owner，不新建里程碑）**：D1（P1）在 `m29_hypothesis_registry` + `backend/backtest/statistics/` 加 Deflated Sharpe / PBO / trial-count（随 M29 续作插入）；D2/D4（P2）真实披露日 PIT + 100–300×3–5y 规模化验证，**本质是数据覆盖里程碑**（瓶颈是 financial 10/70、news 0/70，非引擎），归口 M12，数据补全前禁止规模化回测；D3（P2）paper-only 双解锁 token + 审计审查，归口 ATLAS。
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
4. If not ready, stop and wait. Do not treat partial local data as fresh evidence.
5. If ready, run 1d/3d/5d forward shadow bundle and add artifacts to `m29_evidence_ledger`.
6. Update M29.5 residual attribution in the same forward window. If still non-promoting, keep quant off.

Stop before any production change, checkpoint wiring, Kronos long training, true `sentiment_cache` writes, new dependency download, or extra paid external service.

---

## Other Open Items

| Item | Trigger | Action |
|---|---|---|
| M32 Forward Hypothesis Bridge | Review data becomes thick enough | Register sector / supply-chain theses as forward hypotheses; output falsifiable thesis, not Strong Buy labels |
| M24.3 Long-term constraint reconnect | Suggested checkpoint 2026-06-10 and later test2 freeze end >= 2026-07-18 | Shadow-only outcome analysis; enable constraints only if false positives fall without meaningful missed entries |
| M25 product/community leftovers | Low priority / actual need | README demo, verified quickstart, mobile core paths, virtual list only after watchlist >200 causes lag |
| M21.4 ATR narrow-stop analysis | After 2026-07-18 | Analyze closed test1/test2 positions before changing stop rules |
| M12 external data governance | Any new endpoint | Add provider health, PIT timestamp, field normalization, and tests before DB writes |
| M10.5 migrations | SQLite runtime patch becomes bottleneck | Consider Alembic baseline |
| M4 / M5 automation | Strong validated evidence and explicit user intent | LangGraph / FinMem / broker automation stay deferred; no real trades |

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
