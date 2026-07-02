# M55 Serenity 收敛进 ATLAS 研究脊柱 + s-skill 优点归口

状态：planned 2026-07-02 / observe-only / non-promoting
关联：`docs/ROADMAP.md` M55 段、M50（`docs/dev/m50_research_report_gate_spec.md`）、M51（`docs/dev/M51_EXTERNAL_BORROWING_PLAN.md`）

本文档是 M55 Phase 0 spec 交付物：给出 serenity 收敛与三份外部 skill（ZadAnthony / muxuuu / fadewalk）优点归口的完整判断依据，供 Phase 1-3 落地时直接执行。本文档本身不改动代码。

---

## ① 背景

- **serenity 事实休眠**：`backend/research/serenity_chokepoint.py` 的 `analyze()` 满足"default-off + 零生产入口"的休眠条件——`long_term_serenity_enabled` 默认 `False`，全仓 grep 只命中它自身与 `research_report_gate.py` 里一个可选、从未被任何 CLI/web/pipeline 传入非 `None` 值的 `serenity` 参数（`_check_serenity_layer`）。它是纯 tests + 类型注解引用，生产影响 ≈ 0。
- **ATLAS 脊柱重叠**：`backend/research/` 已有成熟脊柱——`theme_hypothesis_engine.py`（假设落库）、`ai_supply_chain_template.py`（供应链分层字段）、`forward_thesis.py`（可证伪假设 + 置信区间 + 复核节奏）、`thesis_ledger.py`（append-only 置信度序列 + kill_conditions）、`review_loop.py`（独立复核）、`dossier.py`（输出规范）、`research_evidence_defs.py` / `research_report_gate.py`（证据分层 + 门检查，M50 共享地基）。serenity 六步方法论与这套脊柱在字段级高度同构，但 `analyze()` 自己维护一套平行、更弱（无 DB、无 idempotent create、无 kill_conditions 状态机）的 dataclass，正踩 M51「graft-not-parallel」红线。
- **三份外部 s-skill**（ZadAnthony `zad`、`muxuuu`、`fadewalk`）各自沉淀了一些方法论优点，需要逐条判定：合并进 ATLAS 现有模块（strengthen-existing / graft）、保留独立方法论文档（keep-standalone）、隔离（isolate）、还是整体丢弃（drop，通常因为触碰 observe-only 或层纯度红线）。

---

## ② s-skill 优点 → ATLAS 归口映射表

