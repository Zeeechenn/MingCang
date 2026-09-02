# MingCang One Loop — 整体治理与可信闭环计划

> 采纳日期：2026-08-18
>
> 当前状态：**实现阶段已推进；连续运行验收 11/20，治理周期尚未完成**
>
> 规划性质：这是明仓唯一活跃的项目级执行计划。旧 M 编号只作为历史、兼容入口和证据标签，不再作为新工作的组织方式。

## 1. 计划权威与历史边界

- 本文件只维护 **One Loop 当前阶段、顺序、完成条件和阻塞项**。
- `STATUS.md` 只维护当前运行真相；`PROJECT.md` 只维护架构、领域和所有权；`CHANGELOG.md` 只维护已发生的版本历史。
- 旧路线图完整快照已保存到 owner 本机、仓库外的治理档案；本地绝对路径不写入版本库。
- 已发布的历史继续以 Git 与 `CHANGELOG.md` 为准，不删除、不改写。
- 除兼容入口外，禁止新增以 M 编号命名的模块、文件、路线或产品概念。

## 2. 北极星

明仓不是自动交易系统，也不是不断叠加模型的功能仓库。它是一个本地优先、可审计的股票研究与风险纪律工作台。

One Loop 的最终结果只有一个：

> 每个完整交易日形成一份可追溯的盘后操作面板，把数据、候选、持仓、事件风险、观察哨、人工判断、复盘和结果反馈连接成同一个闭环。

闭环必须满足：

1. 每个结论能追溯到唯一运行批次、输入、规则版本和降级状态。
2. 确定性规则负责数据门和风险底线，LLM 负责证据整理、反证、解释与有限裁量。
3. 任何实验先进入 `experimental/shadow`，不得因“代码存在”而被视为生产能力。
4. 任何能力都必须有 owner、消费者、指标、退出条件和替代关系。
5. 不连接券商、不自动下单；最终决策始终由用户负责。

## 3. 为什么现在治理

当前明仓不是失控的意大利面系统：核心领域边界、数据血缘、风险规则和测试守卫仍然有效。但外围已经形成明显的架构沉积：

- 工具、维护入口、证据工具和历史实验对使用者暴露得过于接近；
- 日常总编排器仍直接了解多个工具实现，稳定门面没有完全收口；
- scheduler、手动 CLI、test2 和日常流程没有全部使用同一完成批次合同；
- 信号、记忆和部分数据维护活跃，但操作卡、复盘和任务账本的运行新鲜度不一致；
- 前端存在平铺大页面和页面间耦合，文档存在双源、历史计划与活契约混放；
- 外部项目的优点容易以新增模块的方式进入，而不是替换、合并或淘汰现有能力。

因此本计划优先做减法、归属、统一入口和运行证明；在这些完成前，不启动新的大功能线。

## 4. 目标结构

```text
Production Core
├── data / evidence
├── research
├── decision / risk
├── portfolio
└── review / outcome
        │
        ▼
Daily Orchestration
├── RunEnvelope
├── premarket / intraday / postmarket / weekend
├── proposal → revalidate → gate → audit
└── one authoritative daily panel
        │
        ▼
Operator and Product Surface
├── one daily entry
├── explainable stock/research views
└── explicit stable / shadow / dormant states

Research Lab ──promotion gate──▶ Production Core
Archive ──no imports / no default context──▶ historical lookup only
```

领域规则：

- 正式逻辑归入 `data / analysis / backtest / evidence / research / memory / decision / portfolio / ops / jobs / workflows`。
- `backend.tools` 只承担 CLI、维护、评估、实验和兼容适配，不承载被核心或 workflow 反向依赖的业务实现。
- API、scheduler、agent 和前端只依赖稳定门面。
- Research Lab 与 Archive 不得通过隐式 import、默认配置或共享写路径影响正式信号。

## 5. 能力生命周期

每项能力必须处于且只处于一个状态：

| 状态 | 含义 | 允许的行为 |
|---|---|---|
| `proposed` | 问题和方案待审查 | 不进入运行时 |
| `experimental` | 隔离实验 | 临时数据、无正式消费者 |
| `shadow` | 使用真实形状双跑 | 只读/独立落账，不改变正式输出 |
| `stable` | 通过合同与运行门 | 可进入 Daily Loop |
| `dormant` | 代码保留、默认关闭 | 不被默认导入或展示 |
| `rejected` | 证据否定 | 停止积累，不以新名称复活 |
| `archived` | 历史记录 | 仓库外档案或不可执行历史 |

