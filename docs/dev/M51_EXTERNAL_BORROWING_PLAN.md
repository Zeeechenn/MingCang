# M51 外部金融开源项目借鉴优化方案（统一详案）

> 详案归 `docs/dev/`。里程碑级承重点见 `docs/ROADMAP.md` 的 M51 节。
> 全程 non-promoting：不改 official signal / 仓位 / scheduler / test2 / production weights。

初版：2026-06-13（FinGenius / FinRobot 系）
本次修订：2026-06-15 —— 纳入 QuantDinger、alpha101 评估，做全局而非单点重构。本版取代初版。

---

## 0. 全局结论（先行）

本次新评估了两个项目：

- **QuantDinger**（brokermr810/QuantDinger）：自托管量化交易基建，多 LLM 研究 → Python 策略 → 服务端回测 → 多券商执行（CCXT/IBKR/MT5/Alpaca），paper-only 默认 + Agent Gateway(MCP) + append-only 审计。币圈/美股/外汇，**不碰 A 股**。
- **alpha101**（yydhYYDH/alpha101）：WorldQuant 101 因子在币圈 Freqtrade 上的实现 + 遗传算法挖因子 + IC/Sharpe 评估。**不碰 A 股**。

把它们放进明仓全局后的结论与"再加几个模块"相反：

> **这两个新项目对明仓的净增量≈0。明仓已自建等价能力。真正的风险不是"少做了什么"，而是"照着抄会复制出一条与现有量化轨平行、互相打架的第二条轨"，把局部优化变成全局回归与无尽修 bug。**

证据（明仓已落地、可查的模块）：

| 外部卖点 | 明仓已有等价物 | 位置 |
|---|---|---|
| QuantDinger 服务端回测（equity/回撤/成本/组合约束） | backtrader_eval / walk_forward / portfolio_eval / costs / sweep_threshold / exit_sweep / compare_paths | `backend/backtest/` |
| QuantDinger 不可变审计 | append-only `audit_write` | `backend/memory/audit_log.py` |
| QuantDinger paper-only / 研究与实盘隔离 | `WEIGHT_QUANT=0.0`、`new_framework` 档、non-promoting、生产 diff=0 | `backend/config.py` |
| QuantDinger Agent Gateway + 作用域 | 研究 Agent 编排归口 ATLAS | `docs/ATLAS_MERGE.md` / `backend.tools.atlas_*` |
| alpha101 算子 + IC/分层评估 | Qlib `FEATURE_COLS` 流水线 + Alphalens IC/分层 | `backend/data/qlib_data.py`、`backend/backtest/alphalens_qlib.py` |
| alpha101/"统计门 + 预注册" | M29 假设注册表 ic_min/icir_min/require_monotonic/stride_icir | `backend/tools/m29_hypothesis_registry.py` |
| FinGPT 数据中心主义 | source_tier/fetched_at 贯穿 + M42 price quality guard + M12 治理门 | 见 §2.1 / §3 |

**指导原则（唯一一条）：所有借鉴一律 graft（嫁接）到现有模块，严禁新建平行轨。** 真正的 delta 极小（见 §4），都是"在既有门上加一项指标"或"补一段数据覆盖"。

---

## 1. 全局架构与归口表（防止"单点改完影响全局"的护栏）

明仓事实上有**四个关注域**，各有唯一 owner。任何外部借鉴必须先在此表找到归口，找不到归口就**不做**：

| 关注域 | 唯一 owner | 边界（管 / 不管） | 外部映射 |
|---|---|---|---|
| 研究报告 / 证据前台 / Agent 评测 | **M51**（本方案） | 管：单股报告包、Evidence Card、MingCang-GAIA。不管：信号、仓位、回测引擎 | FinGenius/FinRobot/FinGAIA |
| 量化回测 / 因子 / 统计门 | **M26/M27/M29 + `backend/backtest/`** | 管：因子、IC/ICIR、walk-forward、成本、组合约束、假设注册。不管：研究叙事、前端 | QuantDinger 回测、alpha101 因子 |
| 数据治理 / provider / PIT | **M12 external data governance** | 管：provider card、PIT、披露日、字段归一化、fallback。不管：策略逻辑 | FinGPT、alpha101 数据管线、QuantDinger 数据源 |
| 研究 Agent 编排 / scheduler | **ATLAS**（`ATLAS_ENABLED=false`，dormant） | 管：agent 注册、任务编排、调度。不管：进入生产信号 | QuantDinger Agent Gateway、FinRobot task manager |