| # | 来源 | 强度 | ATLAS 归口 | 决策 | observe-only / 层纯度要点 |
|---|---|---|---|---|---|
| 1 | zad — 独立 reviewer sub-agent（opus，五类高发坑+复核清单+revise 循环） | 强 | `review_loop.py` | strengthen-existing | 合并五类检查项，不新增分数/vote 字段；复核结论仍是 pass/revise 定性判定，不 import `backend.decision`。 |
| 2 | zad — 中文表达规范（术语三分/禁英式句法/禁生造词/加粗上限） | 强 | `dossier.py` | graft | 纯措辞/可读性规范，与 `research_report_gate` 禁词表共用同一词表模块，避免同一检查两处写。 |
| 3 | zad — 逆向链发现硬门（≥1 跳非共识关系才算"有发现"，否则信念档降一档） | 强 | `research_report_gate.py` | graft | 与 serenity 第一步"发现硬门"高度重叠；从 SKILL.md 文字劝导升级为 Gate 检查项（additive，default-safe），只产出档位不产出分数。 |
| 4 | zad — 定性/数字分轨（OSINT 推断只能进定性判断，量化结论必须一手源支撑） | 强 | `research_evidence_defs.py` + `research_report_gate.py` | strengthen-existing | 与 serenity 第三步同构，不重造；只补充 `quant_claim_requires_primary_source` 式校验枚举，不产出份额/TAM 数字结论本身。 |
| 5 | zad — 14 判据 / 10 红旗颗粒度分类清单 | 中 | `theme_hypothesis_engine.py` / `forward_thesis.py` | strengthen-existing | 只吸收供应链结构性判据（垄断/单点失效/认证周期/替代难度），剔除带估值阈值（市值门槛、机构持股分档触发买卖）的判据；吸收后不得输出买卖档位。 |
| 6 | zad — 估值引擎（相对估值/份额跨层法 + bear/base/bull PT + 预期空间 + 买卖五档） | N/A | —— | **drop** | 违反 observe-only 红线，整体丢弃；即使"仅供参考"式改造也不引入，分档逻辑本身即隐含信号语义。 |
| 7 | zad — 精度降级规则（含[推断]/[推测]假设的结论强制降级为数量级/方向） | 强 | `research_evidence_defs.py` | strengthen-existing | 与 serenity 现有规则一致，合并成同一份共享定义，不新增第二套精度分级标准。 |
| 8 | zad — 反确认偏误内置（bear 先写、强制证伪门、用户暗示方向时反向加压） | 强 | `review_loop.py` | strengthen-existing | "用户暗示方向时反向加压"作为复核触发条件之一；不改变输出的 observe-only 属性，不产出立场倾向分数。 |
| 9 | muxuuu — 分层证据标准（strong/medium/weak/unverified 四档） | 中 | `research_evidence_defs.py`（`SourceTier` 已覆盖） | **drop** | 现有 `SourceTier` 颗粒度更细（primary/official/filing/ir/industry/social_lead），muxuuu 四档是子集，不引入第二套证据分级。 |
| 10 | muxuuu — 工程打包纪律（trigger/behavior evals → 可复现测试） | 强（打分脚本本体风险高） | ATLAS 自有测试套件（`backend/tests/research/` 等价目录） | strengthen-existing | 只吸收可测试性模式，转化为 pytest 用例；不落地独立 `scorecard` 打分脚本，不做独立 skill 包。 |
| 11 | muxuuu — 候选池纪律（先排产业链层级再筛标的） | 中 | `theme_hypothesis_engine.py` | strengthen-existing | 只吸收"先层级后标的"排序纪律，不引入固定数量阈值（20 家/25 源）作为硬门，避免形式主义检查；不产出公司排序分数。 |
| 12 | muxuuu — What-could-go-wrong 八分类清单 | 中 | `thesis_ledger.py`（falsification 字段） | strengthen-existing | 作为 `falsification_questions` 分类提示词表，不新增字段；仍是定性问题清单，不产出风险分。 |
| 13 | fadewalk — 卡脖子六步法主体 | 中（与 serenity 高度重叠） | `theme_hypothesis_engine.py`（仅"真伪瓶颈排除规则"中不涉及资金面的 4 条） | strengthen-existing | 只吸收产业逻辑类排除项（蹭热点/格局分散/扩产易/替代逻辑不成立），剔除"估值已 price-in"与"流动性陷阱"两条。 |
| 14 | fadewalk — 资金流维度（龙虎榜/主力净流入/北向/融资融券/筹码/机构评级） | N/A | ——（研究层禁入；归口 `qfii_flow_analyst` 信号/择时层，非本次范围） | **isolate** | 层纯度红线：整体隔离出研究层。若未来要用，只能作 observe-only 纯文字线索备注且强制 source-gating，绝不给分、不进档、不作为候选纳入/排除的判定依据本身。 |
| 15 | fadewalk — 标的四维信号卡"估值水位"（P/E、P/B、板块内分位） | N/A | —— | **drop** | 估值分位是可聚合排序信号，与 zad 估值引擎同一红线处理。 |
| 16 | fadewalk — 结构化报告"操作建议"章节（短/中/长线一句话+风险提示） | N/A | —— | **drop** | 直接产出操作建议，明确违反 observe-only；ATLAS 输出模板以 `research_priority_band` 收尾，不设该章节。 |
| 17 | fadewalk — A 股 source playbook 细项（互动易/CNINFO/官方产业指引） | 中 | `research_evidence_defs.py`（source playbook 扩展） | strengthen-existing | 只补充"官方产业指引类文件"作为 official 级来源子类型，不改变现有 tier 排序，不涉及资金面来源。 |

---

## ③ serenity 六步 vs ATLAS 逐条边界比对表