每个能力注册项最终都要记录：

```text
owner_domain
lifecycle
consumers
canonical_entrypoint
input_output_contract
safety_level
evidence_status
success_metric
expires_at
rollback
replacement
```

## 6. 旧工作线结算与承接

旧编号在 One Loop 中不再是活跃里程碑。未完成的价值按能力归属承接：

| 历史标签 | 当前裁决 | One Loop 承接 |
|---|---|---|
| M54 新闻层 v2 | 方向预测未过门；采集、预算和金字塔机制有价值 | 与新闻镜像合并为“新闻与事件风险”能力；方向继续 shadow |
| M58 出场影子 | 选股用途已证伪；出场实验尚待预注册窗口裁决 | 归入“风险验证实验”，冻结新增变体 |
| M59 操作面板 | 代码存在，但运行闭环未证明持续产卡 | 成为 One Loop 最终产品验收，不再独立发展 |
| M60 观察哨 | 触发器有价值 | 作为 Daily Loop 事件输入 |
| M63 日常编排 | 入口价值成立，内部职责过重 | 归入“编排收口”，兼容命令保留一个发布周期 |
| M64 Live Track | 代码完成、默认未启用 | 保持 dormant；只有独立启用门满足才重新提案 |
| M66 结构治理 | 方向正确、尚未完成 | 直接并入 One Loop 结构和文档治理阶段 |
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

任何外部项目、论文、Skill、Agent 或策略进入代码前，提案必须回答：

1. 它解决明仓哪个已经存在的问题？
2. 明仓是否已有相同或相近能力？
3. 借鉴的是思想、接口、算法还是代码？
4. 归属哪个现有领域，谁负责？
5. 谁是唯一正式消费者？
6. 输入、输出、失败和降级语义是什么？
7. 是否影响信号、仓位、止损、scheduler、provider、DB 或 API？
8. 如何隔离为 experimental/shadow？
9. 当前基线、成功指标和最少样本是什么？
10. 什么时候停止、回滚或删除？
11. 它替代、合并或退出哪个旧能力？
12. 需要哪些合同测试、运行指标和 provenance？

硬规则：没有 owner、消费者、指标、退出条件和替代对象，不得进入正式代码。新增一个顶层能力，原则上必须合并或退出一个旧能力。

## 9. 执行阶段

同一时间最多允许两个实现批次在进行，且结构迁移与业务行为改变不能混在同一批。

### 当前开发计划与接手入口（2026-09-03）

本节已吸收仓库外《明仓优化开发指导》和四项目审计中仍有效的执行内容；后续开发只需
读取 `AGENTS.md → STATUS.md → 本文件`，不得再把外部长报告当第二份路线图。报告的固定
项目结论已压缩到 `docs/evidence/external_quant_projects.md`。

#### 当前状态与真实缺口

本轮已获 owner 合入授权，但授权不绕过批次自身前置门：

| 批次 | 已合入/已决定 | 尚未完成 |
|---|---|---|
| P0-G | 日跑、独立 CLI、审计函数共享唯一默认起算日；同快照语义零差异 | 非权威 override 仍须 fail-closed 或进入显式迁移；输出直接报告被比较日集合 |
| P0-B1 | `manual_only` 重基工具默认 immutable dry-run；execute 仅允许临时独立 SQLite，具备来源/口径 pin、全历史覆盖断言、备份、事务、逐支校验和哈希检查 | 日常 provider 写路径仍须阻断跨源复权拼接；601899 ATR 反向变化原因未解释 |
| P0-R | `manual_only` 现金 NAV v1：下一会话开盘、T+1、锁价不可成交、保守止损、成本、仓位/行业/总仓门和亏损归因 | 公司行动、显式停牌/部分成交、冻结 control/candidate ID；价格口径清零后重跑 |
| P0-A | G1 的 `1/5/2` 产品分类已定；disabled preview 只保存在外部评审历史 | 20/20 前不合入；stable/shadow 生命周期、三张 missing 卡 producer、空状态前端和真实组合回归仍开放 |
| P0-B2 | 未开始 | 生产/历史价格修复仍需独立批准，不包含在本次“合入代码”授权中 |