**横切（四域共用一套，禁止每轨各搞一套）：** non-promoting 红线、append-only 审计、paper-only / 双解锁、source-tier 门。这些是**机制**，全局唯一实现。

---

## 2. 逐项目评估（含重复判定）

### 2.1 FinGenius / FinRobot / FinGPT / FinGAIA（研究轨，沿用初版结论）

借鉴"多角色研究分工 + 反方辩论 + 报告流水线 + 数据中心主义 + agent 评测"的组织思路，**不搬框架、不搬自动决策闭环**。明仓已有等价原语：M45 falsification scoreboard、M50 ResearchReportGate、`ai_supply_chain_template`/Serenity、`research_case`/`forward_thesis`、`deep_research` + source_tier/fetched_at。真实增量集中在 §4 的 Phase 1–3。

### 2.2 QuantDinger（量化基建轨）—— 重复，仅 2 个小点可 graft

- **架构思想值得确认（但明仓已做到）**：研究与实盘代码路径物理隔离、paper-only 默认、不可变审计、服务端回测带成本/组合约束。这是对明仓 non-promoting + `backend/backtest/` + `audit_log` 的外部背书，**不是新需求**。
- **可 graft 的两点**（见 §4 D3）：① agent-token 的"双解锁"实盘闸（默认拒实盘，需 `paper_only=false` + 服务端开关同时为真）固化成 token 级机制，归口 ATLAS / agent runtime；② 对照 QuantDinger 的 append-only 语义审查 `audit_write`，确认研究流程无法静默覆盖。
- **不可借**：CCXT/IBKR/MT5 执行层、`curl|bash` 安装、默认口令、币圈数据源。

### 2.3 alpha101（因子轨）—— 算子重复；Alpha101 是真实但很小的 delta

- **算子库 + IC/分层评估** → 重复（Qlib `FEATURE_COLS` + `alphalens_qlib.py` 已有），**不重写**。
- **已查实：明仓没有 Alpha101/Alpha158**（2026-06-15）。明仓用刻意精简的自建集——`PRODUCTION_FEATURE_COLS`(~24：动量/反转/波动/RSI·MACD·BB/ROE·yoy·毛利/市值/两融，带 PIT 意识，已剔除政策下架的北向/流通市值源) + `M27 ALPHA_FACTOR_COLS`(仅 4 个经典学术因子：12-1 动量、换手异常、量价背离、行业相对强度)。
- **处置要克制**：明仓哲学是"28 个精挑、可解释、PIT 干净"，Alpha101 是"101 个公式批量"。**绝不把 101 个塞进 `FEATURE_COLS`**——会炸开 trial 数、破坏 IC/ICIR 门纪律。正确用法：当**一次性外部基线电池（null-benchmark battery）**，整批跑一遍现有 `m29_hypothesis_registry`（trial-count 全程记账），只回答"明仓这 28 个因子相对公开因子全集强不强"，**不进生产特征、不长期维护**。
- **明确不做：遗传算法挖因子**（海量多重检验，作者自己 README 警告别实盘；会让统计门因 trial 失控而失效）。

---

## 3. 两条轨的边界（最容易出全局事故的地方）

- **M51（研究轨）永远不碰**回测引擎、因子、信号权重；只产可审计的研究报告与证据前台。
- **量化轨永远不碰**研究叙事前台；只产因子/统计证据，全部 non-promoting。
- **唯一交汇点**：量化轨的统计结论（IC/ICIR/回撤）可作为**证据条目**出现在 M51 报告的 Evidence Ledger，但**不得**接成信号或买卖建议。
- **数据只有一个治理层（M12）**：M51 的 source_tier、量化轨的披露日 PIT、未来 provider 全走 M12，禁止任一轨自建数据校验。
- **编排只有一个 owner（ATLAS）**：任何"多 agent 编排"想法归 ATLAS，不在 M51、不在量化轨内另起 scheduler。

