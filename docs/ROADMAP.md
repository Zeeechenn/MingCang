# MingCang One Loop — 当前执行计划

> 更新：2026-09-17。唯一项目级计划；原 20 日连续运行门已完成并封存。
> 新窗口产出、数据可信度及经济验收仍开放。当前证据只见 `STATUS.md`。

## 1. 计划权威与历史边界

本文件只留目标、有效约束、下一步、验收和阻塞项。`AGENTS.md` 管规则，`PROJECT.md`
管结构，`STATUS.md` 管当前运行，`CHANGELOG.md` 管历史，`docs_public/DEVELOPER_GUIDE.md`
管实现合同。2026-09-17 已将重复实施过程、旧计数和已完成清单外部归档压缩；原文/hash
索引见 `docs/evidence/document_archive_digest.md`，归档不是第二份活跃计划。
旧 M 编号只保留作历史/兼容标签，不新增同名开发线。仓内不记录本机归档绝对路径。

## 2. 北极星

用户掌控的投资决策台：每个完整交易日，以唯一运行批次和有来源/时点的证据，把
数据、候选、持仓、事件、观察哨、人工判断、复盘和结果反馈连成一份盘后操作面板。
确定性规则守数据与风险边界；LLM 整理证据、反证和条件化判断。模型原建议、风险处理、
用户选择及真实成交分别留痕。不连接券商、不自动下单。
工程可靠、产出实用、研究省时、收益/风险和明仓自身增益分别验收。

## 3. 当前治理结论

基线封存、文档单源、RunEnvelope 合同、领域/编排收口、单一八卡入口和 20 日 v1
运行证明已交付，停止重复立项。产品内容质量与人工完成不随代码或 committed 状态自动完成。
保留归属、统一入口和新鲜运行证据要求；未过门不得靠新增框架或切换标签绕过。

## 4. 目标结构

Domain core → stable workflows / RunEnvelope → one daily panel / operator surface。
Research Lab 通过单独晋升门进入正式路径；Archive 只供历史查询，不进默认上下文或运行依赖。
正式逻辑归 data/analysis/backtest/evidence/research/memory/decision/portfolio/ops/jobs/workflows；
`backend.tools` 是 CLI/维护/兼容层，API/scheduler/agent/frontend 消费稳定门面。
canonical 与 compatibility 路径、保留周期和退役条件由 PROJECT/AGENTS 维护。

## 5. 生命周期与批次合同

| 状态 | 边界 |
|---|---|
| proposed | 方案未获开工合同，不进运行时 |
| experimental | 隔离输入、临时数据、明确样本/指标/到期 |
| shadow | 真实形状验证，只读或独立落账，不改官方结果 |
| stable | owner/消费者/入口/job-run/新鲜产物/验收/回滚齐备 |
| dormant / rejected / archived | 分别为保留关闭、证据否定、只作历史；不默认消费 |

每批记录 owner_domain、单一 consumer、canonical entrypoint、输入/输出/失败/降级、
safety_level、evidence_status、metric/sample、expires_at、rollback 和 replacement。
同一时间最多两个实现批次；结构迁移与 provider/交易/调度/DB/API/记忆/风控行为分批。
先核基准 commit 和依赖事实，保留脏工作区；反例测试、聚焦/架构检查、完整门与真实证据
均应匹配变更范围。模型/Skill/prompt 改动同样可能改变行为，不能因是 Markdown 而绕门。

## 6. 旧工作线结算与承接

旧编号在 One Loop 中不再是活跃里程碑。未完成的价值按能力归属承接：