P0-R 当前 frozen-snapshot 输出为 `blocked_price_basis`、19 个价格口径问题、
`promotion_eligible=false`。P0-B1 对 `000568` 的实源 dry-run 只取得 14 行，和库内 14 行中
6 行不一致，且未覆盖 2,501 行历史中的 2,487 行，因此拒绝 execute。两项结果都只能作为
诊断，不能证明策略收益。

#### G1 — 八卡产品分类与生命周期未决项

八卡采用 `1 / 5 / 2` 分类，只增加产品元数据，不修改 `daily_panel.v1` 的身份、顺序或
现有语义：

- 运行控制 1 张：`batch_integrity`；
- 决策证据 5 张：`candidate`、`position_health`、`event_risk`、`watchtower`、`daily_delta`；
- 治理闭环 2 张：`human_confirmation`、`review_attribution`。

八张卡仍全部必需。上述分类不等于 stable/shadow 生命周期裁决；P0-A 开工时仍须明确：

- `event_risk` 是每日确定性 stable 事件风险，还是 0-LLM 日跑中的 shadow
  `not_applicable/degraded_zero`；不得为了变绿恢复日常 LLM；
- `watchtower` 必须同日显式传递或写入耐久 artifact，校验 `as_of/run_id`，不得把
  `/private/tmp` 当长期证据目录；
- `daily_delta` 必须有正式 producer，包含 current/previous as-of、结构化变化和
  `no_previous_reason`；
- `ready_zero`/`not_applicable` 必须有结构化原因，前端应将原因渲染给人看。

任何 v2 只能先以 disabled preview 存在。旧 20 日只证明 v1 运行门，不能证明新合同的
产出质量或收益。

#### G2 — 本地产物唯一只读快照协议

1. SQLite 使用 `scripts/sqlite_consistent_snapshot.py` 生成到 `/private/tmp`，禁止裸复制
   活动数据库；快照必须无 `-wal`/`-shm` 依赖。
2. 证据工具以 `mode=ro&immutable=1` 打开快照，前后核对 SHA-256；写测试只用临时
   DB/cache/output，不得连接生产可写句柄。
3. JSON/Markdown 本地产物按显式路径只读并核对哈希；派生报告只写 `/private/tmp`，
   不回写正式八卡、test2、账本或仓库内忽略目录。
4. sidecar、来源/复权混杂、历史覆盖不完整、哈希变化或 continuity 日集合漂移均
   fail-closed。价格修复前后要比较逐日集合，而不只比较 status 或 N/20。

#### G3 — 合入、启用和修库权限

- owner 已授权合入 P0-G、P0-B1、P0-R 和本次文档治理；它们仍保持当前 production
  consumer 为零或原行为不变。
- P0-A 必须同时满足 20/20、旧 v1 基线封存和 owner 再次确认，之后还要重新开始
  output-quality 与 forward-return 验证。
- P0-B2 永远单独批准：先给逐支影响清单、固定 provider/basis 的全历史覆盖证明、备份、
  回滚和维护窗口；涉及当前 LIVE 持仓时重新计算 ATR/NAV 并人工确认。
- P3/P4 等价格口径问题清零且 P0-R 产出可信亏损归因后才可开工。

#### 每个微批次的交付合同

每批只做一个行为主题，并在提交前记录：

1. 基准 commit、依赖事实逐条复核；任一事实不一致就停工报告。
2. owner domain、唯一消费者、行为不变量、改动文件和回滚方式。
3. 一个修复前能暴露缺陷的对抗性测试、聚焦测试、最终完整门；skip 逐项解释。
4. 底层表/JSON 字段和哈希证据；改运行合同须重跑 continuity，改收益引擎须核对
   ledger/NAV 守恒。
5. 未决项、失败门、是否允许合入/启用/写库。测试通过本身不授予任何后续权限。

#### 后续唯一顺序

