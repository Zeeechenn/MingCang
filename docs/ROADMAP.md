# 明仓 / MingCang — 路线图（进行中与待做）

> 2026-07-03 全面重写；2026-07-15 状态刷新。方向裁决：**放弃"把所有信号融合成一个综合大分"的路线**，
> 转向**功能位分工**（选股 / 止跌避雷 / 止盈 / 浮动止盈各用各的公式）+ **模块化**
> （各模块独立演进、可单独更新或接入）。已完成/已证伪/挂起的里程碑压缩为文末
> 归档索引一行一条，详情走 `CHANGELOG.md` 与 `docs/dev/`。

## 北极星

- 目标：真实帮助 owner 实盘炒股、尽可能提高收益；回撤容忍约 20%。
- 最终产出物：**每日盘后操作面板**（买入候选 + 持仓体检 + 避雷警示 + 复盘归因），所有模块的输出向它汇聚。
- 分工哲学：确定性规则做打分与风控底线；**LLM 做裁量**（候选内选股、清仓决断、加减仓时机、复盘提炼——test2 治疗臂已验证的四个价值点），不做机械打分。
- 基准纪律（全局强制）：任何回测/回放报告必须带**同池等权持有基线**与**最大单票贡献占比**（防止把分化市运气读成能力；test2 治疗臂 alpha 主要来自单票天孚 +43%）。

## 当前接手入口（2026-07-15 刷新）

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| **M58 出场影子臂** | 价格系**选股位已终局证伪**（全量 695 支×966 日网格，DSR=0.0，详见 CHANGELOG/LEADER 档案）；仅剩**出场通道影子臂在跑**（4-6 周，2026-07 起） | 影子臂到期后按预注册裁决出场参数 | 单窗口/单 regime 不定稿；试验记账；生产切换需用户确认 |
| M54 新闻层 v2 | 纯新闻腿弱（ICIR 0.167）、公告增强=时段效应、**flow 融合无稳定增量（07-06 全覆盖回放）**——三变体均不判 GO；现役=**前向攒 IC 天**（pyramid 默认，flow 腿自动带上） | 每日盘后自动采集；IC 天≥20 + 跨 regime 后复判 | 裁决前不改权重不接 live；legacy 生产链零接触 |
| M59 盘后操作面板 | 四硬规则+条件卡+风险预算+准备度分+反方审视全接线；**裁量层灰度已开**（07-05 判断门盲裁 B9:A0 后 owner 拍板） | 观察灰度首批实盘卡（质量/截断率/额度），攒判断门二轮素材 | 不自动下单；建议带理由与风险；buy/watch 措辞红线 |
| M60 观察哨 | 触发源全家桶在役（R6 价格/lhb/flow/论点验证/证伪）；2b 第二时间入场影子台账攒样本中 | 2b 样本≥20 后裁决时机规则；触发源按周末体检漏网持续进化 | observe-only；样本不足不下结论 |
| M63 日常编排 | **运转中**：六命令面（盘前/盘中/盘后/周末/研究/喂观点），LLM 只烧盘后 | 按日常跑；周末体检漏网喂触发器进化 | 语言守卫禁买卖词；关注面=test2∪标的1∪持仓非全库 |
| M64 Live Track 安全收口 | **代码完成，未启用**：公开编排与私人台账/池/日志物理分界；子集生成 fail-closed | 以脱敏 schema 建本地 state，首日只做只读 dry-run 与人工验产物 | 不接券商、不自动下单、不写 DB；任一硬门失败不产子集 |
| **M66 仓库结构治理** | **首批落地**：稳定 core 已无静态 `backend.tools` 反向依赖；相关测试按领域归位；前端 API/live 已收进 services；旧入口保留兼容 | 继续把 workflow 内部工具调用迁到稳定门面，并分批降低根层测试与平铺页面数量 | 每批不改业务逻辑、信号/风控、DB schema、Provider 语义、scheduler/API 合同；每批独立可回滚 |
| 量化 v2（M61 §7.5 遗留） | **首轮实跑未过门**（07-06：IC 0.0215/ICIR 0.098 vs 门 0.04/0.40，样本达标） | 资金流历史攒长（滴灌+新浪兜底已在役）后可复跑，工具 `m61_quant_walkforward` | 预注册纪律：不得读作恢复 weight_quant 的证据；过门+全门槛+用户确认才谈晋升 |

