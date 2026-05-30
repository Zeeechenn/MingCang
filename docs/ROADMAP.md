# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情优先见 `CHANGELOG.md`。本文件只列当前未完成任务项（`[ ]`）、暂缓项和少量摘要指针。

---

## ⭐ M27 Alpha 根治工程【P0 当前最高优先】🔬

> 前置：M27.1 IC ≥ 0.04 → M27.2 扩池 → M27.3 / M27.4 并行。

### M27.1 经典因子工程（P1）

**目标**：IC ≥ 0.04 / ICIR ≥ 0.40 / 分层单调

- [ ] 新增因子（`backend/analysis/alpha_factors.py`）：反转动量（12-1）/ 换手率异常（z-score）/ 量价背离 / 板块相对强弱
- [ ] rolling z-score 标准化，防量级差异淹没小因子
- [ ] 重训 LightGBM，过 M20.2 promotion gate（`ic_floor=0.04` / `icir_floor=0.40` / `monotonic=True`）
- [ ] 用 M26.0 同标尺重跑 `python3 -m backend.tools.m26_quant_baseline`，对比前后

**验收**：新模型过 gate，baseline 报告 IC ≥ 0.04 且分位单调。

### M27.2 交易池扩容 25 → 100 支（P1，依赖 M27.1）

- [ ] 从 707 支中筛出 ~100 支（历史 ≥ 500 bar / 近 60 日均换手率 ≥ 0.5% / 板块均匀）
- [ ] 创建 `paper_trading/test3_universe.json`
- [ ] 适配信号 runner（参数化 `--universe`，控制单日 LLM 调用量）
- [ ] 更新 `m26_quant_baseline` 默认 universe 路径，重跑新基线

**验收**：≥ 90 支，baseline 基于 100 支截面。

### M27.3 情感信号事件化（P2，依赖 M27.2，与 M27.4 并行）

**目标**：事件标注后情感信号在 100 支 universe 上 IC ≥ 0.03

- [ ] 定义 A 股事件分类体系 8~12 类（`backend/analysis/event_taxonomy.py`）：大合同/监管批文/管理层增持/股权激励/指数纳入/实控人减持/监管处罚/业绩预警
- [ ] 升级情感 pipeline：在 Anspire/Tavily 新闻流上增加 LLM 事件抽取
- [ ] 新增 `event_score` 字段进入信号合成，有事件覆盖极性分，无事件退回极性
- [ ] A/B 验证：test3 universe 对比「纯极性」vs「极性+事件」IC

**验收**：分类体系落地，pipeline 可跑，IC 对比有明确结论。

### M27.4 Kronos 微调 Path A（P2，依赖 M27.1 + M27.2，与 M27.3 并行）

**目标**：微调后 Kronos IC ≥ M27.1 LightGBM 新基线

- [ ] 准备微调数据集（`backend/tools/m27_kronos_finetune_data.py`）：707 支 × 5 年 OHLCV，滑动窗口 `(context=400, pred_len=5)`；训练集 2020-01~2024-12，验证集 2025-01~2025-10
- [ ] 修改训练目标（`vendor/kronos/finetune/`）：加入 ListMLE 排序损失，`λ_rank=0.7` / `λ_recon=0.3`
- [ ] 微调 Kronos-small（`.venv_kronos/`，MPS 加速，模型存 `~/.stock-sage/models/kronos_finetuned/`）
- [ ] 用 M26.0 同标尺验证（`m26_kronos_eval.py --model kronos-finetuned`），与 LightGBM 同表对比

**决策门**：IC ≥ LightGBM 且分位单调 → 进 M26.3 重启；否则降级路径 B（特征融合）。

---

## M28 调研模块整合与实时搜索接入 🔲

> 背景：deep_research / copilot / 多轮辩论 三模块存在信息孤岛，辩论缺乏真实信息差，
> ResearchSection schema 为纯文本无结构。详细设计见 `docs/M28_RESEARCH_INTEGRATION_PLAN.md`。

### M28.1 ResearchSection IC Memo Schema 升级
**文件：** `backend/research/agents.py`
- [ ] 扩展 `ResearchSection` 增加结构化字段（全部有默认值）：`catalysts / risks / valuation_anchor / evidence_snippets / stance / confidence`
- [ ] 更新五个 builder 函数填充新字段
- [ ] 更新 `_render_report` 展示结构化字段

### M28.2 Tavily 实时 Web 搜索补全 evaluator/planner 循环
**文件：** `backend/research/deep_research.py`
- [ ] 新增 `_tavily_web_search(queries, ...)` — 纯内存路径，不写 DB，直调 Tavily REST API
- [ ] 在 `_execute_plan` 补全 `next_action == "web_search"` 分支（当前已声明但未实现）
- [ ] 报告中对 `source="tavily_web"` 条目展示来源 URL

