# User Guide

这份指南回答“我怎么用明仓完成研究任务”。如果你想查所有功能的逐项说明，去看 [Feature Map](FEATURE_MAP.md)。

## 1. 适合谁读

| 你是谁 | 建议阅读路径 |
|---|---|
| 第一次体验 | 读“最快上手”，跑 `make demo`。 |
| 普通研究用户 | 读“研究工作流”。 |
| 想知道所有能力 | 跳到 [Feature Map](FEATURE_MAP.md)。 |
| 想开发功能 | 读 [Developer Guide](DEVELOPER_GUIDE.md)。 |
| 想查命令/API | 读 [Reference](REFERENCE.md)。 |

## 2. 最快上手

### 2.1 只体验 demo

```bash
make demo
```

启动后打开：

```text
http://127.0.0.1:5173
```

demo 会准备：

- 示例自选：贵州茅台 / 中际旭创 / 中国平安。
- 示例价格、沪深300指数和最新信号，所以首页不是空数据库。
- 示例持仓：中际旭创 100 股，用来展示市值、浮盈亏、止损止盈。
- 示例长期论题：中际旭创。
- 示例复盘。
- 示例待确认记忆候选。

demo 的意义是让你看到明仓的研究闭环，不是真实投资建议。

你应该看到类似结果：

```text
脉冲页：3 只示例股票，最新信号日期 2026-06-03。
信号横条：中际旭创 / 贵州茅台 / 中国平安都有示例建议。
持仓情况：中际旭创示例持仓显示市值、浮盈亏和风险线。
大盘情况：沪深300示例收盘点位和涨跌幅。
```

### 2.2 15 分钟 walkthrough

1. 打开首页：先看“今日焦点”和“信号横条”，确认最新信号日期、综合分、止损/止盈都能读懂。
2. 点击“中际旭创”：在单股详情里看官方信号、价格图、证据链、数据覆盖和 research copilot 区块。
3. 打开“复盘”：查看 demo 复盘，注意它如何把结论、归因和候选记忆分开。
4. 打开“持仓”：确认示例持仓的数量、成本、最新价、浮盈亏和 closed/open 状态。
5. 回到文档：用 [Feature Map](FEATURE_MAP.md) 查每个功能会不会写 DB、会不会影响正式信号、需不需要 key。

### 2.3 安装后使用

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
mingcang
```

常用命令：

```bash
mingcang help
mingcang doctor
mingcang stock 300308
mingcang project
mingcang memory
mingcang premarket
mingcang postmarket
```

### 2.4 判断是否正常

```bash
mingcang doctor
```

成功时你应该能看到：

- DB 可读。
- project root 正确。
- agent mode 正确。
- watchlist、positions、memory 摘要可返回。

## 3. 研究工作流

### 3.1 研究一只股票

适合问题：

- “300308 当前怎么看？”
- “这只票有什么风险？”
- “官方信号和 AI 研究意见冲突吗？”

命令：

```bash
mingcang stock 300308
```

你会看到：

- 股票基本信息。
- 最新官方信号。
- 价格和历史信号摘要。
- 新闻和情绪。
- 长期标签。
- research copilot 影子结论。
- 股票记忆和 L0 上下文。

判断方式：

- 官方信号是规则结果。
- copilot 是研究影子意见，不能覆盖官方信号。
- 记忆用于补上下文，但可信度要看状态。

下一步：

- 加入自选。
- 跑 deep research。
- 建立 ForwardThesis。
- 复盘后升级记忆。

### 3.2 管理自选和候选池

前端：打开“脉冲”页。

CLI dry-run：

```bash
python3 -m backend.agent.cli action watchlist.add \
  --payload-json '{"symbol":"300308","name":"中际旭创","market":"CN"}' \
  --pretty
```

确认执行：

```bash
python3 -m backend.agent.cli action watchlist.add \
  --payload-json '{"symbol":"300308","name":"中际旭创","market":"CN"}' \
  --confirm --pretty