1. One Loop 每日继续到 20/20；同时完成 P0-G override/迁移留痕和 P0-B1 日常写入防混源。
2. 价格口径清零后重跑 P0-R，补齐成交/公司行动边界并冻结 control。
3. 20/20 后封存 v1 基线，经 owner 确认再做 P0-A producer、产品合同和前端空状态。
4. P1 将运行门、产出门、数据门和收益门分账；20 日门只证明链路运行。
5. P2 扩展现有 M29 为 research-only Candidate Manifest：canonical signature、数据快照
   hash、完整试验族/预算、inner/outer folds、purge/embargo、holdout 访问记录、生命周期；
   首版无 DB、UI、scheduler 或第二套 ledger。
6. P3 先按 P0-R 亏损归因选择一个预注册候选。支撑/阻力只是候选之一；若采用，使用
   经审阅规格和未读上游源码的实现方，不复制 GPL/AGPL 表达。
7. P4 使用同一 close-confirmed 数据/universe/撮合/成本/风险预算做冻结 control 与
   单变量 candidate 前向双臂；候选只写独立 shadow/paper ledger，最终仍需统计门和 owner 确认。

收益主指标为候选相对 control 的扣费净主动收益、日主动收益信息比率和包含现金/费用/
公司行动的真实 NAV；最大回撤、尾部损失、换手、成本与贡献集中度不得恶化。20 个交易日
只作运行 smoke，60 日只作方向检查，stock-days 必须按标的/日期 block 处理，不能把重叠样本
当独立观察。

### 阶段 0 — 基线、封档与冲突隔离

状态：**完成（2026-08-19）。** Dirty worktree、历史能力和旧规划均已归属；运行
基线通过 immutable 副本审计，历史叙事进入仓库外治理档案，生产库未被修改。
详细过程只在 Git/CHANGELOG 和外部档案中保留，不再占用活跃计划上下文。

### 阶段 1 — 文档单一权威与 AI 导航

状态：**完成并持续守卫。** `docs_public/` 是公开唯一源；AGENTS/PROJECT/STATUS/
ROADMAP/CHANGELOG 职责分离，旧页面仅保留兼容 stub，`make doc-check` 守卫 authority、
nav、README parity 和 `docs/dev` allowlist。关闭计划和长审计只保留外部原文与仓内短摘要。

### 阶段 2 — 统一 RunEnvelope 与完成批次合同

状态：**合同实现完成；运行验收 11/20。** 所有目标入口使用显式
`run_envelope.v1`，消费者按唯一完整批次 fail-closed；20 个实施后真实收盘日仍是
不可跳过的阶段完成门。

目标：scheduler、手动 CLI、test2、盘前/盘后/周末任务使用同一运行真相。

当前证据（截至 2026-09-02 收盘）：

- `/api/system/health` 已开始暴露 latest workflow 与 latest signal batch
  的覆盖关系，并在信号批次没有同日 `job_runs` 时 fail-closed；
- 2026-08-19、20、21、24、25、26、27、28、31、2026-09-01 和 2026-09-02
  十一个 close-confirmed 日
  均有唯一完整官方信号批次、authoritative RunEnvelope 和 committed 八卡面板；
  当前为 11/20，completeness_rate 1.0、degradation_rate 0.0、审计 blockers 为空；
- 每日 runner 已用一致性 SQLite 快照替代裸复制，并在目标日不 complete 或任一步失败时
  明确 abort；历史/研究性重跑仍留作证据，但不会冒充当日官方批次。

RunEnvelope 至少包含：

```text
run_id / batch_id
trade_date / as_of / scope / entrypoint
started_at / completed_at / status
expected / completed / failed symbols
input freshness / degradations
profile and rule versions
output artifacts
```

工作：

- 优先复用现有 `job_runs`，不无理由新建平行账本；
- 所有正式入口通过同一 tracked execution facade；
- 消费者只接受一个明确的 `complete` 批次；
- partial、修复批、重跑批不能拼成不存在的合成批；
- 新鲜度、覆盖、provider 降级和失败状态结构化落账；
- 为 FriesTrader 式 `proposal → revalidate → gate → audit` 建立研究/模拟合同，不连接券商。

完成门：

- 100% 正式日常入口产生 job/run 记录；
- 每条正式输出能追溯到唯一完整批次；
- scheduler、CLI、test2、API 对同日完成状态回答一致；
- 连续 20 个完整交易日无消费者取错批次。

### 阶段 3 — 编排、工具和领域收口

状态：**完成（2026-08-19）。** core/workflow 到 tool 实现依赖为 0；稳定能力归
canonical domain，旧路径只作兼容 facade。工具生命周期和边界由 registry 与架构测试守卫。

