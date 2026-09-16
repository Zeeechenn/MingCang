# Serenity convergence — retained research contract (legacy M55 path)

Updated 2026-09-17. The old planned/Phase 1–3 queue is archived, not an active M
milestone. This path remains because review_loop and the retired analyzer reference
mapping #1/#8 and sections ③/④. Current work is only ROADMAP.

`backend/research/serenity_chokepoint.py::analyze()` is already retired: returns None,
warns, and never calls LLM/DB. The file/type/methodology loader remain for compatibility;
physical deletion is not a pending task inferred from the old plan. The report gate
retains its optional type-based layer; general research structures remain the reuse target.
Historical design choices below describe boundaries and mapping, not proof all proposed
extensions are implemented or permission to add new production dependencies.

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

已退役独立 LLM 结构化执行；保留兼容函数（只返回 None）、无 score/vote 的报告类型和方法论
加载入口。不得把文件存在描述成仍在运行，也不为“完成旧清单”直接删类型/兼容引用。
新研究复用 theme_hypothesis_engine、forward_thesis、thesis_ledger、review_loop；
方法论 source playbook 仍留 `.pi/skills/serenity-chokepoint/SKILL.md`。

## ⑤ 持续有效边界

observe-only / non-promoting：不改官方信号、仓位、止盈止损、scheduler、test2 或生产权重，
不接 LongTermTeam / 长期标签聚合；只给定性研究判定，不产出可聚合分数、价格目标或买卖档。
资金流/筹码/机构评级/估值分位不得被这套方法引入研究评分/候选准入；未来事件线索也须
source-gating，只作文字、不计分。复用既有 evidence defs/report gate，不新建 analyzer 或平行账本。
blocked 报告不落盘，研究层不反向 import decision；共享代码改动需生产输出对照。
代码、测试和实时消费证据优先，旧材料不授予改动其他未提交 Skill/prompt 的权限。

## ⑥ 历史清单与接手

原 Phase 1–3 未勾选列表已外部归档，其中包含后来已交付或改变为兼容保留的事项。
不逐项重新执行，也不把未逐项复核者批量标成完成。维护本契约时读现有代码/测试，
新增或退役能力依 ROADMAP 重新明确范围；档案索引见 `docs/evidence/document_archive_digest.md`。