| 历史标签 | 当前裁决 | One Loop 承接 |
|---|---|---|
| M54 新闻层 v2 | 方向预测未过门；采集、预算和金字塔机制有价值 | 与新闻镜像合并为“新闻与事件风险”能力；方向继续 shadow |
| M58 出场影子 | 选股用途已证伪；出场实验尚待预注册窗口裁决 | 归入“风险验证实验”，冻结新增变体 |
| M59 操作面板 | v1 连续产卡已证明；新日期内容质量与人工完成仍待验收 | 归入统一 One Loop 面板，不再独立发展 |
| M60 观察哨 | 触发器有价值 | 作为 Daily Loop 事件输入 |
| M63 日常编排 | 入口价值成立，内部职责过重 | 归入“编排收口”，兼容命令保留一个发布周期 |
| M64 Live Track | 代码完成、默认未启用 | 保持 dormant；只有独立启用门满足才重新提案 |
| M66 结构治理 | 首批领域/编排与文档收口已完成，兼容维护仍受退役门约束 | 后续随所属能力增量维护，不重复立项 |
| M67 多市场 | 小池灰度完成、全量晋升 HOLD | 保持 shadow/dormant；公告源、双源、日历和前向证据满足后再提案 |
| M68 新闻金字塔 | 事件风险价值大于方向价值 | 与 M54 合并，不建立平行新闻系统 |
| M69 复权漂移 | 已落地 | 变成周期性数据质量守卫 |
| M57 记忆演化 | 记录和审计有效，决策增益未证明 | `MEMORY_DECISION_CONTEXT_ENABLED=false`；继续显式查询、维护和影子回放 |
| M65 研究可信度 | 通用 Evidence Gate 有效，Serenity 主效应不成立 | 保留通用门；方法实验归档 |
| 量化 v2 | 未过 IC/ICIR 门 | 归档候选；新证据达到重新提案门后再评估 |
| M0–M55 及其他历史线 | 已完成、合并、撤销或证伪 | 只在 CHANGELOG、Git 和外部档案中查询 |

## 7. 六个外部项目的处理决定

原则：借设计，不整套搬框架；合并进现有领域，不建立平行系统。

| 来源 | 仅吸收 | 归属 | 明确不做 |
|---|---|---|---|
| FriesTrader | 盘后方案、下一时点重验、机械风险门、dry-run、追加审计 | RunEnvelope / ops / review | 不接 Robinhood，不实现真实订单和美国税务规则 |
| Vibe-Trading | Run Card、PIT、provenance、Shadow Account 行为复盘 | evidence / trade journal / ReviewCase | 不引入其庞大多智能体和跨市场框架 |
| stock_monitor | 信号去重、被压制事件留痕、推送频控、受限插件合同 | watchtower / notification / experimental registry | 不把单源行情和简化策略作为正式决策依据 |
| stock-analyzer | thesis/anti-thesis、管理层/护城河清单、三情景、证伪条件 | ResearchCase / report gate | 不新建第二套 Skill/Agent 研究系统，不把主观清单直接计分 |
| InStock | “筛选→解释→回测证据”的连贯交互 | daily panel / stock page | 不复制大而全功能和自动交易架构 |
| EliteQuant | 外部资源索引 | 仓库外技术雷达 | 不形成运行依赖或产品能力 |

## 8. 外部能力准入门

开工前冻结：既有问题与基线、重叠能力及为何不足、借思想/接口/算法/代码的范围、owner/
确切入口/唯一消费者、输入输出和失败降级合同、安全影响、隔离方式、最小样本/指标/预算/
绝对到期日、停止/回滚/删除/替代关系、测试/来源/运行证据及用户决策门。
缺 owner、consumer、metric、expiry、rollback 或 replacement 则不进生产；优先吸收进现有领域。

## 9. 执行顺序与剩余门

### 已完成登记

| 已交付 | 保留边界 |
|---|---|
| One Loop v1 20/20 封存；P0-G 唯一起算日 | 继续日常健康；旧 20 日不用于新质量或收益认证 |
| P0-A producer/同日耐久证据/delta/空态/人工意见记录 | 自 09-16 起验新日期；意见≠任务完成≠成交 |
| P0-B1 dry-run/strict/warmup 与 ATR 原因复现 | 默认 caller 不启用；25 官方池候选不是修库批准 |
| P0-R manual_only NAV；P0-C 严格候选读取/草稿 | 价格/公司行动/资料时点不齐仍 diagnostic；默认 copilot 未整体替换 |
| P1 四门+固定窗口读取；P2 记录器/session/manifest v2/进程保护 | 不证明实际 provider 身份、费用、跨账户权限、源事实或经济试验启动 |

