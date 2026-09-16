# Developer Guide

这页回答“怎么继续开发明仓”。具体顺序和启用条件由仓内 `docs/ROADMAP.md` 管理，本页维护实现方法与验收要求，不另设任务队列。普通用户先读 [User Guide](USER_GUIDE.md)，查功能先读 [Feature Map](FEATURE_MAP.md)。

开发使用当前会话配置，不从旧交接文档自动切换模型或派工。开发模型与实验治疗臂分别记录，
不占现有日跑预算。AGENTS 是共享规则；本页保留可调用接口、参数和验证边界，已完成实施过程
只见 CHANGELOG/归档。AGENTS/CLAUDE/Pi 文档整理不授权改变运行 prompt、交易规则或默认消费者。

## 1. 开发原则

- 先明确用户任务，再写页面或接口。
- 区分用户动作确认、已授权隔离开发、生产启用与修库；按当前任务和ROADMAP执行，不为已授权小步骤重复确认。
- AI/LLM 默认是 shadow，不自动覆盖官方信号。
- 量化和研究实验默认 non-promoting。
- 新功能要能被 demo 或小样例解释清楚。

## 2. 加一个前端页面

1. 新增 `frontend/src/page-<name>.tsx` 页面（TypeScript）。
2. 在 `frontend/src/main.tsx` 增加路由和导航。
3. 在 `frontend/src/services/` 正式入口增加 API wrapper；根目录 `src/api.ts` 保留兼容。
4. 把“是否写入/是否需确认”写到 UI 行为里。
5. 给复杂 helper 加测试。
6. 用 demo 数据跑一遍。

页面文案原则：

- 普通用户第一眼应知道这页能做什么。
- 休眠/影子功能不能包装成生产能力。
- 高风险动作要有确认。

## 3. 加一个后端 API

1. 找到对应 domain route，例如 `backend/api/routes/research.py`。
2. 在 `backend/api/schemas.py` 增加 schema。
3. 复用现有 service，不复制业务逻辑。
4. 写 focused tests。
5. 外部 provider 调用要说明 key、side effect 和失败模式。
6. 写操作要明确权限和确认路径。

## 4. 加一个 agent action

1. 在 `backend/agent/action_registry.py` 定义 action。
2. 给出 JSON schema。
3. 设置 risk level。
4. 默认 `requires_confirmation=True`。
5. handler 复用 API/service。
6. dry-run 返回足够清楚的 payload、risk 和 side effects。
7. 写 `tests/test_agent_action_registry.py` 相关测试。

标准流程：

```text
candidate -> dry-run -> human review -> confirm -> execute -> audit/result
```

## 5. 加一个研究模块

先判断它属于哪条 lane：

| Lane | 说明 | 可写入对象 |
|---|---|---|
| breadth | 扩展信息面，发现资料和候选论题 | ResearchState / Dossier / ForwardThesis draft |
| falsification | 找反例、失效条件和结果归因 | ReviewCase / scoreboard / MemoryPromotionCandidate |
| short-term risk | 风险纪律、止损、持仓和组合暴露 | risk warning / position context |

研究模块默认不改官方信号。需要 promotion 时必须有前向证据和用户确认。

### 5.1 条件化建议与用户选择

1. 每个方案标明证据时点、来源、反证、预期持有方式、继续成立条件、失效条件和有效期。
2. 分开官方信号、模型原建议、风险裁剪、用户接受/修改/拒绝和成交；建议不是成交。
3. 当前持仓必须来自明确账户/时点/来源；旧DecisionRun目标不是现仓证明。unknown不当空仓，
   不依据未知状态输出增加风险的数值比例；确认空仓后才适用已有试错政策。
4. 用户偏好有标的/范围/生效时间，不自动写成公司负面事实；无回复保持pending。
5. 复用现有候选、持仓、人工确认和复盘入口；待办须去重、过期和记录最终处理。
6. 新方法先做显式候选；改变默认prompt/Skill也算行为变更，不因文件是Markdown而绕过One Loop门。

### 5.2 增加模型治疗臂或验证明仓增益

**问题先固定**：同模型raw/desk测明仓帮助；同desk Claude/GPT-6测模型代理路径；
同模型同数据、仅改一个流程测开发效果。每轮只选一个问题，默认两臂。

1. 复用现有evidence登记与P0-R执行能力，不为模型分别复制业务引擎或生产账本。
2. 首次决定前冻结输入、版本、模型、工具、风险、成本、基准、预算、评价窗口与停止规则。
3. 各臂的现金、持仓、订单、决定、记忆和恢复目录独立；公共事实只读。实际查询可不同，
   但须记录所见内容和工具成功率；固定packet模式禁止额外查询。
