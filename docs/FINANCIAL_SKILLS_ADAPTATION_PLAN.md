# 金融 Skills 能力适配执行计划

## 1. 总体判断

图片里的 10 个金融 skill 更像一套金融 Agent 能力架构，而不是必须新建的 10 个独立模块。StockSage 已经具备日常信号、数据、回测、风控、多 Agent、深度研究和推送基础，因此接入策略应该是：

1. 先把已有能力产品化和命名化。
2. 再补真实缺口。
3. 最后用安全审计统一约束所有金融输出。

这套计划不改变 StockSage 的核心边界：LLM 不预测价格、不自动交易；系统只提供辅助决策、证据链、风险提醒和复盘。

## 2. 能力映射

| Skill | StockSage 现有落点 | 适配结论 | 建议方向 |
|---|---|---|---|
| Policy-Monitor | `backend/data/news.py`、`backend/data/news_audit.py`、`backend/research/deep_research.py` | 部分适配 | 作为政策/行业专题研究入口，后置接入日常信号 |
| Stock-Analyst | `backend/analysis`、`backend/decision/aggregator.py`、`backend/agents` | 已高度适配 | 产品化为单股分析主入口 |
| Daily-Trade-Review | `backend/scheduler.py::job_postmarket`、`backend/decision/harness.py`、`Signal`/`DecisionRun` | 高优先级缺口 | 新增每日复盘报告 |
| Quant-KB | `PROJECT.md`、`docs/ROADMAP.md`、`backend/backtest`、策略代码 | 适合 | 建立策略/指标/模型知识库 |
| Stock-Watcher | `/watchlist`、`Stock`、`Signal`、`Bark`、止损检查 | 高优先级缺口 | 新增异动监控和条件提醒 |
| A-Shares-Data | `backend/data`、`FinancialMetric`、`MarketSnapshot`、`quality.py` | 已适配 | 补数据覆盖、披露日、板块和资金流质量 |
| Report-Extractor | `backend/research/deep_research.py` | 适合新增 | PDF/公告/财报提取后进入深度研究 |
| Risk-Alert-System | `backend/ops/kill_switch.py`、`backend/agents/risk_manager.py`、`job_stoploss_check` | 已适配但分散 | 汇总成统一风险中心 |
| Backtest-Engine | `backend/backtest`、walk-forward、threshold/exit sweep | 已适配 | 统一 CLI/API 和报告格式 |
| Skill-Vetter | 项目约束、来源审计、risk manager | 必须新增 | 所有 skill 输出前的安全审计 |

## 3. 目标架构

### 3.1 不新增独立大框架

不建议新建一个与现有 `backend/agents` 平行的大型 skill 系统。更稳的方式是新增一层很薄的能力注册/编排层，例如：

```text
backend/skills/
  registry.py              # skill 名称、输入输出 schema、权限边界
  vetter.py                # Skill-Vetter 安全审计
  daily_review.py          # Daily-Trade-Review façade
  watcher.py               # Stock-Watcher façade
  reports.py               # Report-Extractor façade
  quant_kb.py              # Quant-KB façade
```

这些文件只做组织和产品化，核心计算继续调用现有模块。

### 3.2 统一输出协议

每个 skill 输出都应包含：

- `skill_name`
- `as_of`
- `scope`
- `inputs`
- `evidence`
- `result`
- `risk_flags`
- `confidence`
- `allowed_actions`
- `blocked_actions`

这样前端、API、日志和审计都能消费同一种结构。

## 4. 分期计划

### Phase 0：Skill-Vetter 与输出协议

目标：先把边界立住，后面所有能力都套进来。

工作项：

- 新增 `backend/skills/vetter.py`。
- 定义禁止项：自动下单、直接预测未来价格、无证据推荐、绕过止损规则、泄露 API key/本地敏感路径。
- 定义降级项：新闻源不足、财报覆盖不足、数据过期、回测样本不足、LLM 仲裁失败。
- 给现有深度研究和日常信号输出增加 vetter 检查点。

验收：

- 能对一个模拟输出返回 pass/warn/block。
- 测试覆盖自动交易、无证据结论、价格预测三类阻断。

### Phase 1：Daily-Trade-Review

目标：把现有盘后任务沉淀成可读、可回放、可比较的每日复盘。

复用：

- `Signal`
- `DecisionRun`
- `ResearchState`
- `review_latest_signal`
- `paper_trading/test*.md`
- `docs/research`

工作项：

- 新增 `backend/skills/daily_review.py`。
- 汇总当日信号、分数拆解、推荐变化、新闻审计、风险提示、持仓/纸上交易状态。
- 生成 Markdown 报告到 `docs/reviews/YYYY-MM-DD.md`。
- 增加 API：`POST /api/reviews/daily/run` 和 `GET /api/reviews/daily/latest`。

验收：

- 无 LLM key 时也能输出确定性报告。
- 报告包含“新增信号、退出/止损风险、数据覆盖、待验证问题”。

### Phase 2：Stock-Watcher

目标：从“只有止损提醒”升级到“自选股事件监控”。

复用：