```

边界：

- 添加自选会写本地 DB。
- 不会自动买入。
- 不改变信号权重。

### 3.3 每日扫描

明仓把日常节奏分成四段：

```bash
mingcang premarket
mingcang intraday --symbol 300308
mingcang postmarket
mingcang weekend
```

| 阶段 | 主要用途 | 默认边界 |
|---|---|---|
| 盘前 | 数据覆盖、新闻、指数、关注标的准备 | 默认 dry-run 合同。 |
| 盘中 | 只读本地缓存，快速看单股和止损 | 不默认触发远端网络。 |
| 盘后 | 全市场信号、复盘、报告导出 | 重任务需确认。 |
| 周末 | 长期标签、慢变量和周度复盘 | 重任务需确认。 |

### 3.4 做专题 / 公司深度研究

例子：研究“AI 光模块景气链”。

dry-run：

```bash
python3 -m backend.agent.cli action research.deep.run \
  --payload-json '{"topic":"AI 光模块景气链","symbols":["300308"],"seed_queries":["AI 光模块 800G 1.6T 需求"]}' \
  --pretty
```

确认执行才加：

```bash
--confirm
```

Deep Research 会做：

- 整理本地行情、新闻、财务和已有研究。
- 调用配置好的搜索或 LLM provider。
- 形成 research state / dossier / evidence。
- 不直接改变官方信号。

### 3.5 建立长期论题

长期论题适合这些问题：

- “这个行业的慢变量是否变化？”
- “外部研究员的判断怎样跟踪？”
- “什么时候说明这个逻辑失效？”

明仓用 `ForwardThesis` 记录：

- 论题陈述。
- 来源和 as_of。
- 失效条件。
- 跟进指标。
- 复盘节奏。
- 当前状态。

长期论题是研究态，不是买入信号。

### 3.6 复盘和记忆

打开前端“复盘”页，或用 action：

```bash
python3 -m backend.agent.cli action review.daily.ensure \
  --payload-json '{}' --pretty
```

记忆查看：

```bash
mingcang memory
python3 -m backend.agent.cli memory-context --symbol 300308 --query "光模块风险" --pretty
```

写记忆时先 dry-run：

```bash
python3 -m backend.agent.cli action memory.write \
  --payload-json '{"key":"risk_rule.optical_module","value":"光模块高景气标的要特别关注订单兑现和估值消化。","category":"risk","scope":"global"}' \
  --pretty
```

记忆规则：

- LLM 输出默认 pending。
- 复盘归因后产生候选。
- 人工确认后才升级可信记忆。

### 3.7 管理持仓和风险

前端：打开“持仓”页。

CLI dry-run：

```bash
python3 -m backend.agent.cli action position.add \
  --payload-json '{"symbol":"300308","name":"中际旭创","market":"CN","quantity":100,"avg_cost":120.5}' \
  --pretty
```

边界：

- 持仓只是记录和分析。
- 不连接券商。
- 不自动交易。
- 止损/止盈来自 ATR 公式，不是 AI 预测。

## 4. 前端怎么用

| 页面 | 用途 | 优先看什么 |
|---|---|---|
| 脉冲 | 自选、搜索、候选池、最新状态 | 今天要研究哪只票。 |
| 单股详情 | 单票完整研究视图 | 官方信号、新闻、证据、copilot、记忆。 |
| 复盘 | 每日和长期复盘 | 结论是否兑现，是否产生记忆候选。 |
| 持仓 | 记录持仓和风险 | 市值、成本、浮盈亏、止损止盈。 |
| 聊天 | AI 项目助手 | 问项目、生成候选动作、确认执行。 |
| 配置 | 系统参数 | 权重、阈值、LLM、数据覆盖、kill switch。 |

## 5. 什么时候不要继续加功能

如果以下基础没有跑通，先别加复杂功能：

- `make demo` 不能展示前端。
- `mingcang doctor` 不通过。
- 单股详情没有数据。
- README 没有清楚告诉用户下一步。
- 功能状态没有写清楚默认启用/只读/休眠。

明仓功能已经很多，下一阶段重点不是堆功能，而是让用户看懂这些功能。

## 6. 下一步

- 查全部功能：[Feature Map](FEATURE_MAP.md)
- 查命令/API/配置：[Reference](REFERENCE.md)
- 查如何开发：[Developer Guide](DEVELOPER_GUIDE.md)
- 查架构：[Architecture](ARCHITECTURE.md)