4. 同时记录requested/resolved模型身份，禁止静默fallback；模型自述和外层开发宿主不算回执。
5. 保存实际可见输入和逐次工具请求/返回/hash/cutoff/错误/用量；不以完整允许包代替实际所见。
6. 用FakeProvider和合成账本先测未来信息、混臂、超预算、事后freeze、模型替换、失败和恢复。
   纯校验器不能证明资料真伪或OS隔离；未实现的运行器不能写“已运行”。
7. 前向主结果使用完整冻结窗口，失败日按统一政策保留，成功日子集只辅助；版本变化新开窗口。
8. AI-only shadow可在事前批准虚拟政策内模拟，不需逐笔再确认；human-assisted模式单独记录
   人工影响，无回复不新增风险。用户看过另一臂后的修改不归因给单一模型。
9. 生产路径保持不变；价格、公司行动、数据更新、模型身份、预算和启动范围未就绪时只做离线准备。

历史回测分清“旧决定重新核算”和“模型重新作历史决定”；后者不能排除训练知识污染。
前复权代理数量不能标为真实股数/NAV。5日记录检查、20日运行门或60日观察都不自动证明盈利。
收益评价同时报告基准、暴露、成本、回撤、贡献集中、失败及不确定性，不能只挑上涨窗口。

### 5.3 本轮已实现的候选入口与接手方式

| 入口 | 能做什么 | 当前边界 |
|---|---|---|
| `backend.data.context_builder.build_stock_context_pack(..., strict_research_inputs=True)` | 同一显式 cutoff 读取已披露财务、可用标签，保留缺口 | 必须传研究 DB 和 datetime；不会自动补源，未证明日内可见或历史修订 |
| `backend.data.context_builder.render_context_text(..., strict_research_inputs=True)` | 先保留股票/时点/风险和缺口，正文截断有标记 | 必需内容装不下抛 `StrictContextBudgetError`，不能吞错后照常判断 |
| `backend.research.decision_draft.build_decision_draft(...)` | 分开实际持仓、原始提议、历史目标与禁买约束 | 所有比例为 0–1；永远 pending、不能执行；不替代组合风控 |
| `backend.research.copilot.prepare_candidate_copilot(...)` | 将严格上下文和草稿组合成只读研究预览，返回实际文本 SHA-256 | 显式 DB、带时区 cutoff、账户、提议和限制；不调用模型或写 ResearchState；原默认 copilot 未接线 |
| `backend.evidence.decision_desk_validation.validate_experiment_spec(...)` | 检查已冻结声明与运行后回执的结构、两臂条件、预算及失败日保留 | 最高仅 evidence_structure_valid；不证明事前冻结、源事实、隔离或盈利 |

研究预览的 `partial` 表示有数据缺口，不是数据合格；`unavailable` 不给数值目标。
单股草稿只约束显式提议，账户持仓“已知”只表示通过本地输入检查，不认证券商事实。
新入口目前没有 API、scheduler、UI 或默认消费者；合并代码不等于日跑已经采用修复。
调用样例和不触发 provider/flush 的集成测试见 `tests/test_candidate_review_boundaries.py`；
各字段和有效/无效规格见 `tests/test_decision_draft.py`、
`tests/evidence/test_decision_desk_validation.py`。这些 fixture 都是合成测试，不可当真实模型证据。

实验 JSON 可显式离线检查：

```bash
python -m backend.evidence.decision_desk_validation "$EXPERIMENT_JSON" --artifacts-root "$EXPERIMENT_ARTIFACTS"
```

命令不写文件；blocked 返回退出码 1，结构通过返回 0。退出码 0 也可能只允许 diagnostic/smoke，
调用者必须读 capability。`artifacts` 是观察内容 SHA-256 到根目录内相对文件的映射；
附加检查会读取原始输入、工具返回、请求/响应和每日观察文件，拒绝缺文件、字节变化和路径越界。
它只证明保存的字节与声明一致，仍不能证明模型确实看到这些字节。未传 artifacts-root 时
`observation_bytes_verified=false`。注入式单次记录器已提供 `backend.evidence.decision_desk_recording.record_model_observation(...)`：
必须给仓库外输出根、实验/臂/attempt身份、请求原文、带时区cutoff、期望模型、显式预算及provider callable。
它把同一份已保存请求bytes传入provider，保存响应/模型身份/用量/异常；重复attempt不覆盖，
模型不符或用量超限留下failed回执。工具原文只标调用者提供，不假称模型看到。
FakeProvider及字节校验对接测试已覆盖；它没有默认模型客户端、没有自动fallback，也不负责
整个实验的累计预算或OS隔离。单次成本只在回执后检查，不是远端API费用硬限额。
不要把本 CLI 当成完整实验 runner，也不要用假回执让待启动实验“通过”。