- `Stock`
- `Price`
- `Signal`
- `NewsItem`
- `backend/notification/bark.py`
- `backend/scheduler.py`

工作项：

- 新增监控规则：单日涨跌幅、近 N 日突破、放量、接近止损/止盈、新闻异动。
- 新增 `watch_events` 表或先复用 `audit_log_fts` 记录事件。
- Bark 推送按严重度分级，避免噪声。
- 前端 watchlist 增加“事件/提醒”区域。

验收：

- 可在本地用固定价格样本触发每类事件。
- 同一事件有去重窗口，防止重复推送。

### Phase 3：Report-Extractor

目标：把 PDF 研报、公告、财报变成深度研究的结构化输入。

复用：

- `backend/research/deep_research.py`
- `backend/research/agents.py`
- `backend/data/news_audit.py`
- `backend/memory/research_memory.py`

工作项：

- 新增 `backend/skills/reports.py`。
- 支持 PDF/本地文件输入，抽取核心数据、观点、风险、来源页码。
- 输出结构化 JSON，再交给深度研究报告渲染。
- 报告只进入 research memory，不进入日常 `Signal`。

验收：

- 给定一个 PDF fixture，能提取标题、公司/行业、关键数字、观点、风险和页码证据。
- 明确标注“研究材料，不构成交易信号”。

### Phase 4：Risk-Alert-System 统一化

目标：把分散的风险逻辑合并成风险中心。

复用：

- `kill_switch.py`
- `risk_manager.py`
- `job_stoploss_check`
- `portfolio` 模块

工作项：

- 新增风险总览 API：组合回撤、连续亏损、止损触发、数据陈旧、新闻源风险。
- 前端 Admin/Watchlist 增加风险中心摘要。
- 每日复盘报告引用同一风险中心输出。

验收：

- 单一接口能返回系统级、组合级、个股级风险。
- kill switch 状态在报告和前端一致展示。

### Phase 5：Backtest-Engine 产品化

目标：把已有回测脚本统一成“策略验证面板”。

复用：

- `compare_paths.py`
- `sweep_threshold.py`
- `exit_sweep.py`
- `walk_forward.py`
- `alphalens_qlib.py`

工作项：

- 新增统一 CLI：`python -m backend.skills.backtest_engine --mode threshold|exit|walk-forward`。
- 输出统一 JSON/Markdown 报告。
- 前端只展示摘要，不在 UI 中跑重任务。

验收：

- 同一输入窗口可生成阈值、退出、walk-forward 三类报告。
- 报告包含样本数、交易数、胜率、Sharpe、最大回撤和是否建议上线。

### Phase 6：Quant-KB

目标：把项目策略知识从散落文档变成可检索知识库。

复用：

- `PROJECT.md`
- `STATUS.md`
- `docs/ROADMAP.md`
- `docs/M4*.md`
- `ai_memory`
- `audit_log_fts`

工作项：

- 抽取策略规则、指标解释、历史决策、回测结论。
- 提供按主题查询：ATR、RSRS、Qlib、阈值 25、trailing stop、M2 测试规则。
- 作为 Agent prompt 的引用上下文，不直接改变信号。

验收：

- 查询一个指标或历史决策，能返回来源文件和结论摘要。
- 不把不可信外部文本写入高权限计划文件。

### Phase 7：Policy-Monitor 后置接入

目标：政策监控先用于研究，不直接驱动交易。

工作项：

- 扩展新闻抓取：政策/监管/行业关键词。
- 先进入 deep research 或 daily review 的“政策观察”板块。
- 只有经过回测/纸上交易验证后，才考虑加入信号权重。

验收：

- 能按主题生成政策观察摘要。
- 不改变 `job_postmarket` 的综合分。

## 5. 推荐实施顺序

建议顺序：

1. Phase 0 Skill-Vetter
2. Phase 1 Daily-Trade-Review
3. Phase 2 Stock-Watcher
4. Phase 3 Report-Extractor
5. Phase 4 Risk-Alert-System
6. Phase 5 Backtest-Engine
7. Phase 6 Quant-KB
8. Phase 7 Policy-Monitor

原因：

- 前三项直接增强日常使用体验和安全性。
- Report-Extractor 能补研究资料质量，是中期增益。
- Risk/Backtest/KB 多数已有基础，适合在前面能力稳定后统一产品化。
- Policy-Monitor 噪声和误判风险更高，应后置。

## 6. 不建议做的事

- 不建议把 10 个 skill 全部做成独立 Agent 并并行调用。
- 不建议让 Policy-Monitor 或 Report-Extractor 直接修改交易分数。
- 不建议恢复 Qlib quant 权重，除非新增强因子后通过 walk-forward/holdout 验证。
- 不建议现在接自动交易；仍应等待 M2 纸上交易和独立验证通过。

## 7. 第一批落地切片

如果开始实现，第一批建议只做：

1. `backend/skills/vetter.py`
2. `backend/skills/daily_review.py`
3. `backend/skills/watcher.py`
4. 最小 API 和测试

这批完成后，StockSage 会从“有信号”升级到“有复盘、有提醒、有护栏”，是对当前项目整体收益最高的一步。