---

## 4. 真正的 delta 清单（很短——这才是要做的事）

### 研究轨 delta（= M51 Phase 1–3）

- **Phase 1（P0）单股研究报告包 v1**：把已落地的 `deep_research` / `ResearchReportGate` / `falsification_scoreboard` / `ai_supply_chain` / `research_case` 封装成稳定报告包 schema（固定章节 + gate/source 元数据贯穿 + Markdown/HTML 导出）。工作是"封装与契约"，不重写分析器。章节：Executive Brief / Thesis·Anti-Thesis / Evidence Ledger / Financial·Industry·News·Technical Blocks / Risk Triggers / Peer·Supply Chain / Validation Questions / ReviewCase Hook。验收：同股报告结构稳定可横比；每个结论可追 source tier/freshness/evidence；无"强买/必涨/目标价确定性"语气；blocked 不落盘、warning 必显。
- **Phase 2（P1）前端 Evidence Card / Report Viewer**：M51 **最实打实的缺口**（后端纪律齐备但用户看不见）。交付 Evidence Card（source tier/freshness/coverage/warning）、Falsification Panel、Report Diff、带 gate metadata 的导出。边界：不把报告评级接官方信号、不把 source-tier 变加权因子。
- **Phase 3（P1）MingCang-GAIA 评测集**：净新建。首批 20–30 任务，覆盖财报核验/数据异常/新闻核验/技术·情绪冲突/产业链假设/风险纪律/ReviewCase 归因。评分维度：factual correctness、source fidelity、tool-use discipline、risk language、reproducibility、boundary compliance。先静态 fixtures + 本地 SQLite，CI 先 smoke、不作 release blocker；结果只作研发质量指标，绝不回流信号。

### 量化轨 delta（全部为"在现有模块上加一项"，不新建系统）

- **D1（P1）统计门补强**：在 `m29_hypothesis_registry` + `backend/backtest/statistics/` 现有 IC/ICIR/单调门之上，**加 Deflated Sharpe Ratio、PBO、显式 trial-count 记账**（对抗回测过拟合的标准武器）。必须落在既有门里，不另起评估器。
- **D2（P2）真实披露日 PIT**：明仓 schema 目前只有报告期、无真实披露日（CHANGELOG 已自列为 next step）。把 point-in-time join 从报告期切到披露日，**归口 M12**，回测层不私自修。
- **D3（P2）paper-only 双解锁 + 审计审查**：见 §2.2，graft 到 ATLAS / `audit_log`。
- **D4（P2，本质是数据覆盖里程碑而非引擎）规模化可信验证**：100–300 只 × 3–5 年。**引擎已具备**（walk_forward/costs/portfolio_eval），**真正瓶颈是数据覆盖**——当前 financial covered 10/70、news 24h 0/70。立为**数据覆盖补全里程碑**：先补披露日/资金流/市值/财报覆盖，再跑既有回测，**不新建"回测实验室"**。
- **明确不做**：alpha101 遗传挖矿、QuantDinger 执行层、任何新的并行回测/因子/审计/数据校验系统。

> 关键判断：曾提议的"M29.6 Historical Backtest Lab"**降级取消**——80% 已由 M26/M27/M29 + `backend/backtest/` 实现。剩余 20% 拆成 D1–D4 小 graft 分别归口现有 owner。**开新 lab = 制造平行轨 = 修 bug 黑洞。**

---

## 5. 全局风险与"防止陷入修 bug"的护栏