#### 离线实验会话控制

`backend.evidence.decision_desk_session` 在单次记录器上增加三个显式入口：

| 入口 | 行为 |
|---|---|
| `freeze_plan(output_root, experiment_id, plan)` | 在仓库外独占创建实验目录，写机器生成时间及校验hash；已有目录一律拒绝，不能补写事前冻结 |
| `run_frozen_attempt(...)` | 从冻结计划取得模型和逐臂预算；先加锁、落盘预留，再调用注入provider；重复attempt拒绝 |
| `inspect_session(output_root, experiment_id)` | 只读汇总每臂预留费用/次数及成功、失败、缺失回执；不是可执行的“启动许可” |

`plan` 必须完整给出以下字段，未知字段会被拒绝；它不是完整版实验规格的替代：

- `problem`：沿用上文三个验证问题；同模型问题必须同requested_model，模型比较必须不同。
- `date_window: {start, end}`：ISO日期，固定以`Asia/Shanghai`解释带时区cutoff；未来cutoff拒绝。
- `shared_input_hash`、`risk_hash`、`execution_hash`：SHA-256声明；仍须原字节及完整版规格验证。
- `budget_policy`：`matched`要求两臂预算相同；`declared_per_arm`只声明各自预算，不宣称预算可比。
- `arms`：恰好两项，各有独立`arm_id`、`account_id`、`requested_model`，以及
  `budget: {total_model_calls, total_cost_cny, max_attempt_cost_cny}`；预算为正且单次上限不超过总额。

接手顺序：先用完整P2规格明确prompt、工具、基准及失败政策，再冻结上述小型控制计划，
然后按日期/治疗臂给新的attempt_id，向`run_frozen_attempt`传显式cutoff、请求bytes和provider。
请求记录位于`output_root/experiment_id/arm_id/attempt_id`；不允许自定义另一套输出namespace。
回执附带计划hash和账户标识，原始请求/响应沿用单次记录器。样例和合成计划见
`tests/evidence/test_decision_desk_session.py`，进程退出/恢复反例见
`tests/evidence/test_decision_desk_session_process.py`。不要将测试中的虚构hash或FakeProvider用于正式证据。

每次预留一调用和`max_attempt_cost_cny`，即使实际费用更少、provider失败或进程中断也不自动退回。
重启后先inspect并核对原始记录，未知结果保留为缺失；不能删预留文件来重试或事后修改原计划。
已知任一臂超限或预留/回执损坏将阻止整个实验后续调用，在途调用不能由本层撤销。
文件锁用于同一Unix主机的协作进程；fsync不保证磁盘损坏或恶意文件篡改后的恢复。
`freeze_signature`只是本地完整性hash，不是身份签名/可信时间戳，也不认证完整事前登记。
inspect不锁定跨进程一致快照，执行前仍会加锁复核；读到部分/损坏文件应停止并核查。

session 本身不带默认真实模型客户端、账单硬限额、调度器或第二交易总账。显式诊断脚本现已
使用 `decision_desk_process` 实现本地时间/字节/进程组和 macOS 文件保护，不能保证远端取消。
外部 provider 仍须验证实际身份/已计费用量、工具/记忆权限与跨账户隔离；默认链与原轨迹不接线。
真实治疗臂尚未启动，完整runner与收益认证仍受数据、价格、隔离及预算/窗口启动门约束。

### 5.4 已保存质量窗口的只读汇总

日采集后可复用 `backend.evidence.decision_desk_readiness` 汇总整个预定窗口。
显式 schedule JSON 必须包含 `timezone`、`contract_start` 和按日期排序、每天唯一且带时区的
`scheduled_at` 数组，例如：

```json
{"timezone":"Asia/Singapore","contract_start":"2026-09-16","scheduled_at":["2026-09-16T23:30:00+08:00","2026-09-17T23:30:00+08:00"]}
```

按已批准安排传入完整日期集合；此文件是调用方声明，工具不认证交易日历或事前冻结。
不重写原实验协议，不能删除失败日期来缩小分母。