## M66 仓库结构治理

目标是让目录重新表达业务职责，同时保持现有模块化单体、运行入口和发布合同不变；不借结构治理
重写业务逻辑，也不把项目拆成微服务或复杂 monorepo。

### 放置规则

1. 正式逻辑按领域归入 `data / analysis / backtest / evidence / research / memory / decision / portfolio`；
   M 编号只保留在路线图、变更史、schema/version 和旧命令兼容入口中。
2. `backend.tools` 只保留 CLI/维护/评估适配器；业务模块不得反向依赖工具实现。
3. 日常编排归工作流层；API、scheduler 和 agent 只依赖稳定门面，不直接复用工具私有函数。
4. 测试随被迁移模块一起移动，最终按领域区分 unit / contract / integration；不做一次性 195 文件搬家。
5. 前端后续按 app / features / services / ui / fixtures / styles 收敛；单独批次只改结构，不改 UX/API。
6. `docs_public` 继续作为站点源，`docs` 保持维护者资料；同名页面必须明确唯一权威来源。

### 执行阶段

- [x] **Phase 0 基线与冲突隔离**：确认当前 WIP 已收口、工作树干净、CodeGraph 可用；记录正式模块
  反向依赖 `backend.tools` 的边和 668 文件基线。
- [x] **Phase 1a 稳定 core 依赖倒置**：资金流/Tavily、lookahead 审计、IC 统计、量化基线、研究
  reference/watchtower path 与 M63 编排门面已有领域归属；架构守卫禁止 core 新增静态
  `backend.tools` 依赖，旧模块继续作为兼容别名或 CLI。
- [ ] **Phase 1b workflow 适配器收口**：`backend.workflows.m63_daily` 内仍有面向维护工具的动态调用；
  只在对应能力具备稳定领域门面时逐项迁移，不为清零而复制逻辑。
- [x] **Phase 2a 关联测试归位**：首批 8 个根层测试迁入 architecture/backtest/data/evidence/workflows，
  pytest 契约和旧入口兼容测试保留。
- [ ] **Phase 2b 根层测试分批下降**：当前仍有 190 个根层测试；后续只随所属模块变更搬迁，避免
  一次性重排造成审查噪音。
- [x] **Phase 3a 前端 services 边界**：API 与 live runtime 迁入 `frontend/src/services/`，生产代码改用
  canonical import，旧 `src/api.ts`/`src/live.ts` 保留 re-export 兼容并有测试守卫。
- [ ] **Phase 3b 前端功能聚合**：后续再拆 app shell、shared UI 与 reports/stock 等大功能；每批以
  TypeScript/Vitest/ESLint/build 和真实浏览器流程为硬门。
- [ ] **Phase 4 data/docs 收口**：在稳定门面保护下细分 market/news/fundamentals/storage/provider；
  同步清理文档双源和本地运行产物位置。该阶段涉及 Provider/DB/cache/PIT，必须单独评审。

### 每批验收

- 旧 CLI/import 入口至少保留一个版本周期；迁移表记录 canonical path 与 compatibility path。
- 不改变 signals、positions、止盈止损、production weights、scheduler 时序、API schema 或数据库。
- 聚焦测试、架构边界测试和 `make verify` 全绿；CodeGraph 无新增循环或意外反向依赖。
- 每批独立提交、可独立回滚；不混入 runtime DB、日志、模型、个人台账或生成报告。

## 触发待命（不占活跃执行队列）

| 工作线 | 已完成裁决 | 重新立项条件 |
|---|---|---|
| M57 记忆系统自进化 | Phase 1-3 已落地；真实 trace/miner/治理演练完成，自动 trusted=0；本轮 Memory 价值因 reference-set 偏差无法精确归因 | 冻结可核验记忆附录、重新预注册并保留 human promotion gate |
| M65 研究可信度 | Phase 0-2 完成并裁决 `HOLD_STOP_PHASE_3_4`；通用 Evidence Card/结构化 Gate 保留，Serenity 主效应总体为负 | 先补适用性门、逐 claim 证据绑定和公平评审基线，再预注册 v1.1；不得事后改判本轮 |