下面的剩余工作是唯一队列，不再执行已归档的阶段 0–6 或旧 M 清单。

### 第一优先：新日期产出与真实用户完成（P0-A/P1）

先验证“看变化 → 查证据 → 接受/修改/拒绝 → 查结果”，再考虑页面增量。
八卡身份/顺序不变：运行控制 batch_integrity；五张决策证据 candidate、position_health、
event_risk、watchtower、daily_delta；治理 human_confirmation、review_attribution。

- 同日 watchtower 绑定 as_of/run_id 并存现有 JobRun/committed artifact；不拿临时旧文件顶替。
  ready_zero 必须有完整扫描覆盖和原因；扫描完成不认证通知送达/被抑制事件。
- 零 LLM 的 event_risk 为 shadow/not_applicable 并说明原因，不能解释成“没有风险”。
- daily_delta 对比上一价格日唯一已提交面板，绑定 current/previous as_of、previous run、
  结构化名单变化或 no_previous_reason；不推断实际成交/NAV。
- 人工意见保留原面板日期/run/hash、理由和改后判断；重复幂等、过期仅拒绝、观察只追加并校验版本。
  用户禁买只在明确标的/范围/时间生效，不自动清仓或扩大行业。无回复保持 pending。
  保存意见不更新原研究任务、仓位、ResearchState、验证后记忆或旧完成指标。
- 不强制每天新交易或长报告。新日期输出、真实完成与独立结果归因分别交证据。
  回滚为停用新入口，保留记录及原面板；不重写已封存日期。

显式质量窗口由 evidence 负责，唯一消费者为
`backend.evidence.decision_desk_readiness` 的离线 CLI，替代手工仅统计成功日。
日清单保留 passed/blocked/failed/missing/not_due，全部到期日为分母，核五份源文件/hash并重算四门。
不访问生产 DB、不补跑、不修改协议/预约；不认证人工完成、模型质量或交易日历/事前冻结。
沿用 09-16、17、18、21、22 五次安排，`expires_at=2026-09-22T23:59:59+08:00`；
到期复审，未减少漏记失败/缺失则停用增量，保留原单日工具和失败证据。

### 第二优先：数据地基与独立维护（P0-C、P0-B1/B2 → P0-R）

先补官方池与**当前实际持仓**并集的覆盖，不沿用旧日期固定持仓数。

1. 财报原值和因子共用 as_of；报告期、披露、抓取、修订时点分开，披露未知不放行。
   标签同时检查生成/有效期/质量；未知/不适用/负面分开，分母和缺口可解释。
2. 文本预算先保留时点/风险/缺口；必需内容装不下则不可判断。账户未知不给增加风险的数值目标，
   历史 DecisionRun 目标不当现仓；草稿仍 pending，严格候选不能冒充默认路径已修复。
3. 来源与复权按一致多源/冲突/真实重基/unknown 分类。25 官方池全历史候选已备，仍需当前持仓
   外部覆盖、权威公司行动、逐行/ATR/NAV 影响；来源成功率不等于数据可信。
4. P0-B2 **单独批准**备份、维护窗口、回滚和必要账本重述后才能写；strict/warmup 激活也需此门。
   既有 warmup 必须严格同源、固定 end、有效 OHLC 和充分前置行；不自动改 routine caller。
5. 价格问题清零、权威公司行动完整后，用既有现金 NAV 验现金/持仓/成本/成交守恒，覆盖下一开盘、
   T+1、跳空、停牌、量能限价/部分成交、现金不足、分红拆股。不得另建收益引擎或用 qfq 代理数冒充真实股数。

P0-C 后续接线仍需默认旧输出对照和当前窗口保护；未来财报/标签、修订、极小文本预算、
未知持仓、负面/空资料等反例不能省。候选覆盖/ATR/NAV 敏感性不是写库许可或策略改进证据。

### 第三优先：真实回执、隔离与经济前向准备（P2）

三个问题串行：同 GPT-6 raw/desk 测明仓增益；同 desk 的 Claude/GPT-6 测模型路径；
同模型/同数据、只改一个流程测开发效果。默认两臂，不叠成四臂混合实验。

