# MingCang One Loop — 整体治理与可信闭环计划

> 采纳日期：2026-08-18
>
> 当前状态：**实现阶段已推进；连续运行验收 0/20，治理周期尚未完成**
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

### 阶段 0 — 基线、封档与冲突隔离

状态：**完成（2026-08-19）。** Dirty worktree 已逐项归属，运行基线通过生产库的
immutable 副本审计，旧路线图与关闭计划已进入仓库外治理档案；生产库未被修改。

工作：

- 识别当前 dirty worktree 中每项改动的归属，不覆盖、不回滚用户工作；
- 记录 commit、版本、文档、工具、运行入口、schema、测试和当前生产输出基线；
- 形成旧里程碑总账：完成、保留、shadow、dormant、rejected、archived、重新提案条件；
- 将详细旧规划和实验叙事保存到仓库外治理档案；
- 保留 CHANGELOG 与 Git 历史，不复制数据库、持仓、日志、密钥或模型。

完成门：

- 当前未提交内容都有归属；
- 旧工作线均有结算裁决和承接领域；
- 活跃项目文档不再要求读取旧 M 路线图才能继续开发；
- 没有删除仍被代码、测试或安全合同引用的资料。

### 阶段 1 — 文档单一权威与 AI 导航

状态：**完成（2026-08-19）。** `docs_public/` 为公开唯一源，重复内部页面只保留
兼容 stub；文档 authority/nav/中英文一致性检查与严格 MkDocs 构建已建立。

工作：

- 逐个文档分类为：当前权威、公开源、活契约、证据、运行产物、历史档案；
- `AGENTS.md` 只写 Agent 规则；`PROJECT.md` 只写架构与所有权；`STATUS.md` 只写运行真相；本文件只写计划；`CHANGELOG.md` 只写历史；
- `docs_public` 作为公开站点源，同一主题不得与 `docs` 双份维护；
- 将已关闭的 `docs/dev` 计划移到外部档案，但先把仍有效的不变量提炼进代码、测试或活契约；
- 把本地 `docs/research`、`docs/reviews` 等运行产物真正移出仓库目录；
- 收口重复的 ARCHITECTURE、WHY_NOT、架构图、Fresh-Agent 路由和能力地图；
- 为内部与公开文档建立链接、nav、authority、上下文预算和中英文一致性检查。

完成门：

- 每个主题只有一个权威来源；
- 默认 AI 入口不重复加载相同状态；
- `mkdocs build --strict`、链接、nav、README parity 和文档所有权检查全绿；
- 归档过程没有丢失安全边界、证伪结论和运行证据。

### 阶段 2 — 统一 RunEnvelope 与完成批次合同

状态：**合同实现完成；运行验收 0/20。** 所有目标入口使用显式
`run_envelope.v1`，消费者按唯一完整批次 fail-closed；20 个实施后真实收盘日仍是
不可跳过的阶段完成门。

目标：scheduler、手动 CLI、test2、盘前/盘后/周末任务使用同一运行真相。

当前证据（2026-08-19）：

- `/api/system/health` 已开始暴露 latest workflow 与 latest signal batch
  的覆盖关系，并在信号批次没有同日 `job_runs` 时 fail-closed；
- 真实 DB 审计显示最新价格与信号为 2026-08-18，但最新 `job_runs` 仍为
  2026-07-16 的 smoke 记录，说明手动/test2 信号路径尚未统一落账；
- 合同与入口收口已经完成；由于实施日期为 2026-08-19，真实连续性审计尚无
  可计数收盘日，因此阶段 2 仍不可标记为完整验收。

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

状态：**完成（2026-08-19）。** core/workflow 到 tool 实现依赖均为 0；稳定能力已
迁到 canonical domain module，旧路径只作兼容 facade；registry 元数据和边界测试已补齐。

工作：

- 把当前日常总编排器拆成稳定领域服务和薄 workflow；
- 逐项清零 workflow→tool 实现依赖；
- tools registry 增加 owner、lifecycle、consumer、expiry、replacement；
- 默认只展示 stable 工具；maintenance/evidence/attic 分入口；
- dormant/rejected/archived 能力不被默认导入或运行；
- 冻结新的 M 编号模块，兼容入口按发布周期退役。

完成门：

- core→tools 和 workflow→tools 实现依赖均为 0；
- 每项稳定能力只有一个 canonical owner 和入口；
- 架构边界测试、CodeGraph、聚焦测试和 `make verify` 全绿；
- 结构批次对 signals、positions、weights、stops、scheduler 时序、API 和 DB schema 的差异为 0。

### 阶段 4 — 研究、风险与外部优点归口

状态：**完成（2026-08-19），无生产晋升。** 吸收点均落入现有领域并保持
additive、shadow/read-only。预注册锁定出场样本中 baseline 为 +14.78%、最大回撤
-27.50%，四个替代方案均更差且未过回撤门，故保留 baseline、冻结新变体。

工作：

- 把 stock-analyzer 的正反论点、三情景和证伪条件合并进现有 ResearchCase/report gate；
- 把 Vibe 的 Run Card、PIT 和行为复盘合并进 evidence、trade journal、ReviewCase；
- 把 stock_monitor 的去重、压制原因和频控合并进观察哨/通知层；
- 把 M54/M68 统一为“新闻与事件风险”能力，风险槽位和方向实验分账；
- 完成现有出场影子实验的预注册裁决，不新增变体；
- 记忆继续 shadow-only，达到明确重新提案门前不恢复决策注入。

完成门：

- 六个外部项目没有产生新的平行框架；
- 每个吸收点都有既有 owner、测试、指标和退出条件；
- 主观研究清单不直接改变短线分数；
- 事件风险可以进入面板，方向权重仍需独立统计门和用户确认。

### 阶段 5 — 单一日常产品面与前端收口

状态：**完成（2026-08-19）。** 后端提供固定八卡的权威盘后面板；前端单一入口、
shadow 过滤、证据下钻、桌面和 390px 移动布局均已验收。权威产物与 JobRun 绑定，
先写 pending、账本提交后原子标记 committed，失败时不会伪装成完整证据。

每日权威面板至少展示：

- 批次完整性和数据降级；
- 候选变化和理由；
- 持仓体检、机械风险线与风险预算；
- 新闻/事件风险与证据；
- 观察哨触发和被压制事件；
- 与上一交易日的变化；
- 需要人工确认的问题；
- 后续 ReviewCase 与结果归因入口。

工作：

- 将 InStock 的“筛选→解释→回测证据”体验用于现有页面，不复制其系统；
- 前端按 app/features/services/ui 收敛，禁止页面直接依赖其他页面实现；
- stable/shadow/dormant/rejected 在导航和卡片中明确区分；
- 合并重复状态面、研究面和报告入口。

完成门：

- 用户从一个入口看清当天发生了什么、为什么、还需确认什么；
- 每张卡能追溯 RunEnvelope 和证据；
- 页面之间无实现级依赖；
- TypeScript、Vitest、ESLint、build 和桌面/移动真实浏览器流程全绿。

### 阶段 6 — 连续运行证明与治理发布

状态：**审计器和指标合同已完成；真实连续运行 0/20。** 当前唯一剩余主门是收集
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