1. **平行轨风险（最高）**：照外部项目新建回测/因子/审计模块，与现有双轨并存 → 两套门、两套口径、互相覆盖。**护栏**：§1 归口表，新增一律 graft；任何 PR 若新建 `backtest_v2/`、`factors_v2/`、第二个 audit，直接拒。
2. **数据治理碎片化**：M51 source_tier、量化轨披露日、新 provider 各自校验 → 同一数据多套可信度口径。**护栏**：数据只走 M12（§3 已锁）。
3. **度量系统重复**：MingCang-GAIA（agent 推理评测）与量化统计门（因子稳健性）是**不同对象**，不合并，但共用同一"记分板/呈现"纪律，且都只作研发指标、不回流信号。
4. **边界一致性**：non-promoting/审计/paper-only 若每轨各实现一遍 → 总有一条漏掉红线。**护栏**：横切机制全局唯一（§1 末）。
5. **改动顺序纪律**：先做最小 graft（D1、Phase 1）并跑**全量回归**（`make verify`，当前基线 backend 1214 passed / 5 skipped），绿了再碰 D2/D4 这类涉及数据层的改动。**禁止在数据覆盖未补全前启动规模化回测**——否则跑出的曲线是数据缺口造成的伪信号，引发"改一处、坏一片"的连锁排查。

---

## 6. 不建议做的事

- 不做自动交易 Agent；不把"下周涨跌预测"作为主产品入口。
- 不把 FinGPT/FinRobot/QuantDinger/alpha101 的框架、执行层或遗传挖矿搬进明仓。
- 不新建任何平行的回测 / 因子 / 审计 / 数据校验系统。
- 不把多 Agent 结果或回测结果直接接入 official signal、test2、positions、scheduler、production weights。
- 不为漂亮报告或漂亮回测曲线牺牲 source tier、freshness、warning/blocker 的可见性。
- 不在数据覆盖补全前启动 100–300 只规模化验证。

---

## 7. 里程碑与排期

### M51 Research Report Pack / MingCang-GAIA Seed（研究轨，已启动）

范围仅 Phase 1–3，全程 non-promoting。
- 2026-07-02 当前：报告包 schema 的前端归一 adapter 已落地为 `research_report_pack.v1`，Reports 页可展示 pack 覆盖度并复制 Markdown；D1 统计门合约也已接入 M29 registry。下一步是把 Report Viewer / Evidence Card 做成更完整的前端体验，而不是重写 deep_research。
- 近期 1–2 周：深化 Report Viewer / Evidence Card + 报告头显式 gate/source/coverage warning；后端仍沿用 deep_research / ResearchReportGate / falsification / ai_supply_chain / research_case，不新建分析器。
- 中期 2–4 周：Report Viewer / Evidence Card 前端入口 + 首批 20–30 个 MingCang-GAIA fixtures + 本地/CI eval summary + Markdown/HTML 导出。
- 后续 1–2 月：扩到 50 任务 + report diff + ReviewCase 回填闭环。

### 量化轨：不新建里程碑，作为 M29 续作的小 graft
- D1（统计门补强）已先行插入 M29 registry 合约：每个候选必须报告 Deflated Sharpe / PBO / trial-count，复用既有 `backend/backtest/statistics/`，不改算法、不恢复 quant。
- D2 / D4 合并为**数据覆盖补全里程碑**（归口 M12），P2，触发条件驱动；启动前必须先补披露日/资金流/财报覆盖。
- D3 归口 ATLAS，随 ATLAS 推进。

### 编排轨：研究 Agent Registry / Scheduler 全归口 ATLAS，不在 M51、不在量化轨内展开。

---

## 8. 停止条件 / 成功标准

**停止条件（任一触发即停）：**
- 任何改动会影响 official signal、仓位、scheduler、test2、production weights。
- 任何报告把 blocked 输出落盘。
- 任何 eval 或回测结果被用于自动提升信号或可信记忆。
- 出现第二个回测 / 因子 / 审计 / 数据校验系统。
- 在数据覆盖未补全前启动规模化回测。

**成功标准：**
- 研究输出从"能回答"升级为"能审计、能复盘、能比较、能回归测试"。
- 外部项目的长处被**嫁接进既有模块**而非新增平行轨；全量回归（`make verify`）始终保持绿。
- 量化轨在既有门上多了 DSR/PBO/trial-count 的过拟合防线，但权重仍为 0、仍 non-promoting，直到历史稳健 + 前向 shadow 持续有效 + 人工确认三者同时满足。