- 首次决定前冻结 problem、模型/prompt/工具/数据/基准版本与 hash、执行/风险、窗口、预算、
  失败/重试政策、逐臂账户/现金/持仓/决定/记忆/恢复目录；原生 Claude 历史轨迹保持独立。
- 保存实际可见输入和每次请求/返回原字节、hash、cutoff、失败和用量；允许包不等于实际看到。
  requested/resolved 以 provider 回执为准，模型自述与开发宿主不算，禁止静默 fallback。
- 记忆按每次 cutoff 和臂过滤，未来 outcome 不可见。首期五日 raw/desk 初始记忆为空且无工具；
  09-16 失败日保留不重跑，不以早期预演或后来答案替代。5 日只验记录/对账。
- session 独占冻结、先锁定预留再调用；失败/中断不退款、不覆盖 attempt。任一臂已知超限或损坏阻止新调用。
  manifest v2 绑定候选族/参数/次数、嵌套前向 folds、标签跨度 purge/embargo、holdout；未完 attempt
  阻止读取，失败读取仍消耗，一次读取预约后不得新增模型调用，无 stable 晋升入口。
- 进程保护只证明限定本地行为：输入/输出/时间上限、进程组、背压、保留部分输出；macOS 限定写目录
  并拒绝受保护读和 runtime key 继承。不能保证远端取消、账单硬上限、整个账户隔离或无人看过 holdout。
- 下一步补真实 provider 身份/已计费用量、跨账户权限和可信来源。经济启动另验模型/预算/窗口/范围；
  不新建 DB、scheduler、第二总账，不消耗旧日跑预算。结构通过不等于源事实、PIT或原登记认证。

### 其后：可信归因选一个改进，再做单变量比较（P3/P4）

先用旧决定重放独立验算，不重新问模型或改历史；模型历史回放只能作训练知识可能污染的探索。
待 P0-R 与数据/启动门通过后先同 GPT-6 raw/desk 经济前向，再在新共同窗口比较 Claude/GPT-6。
之后按亏损归因选持有/退出、机会发现、组合选择、第二意见或记忆中的**一个**候选；
不预定放宽止损/延长持有就是答案。若借鉴支撑阻力，先审规格，未读上游实现方可独立实现，勿复制 GPL/AGPL 表达。

同起点、close-confirmed 数据/universe、撮合/费用/风险；固定资料禁额外查询，允许自主查询则说明
比较的是整条工具路径。冻结现金/可执行买入持有/简单规则基准；整手买不起列入暴露，不称严格等权。
主结果用完整窗口，失败日按事前规则保留，成功子集仅辅助；报告扣费净主动收益、IR、真实 NAV、
回撤/尾部/换手/成本、暴露/行业/单票贡献集中和不确定性。20 日只验运行，60 日只作方向检查；
stock-days 按标的/日期分块，重叠样本不当独立；卖后上涨不能直接加进组合收益。
各轮交冻结规格、逐次所见/决定、全账本、基准、费用、失败及支持/不支持/证据不足结论。

### 条件性维护余项（保留，不冒充已完成）

旧交接中的以下事项尚未逐项关闭，随所属能力的小批次处理，不另开并行工作线：

- `require_signal_run_context` 当前仍为 false；是否收紧需调用方覆盖、旧输出对照及明确启用评审，不能按旧周检查日期自动打开。
- 面板候选分层的生产形状 fixture 仍需专项核对时间戳/推荐阈值等边界；已有测试通过不等于这项验收已完成。
- `live_trading/live_subset.py` 仍有本机绝对 ROOT；路径可移植性留待隔离的小维护批次，不与日跑行为混改。
- 兼容入口退役必须满足零内部消费者、至少一个发布周期和明确批准；Atlas 未启动集成/影子臂保持 dormant，不借归档自动恢复或删除。

### 外部产品与方法的开发吸收（2026-09-16，proposed）