| 步骤 | 重叠的 ATLAS 结构 | 决策 | 理由摘要 |
|---|---|---|---|
| 1. 瓶颈分层拆解（chain_layers/scarce_layer + 发现硬门） | `ai_supply_chain_template.py` 的 chain_layers 结构（M50 Phase 2 已合法化进模板，未在 `FORBIDDEN_TEMPLATE_KEYS`） + `theme_hypothesis_engine.create_hypothesis(ai_supply_chain=...)` | merge-into-atlas | 字段级已落地在存储层；唯一未归口的"发现硬门"纪律作为 `research_report_gate` additive 检查项落地（见映射表 #3），不需要独立 analyzer。 |
| 2. 快速预筛（forced_demand/size_mismatch/no_substitute/outside_voice） | 同上 `ai_supply_chain_template.py` 逐层字段（已落地）；`research_report_gate._check_serenity_layer` 现有门逻辑 | merge-into-atlas | 数据结构已同构，缺口是 gate 只在 `serenity` 参数非 None 时触发；应改为直接读 `hypothesis.ai_supply_chain` 字段做门检查，让所有 theme hypothesis 受益（additive）。 |
| 3. 证据分层（source tier + 定性数字分轨） | `research_evidence_defs.py` 的 `SourceTier` + `scan_forbidden_wording`（已是共享地基，被 gate/template/M45 importer 共用） | merge-into-atlas | 代码层面已"merge 完成"；serenity 六步文档只是复述已存在的分层规则；只需 SKILL.md 措辞明确"消费 ATLAS 既有 SourceTier，不重新定义"。 |
| 4. A 股 source playbook（渠道优先级清单 + 降级触发器） | 无直接结构化对应；最近邻居只是 SourceTier 等级语义 | **keep-standalone** | 纯提示词/方法论清单，不是数据结构；ATLAS 六个存储模块没有"信息渠道类型清单"字段可归口；按 M55 Phase 2 规划原样保留在 SKILL.md 作为研究员/LLM 提示词参考。 |
| 5. 贝叶斯论题追踪（prior/new_evidence/posterior/confidence_delta/stale_after） | `forward_thesis.py`（confidence 波段 + evidence_manifest_json + invalidation_conditions + review_cadence）+ `thesis_ledger.py`（`append_confidence` append-only 序列 + `kill_conditions`） | merge-into-atlas | 六步里重叠度最高的一步；serenity 的 bayesian dict 本质是两张表字段的重新包装；应直接调用 `forward_thesis.update_confidence_band` / `attach_evidence_manifest` + `thesis_ledger.append_confidence`，不维护第二套 in-memory 字典。 |
| 6. 反方先行 QA（bear_case + falsification_questions≥3 + 独立复核） | `thesis_ledger.py` 的 `kill_conditions`（创建时必填证伪条件）；`review_loop.py` 的 `create_review_case`；`research_report_gate._check_serenity_layer` 已有的空值检查 | merge-into-atlas | 与 M55 归口一致（zad reviewer → review_loop）；把 bear_case/falsification_questions 映射进 `thesis_ledger.create_thesis(kill_conditions=...)` 获得同等强制性；门检查只需通用化到读 `kill_conditions` 而非只读 serenity dataclass。 |

结论：六步中 5 步（1/2/3/5/6）判 **merge-into-atlas**，1 步（4）判 **keep-standalone**（纯文档，非代码归口）。

---

## ④ analyze() 归宿决定

**决定：退役（retire）**，仅限 `serenity_chokepoint.py` 这个 322 行的 LLM 结构化器文件本身。

判定依据：
1. **事实休眠**：`long_term_serenity_enabled` 默认 `False`，全仓无 CLI/web/pipeline 入口调用 `analyze()`（仅 tests + gate 类型注解引用）。
2. **全面重复**：其 `SerenityChokepointReport` 冻结 dataclass 的字段（chain_layers/scarce_layer/quick_filter_by_layer/evidence_tier/source_refs/bayesian/bear_case/falsification_questions/research_priority_band）逐字段对照，六步中五步已在 `theme_hypothesis_engine` + `ai_supply_chain_template` + `forward_thesis` + `thesis_ledger` + `review_loop` 中有对应的、真正接了 DB/audit/idempotency 的存储原语；只有第 4 步（source playbook）无代码对应，但那本来就该是纯文档。
3. `analyze()` 现在做的事——调 LLM、按自定义 tool schema 结构化、装进一个从不落盘的 dataclass——是给已存在的 ATLAS 模块做了一份平行、更弱的重复实现，正踩 M51「graft-not-parallel」红线。
4. "thin-wrapper 复用 ATLAS plumbing"技术上可行，但零调用方情况下，包一层 wrapper 除保留接口名外无增量收益；任何未来想用 serenity 六步的调用方，直接调 ATLAS 五个模块的公开函数即可，不需要再翻译一层 serenity 专属 schema。

**真正保留的资产**：
- `.pi/skills/serenity-chokepoint/SKILL.md`（六步方法论 + A 股 source playbook 文档，Phase 2 转为方法论透镜文档）
- `research_evidence_defs.py` / `research_report_gate.py`（M50 共享地基，继续做，不动对外契约）

**退役范围仅限**：`backend/research/serenity_chokepoint.py`。退役时必须保持 `test_serenity_chokepoint` 的隔离不变量（no score/vote 字段、不 import `backend.decision`/`LongTermTeam`、非 `LongTermReport` 子类）在新落地位置同等成立；`research_report_gate.py` 里的 `serenity` 可选参数与 `_check_serenity_layer` 应整体移除或改为直接读 `ai_supply_chain`/`kill_conditions` 字段——这是 Phase 2/3 的具体实现工作。

---

## ⑤ observe-only / 层纯度 / 生产 diff=0 边界