```bash
python -m backend.evidence.decision_desk_readiness --runs-root "$SAVED_RUNS" --schedule "$WINDOW_SCHEDULE"
```

只向 stdout 输出 JSON，派生报告保存在仓库外。可传带时区的 `--evaluated-at` 复现某个
检查时点；默认当前 UTC。尚未到期的目录不读；到期无目录为 missing，已有但不完整/损坏
为 failed，合法证据未过运行/产出门为 blocked。分门通过率以全部到期日为分母，零到期为
null，任何未到期日都阻止整个窗口宣布完成。退出 0 只表示完整窗口的运行/产出合同检查
通过；pending/blocked 返回 1，调用参数错误返回 2，数据/经济门必须分别查看。

每个 collection 核对 manifest 与 continuity/panel/nav/readiness/snapshot 五份文件，
拒绝符号链接、snapshot sidecar、错日、重复当天记录、非当日采集与检查过程中变化。
报告列出已核对文件的 hash；不核对模型请求/响应等其他文件，也不证明文件作者、底层
来源正确、用户实际完成或收益。人工完成和模型质量明确为 not_evaluated。
此入口不读生产 DB、不调用模型、不补跑，也不影响原单日分类或已有五日日程。

## 6. 加一个量化模块

1. 写清假设和失败条件。
2. 先跑只读验证。
3. 报告 IC、ICIR、DSR/PBO、样本窗口和口径。
4. 输出 shadow evidence。
5. 不改 `weight_quant`。
6. 不改 production profile。
7. 不改 test2 baseline。

量化模块的默认身份是“证据生产者”，不是“自动荐股者”。

## 7. 加一个数据源

1. 放在 `backend/data/`。
2. 标明 market、coverage、freshness、adjustment、rate limit。
3. 接入 provider registry 或 explicit route。
4. 对可选外部源做 health/probe。
5. 默认不要悄悄进入正式信号。

### 7.1 决策资料的读取与展示

- 财报期末、披露、抓取、版本和生成时间分开；历史原值与衍生指标使用同一as_of。
  披露未知不凭期末自动认定可见，事后修订不倒灌，比较期/口径不可比须明确缺口。
- 未知、不适用与真实负面分开。总分、有效分母、覆盖率和available互相解释；不填零制造完整。
- 标签同时检查日期、有效期和质量；未来/过期记录只能作为有标注的历史参考。
- 文本预算先保留时点、风险和缺口；报告省略内容。预算小到装不下必需信息时明确不可判断。
- 严格候选显式接收数据库/时点；不得默认读生产SessionLocal、联网回填或写研究状态。
- 覆盖检查按当时官方池与持仓并集，不硬编码历史25/27数量；生产回填单独评估影响、备份和回滚。

## 8. 加文档

文档分工：

| 文档 | 职责 |
|---|---|
| `docs_public/index.md` | 文档站首页和导航。 |
| `docs_public/USER_GUIDE.md` | 使用路径和 demo walkthrough。 |
| `docs_public/FEATURE_MAP.md` | 所有功能逐项说明。 |
| `docs_public/DEVELOPER_GUIDE.md` | 后续开发规则。 |
| `docs_public/REFERENCE.md` | CLI/API/config reference。 |
| `docs_public/ARCHITECTURE.md` | L0-L4 架构。 |

## 9. 验证

最完整：

```bash
make verify
```

文档-only 最低检查：

```bash
git diff --check
make doc-check
```

涉及前端体验时，还要启动本地服务并看 demo 页面。

### 9.1 每个行为微批的收活格式

按以下五项交付，证据放仓库外，当前状态只回写对应权威文档：

1. **事实复核**：基准、问题反例、owner、唯一消费者；已修或前提变更先核验再调整。
2. **最小改动**：文件、默认行为不变量、候选预期差异和回滚方法；不混结构与策略。
3. **测试证据**：修复前失败/修复后通过、正常对照、聚焦检查；适用完整门在收口执行，skip逐项解释。
4. **产物核验**：实际表/JSON字段、hash、账户守恒；旧/新冻结输入比较，默认输出和写路径不得漂移。
5. **未决与权限**：分别写实现、测试、合入、启用、运行和经济证据，缺哪一门就保留哪一门。

隔离worktree只解决源码冲突；DB/cache/memory/log/artifact/子进程还需独立路径与写保护。
不得用正式日跑验证候选或重复成功日，不重置起算日，不为消除失败而改生产数据。
