# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M50 Serenity 瓶颈 skill + 强制报告门 | Phase 0-3 complete/released：SKILL/spec/Serenity/ResearchReportGate + `ai_supply_chain` source-tier fields + research-positioning importer/scoreboard source gate 均已落地；non-promoting | 下一步只在明确需要时开下一批质量门或前端 evidence card；否则回到 M29 evidence ops / 用户反馈 | 不接长期标签加权、不改 official signal/仓位/scheduler/test2、blocked 报告不落盘 |
| M29 Forward Evidence | active / blocked for now：2026-06-09 只读 readiness 显示 `ready_to_run_forward_shadow=false`；100 标的完整覆盖只到 2026-06-02，1d/3d/5d 既有 forward artifacts 缺失 | 先只读/preview 诊断覆盖和 baseline artifact 缺口；ready 后才追加 1d/3d/5d shadow + ledger | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| v0.4.2 frontend TypeScript / visibility hardening | complete：前端迁移到 TypeScript/TSX + 真实 ES module imports；CI 覆盖率门、Dependabot 和威胁模型说明已发布；生产信号零漂移 | 推送后只跟进 CI 或前端类型/构建反馈 | 不改 official signal/仓位/scheduler/test2；不启用 quant/Kronos/Atlas |
| v0.4.1 public-surface polish | complete：恢复旧版折线 favicon 语义并匹配新前端配色；GitHub 首页截图刷新；GitHub release notes 统一中英文双版本 | 后续只跟进 CI 或公开页面显示问题 | 不改 official signal/仓位/scheduler/test2 |
| v0.4.0 frontend glass-shell refresh | complete：高保真玻璃拟态前端替换旧 Tailwind 页面，live/demo 数据回落与 ATLAS 账本界面接线已发布；生产信号零漂移 | 推送后只跟进 CI 或用户反馈的 UI/接线小修 | 不改 official signal/仓位/scheduler/test2；ATLAS 后端门控仍默认休眠 |
| v0.3.4 research source-gate hardening | complete：ResearchReportGate / Serenity foundation、`ai_supply_chain` source-tier metadata、research-positioning importer/scoreboard execute guards 已发布；`main == origin/main` | 后续只在明确需要时补下一批质量门或前端 evidence card | 不改 production profile、不把 source-tier metadata 接到真实决策 |
| v0.3.3 / 0.4-1.0 收尾 | complete：首次启动引导、数据健康页、per-signal rule/provenance 展示、离线复现证据、provider 插件示例、API contract、CI/dependency 硬门禁已落地；release tag 为 `v0.3.3` | 后续先做 M29 evidence ops 或用户反馈驱动的文档/界面微调；不要从 0.3.3 产品化收尾推出新信号行为 | 不改 production profile、不复活 quant/Kronos/Atlas、不把 demo/community 入口接到真实决策 |
| M49 工具入口与可观测性 | complete：tools registry、`mingcang tools`、historical tools read/write 边界、correlation id 链路已落地 | 后续只按实际维护需要补 registry 或入口说明 | 不改变 signal、scheduler、production profile、memory promotion 行为 |
| M46-M48 可信/可发现/前端可靠性 | complete：M46 demo/docs_public，M46.5 warning-only/no-blocker 审计与关键数字测试，M47 standing lookahead/data trust visibility，M48 TS/API/status primitive 基线均已收口 | 后续只按用户反馈补截图、说明或小型可靠性测试 | warning 不影响正式信号；blocked 仍不得自动 promotion；不把 README 变成大而全文档 |
| M45 研究定位落地 | 主体完成：source-gated importer、falsification scoreboard、模块分诊、Stage 2b shadow 预注册都已落地；后续只保留守门合同 | 后续导入仍先 dry-run + source fidelity review；Stage 2b 只做 non-promoting shadow | 不复活 quant、不改 production profile、不让未过门 alpha 影响真实决策 |
| M44 Atlas 合并 | complete / dormant：`9820143` 已包含在 `origin/main`；Atlas/test4 Stage 2b signal-overlay shadow starter 已可用；`ATLAS_ENABLED=false` | 只用 `backend.tools.atlas_test4_stage2b_shadow` 做 non-promoting shadow accrual；exit overlay 另走单独任务 | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5 | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M50 Serenity 瓶颈研究 skill + UZI 强制报告门【Phase 0-3 released / next batch optional / non-promoting】

Goal: 补两块研究方法真空 —— Serenity 风格供应链瓶颈拆解 + 证据分层纪律（借鉴 A老师"SKILL.md + 结构化 LLM 输出"的工程模式，但**不接入长期标签聚合**），以及 UZI 风格的**输出侧强制报告门**（检查不过的报告物理上写不出）。两者配套：Serenity 产检查项，Gate 负责强制执行。全程 observe-only / source-gated / non-promoting。来源是两份外部 skill 学习报告（Serenity 系列 S1–S8 + UZI）。

Key design constraints（已对代码核实）:

- **Serenity 不复用 `role="track"`、不返回 `LongTermReport`、不进 `LongTermTeam._aggregate_score`**。`LongTermReport` 强制带 `score`/`label_vote`，且 `team.py` 把 track(A老师)/quality(piotroski)/boom(jingqi)/flow(QFII) 加权合成长期标签——Serenity 一旦走 track 槽就会污染长期标签，违背 non-promoting。改出独立 `SerenityChokepointReport`：`chokepoint_layer` / `chain_layers[]` / `evidence_tier` / `source_refs[]` / `substitute_risk` / `quick_filter_pass` / `falsification_questions[]` / `bear_case` / `research_priority_band`（枚举 `够查`/`暂缓`/`证据不足`，**非数字**）。不出 score/vote。
- **ResearchReportGate** 落 `backend/research/research_report_gate.py`，沿用 M46.5/M47 的 `pass/warning/blocked` 口径。必须在 `deep_research.py` 的 `write_text()` **之前**执行（当前顺序 `_render_report()`→`write_text()`→`_persist_report()`；放 persist 前文件已落盘，达不到"物理上发不出"）。blocked 时不 `write_text` / 不 `record_decision_run` / 不 `remember_deep_research` / 不建 memory candidate。
- **Gate 作用域 = 所有 deep research 报告**：以 `DeepResearchReport` + audits 为基线检查，Serenity 字段有则加严、无则按现有字段判（不假设 Serenity 一定跑过）。
- **共享 module**：`source_tier` 枚举 + forbidden-wording 词表，被 Serenity 与 Gate 同时 import。与输入侧 `FORBIDDEN_TEMPLATE_KEYS` 职责切开——前者查输入字段名，后者查最终文本措辞，同一检查不两处写。
- Serenity 调用方：主入口在 `deep_research.py` 内 `write_text()` 前；旁路入口为独立 CLI/tool 供单主题人工试跑，结果只回显不写 DB。

Phases:

0. ✅ done — 纯文档/prompt，零代码：`serenity-chokepoint/SKILL.md`（瓶颈分层 / quick filter 分层 / source tier / A股 source playbook / 贝叶斯追踪 / 反方先行 QA）+ Gate 检查清单 spec + 共享定义；固态电池主题人工试跑通过（证据/叙事/风险分清、零买卖语气、媒体-only 判 blocked）。
1. ✅ done — 独立 Serenity 结构化器（flag 默认 False，不写 DB，不接 LongTermTeam）+ `research_evidence_defs.py` + `research_report_gate.py` + `deep_research` 写前挂点；50 M50 测试 green（schema 不生成 score/vote、Gate blocked 不落盘、聚合隔离均覆盖）。
   - ✅ Phase 1 收尾 done：① 数据覆盖最终定为 **warning（永不 blocked）**——gate 接真实 prices/financials，纯主题(symbols=[])不罚，理由见 spec §3；② blocked 报告经新增 `DeepResearchReport.gate_status` 字段区分（不靠 path.exists）。70 M50 测试 green、lint/mypy clean。
2. ✅ done — 扩 `ai_supply_chain_template.py`：加 `chain_layers` / `source_tier` / `substitute_risk` / `source_freshness`；新合法字段**不得进** `FORBIDDEN_TEMPLATE_KEYS`；`observe_only/signal_impact/not_a_buy_score` 仍不可覆盖。
3. ✅ done — M45 importer 现有 source gate **增强（非重写）**：加 `source_tier`（execute 不能只有 social）、`evidence_level != needs_check`；`source_kind=derived_summary`/`handoff_context` 仍只能 dry-run。`m45_ateacher_hook_update` 继承 importer gate；`m45_falsification_scoreboard` 同步相同 source-tier / evidence-level guard，避免 M45 旁路漂移。

Not in this batch: research_priority 数字分（用档位防漂移）、TradingAgents 多 agent/checkpoint（重、撞 dormant Atlas、ReviewCase 已覆盖闭环）、QuantDinger action scope 细分（audit 字段加厚/可复现快照留 P2 顺手）、UZI 评委团人格、前端 evidence cards（P2）、Buffett 质量门（P1 下一批，做时须与 piotroski 交叉引用防双重扣分）。

Stop conditions: 不改 official signal / 仓位 / 止盈止损 / scheduler / test2 / production weights；不进长期标签加权；不写 trusted memory（除非 ReviewCase + 人工确认）；blocked 报告不得落盘或 promotion；本地开发不加多余确认门。

> 完整 S1–S7 协同 / C1–C6 冲突矩阵与逐 Phase 验收在工作规划文档维护，本节只保留里程碑级承重点。

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
3. Current 2026-06-09 readiness artifact is not ready:
   `ready_to_run_forward_shadow=false`, full 100-symbol complete coverage only
   through 2026-06-02, missing existing 1d/3d/5d forward artifacts. Diagnose or
   repair those inputs before any shadow bundle.
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