本节吸收六篇外部分享中可验证的增量，与第 7 节原有六个代码项目分别记录。
纳入开发计划不代表能力已实现或启用；以下候选均为 `proposed`，按第 8 节准入门推进，
不改变本节“新日期质量 → 数据地基 → provider 回执/隔离 → 经济前向”的顺序。
在途批次优先，同一时间最多两个实现批次；不因六篇分享新增六条开发线。

#### 来源与取舍

| 来源 | 吸收的增量 | 承接与边界 |
|---|---|---|
| [同花顺 Financial-API 分享][external-share-1] | 补源前验证字段、来源、时点与价格口径 | 候选 A，承接 P0-C/P0-B 数据缺口；不重复接入已有 iFinD |
| [OpenBB 产品分享][external-share-2] | 页面与 AI 共用当前数据和证据引用 | 候选 B1；借交互与合同设计，不迁移整套平台 |
| [Serenity 模型组合分享][external-share-3] | 原始来源核验、同输入下的模型差异记录 | 并入既有 P1/P2；目标收益与候选清单不是收益证据，不重启已停止的方法实验 |
| [AI 自动交易终端分享][external-share-4] | 结构化事实、流程状态、超时与降级说明 | 候选 C 与既有面板验收；不新增日跑引擎，不引入自动交易、情绪否决或 LLM 风险偏置 |
| [盈利广度与配置解读][external-share-5] | 区分盈利强度/广度、共同风险与证伪条件 | 候选 C；原报告未核验，二手机构归属、数字和配置观点不作事实输入 |
| [财报学习与认知盲区分享][external-share-6] | 用有出处的问题暴露研究理解缺口 | 候选 B2；可选研究交互，不独立建设题库平台，不以 token 消耗衡量价值 |

[external-share-1]: https://www.xiaohongshu.com/explore/6a89c7af000000002b026579 "# hygiene-allow: reviewed proposal source URL; provenance only"
[external-share-2]: https://www.xiaohongshu.com/explore/6a953cda000000002303ce5c "# hygiene-allow: reviewed proposal source URL; provenance only"
[external-share-3]: https://www.xiaohongshu.com/explore/6a9db5c40000000028037917 "# hygiene-allow: reviewed proposal source URL; provenance only"
[external-share-4]: https://www.xiaohongshu.com/explore/6a9fd7f50000000011032a3c "# hygiene-allow: reviewed proposal source URL; provenance only"
[external-share-5]: https://www.xiaohongshu.com/explore/6a9fff5b00000000120027f1 "# hygiene-allow: reviewed proposal source URL; provenance only"
[external-share-6]: https://www.xiaohongshu.com/explore/6aa4238a000000001103a95d "# hygiene-allow: reviewed proposal source URL; provenance only"

#### 候选 A｜验证新数据源的净增量，归入现有数据工作批次

**缺口与基线**：P0-C 的财报覆盖/修订链、P0-B 的价格口径和权威公司行动尚有缺口。
已有 `backend/data/ifind_mcp.py` 与 `docs/data-sources/ifind.md`，新 Financial-API 是另一接口体系，
账号、权限、限流、覆盖不能互认；同一底层供应商的两个接口不算独立来源，旧客户端只作覆盖对照。

**归属/消费者**：owner 为 data，evidence 负责验收口径；唯一消费者为显式离线源数据验收报告，
无生产消费者。复用 P0-C/P0-B 的来源比对与只读流程；当前尚无获准的新源适配入口，进入
`experimental` 前须在 data 域登记确切 canonical 入口、输入输出合同及替代关系，
不把新接口隐式塞入 iFinD 或默认 provider 链。

**最小实现**：先冻结 5–10 个公开边界样本及字段清单，覆盖普通交易、分红送转、停牌、退市、
财务更正；比较已有来源能做什么、新源补了什么。保存脱敏请求、原始响应及 hash、接口版本、
采集时间、披露时间、报告期和价格口径；密钥不落入报告。公司行动缺失字段、历史修订无法回溯、
权限不足、限流和超时分别记录，未知不得推导成“无事件”或“严格 PIT 可用”。

