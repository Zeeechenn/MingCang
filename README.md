# StockSage

面向个人 A 股研究的 Agent-ready 决策工作台：把本地数据底座、多源行情/新闻、技术与情感分析、长期研究、组合风控和可审计记忆组织成一套可追溯的辅助决策系统。StockSage 只做研究、复盘和风险提示，不预测价格，不自动下单，最终决策始终由用户负责。

![Tests](https://img.shields.io/badge/tests-300%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[产品预览](#产品预览) · [Agent 使用指南](#agent-使用指南) · [主要能力](#主要能力) · [推荐使用方式](#推荐使用方式) · [无前端使用方式](#无前端使用方式) · [注意事项](#注意事项) · [更多文档](#更多文档)

[简体中文](README.md) | [English](README_EN.md)

---

## 中文版

### 项目概览

StockSage 是一个本地优先的个人 A 股研究系统，也是一个已经 agent 化的投资研究内核。它把行情、新闻、财务、QFII、指数、持仓、复盘和长期记忆写入本地 SQLite，再通过技术指标、LLM 新闻情感、长期分析师团、Research Director、Trader、Risk Manager 和 Portfolio Manager 形成可审计建议。

当前项目的重点不是“让 LLM 猜涨跌”，而是把数据、证据、风险和历史记忆放到同一个工作台里：每天盘前同步数据，盘后生成信号，盘中检查止损，周度更新长期标签；用户也可以显式触发单股研究、行业专题研究、纸上交易统计和项目记忆检索。

项目已完成 Agent-ready 本地/远程双模式接口。Codex / Claude Code 等本地 agent 可以读取项目上下文、查询记忆、跑测试、做复盘和调用 MCP 工具；远程 agent 默认只读，必须显式开启 API key、写权限和 action allowlist。后续产品方向会从当前 Web 控制台继续演进为更完整的客户端体验，让日常研究、提醒、复盘和 agent 协作更自然地进入个人工作流。

### 产品预览

![StockSage 系统架构](docs/assets/architecture.svg)

### Agent 使用指南

StockSage Agent 是面向个人 A 股研究的协作式研究助理，适合交给 Codex、Claude Code、Claude Desktop、Cursor 等支持本地命令或 MCP 工具的 agent 客户端使用。它可以读取项目数据和记忆，辅助做个股研究、专题研究、长期研究、深度调研、复盘和项目维护；它不是自动交易机器人。

最推荐的外部用户用法，是把这个 GitHub 主页或仓库地址发给 Codex / Claude Code，并让它按项目说明下载、安装、配置和运行：

```text
请阅读这个项目主页和 AGENTS.md，下载并运行 StockSage。
先说明需要我配置哪些 API key，然后初始化数据库、启动后端/前端或 MCP 工具。
运行前请列出会执行的命令；涉及写文件、安装依赖、启动服务或调用付费 API 时先征求确认。
```

### 主要能力

| 能力 | 说明 |
|---|---|
| 个股研究 | 汇总单股信号、新闻、持仓、长期标签、历史复盘和项目记忆，给出可追溯研究上下文。 |
| 专题研究 | 围绕行业、主题、产业链或一组股票生成结构化研究报告。 |
| 长期研究 | 调用长期分析师团，从赛道、财务质量、景气度、QFII 流向等角度生成长期标签。 |
| 深度调研 | 使用行业研究员、公司研究员、风险复核员、来源审计员、研究写作员协作生成报告。 |
| 记忆功能 | 读取和写入长期规则、风险偏好、研究索引、聊天摘要、分层决策记忆和审计日志。 |
| 复盘与纸上交易 | 统计测试表现、信号归因、胜率、回撤、exit reason 和风险规则执行情况。 |
| 项目维护 | 跑测试、看数据覆盖、检查 scheduler / API / 配置、更新文档和排查运行问题。 |

常用 MCP 工具：

| 工具 | 用途 |
|---|---|
| `stock_sage_project_context` | 获取项目运行概况、配置、持仓、自选和记忆摘要。 |
| `stock_sage_memory_snapshot` | 查看 `ai_memory`、分层记忆、审计日志和聊天摘要状态。 |
| `stock_sage_stock_context` | 获取单只股票的信号、新闻、持仓、长期标签和记忆上下文。 |
| `stock_sage_health` | 检查 agent 模式、数据库、依赖和权限状态。 |

### 推荐使用方式

**方式 A：把项目交给 Codex / Claude Code**

1. 把 GitHub 主页或仓库地址发给 Codex / Claude Code。
2. 让 agent 阅读 `README.md` 和 [AGENTS.md](AGENTS.md)，确认运行边界。
3. 按提示配置 `.env`，例如 `AI_PROVIDER=local_cli`，或填入 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等 runtime key。
4. 让 agent 下载依赖、初始化数据库、启动服务或 MCP，并在需要权限时由你确认。
5. 直接用自然语言发任务，例如：

```text
读取项目记忆后，研究 300308 当前是否值得继续关注。
跑一个 AI 算力产业链专题研究，覆盖 300308、300394。
总结测试 2 的纸上交易表现，并指出风险规则是否需要调整。
检查当前数据覆盖和 scheduler 健康状态。
```

**方式 B：本地手动启动**

```bash
git clone <repo-url> && cd stock-sage
pip install ".[dev]"
cp .env.example .env
python3 backend/data/database.py
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev
```

浏览器访问 http://localhost:5173 打开 Web 控制台；后端 API 文档位于 http://localhost:8000/docs。

**方式 C：只启动 Agent MCP**

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
```

### 无前端使用方式

如果使用者只换自己的 API key、但不打开 Web 前端，仍然可以使用 StockSage，但入口不是“API key 自动变成聊天界面”。API key 只是 StockSage runtime 调用模型、搜索或数据源的凭证；真正负责对话、申请权限和调工具的是 Codex / Claude Code 这类 agent 客户端。

| 入口 | 适合场景 |
|---|---|
| Codex / Claude Code + MCP | 最接近自然语言对话体验：让 agent 读项目、跑命令、调用工具、解释结果。 |
| FastAPI + curl / HTTP 客户端 | 适合脚本化调用 `/api/ai/chat`、`/api/research/deep/run` 等接口。 |
| CLI 脚本 | 适合确定性任务，例如深度研究、覆盖快照、纸上交易统计。 |

示例：

```bash
PYTHONPATH=. python3 -m backend.research.deep_research \
  --topic "AI算力产业链" \
  --symbols 300308,300394

PYTHONPATH=. python3 -m backend.tools.coverage_snapshot
PYTHONPATH=. python3 -m paper_trading.stats
```

目前项目没有独立的 `stocksage chat` 终端 REPL。若希望像 Claude Code 一样在终端里连续对话，推荐直接使用 Codex / Claude Code 作为外层 agent，让它连接本项目 MCP 或调用项目命令。

### 注意事项

- StockSage 是研究与辅助决策工具，不构成投资建议，不自动下真实订单。
- LLM 不直接预测价格；止盈止损来自 ATR 公式、组合约束和风险规则。
- 本地 Codex / Claude Code 会话默认可信；远程 agent 默认只读。
- 远程写操作必须同时配置 API key、写开关和 action allowlist。
- 交易、研究、复盘前应先读取项目上下文和项目记忆，不只依赖当前聊天窗口。
- 长期记忆写入必须有明确用户意图；一次性问题和普通编码偏好不要写入交易系统记忆。
- 日常批量盘后信号默认不开多 Agent，避免 25+ 股票池线性消耗 runtime LLM token。
- `.env`、数据库、模型文件、个人交易记录和真实 key 不应进入 Git。

### 更多文档

| 文档 | 内容 |
|---|---|
| [PROJECT.md](PROJECT.md) | 项目索引、里程碑和关键文件导航 |
| [STATUS.md](STATUS.md) | 当前快照、信号权重、调度、测试和启动命令 |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑和重要变更 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中任务、未来规划和后置事项 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、测试要求和贡献流程 |
| [AGENTS.md](AGENTS.md) | Codex / Claude Code / MCP 本地 agent 使用说明 |

### 风险声明

StockSage 是个人研究和辅助决策工具，不构成投资建议。系统不会自动下单，LLM 不做价格预测，止盈止损由 ATR 公式和风险约束生成。任何交易决策和资金风险均由使用者自行承担。