- **observe-only / non-promoting**：本里程碑不改 official signal / 仓位 / 止盈止损 / scheduler / test2 / production weights；不进 `LongTermTeam` / `_aggregate_score` 长期标签聚合；serenity 及归口后的检查项一律不产出可聚合分数或价格目标，只产出定性判定（pass/revise、够查/暂缓/证据不足档位）。
- **层纯度红线**：龙虎榜/主力净流入/北向/融资融券/筹码/机构评级/估值分位（fadewalk 全部资金流相关项 + zad 估值引擎）**整体不进入研究层**，判 `isolate` 或 `drop`；唯一记录的例外路径是未来可能的 observe-only 纯文字事件线索（本次不落地），且强制 source-gating，不给分、不进档、不作为候选纳入/排除判定依据。
- **不新增平行轨**：所有归口目标（`atlas_home`）均落在 `backend/research/` 现有模块内，不新建平行文件；`analyze()` 退役后不建替代 analyzer。
- **blocked 报告不落盘**：沿用 M50 既有约束，不因本里程碑改变。
- **生产 signal diff=0**：本里程碑全部改动为 additive（新增检查项/字段/枚举值）或代码删除（退役 `serenity_chokepoint.py`），不修改任何已生产路径的入参默认值或输出 schema 语义；Phase 3 验收须跑现有生产信号回归确认 diff=0。
- **不碰 `.pi/skills/track-analyst/`**（他人未提交改动），不 import `backend.decision`。

---

## ⑥ Phase 1-3 落地清单

### Phase 1（additive 检查项落地，unblock 前先做）
- [ ] `research_report_gate.py`：新增"发现硬门"检查（≥1 跳非共识关系，否则信念档降一档）——映射表 #3
- [ ] `research_report_gate.py` / `research_evidence_defs.py`：补充 `quant_claim_requires_primary_source` 校验枚举——映射表 #4
- [ ] `research_evidence_defs.py`：合并精度降级规则（[推断]/[推测] → 数量级/方向）为唯一共享定义——映射表 #7
- [ ] `research_evidence_defs.py`：补充"官方产业指引类文件"作为 official 级来源子类型——映射表 #17
- [ ] `research_report_gate._check_serenity_layer`：改为直接读 `hypothesis.ai_supply_chain` 字段，脱离对 `serenity` 参数非 None 的依赖——比对表步骤 2
- [ ] `dossier.py`：吸收中文表达规范（术语三分/禁英式句法/加粗上限），与禁词表共用词表模块——映射表 #2

### Phase 2（模块级合并 + review/thesis 强化）
- [ ] `review_loop.py`：合并 zad 五类复核检查项 + "用户暗示方向时反向加压"触发条件——映射表 #1、#8
- [ ] `theme_hypothesis_engine.py` / `forward_thesis.py`：吸收非估值类判据/红旗清单（剔除市值门槛、机构持股分档）——映射表 #5
- [ ] `theme_hypothesis_engine.py`：吸收"先层级后标的"排序纪律（不设固定数量硬门）——映射表 #11
- [ ] `theme_hypothesis_engine.py`：吸收 fadewalk 真伪瓶颈排除规则中非资金面的 4 条——映射表 #13
- [ ] `thesis_ledger.py`：`kill_conditions` 吸收 muxuuu what-could-go-wrong 八分类作为提示词表——映射表 #12
- [ ] `forward_thesis.py` + `thesis_ledger.py`：serenity 贝叶斯字段迁移为 `update_confidence_band` / `attach_evidence_manifest` / `append_confidence` 调用路径——比对表步骤 5
- [ ] `thesis_ledger.create_thesis(kill_conditions=...)`：接入 bear_case/falsification_questions 前置校验，门检查通用化读 `kill_conditions`——比对表步骤 6
- [ ] `.pi/skills/serenity-chokepoint/SKILL.md`：转为方法论透镜文档（六步方法论 + A 股 source playbook 保留原样），移除对 `analyze()` 独立入口的引用——比对表步骤 4
- [ ] ATLAS 测试套件：吸收 muxuuu trigger/behavior evals 转化为 pytest 用例（不落地独立 scorecard 打分脚本）——映射表 #10

### Phase 3（退役 + 回归验收）
- [ ] 移除 `backend/research/serenity_chokepoint.py`；迁移/保留 `test_serenity_chokepoint` 隔离不变量断言到新落地位置（不含 score/vote 字段、不 import `backend.decision`/`LongTermTeam`、非 `LongTermReport` 子类）
- [ ] `research_report_gate.py`：移除或改造 `serenity` 可选参数与 `_check_serenity_layer` 对 `SerenityChokepointReport` 类型的依赖
- [ ] 全量跑 ATLAS 相关测试（`backend/tests/research/` 等）+ M50/M51 既有测试，确认 green
- [ ] 生产信号回归：对比改动前后 official signal 输出，确认 diff=0
- [ ] README / STATUS.md 诚实口径检查：确保不暗示 serenity 独立分析器仍在驱动生产信号
- [ ] `docs/ROADMAP.md` M55 行更新为 complete，归档判定依据链接回本文档