### M28.3 辩论注入结构化信息差
**文件：** `backend/agents/researcher.py` / `backend/agents/pipeline.py`
- [ ] `multi_round_debate` 增加可选参数 `research_context: dict | None = None`（向后兼容）
- [ ] bull 轮 prompt 注入 `catalysts + 正面 evidence_snippets`；bear 轮注入 `risks + 负面证据`
- [ ] `pipeline.py`：若当日已有 deep_research 结果，自动提取并传入 `research_context`

### M28.4 建立 copilot → deep_research 信息流
**文件：** `backend/research/copilot.py` / `backend/research/deep_research.py` / `backend/research/dossier.py`
- [ ] `run_deep_research` 增加可选 `seed_queries: list[str] | None = None`；CLI 支持 `--seed-queries`
- [ ] `dossier.build_research_dossier` 新增 `pending_questions` 字段（从 copilot validation_questions 提取）

---

## M26 量化层重估 ⏳

M26.0 基线 ✅ / M26.1 扩盘 ✅ / M26.2 Kronos 零样本 ✅（IC=-0.0017，不替换）

### M26.3 小权重 Paper Trading 验证（暂停）

> **重启条件**：M27.1 因子工程使 IC ≥ 0.04 后重新评估。

- [ ] 在 `test2_ab_runner.py` 新增第三臂 `quant_small`（Q=0.15, T=0.55, S=0.30, threshold=25）
- [ ] 跑满 4 周，按测试 2 汇报约定只汇报总结
- [ ] 决策门：`quant_small` 收益持续跑赢 `quant_off` ≥ 2pp 且最大回撤不高 → 进入生产权重恢复讨论

---

## M24.3 长期约束重新接入验证 ⏳

- [ ] **shadow forward outcome 观察**（从 2026-05-27 起）：每天保留只读报告输出，跟踪 `blocked_entry / position_reduced / score_capped` 样本的 1d/3d/5d/10d 表现；口径优先用相对沪深 300 超额收益。只观察，不开启约束。
- [ ] **中期检查点（建议 2026-06-10）**：汇总首批 shadow 样本，判断长期标签是否降低假阳性；不足或不稳定则继续观察。
- [ ] 测试 2 冻结期结束后（≥ 2026-07-18），用重建后的可信标签回放历史信号，严格按 PIT 口径对比「无约束」vs「有约束」；禁止使用未来生成的标签回改过去交易。
- [ ] 只有约束降低假阳性且不显著误杀有效入场时，才将 `LONG_TERM_CONSTRAINTS_ENABLED=true` 纳入下一轮测试架构。

---

## M25 综合改进路线图（剩余项）⏳

已完成：M25.0–M25.4 主体 / M25.2 统计口径补债 / M25.3 LLM 成本可观测性 + 跨入口契约回归测试

**M25.4 剩余（低优先）**
- [ ] 自选股 200+ 卡顿后再上虚拟列表；当前保留本地搜索/筛选
- [ ] 移动端先保障 Watchlist / StockDetail / Chat 三条核心路径可用，不急于完整复刻

**M25.5 Qlib 灰度（阻塞于 M27）**
- [ ] 只有多个窗口稳定通过 promotion gate 后，才允许小权重灰度（`quant=0.1`）；需配 kill switch 与复盘闭环

**M25.6 社区与战略（P3）**
- [ ] README demo 截图/GIF / release notes / 真实 quickstart 验证路径 / 典型研究案例
- [ ] PostgreSQL / pgvector：SQLite 成为真实瓶颈后再启动
- [ ] HK/US 多市场：A 股主线验证稳定后再做
- [ ] Tauri / 桌面客户端：Web 控制台稳定后再评估
- [ ] WebSocket：止损预警优先复用 scheduler + Bark，有多用户实时需求再引入

---

## M21.4 ATR 窄止损统计分析（触发条件：2026-07-18 后）

- [ ] 在 test1 + test2 全部 `closed` 仓位上统计 `ATR / 买入价` 分布，重点看 ATR 占比 < 0.5% 样本是否系统性触发假止损；如有问题评估：① 加 ATR 下限 `max(ATR×2, 买入价×3%)`；② 改用 trailing ATR×2.5。先出统计报告，不直接改测试 1（规则已冻结）。

---

## M12 外部数据源扩展治理（剩余）⏳

- [ ] 对任何新端点先补 provider health / PIT 时间戳 / 字段归一化 / 测试，再考虑写入 SQLite

---

## M10.5 长期工程基础（后置 / P3）

- [ ] 数据库迁移体系：先保留 `create_all + runtime patch`，中期引入 Alembic baseline
- [ ] 只有多个验证窗口通过后才允许小权重灰度；默认生产继续 `weight_quant=0.0`