## 归档索引（一行一条，详情不再占活跃表）

- **M65 研究可信度收口**：2026-07-15 Phase 0-2 完成，20 例×四臂/20 次单盲评分裁决 HOLD；Both 四项质量均下降且幻觉率恶化，Phase 3-4 停止；Evidence Card 与结构化 ResearchReportGate 保留。完整结果见 `CHANGELOG.md` Unreleased。
- **M57 本轮自进化闭环**：2026-07-15 完成真实 research trace、过滤 miner 与治理台归档演练；候选保持 pending/archived，自动 trusted=0。后续仅按上方触发条件复测。
- **M64 代码交付**：安全漏斗已随 v0.6.2 完成并归档；活跃表只保留尚未执行的本地 state/dry-run 人工启用门。
- **M61 数据基建统筹改造**：2026-07-06 收官——手册库/发牌表/七簇品类/消费端接线/判断门盲裁（B2:A2，数据面 PASS）全落地；价格层清零（300759 含首窗）；fund_flows 经新浪兜底 provider 破局（84 支~1 万行）。计划全文 `docs/dev/M61_DATA_FOUNDATION_PLAN.md`。
- **M62 GitHub 大版本发布**：v0.6.0→v0.6.1 已发布（2026-07-05），公开 CI 四 job 全绿；发布门五项全过。
- **M63 复盘编排**：已交付并转日常运行（见上表活跃行）。
- **操作闭环一、二期**：论点合流/演练场/触发器/条件卡/风险预算/准备度分/反方审视/交易台账/分散模式全落地（2026-07-05）。

- **M44 / ATLAS**：2026-07-03 终局 **REJECT**——Gate-B 全量历史回填（1108 realized）判定 REJECT（delta -0.59pp）；门判据放宽变体 v2a-d 全部更差（-2.3~-2.7pp，标签层反向）；Stage 2b 组合回放 overlay 8.0% vs 基线 27.95%（吞吐塌缩）。**结论：研究工件折进短线过滤器整条线证伪。** L0-L4 记忆、案例结构、复盘闭环、证据台账**保留为研究质量与记忆基础设施**（归 M57 使用，不参与打分）。Gate-B/Stage 2b 证据积累停线，观测库保留 `~/.stock-sage/gate_b.db`。历史详见 `docs/ATLAS_MERGE.md`。
- **M56 AI 产业预警雷达**：未立项撤销（2026-07-03，方向收敛，砍）。
- **M51 外部借鉴**：冲 star 战略滞后，随之挂起；已落地部分（D1 统计门合约、report-pack v1 adapter）保留使用。详案 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md`。
- **M29**：假设注册/前向证据机制（registry、readiness、ledger 工具链）**并入 M58** 作为基础设施，不再单列工作线。
- **M21.4**：裁决已执行（v2 出场参数不改），exit_sweep 大样本通道并入 M58 Phase 1。
- **M32 / M24.3 / M25 / M12 / M10.5 / M4 / M5**：触发待命项集体归档；若未来触发条件满足再按需复活。
- 更早里程碑（M0–M55、v0.x 发布史）：见 `CHANGELOG.md`。

## 纪律备忘（从证伪中花钱买来的）

1. 好公司 ≠ 好的短线买点：长期研究工件（标签/深研）不得折进短线信号（M44 教训）。
2. 单边行情里的动量神话不可信：任何组件必须跨 regime 验证（6 月动量 ICIR 2.59 幻觉教训）。
3. 降级必须显式：组件退化必须告警 + 溯源落库（quant placeholder 静默降级一个月教训）。
4. 小样本盈利先查集中度：先看剔除最强单票后还剩多少（test1 兆易、test2 天孚教训）。
5. 权重由 OOS 定，中途不手调（M54 纪律，推广到所有功能位）。
