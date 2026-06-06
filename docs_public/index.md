# MingCang

明仓是一个本地优先的股票研究工作台。它把自选、行情、新闻、官方信号、AI 研究、长期论题、复盘和记忆放进同一个可审计流程。

[Get Started →](USER_GUIDE.md){ .md-button .md-button--primary }
[Feature Map](FEATURE_MAP.md){ .md-button }
[View on GitHub](https://github.com/Zeeechenn/MingCang){ .md-button }

## Install

### 体验 demo

```bash
make demo
```

启动后打开：

```text
http://127.0.0.1:5173
```

### 安装命令行

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
mingcang
```

最快路径：

```bash
mingcang doctor
mingcang stock 300308
mingcang project
```

## What is MingCang?

明仓不是 AI 荐股器，也不是自动交易系统。它不接券商，不自动下单，不让 LLM 替你买卖。

它更像一个研究操作台：把每只股票的价格、新闻、官方信号、长期论题、AI 研究、复盘记录和记忆上下文放在一起，让你能看清一次判断来自哪里、哪些内容只是影子研究、哪些动作会写入本地状态。

## Quick Links

- [Getting Started](USER_GUIDE.md)：跑 demo、研究第一只股票、建立每日使用节奏。
- [Feature Map](FEATURE_MAP.md)：查看全部功能、入口、状态、写入边界、信号影响和 key 要求。
- [Safety Boundary](WHY_NOT_AI_STOCK_PICKER.md)：理解明仓为什么不做自动荐股和自动交易。
- [Architecture](ARCHITECTURE.md)：了解研究闭环、证据对象、复盘和记忆促进模型。
- [Reference](REFERENCE.md)：查前端页面、后端 API、CLI、action registry 和配置项。
- [Developer Guide](DEVELOPER_GUIDE.md)：后续开发和扩展功能时阅读。

## Key Features

- 单股研究：聚合官方信号、新闻、长期标签、research copilot 和记忆上下文。
- 每日扫描：按盘前、盘中、盘后、周末组织研究节奏。
- LLM 研究：用于资料整理、反方质询、风险提示和候选动作生成，不覆盖官方信号。
- 长期论题：记录外部判断、失效条件、跟踪指标和复盘节奏。
- 复盘记忆：通过 ReviewCase 归因，再由人工确认升级可信记忆。
- 风控纪律：ATR、trailing stop、仓位上限、组合暴露和 kill switch。
- 数据系统：行情、新闻、财务、QFII、provider 健康和只读 global data。
- 量化验证：Qlib、Kronos、回测和 shadow evidence；当前不进正式信号。

## Core Boundaries

| Boundary | Behavior |
|---|---|
| 官方信号 | 规则系统输出，当前主要由技术、情绪和风控组成。 |
| LLM 研究 | 负责整理、反问、辩论和风险提示；默认不覆盖官方信号。 |
| 量化系统 | 当前是验证和影子证据路径，不进正式信号。 |
| 写入动作 | 自选、持仓、配置、记忆等高风险动作必须显式确认。 |
| 交易执行 | 不接券商，不自动下单。 |
