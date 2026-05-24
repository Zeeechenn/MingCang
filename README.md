# StockSage

面向个人 A 股研究的 Agent-ready 决策工作台：把本地数据底座、多源行情/新闻、技术与情感分析、长期研究、组合风控和可审计记忆组织成一套可追溯的辅助决策系统。StockSage 只做研究、复盘和风险提示，不预测价格，不自动下单，最终决策始终由用户负责。

![Tests](https://img.shields.io/badge/tests-300%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[Agent 使用指南](#agent-使用指南) · [产品预览](#产品预览) · [推荐使用方式](#推荐使用方式) · [API Key 配置](#api-key-配置) · [当前推荐配置](#当前推荐配置) · [注意事项](#注意事项) · [更多文档](#更多文档)

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
3. 让 agent 先跑 `python3 -m backend.agent.cli health --pretty`，确认数据库、记忆、自选和持仓状态。
4. 按提示配置 `.env`，例如 `AI_PROVIDER=local_cli`，或填入 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等 runtime key。
5. 让 agent 下载依赖、初始化数据库、启动服务或 MCP，并在需要权限时由你确认。
6. 直接用自然语言发送研究、复盘、记忆或项目体检任务。

**方式 A2：终端 pi Agent**

```bash
git clone <repo-url> && cd stock-sage
make agent-setup
make agent
```

`make agent-setup` 会检查 Python、安装 StockSage agent 依赖、创建 `.env`、初始化数据库，并提示安装 pi。V1 默认把同一把 Anthropic/OpenAI key 用于 pi 外层对话和 StockSage 内部 LLM runtime；如果选择 `AI_PROVIDER=local_cli`，StockSage 内部 LLM 会走本地 Claude CLI。

进入 pi 终端后可以直接问：

```text
检查 StockSage 健康状态。
研究 300308，结合记忆、新闻、持仓和长期标签。
总结测试 2 纸上交易表现。
把 300394 加入自选股。
```

研究和健康检查会直接读取本地上下文；自选、持仓、记忆、配置等写操作会先 dry-run 并要求你明确确认，再通过 `backend.agent.cli action ... --confirm` 执行。

**方式 B：启动 Web 控制台（开发中）**

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
# 或：
make agent-mcp
make agent-mcp-config
```

把这个 MCP server 配到 Claude Desktop、Claude Code、Cursor 或其他支持 MCP 的客户端后，就可以让外层 agent 调用 StockSage 的项目上下文、记忆快照、单股上下文和健康检查工具。

### API Key 配置

StockSage 的外部 key 都从项目根目录 `.env` 读取；不要把 `.env`、真实 key、数据库或个人交易记录提交到 Git。最小本地运行可以只用 `AI_PROVIDER=local_cli`，不配置云 LLM key；新闻补充、推送和远程 agent 暴露再按需启用。

| 配置项 | 当前用途 | 是否必需 | 获取/配置方式 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `AI_PROVIDER=anthropic` 时供 StockSage 内部 LLM 调用。 | 可选；选 Anthropic runtime 时必需。 | 在 Anthropic Console 创建 key，写入 `.env`。 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | `AI_PROVIDER=openai` 时供 OpenAI 或 OpenAI-compatible endpoint 使用。 | 可选；选 OpenAI runtime 时必需。 | 在对应平台创建 key；第三方兼容接口同时填写 `OPENAI_BASE_URL`。 |
| `TAVILY_API_KEY` | 数据库 24 小时内新闻不足时，补充实时搜索标题；`backfill_coverage --use-tavily` 和长期 A-teacher 证据搜索也会用。 | 可选备用 key。 | 到 [Tavily](https://app.tavily.com/) 创建 API key，写入 `.env`。 |
| `ANSPIRE_API_KEY` | 盘后情感链路的严格事件型新闻补缺，优先过滤行情页、资料页和噪音来源。 | 可选备用 key。 | 到 [Anspire AI Search](https://aisearch.anspire.cn) 注册，在 API Keys 页面创建 key，写入 `.env`。 |
| `BARK_KEY` / `BARK_SERVER` | 盘后信号、止损预警和熔断提醒的 iOS Bark 推送。 | 可选；不配置会静默跳过推送。 | 打开 Bark App 复制设备 key；默认服务为 `https://api.day.app`，自建服务时改 `BARK_SERVER`。 |
| `STOCKSAGE_AGENT_API_KEY` | 仅 `STOCKSAGE_AGENT_MODE=remote` 时用于远程 agent/MCP/HTTP 写操作鉴权。 | 本地模式不需要；远程暴露时必需。 | 自己生成一段高强度随机字符串，写入 `.env`，并按需开启 `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED` 和 action allowlist。 |
| `TUSHARE_TOKEN` | A 股日线行情补充 provider；配置后进入 CN fallback 链，用 Tushare `daily` 拉取未复权 OHLCV。 | 可选备用 key。 | 到 [Tushare](https://tushare.pro/) 获取 token 并写入 `.env`；不配置时自动跳过 Tushare。 |

推荐的个人配置流程：

```bash
cp .env.example .env
```

然后只填写你实际要启用的 key。一个常见的本地备用配置是：

```env
AI_PROVIDER=local_cli
TUSHARE_TOKEN=your_tushare_token_here
TAVILY_API_KEY=your_tavily_api_key_here
ANSPIRE_API_KEY=your_anspire_api_key_here
BARK_KEY=your_bark_device_key_here
BARK_SERVER=https://api.day.app
```

远程部署或把 MCP/HTTP 暴露给其他机器时，再额外加：

```env
STOCKSAGE_AGENT_MODE=remote
STOCKSAGE_AGENT_API_KEY=replace_with_a_long_random_secret
STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=false
STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS=
```

配置后可先跑：

```bash
python3 -m backend.agent.cli health --pretty
```

### 当前推荐配置

当前生产默认使用 `new_framework` 信号权重。基于现有回测与测试 1 / 测试 2 早期对照结果，推荐暂时保持量化层不参与综合分，只保留技术面与新闻情绪：

| 配置项 | 当前推荐值 | 含义 |
|---|---:|---|
| `WEIGHT_QUANT` | `0.0` | Qlib / Kronos 等量化层仍可计算和记录，但默认不影响综合分。 |
| `WEIGHT_TECHNICAL` | `0.6` | 技术信号权重。 |
| `WEIGHT_SENTIMENT` | `0.4` | 新闻情绪 / 事件信号权重。 |
| `NEW_FRAMEWORK_ENTRY_THRESHOLD` | `25.0` | 综合分高于该阈值才进入小仓试错候选。 |

这些是当前项目推荐值，不是硬编码交易建议。用户可以在 Web 配置页或项目根目录 `.env` 中自行调整，并用纸上交易、回测和复盘结果验证自己的参数组合。

### 注意事项

- StockSage 是研究与辅助决策工具，不构成投资建议，不自动下真实订单。
- LLM 不直接预测价格；止盈止损来自 ATR 公式、组合约束和风险规则。
- 本地 Codex / Claude Code 会话默认可信；远程 agent 默认只读。
- 远程写操作必须同时配置 API key、写开关和 action allowlist。
- API key 是 StockSage 运行时凭证，不是 Codex / Claude Code 外层对话凭证；只有运行到内部 LLM、搜索、推送或远程 agent 链路时才会消耗。
- 数据来源与 API key 对应关系：A 股日线行情当前使用 efinance / Eastmoney / AkShare fallback，配置 `TUSHARE_TOKEN` 后会追加 Tushare `daily` 作为补充来源，最后再 fallback 到 yfinance；A 股财务、QFII、新闻基础数据主要走 AkShare/Eastmoney，不需要 key；实时新闻补充使用 `TAVILY_API_KEY`；严格事件型新闻补缺使用 `ANSPIRE_API_KEY`；iOS 推送使用 `BARK_KEY`；远程 agent 鉴权使用 `STOCKSAGE_AGENT_API_KEY`。
- 免费/试用 key 有额度限制，以下为 2026-05-23 查到的公开说明：
  - Tavily Researcher 免费档为 1,000 API credits/月；StockSage 当前使用 basic search，每次请求约消耗 1 credit；development key 默认 100 RPM，production key 1,000 RPM，production key 需要付费计划或 PAYGO。见 [Tavily Credits & Pricing](https://docs.tavily.com/documentation/api-credits) 和 [Tavily Rate Limits](https://docs.tavily.com/documentation/rate-limits)。
  - Anspire 公开文档说明可在控制台查看每个资源包的总额度和使用情况，但未给出固定免费额度数字；以 [Anspire 控制台](https://aisearch.anspire.cn) 的资源包页面为准。见 [Anspire 使用教程](https://open.anspire.cn/document/docs/openPlatform/)。
  - Tushare 在 StockSage 中只作为 A 股日线行情补充来源，调用 `daily` 未复权行情接口；官方权限说明显示日线行情 `daily` 为 120 积分起，日线接口文档说明基础积分每分钟可调取 500 次、每次最多 6,000 条。其他 Tushare 数据需要更高积分或单独权限。见 [Tushare A 股日线行情](https://www.tushare.pro/document/2?doc_id=27) 和 [Tushare 权限说明](https://www.tushare.pro/document/2?doc_id=108)。
  - Bark 的 `api.day.app` 是推送服务入口，项目只在配置 `BARK_KEY` 后发送通知；公开教程说明 key 来自 App 测试 URL/设备 key，未承诺免费额度或 SLA。高频推送建议自建 Bark server。见 [Bark tutorial](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md)。
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