**验收/退出**：固定样本中的返回值和差异 100% 可追溯，至少一项预先声明的关键缺口获得可核验
净增量，才继续适配；响应成功率不代替可信度。无净增量则停止接入；只覆盖部分字段则仅保留
该字段用途。正式晋升另验所需完整覆盖，5–10 样本不证明全市场/全历史可靠。
隔离输出留在仓库外，撤除试验入口即可回滚；不写生产历史、不修复旧账、不改变价格基准。
P0-B2 的备份、维护窗口和单独批准条件保持有效。

**来源限制（09-16 核验基线）**：固定 40 QPS 和永久免费未获核验，不作为接入假设；
[官方仓库](https://github.com/HiThink-Tech/Financial-API)与[接口总览](https://fuyao.aicubes.cn/docs/api-reference/overview/)用于复核合同。
[公司行动](https://fuyao.aicubes.cn/docs/api-reference/corporate-actions/)字段不等于完整权威账本，
[财务接口](https://fuyao.aicubes.cn/docs/api-reference/financials/)的披露日不等于历史修订可重建。
实现前复核版本与权限；这些链接提供契约线索，不替代实际回执。

#### 候选 B｜在现有股票研究页补证据对齐与认知盲区

**归属/顺序**：owner 为 research，frontend 负责呈现；纳入现有研究页优化，待新日期质量与真实
用户完成验收后排期。B1 → B2 串行拆成微批，不和在途批次一起超过并行上限。
已有同 run 观察哨、delta、空态、人工接受/修改/拒绝及观察追加只补验证，不重复立项。

**B1 页面与 AI 共用证据**：唯一产品消费者为现有 copilot；在
`backend/data/context_builder.py::build_stock_context_pack` 之上补页面选择与证据引用，
复用现有 research copilot、ResearchCase 和 report gate。输入绑定股票、as_of、所选时间范围、
筛选条件、复权/单位/币种、数据版本/hash 及源记录；输出数字可回到同一版本的证据。
切换股票、日期或口径后，历史回答保留原上下文并标为不适用于当前选择；缺失、过期或版本
不一致时明确不能判断，不悄悄换源、使用最新值回答历史问题或另建上下文平台。

**B1 验收/回滚**：冻结 10 个问题，包含股票/日期/复权切换、缺失和过期反例；股票、时点、口径
串用为零，全部数值引用可定位源记录。记录现有页面与候选页面的人工核查时间及错误数，不先
承诺节时比例。若现有能力已满足则仅补验证；失败时停用新增页面上下文入口，保留原 copilot。
借鉴 [OpenBB 后端](https://github.com/OpenBB-finance/backends-for-openbb)与
[Agent 官方示例](https://github.com/OpenBB-finance/agents-for-openbb)的设计，代码复用另查对应版本许可，
不把开放计划视为主仓已改为宽松许可。

**B2 可选的“我还不知道什么”**：唯一产品消费者为现有股票研究页；沿用 research dossier/case
与 `research_report_gate` 的证据路径、研究卡呈现。先选 3 家公司的公开报告，每家 8–10 个问题，
围绕利润来源、业务/客户集中、现金流差异、管理层激励和推翻假设的风险。每题绑定公司、报告期、
公告版本、页码/段落和证据链接；客观披露题有原文答案，主观判断只收理由，不伪装成标准答案。
提供“不知道”“材料不足”和跳过；报告更新或更正后暂停受影响旧题，重新核验再展示。

**B2 验收/回滚**：所有已展示题目均可定位原文；客观披露题答案与原文一致且无关键歧义，
主观题明确不作正误评分。无出处或歧义题撤下。以用户直接阅读同批报告为基线，
记录完成/跳过、耗时、发现的具体知识缺口和再次查证结果，
据此决定保留、删减或停止，不以答对率证明投资能力。学习状态与日面板人工选择分开，不借用
`daily.research_review` 的动作身份、不增加旧复核完成数、不写入验证后策略记忆。若需持久化，
先单独明确 research 的记录合同；关闭可选入口即可回滚，原研究流程继续可用。

#### 候选 C｜宏观与盈利广度作为后续研究模板，不单独开工

owner 为 research，唯一产品消费者为现有 ResearchCase 的主题情景卡；canonical 入口为
`backend/research/theme_hypothesis_engine.py`，组合情景复用现有 `backend/research/stress_test.py`。
只在相关数据口径可核验且 A/B 复审后，作为已有主题研究的模板增量排期：

- 宏观材料区分事实、模型解释和条件化判断，保留来源、发布/采集时间、可知时点与有效期；
  休市、延迟、缺失、超时分别展示。既有日面板承接完成/失败/降级状态，不另建时间线系统；
  有外部调用时同时设单次超时与全任务截止时间，零 LLM 下继续明确 not_applicable。
- 盈利强度、改善公司占比、行业贡献集中度分别计算；先固定时点和样本分母，明确负值/近零
  基期、样本变更、财务更正及当时尚未披露的处理。组合分析列出共同依赖与失效情景，
  不预设科技与红利天然对冲，不把主观综合分、gate_bias 或情绪否决接入权重和风险阈值。

**最小验证/退出**：启用前冻结至少 3 个公开历史截面，覆盖未披露、更正、负/零基期和宏观缺失
反例，核对每个事实的来源/时点与每个比率的分母；历史修订无法重建则标为仅适用当前观察。
比较现有自由叙述与模板的漏项、来源错误和核查耗时；未减少预先登记的具体漏项或证据不足，
撤下模板，不形成新的评分、风险、调度或交易消费者。

#### 候选共同开工与到期规则

具体负责人、canonical 入口、样本/问题清单、基线与成本/时间预算须在各微批开工前冻结；
缺项保持 `proposed`。试验只用临时数据与独立输出，外部调用遵守现有数据发送和预算边界。
实际开工时登记绝对 `expires_at`，最迟在开工后第 10 个交易日复审；到期未过门转 `dormant`，
停止新增依赖，保留失败证据。通过也只支持该项合同或使用价值，按第 8 节另验正式消费者与晋升，
不认证收益；增加成本、无净增量或给用户增加无效负担时缩小或退出。
本次只更新计划，运行真相、架构所有权和已完成历史仍由对应权威文档维护。

## 10. 全局安全与快照门

- 活动 SQLite 先用 `scripts/sqlite_consistent_snapshot.py` 到临时目录生成一致快照，禁止裸拷活动主文件；
  以 `mode=ro&immutable=1` 读取，无 WAL/SHM 依赖，前后核 SHA-256。JSON/Markdown 也按显式路径核 hash。
- 派生报告/测试 DB/cache/output 在仓库外临时区，正式八卡、test2、价格、账本不回写。
  sidecar、来源混杂、不完整覆盖、hash 变化或连续性日期集合漂移都拒绝放行。
- 起算日保持唯一，不拼 partial/重跑/修复行制造完整批次。RunEnvelope 绑定 run_id/batch_id、
  trade_date/as_of/scope/入口、起止/status、expected/completed/failed symbols、freshness/degradations、规则/产物。
- clearance 只叠加独立 operator 事实，不改原漂移事件，不修价格；成功日不重生成面板。
- 未授权不发布/下单/启用实验；不以进程退出、代码存在、文档声明或测试全绿代替运行/来源/用户完成证据。

## 11. AI 接手协议

AGENTS → STATUS → 本文件；架构再读 PROJECT，具体合同再读 Developer Guide。
先检查 dirty worktree，再选最早未阻塞微批；开工前明确 owner/不变量/验收/回滚。
问题涉及敏感边界就按本计划单独评审，不用平行模块绕过阻塞。完成实现与通过运行/质量门分别登记。
每批只更新对应权威文档：已完成细节归 CHANGELOG/外部档案，STATUS 留当前快照，计划只留下一步。
档案只在明确历史查询时加载，旧 unchecked 清单不恢复为新任务。

## 12. 完成定义

运行、产出、数据、经济四门分别出证据；单一面板连接证据、人工选择与可核结果，实验生命周期诚实，
核心无反向工具依赖，文档单源且档案外置，用户确认治理周期与任何生产晋升。
已关闭 20 日 v1 运行门，不宣称整个决策台质量或投资增益已完成。