---

## M4 多 Agent 决策深化（暂缓项）🟡

- [ ] **M4.4 LangGraph 重构 pipeline**：触发条件：本地验证 ≥ 10 笔样本 + path B Sharpe ≥ path A + 0.3
- [ ] **M4.5 FinMem 完整替换 `decision_memory.py`**：触发条件：≥ 30 笔样本证明"记忆深度 → Sharpe 改善"

---

## M5 自动化执行 🔲（后置，最不关键）

QMT/miniQMT 券商对接；盘中实时止损；半自动→全自动渐进。
**门槛**：本地验证通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

---

## M2 本地验证材料 🏠

本地验证材料、个人记录和临时统计不进入 GitHub。

---

## 里程碑摘要（详情见 CHANGELOG / PROJECT）

| 里程碑 | 完成时间 | 简述 |
|---|---|---|
| M27.0–M27.4 | 进行中 | Alpha 根治工程，见本文件 M27 |
| M26.0 量化基线 | 2026-05-30 | IC=0.010，分位单调，`consider_small_weight_experiment` |
| M26.1 训练盘扩容 | 2026-05-30 | 707 支，IC=0.021，仅过 M26 诊断阈值，未过生产 promotion gate |
| M26.2 Kronos 评估 | 2026-05-30 | 零样本 IC=-0.0017，不替换 |
| M25 综合改进主体 | 2026-05-27 | LLM 成本可观测性 / Chat SSE / 跨入口契约回归 |
| M24.0–M24.2 长期标签隔离 | 2026-05-26 | 测试 1/2 冻结期隔离 + 质量门 |
| M23 信号证据链 + 回测口径 | 2026-05-25 | M17.1 / M18.1 / 前端 EvidenceCard |
| M22 持仓完整性与状态隔离 | 2026-05-24 | 持仓 schema 锁定 / agent action 对齐 |
| M21 基础设施评审修复 | 2026-05-23 | 远程写守卫 / model_tier 分层 / runtime-config 校验 |
| M20 量化与分析层评审修复 | 2026-05-23 | RSRS 共线修复 / 涨跌停阈值板块差异 |
| M19 数据层与 PIT 修复 | 2026-05-23 | PIT 用 disclosure_date / 复权口径统一 / Q1/Q3 披露日 |
| M18 回测统计口径修复 | 2026-05-23 | 滑点建模 / Sharpe 年化统一 / DSR trial 语义 |
| M17 决策链评审修复 | 2026-05-23 | regime 不覆盖风控否决 / 证据仓位归属 / 幂等写 |
| M16 全项目分层评审 | 2026-05-23 | 六层评审完成，缺陷转入 M17–M21 |
| M15 记忆系统与影子副驾驶修复 | 2026-05-23 | judgment 去重 / vetter 接线 / 召回副作用降级 |
| M14 股票长期记忆与跨入口召回 | 2026-05-23 | `stock_memory_items` + 统一召回 `build_memory_context` |
| M13 pi Shell + Agent Kernel | 2026-05-23 | `backend/agent/cli.py` / `.pi/` 本地配置 |
| M11 Agent-Ready 本地/远程接口 | 2026-05-21 | AGENTS.md / MCP 工具桥 / PortfolioManager 闭环 |
| M10 运行可靠性与产品化优化 | 2026-05-20 | 覆盖快照 / scheduler 状态 / Bark 重试 / 前端渐进加载 |
| M9 记忆系统接入与治理 | 2026-05-19 | 分层 DB / AdminPage 记忆管理 / 摘要器 / 过期清理 |
| M8 深度研究与来源审计层 | 2026-05-17 | deep_research.py / news_audit / research_memory |
| M6 量化与前端升级 | 2026-05-19 | M6.1 PIT 基本面因子 / M6.3 前端操作台 |
| M7 工程化与开源就绪 | 2026-05-16 | README / CI / Docker / pyproject / Makefile |
| M4 多 Agent（已完成部分） | 2026-05-16 | 多轮辩论 / Director / Portfolio Manager / M4.6–M4.9 |
| M3 可信度审计层 | 2026-05-15 | DSR / PBO / Walk-Forward / PIT 拦截 / Kill Switch |
| M1 严肃化与质量门槛 | 2026-05-15 | Backtrader / regime 过滤 / 长期分析师团 / 双 profile |
| M0 系统骨架 | — | 数据/技术/情感/量化/Web/复盘全链路打通 |

---

## 历史决策点（不再阻塞）

**Qlib 归零**（M1.1）：IC=0.0228，分层非单调 → 权重归零；M26/M27 正在从训练盘广度不足的根因重建。

**跨市场信号（已移除）**：美股 ETF 作为领先指标，全板块回测无显著改善，已移除。