### 阶段 4 — 研究、风险与外部优点归口

状态：**完成（2026-08-19），无生产晋升。** 外部方法只作为 additive、shadow/
read-only 候选进入既有领域。锁定出场样本的四个替代方案均劣于 baseline，故保留
baseline、冻结变体；新四项目的固定审计结论见短证据摘要，不建立平行框架。

### 阶段 5 — 单一日常产品面与前端收口

状态：**结构合同完成（2026-08-19），内容质量门仍开放。** 固定八卡、单一入口、
pending/committed 协议和证据下钻已验收；P0-A 仍需补三张卡的真实 producer、生命周期
合同与人类可读空状态，因此“八卡 committed”不得写成“八卡都有有效内容”。

### 阶段 6 — 连续运行证明与治理发布

状态：**审计器和指标合同已完成；真实连续运行 11/20。** 当前唯一剩余主门是收集
至少 20 个实施后 close-confirmed 日，并在每日 RunEnvelope、信号批次、committed
八卡面板和六项运行指标一致后，由用户显式确认治理周期完成。当前不发布、不晋升。

工作：

- 在不改变真实交易边界的前提下连续运行 One Loop；
- 记录完整率、降级率、重复提示率、人工复核率、复盘新鲜度和失败恢复；
- 核对治理前后正式信号、仓位、风险线和生产配置差异；
- 清理已到期兼容入口和确认无消费者的历史工具；
- 形成双语发布说明，但公开发布不使用内部 M 编号。

完成门：

- 至少连续 20 个 close-confirmed 交易日形成完整面板；
- 日常任务账本覆盖率 100%，批次身份无歧义；
- 关键下游不以陈旧结果冒充当日结果；
- 全量验证、文档验证、浏览器验证和发布一致性检查全绿；
- 由用户显式确认治理周期完成及任何生产能力晋升。

## 10. 全局安全门

所有阶段均适用：

- 结构迁移不得顺带修改交易逻辑；
- provider、cache、PIT、DB schema、scheduler、memory routing、风险规则和 API 合同必须单独评审；
- 使用生产 SQLite 时先建立一致只读快照，默认不可修改真实数据；
- 每批独立、可回滚；不混入数据库、日志、模型、持仓或生成报告；
- 不因测试通过就宣称运行闭环，必须核对进程、任务账本、真实数据库和新鲜产物；
- 不因文档存在就宣称能力在用；
- 不自动下单，不连接券商，不把输出表述为财务建议。

## 11. AI 接手协议

任何新的 Codex、Claude 或其他开发 AI 在执行本计划时：

1. 先读 `AGENTS.md`、`STATUS.md` 和本文件；架构任务再读 `PROJECT.md`。
2. 先检查 dirty worktree，现有修改默认属于用户，不覆盖、不重置。
3. 从最早的未完成且未阻塞阶段选一个最小批次；不得跳过前置门。
4. 开始前写清本批 owner domain、行为不变量、测试和回滚方式。
5. 结构和行为变化分批；一次最多推进两个批次。
6. 完成后先验证代码，再验证运行证据；没有新鲜运行证据不得把状态写成 complete。
7. 只更新职责对应的权威文档，不在仓库创建临时 plan/progress/notes 文件。
8. 外部项目必须先过第 8 节准入门。
9. 阻塞时记录具体证据，不以新增平行模块绕过问题。
10. 每完成一个阶段，将历史事实写入 `CHANGELOG.md`，并从本文件移除已完成细节，只保留下一阶段入口。

## 12. One Loop 完成定义

只有同时满足以下条件，整个计划才算完成：

- 一个权威完成批次合同贯穿所有日常入口和消费者；
- 一个盘后操作面板连接数据、研究、风险、持仓、事件、观察哨和复盘；
- core/workflow 不依赖工具实现；
- 能力生命周期可见，实验不会伪装成生产；
- 文档每个主题只有一个权威来源，本地产物和历史档案不占活跃仓库；
- 六个外部项目只留下有指标、有 owner、有退出条件的增量；
- 连续运行和完整验证证明闭环，而不是只证明代码存在；
- 用户确认治理结果，并决定是否进入下一个有明确问题定义的产品周期。
