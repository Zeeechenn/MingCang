# StockSage

面向个人 A 股研究的 Agent-ready 决策工作台：把本地数据底座、多源行情/新闻、技术与情感分析、长期研究、组合风控和可审计记忆组织成一套可追溯的辅助决策系统。StockSage 只做研究、复盘和风险提示，不预测价格，不自动下单，最终决策始终由用户负责。

![Tests](https://img.shields.io/badge/tests-300%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[Agent 使用指南](#agent-使用指南) · [产品预览](#产品预览) · [推荐使用方式](#推荐使用方式) · [注意事项](#注意事项) · [更多文档](#更多文档)

[简体中文](README.md) | [English](README_EN.md)

---

## 中文版

### 项目概览

StockSage 是一个本地优先的个人 A 股研究系统，也是一个已经 agent 化的投资研究内核。它把行情、新闻、财务、QFII、指数、持仓、复盘和长期记忆组织到本地 SQLite 中，用技术指标、LLM 新闻情感、长期研究、组合风控和审计记忆辅助用户做可追溯决策。

项目当前聚焦纸上交易验证和 agent 化使用体验。它不是自动交易系统，不让 LLM 直接预测价格，后续会从 Web 控制台继续演进为更完整的客户端体验。

### Agent 使用指南

StockSage Agent 适合交给 Codex、Claude Code、Claude Desktop、Cursor 等支持本地命令或 MCP 工具的 agent 客户端使用。用户最需要知道的不是它“怎么运行”，而是可以把哪些研究和复盘任务交给它。

| 你想做的事 | 可以交给 Agent 的任务 | 典型输出 |
|---|---|---|
| 个股研究 | 让它读取单股信号、新闻、持仓、长期标签、历史复盘和项目记忆。 | 个股研究摘要、证据链、风险点、可继续观察的问题。 |
| 专题研究 | 让它围绕行业、主题、产业链或一组股票做结构化研究。 | 主题结论、涉及标的、来源审计、待验证问题。 |
| 长期研究 | 让它调用长期分析师团，检查赛道、财务质量、景气度和 QFII 流向。 | 长期标签、评分、关键发现、规避或持有理由。 |
| 深度调研 | 让它组织行业研究员、公司研究员、风险复核员、来源审计员和写作员生成报告。 | Markdown 调研报告、核心结论、风险复核、引用来源。 |
| 记忆管理 | 让它读取或写入长期规则、风险偏好、研究索引、聊天摘要和分层决策记忆。 | 记忆摘要、召回结果、待确认的记忆写入操作。 |
| 复盘与纸上交易 | 让它统计测试表现、信号归因、胜率、回撤、exit reason 和风险规则执行情况。 | 复盘摘要、表现归因、规则校准建议。 |
| 项目体检 | 让它检查数据覆盖、scheduler、API、配置、测试和文档状态。 | 健康检查结果、异常项、下一步维护建议。 |

常见提示词示例：

```text
读取项目记忆后，研究 300308 当前是否值得继续关注。
跑一个 AI 算力产业链专题研究，覆盖 300308、300394。
调用长期分析师团，更新我自选股里的长期标签。
总结测试 2 的纸上交易表现，并指出风险规则是否需要调整。
检查当前数据覆盖和 scheduler 健康状态。
```

常用 MCP 工具：

| 工具 | 用途 |
|---|---|
| `stock_sage_project_context` | 获取项目运行概况、配置、持仓、自选和记忆摘要。 |
| `stock_sage_memory_snapshot` | 查看 `ai_memory`、分层记忆、审计日志和聊天摘要状态。 |
| `stock_sage_stock_context` | 获取单只股票的信号、新闻、持仓、长期标签和记忆上下文。 |
| `stock_sage_health` | 检查 agent 模式、数据库、依赖和权限状态。 |

### 产品预览

![StockSage 系统架构](docs/assets/architecture.svg)

### 推荐使用方式

**方式 A：交给 Codex / Claude Code**

1. 把 GitHub 主页或仓库地址发给 Codex / Claude Code。
2. 让 agent 阅读 `README.md` 和 [AGENTS.md](AGENTS.md)，确认运行边界。
3. 按提示配置 `.env`，例如 `AI_PROVIDER=local_cli`，或填入 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等 runtime key。
4. 让 agent 下载依赖、初始化数据库、启动服务或 MCP，并在需要权限时由你确认。
5. 直接用自然语言发送研究、复盘、记忆或项目体检任务。

**方式 B：启动 Web 控制台**

```bash
git clone <repo-url> && cd stock-sage
pip install ".[dev]"
cp .env.example .env
python3 backend/data/database.py
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev
```

浏览器访问 http://localhost:5173 打开 Web 控制台；后端 API 文档位于 http://localhost:8000/docs。

**方式 C：用 Docker / compose 启动**

```bash
cp .env.example .env
make docker-up
```

Docker 会启动 backend 和 frontend；本地访问 http://localhost，API 文档访问 http://localhost:8000/docs。

**方式 D：接入 MCP 工具**

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
```

把这个 MCP server 配到 Claude Desktop、Claude Code、Cursor 或其他支持 MCP 的客户端后，就可以让外层 agent 调用 StockSage 的项目上下文、记忆快照、单股上下文和健康检查工具。

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
