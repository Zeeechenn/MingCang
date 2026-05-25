# StockSage

> 🎯 本地优先的个人 A 股研究工作台 · Agent-ready · 可审计、可追溯

StockSage 把行情、新闻、财务、QFII、持仓、复盘和长期记忆，统一组织在本地 SQLite 中，再用技术指标、LLM 新闻情绪、长期研究、组合风控和分层记忆，拼成一套**给个人投资者用的可追溯研究工作台**。

它只做研究、复盘和风险提示，**不预测价格，不自动下单，最终决策始终由用户负责**。

StockSage 的定位是 **agent 的研究底座，而不是 agent 本身**——通过 MCP / CLI 把上下文、记忆和健康检查暴露成工具集，让 Codex / Claude Code / Cursor 这类外层 agent 直接驱动；研究结论由机构级审计层兜底（DSR、PBO、Walk-Forward、Point-in-Time 拦截、IC 显著性、Kill Switch），每次判断通过 FinMem 风格的分层决策记忆和全文检索审计日志留下可回溯证据。

同时自带 Bull/Bear 三轮辩论 + Research Director + Risk Manager + Portfolio Manager 完整多 Agent 流水线，按需启用，日常盘后默认走单 agent 控制 token；本地 dev 默认信任，远程暴露则需 API key + 写开关 + action allowlist 三重门，远程默认只读。

[![CI](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/stock-sage?logo=github&color=success)](https://github.com/Zeeechenn/stock-sage/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Codex%20%7C%20Claude%20Code%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-agent%20research-yellow)

**语言**：[简体中文](README.md) · [English](README_EN.md)

**目录**：[核心特性](#-核心特性) · [快速开始](#-快速开始) · [推荐使用方式](#-推荐使用方式) · [Agent 使用指南](#-agent-使用指南) · [配置](#-配置) · [架构预览](#-架构预览) · [未来开发计划](#-未来开发计划) · [注意事项](#-注意事项) · [更多文档](#-更多文档) · [风险声明](#-风险声明)

---

## ✨ 核心特性

| | |
|---|---|
| 🗂 **本地优先** | 行情 / 新闻 / 财务 / QFII / 持仓 / 复盘 / 长期记忆，全部落在本地 SQLite，可离线运行、可审计。 |
| 🤖 **Agent-Ready** | 原生适配 Codex、Claude Code、Claude Desktop、Cursor，CLI 与 MCP 双通道开箱即用。 |
| 🔗 **多源行情** | efinance / Eastmoney / AkShare 默认 fallback；可选接入 Tushare、yfinance、TickFlow、Tavily、Anspire。 |
| 🧩 **分层信号** | 技术指标 + LLM 新闻情绪 + 长期分析师团 + 组合风控，每层独立、可单独复盘。 |
| 📒 **可审计记忆** | 项目记忆、分层决策记忆、聊天摘要分桶落库，每次写入都有审计日志。 |
| 🛡 **风险优先** | 止盈止损全部由 ATR 公式与组合约束生成，LLM 不直接预测价格。 |

> 当前聚焦 **agent 化使用体验**、数据质量与研究复盘能力；不是自动交易系统，Web 控制台仍在演进中。

---

## 🚀 快速开始

```bash
git clone <repo-url> && cd stock-sage
make agent-setup        # 检查 Python、安装依赖、创建 .env、初始化数据库
make agent              # 进入终端 shell，开始用自然语言对话
```

最小本地配置只需 `AI_PROVIDER=local_cli`（走本地 Claude CLI），**不需要任何云 LLM key**。

如果想使用自己的 Anthropic / OpenAI 或兼容接口 key，先复制并编辑 `.env`：

```bash
cp .env.example .env
# 在 .env 中设置 AI_PROVIDER=anthropic + ANTHROPIC_API_KEY
# 或 AI_PROVIDER=openai + OPENAI_API_KEY（兼容接口再填 OPENAI_BASE_URL）
```

配置完成后仍然从终端进入项目目录运行 `make agent-setup && make agent`；Web 控制台和 MCP 接入见下方推荐使用方式。

验证一切正常：

```bash
python3 -m backend.agent.cli health --pretty
```

进入终端 shell 后可以直接问：

```text
检查 StockSage 健康状态。
研究 300308，结合记忆、新闻、持仓和长期标签。
把 300394 加入自选股。
```

> 研究和健康检查会直接读取本地上下文；自选、持仓、记忆、配置等**写操作**会先 dry-run 并要求明确确认，再通过 `backend.agent.cli action ... --confirm` 执行。

---

## 📋 推荐使用方式

| 方式 | 适合场景 | 入口 |
|---|---|---|
| **A. 交给 Codex / Claude Code** | 把仓库丢给 agent，让它自己读 README、跑健康检查、配 `.env` | 任意 agent 客户端 |
| **A2. 终端 Agent** | 想要自带研究/复盘对话界面 | `make agent-setup && make agent` |
| **B. Web 控制台**（开发中） | 想要图形化的研究看板 | <http://localhost:5173>（API: <http://localhost:8000/docs>） |
| **C. Docker / compose** | 想要一键部署整套前后端 | `cp .env.example .env && make docker-up` |
| **D. 接入 MCP 工具** | 想把 StockSage 作为外层 agent 的工具集 | `make agent-mcp && make agent-mcp-config` |

<details>
<summary><b>方式 A — 把项目交给 Codex / Claude Code</b></summary>

1. 把 GitHub 主页或仓库地址发给 Codex / Claude Code。
2. 让 agent 阅读 `README.md` 和 [AGENTS.md](AGENTS.md)，确认运行边界。
3. 让 agent 先跑 `python3 -m backend.agent.cli health --pretty`，确认数据库、记忆、自选、持仓状态。
4. 按提示配置 `.env`（例如 `AI_PROVIDER=local_cli`，或填入 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`）。
5. 让 agent 安装依赖、初始化数据库、启动服务或 MCP，需要权限时由你确认。
6. 直接用自然语言发送研究、复盘、记忆或项目体检任务。

</details>

<details>
<summary><b>方式 A2 — 终端 Agent</b></summary>

`make agent-setup` 会检查 Python、安装 StockSage agent 依赖、创建 `.env`、初始化数据库，并提示安装 pi。V1 默认把同一把 Anthropic/OpenAI key 用于 pi 外层对话和 StockSage 内部 LLM runtime；如果选 `AI_PROVIDER=local_cli`，StockSage 内部 LLM 会走本地 Claude CLI。

</details>

<details>
<summary><b>方式 D — 接入 MCP 工具</b></summary>

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
# 或：
make agent-mcp
make agent-mcp-config
```

把这个 MCP server 配到 Claude Desktop / Claude Code / Cursor 或其他 MCP 客户端后，外层 agent 就能调用 StockSage 的项目上下文、记忆快照、单股上下文与健康检查工具。

</details>

---

## 🤖 Agent 使用指南

StockSage 已经把研究、记忆、复盘、健康检查全部 agent 化。重点不是"它怎么跑"，而是**可以把哪些任务交给它**。

### 可以委派的任务

| 你想做的事 | 交给 Agent 的任务 | 典型输出 |
|---|---|---|
| **个股研究** | 读取单股信号、新闻、持仓、长期标签、历史复盘和项目记忆。 | 研究摘要、证据链、风险点、可继续观察的问题。 |
| **专题研究** | 围绕行业、主题、产业链或一组股票做结构化研究。 | 主题结论、涉及标的、来源审计、待验证问题。 |
| **长期研究** | 调用长期分析师团，检查赛道、财务质量、景气度、QFII 流向。 | 长期标签、评分、关键发现、规避或持有理由。 |
| **深度调研** | 组织行业研究员、公司研究员、风险复核员、来源审计员、写作员生成报告。 | Markdown 报告、核心结论、风险复核、引用来源。 |
| **记忆管理** | 读写长期规则、风险偏好、研究索引、聊天摘要和分层决策记忆。 | 记忆摘要、召回结果、待确认的写入操作。 |
| **复盘与验证** | 统计信号表现、归因、胜率、回撤、exit reason 和风险规则执行。 | 复盘摘要、表现归因、规则校准建议。 |
| **项目体检** | 检查数据覆盖、scheduler、API、配置、测试、文档状态。 | 健康报告、异常项、维护建议。 |

### 常用提示词

```text
读取项目记忆后，研究 300308 当前是否值得继续关注。
跑一个 AI 算力产业链专题研究，覆盖 300308、300394。
调用长期分析师团，更新我自选股里的长期标签。
检查当前数据覆盖和 scheduler 健康状态。
```

### 常用 MCP 工具

| 工具 | 用途 |
|---|---|
| `stock_sage_project_context` | 项目运行概况、配置、持仓、自选、记忆摘要。 |
| `stock_sage_memory_snapshot` | `ai_memory`、分层记忆、审计日志、聊天摘要状态。 |
| `stock_sage_stock_context` | 单只股票的信号、新闻、持仓、长期标签和记忆上下文。 |
| `stock_sage_health` | agent 模式、数据库、依赖、权限健康检查。 |

---

## ⚙️ 配置

### API Key

所有外部 key 都从项目根目录 `.env` 读取；**`.env`、真实 key、数据库、个人交易记录都不应进入 Git**。最小本地配置只需 `AI_PROVIDER=local_cli`；新闻补充、推送、远程 agent 暴露按需启用。

| 配置项 | 用途 | 是否必需 | 获取方式 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `AI_PROVIDER=anthropic` 时供 StockSage 内部 LLM 调用。 | 可选；选 Anthropic runtime 时必需 | Anthropic Console 创建 key |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | `AI_PROVIDER=openai` 时供 OpenAI 或兼容 endpoint 使用。 | 可选；选 OpenAI runtime 时必需 | 对应平台创建 key；第三方兼容接口需同时填 `OPENAI_BASE_URL` |
| `TAVILY_API_KEY` | 信号生成时补充实时搜索；`backfill_coverage --use-tavily` 与长期 A-teacher 证据搜索也会用。 | 可选 | [Tavily](https://app.tavily.com/) 创建 API key |
| `ANSPIRE_API_KEY` | 盘后情感链路的严格事件型新闻补缺，过滤行情页、资料页与噪音。 | 可选 | [Anspire AI Search](https://aisearch.anspire.cn) 创建 key |
| `BARK_KEY` / `BARK_SERVER` | iOS Bark 推送盘后信号、止损预警、熔断提醒。 | 可选；未配置则静默跳过 | Bark App 复制设备 key；默认 `https://api.day.app`，自建服务时改 `BARK_SERVER` |
| `STOCKSAGE_AGENT_API_KEY` | `STOCKSAGE_AGENT_MODE=remote` 时用于远程 agent / MCP / HTTP 写鉴权。 | 本地不需要；远程暴露时必需 | 自己生成高强度随机串；按需开启 `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED` 和 action allowlist |
| `TUSHARE_TOKEN` | A 股日线调试源；当前只调 `daily` 未复权接口，不进入 CN 生产 fallback。 | 可选 | [Tushare](https://tushare.pro/) 获取 token |
| `TICKFLOW_ENABLED` / `TICKFLOW_API_KEY` / `TICKFLOW_BASE_URL` | TickFlow A 股日线源；默认关闭，启用后用 `forward_additive` 前复权口径作为 CN 优先 provider。 | 可选；需显式设 `TICKFLOW_ENABLED=true` | [TickFlow](https://tickflow.org/) 控制台获取 key；默认 `https://api.tickflow.org` |

**典型的本地配置**：

```env
AI_PROVIDER=local_cli
TUSHARE_TOKEN=your_tushare_token_here
TICKFLOW_ENABLED=false
TICKFLOW_API_KEY=your_tickflow_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
ANSPIRE_API_KEY=your_anspire_api_key_here
BARK_KEY=your_bark_device_key_here
BARK_SERVER=https://api.day.app
```

**远程部署 / 把 MCP / HTTP 暴露给其他机器时再加**：

```env
STOCKSAGE_AGENT_MODE=remote
STOCKSAGE_AGENT_API_KEY=replace_with_a_long_random_secret
STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=false
STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS=
```

### 推荐信号权重

当前生产默认使用 `new_framework` 权重。基于现有回测与验证结果，**暂时不让量化层参与综合分**，只保留技术面与新闻情绪：

| 配置项 | 推荐值 | 含义 |
|---|---:|---|
| `WEIGHT_QUANT` | `0.0` | Qlib / Kronos 等量化层仍在计算并记录，默认不进入综合分 |
| `WEIGHT_TECHNICAL` | `0.6` | 技术信号权重 |
| `WEIGHT_SENTIMENT` | `0.4` | 新闻情绪 / 事件信号权重 |
| `NEW_FRAMEWORK_ENTRY_THRESHOLD` | `25.0` | 综合分高于该阈值才进入小仓试错候选 |

这些是**项目默认推荐值，不是硬编码交易建议**。用户可在 Web 配置页或 `.env` 中调整，并用回测和复盘验证自己的参数组合。

---

## 🖼 架构预览

![StockSage 系统架构](docs/assets/architecture.svg)

---

## 🗺 未来开发计划

下一阶段会沿三个方向扩展项目能力，让 StockSage 从"个人 A 股研究"走向**跨市场、跨终端的个人投资研究工作台**。

| 方向 | 计划内容 | 状态 |
|---|---|---|
| 🌐 **多市场支持** | 在 A 股之外接入港股（HKEX）与美股（US）的行情、新闻和基础财务数据；复用现有的分层信号、长期研究与记忆体系。 | 规划中 |
| 🎨 **前端优化** | Web 控制台体验打磨：研究看板可视化、信号详情页、组合视图、记忆浏览器与移动端适配。 | 持续迭代中 |
| 📱 **客户端开发** | 提供桌面 / 移动端原生客户端，让本地数据与 agent 工作流脱离命令行与浏览器即可使用。 | 待启动 |

> 详细里程碑、子任务与排期见 [docs/ROADMAP.md](docs/ROADMAP.md)。欢迎在 GitHub Issues / Discussions 提出建议。

---

## ⚠️ 注意事项

### 🛡 风险与边界

- StockSage 是研究与辅助决策工具，**不构成投资建议，不自动下真实订单**。
- LLM 不直接预测价格；止盈止损来自 ATR 公式、组合约束和风险规则。

### 🔐 安全与权限

- 本地 Codex / Claude Code 会话默认可信；远程 agent 默认只读。
- 远程写操作必须**同时**配置 API key、写开关和 action allowlist。
- API key 是 StockSage **运行时**凭证，不是 Codex / Claude Code 外层对话凭证；只有运行到内部 LLM、搜索、推送或远程链路时才会消耗。
- `.env`、数据库、模型文件、个人交易记录、真实 key 不应进入 Git。

### 📊 数据与额度

- **数据来源对应**：A 股日线行情默认走 efinance / Eastmoney / AkShare fallback；显式设置 `TICKFLOW_ENABLED=true` 且配置 `TICKFLOW_API_KEY` 后，TickFlow 以 `forward_additive` 口径成为 CN 优先 provider，后续仍保留原 fallback；Tushare `daily` 当前仅保留为未复权调试源，不进入生产信号；财务、QFII、基础新闻走 AkShare / Eastmoney（不需要 key）；实时新闻补充用 `TAVILY_API_KEY`；严格事件型新闻补缺用 `ANSPIRE_API_KEY`；iOS 推送用 `BARK_KEY`；远程 agent 鉴权用 `STOCKSAGE_AGENT_API_KEY`。
- **免费 / 试用额度**（2026-05-23 公开信息）：
  - **Tavily** Researcher 免费档 1,000 credits / 月；StockSage 当前用 basic search，每次约 1 credit；development key 100 RPM，production key 1,000 RPM（需付费或 PAYGO）。见 [Tavily Credits](https://docs.tavily.com/documentation/api-credits) · [Rate Limits](https://docs.tavily.com/documentation/rate-limits)。
  - **Anspire** 控制台可查看资源包总额度与使用情况，未给出固定免费额度；以 [Anspire 控制台](https://aisearch.anspire.cn) 资源包页为准。见 [使用教程](https://open.anspire.cn/document/docs/openPlatform/)。
  - **Tushare** 当前只作为 A 股日线调试源，调 `daily` 未复权接口，不进入 CN 生产 fallback；日线 `daily` 需 120 积分起，基础积分每分钟 500 次、每次最多 6,000 条。见 [日线行情](https://www.tushare.pro/document/2?doc_id=27) · [权限说明](https://www.tushare.pro/document/2?doc_id=108)。
  - **TickFlow** 可选作为 A 股日线优先源；当前使用 `forward_additive`，官方文档说明该口径与东方财富/同花顺价格对齐。实时行情、分钟 K 和更高频率访问取决于套餐。见 [开始之前](https://docs.tickflow.org/zh-Hans/quickstart) · [API 概述](https://docs.tickflow.org/zh-Hans/api-reference/introduction)。
  - **Bark** `api.day.app` 是推送入口，key 来自 App 测试 URL / 设备 key；公开教程未承诺免费额度或 SLA，高频推送建议自建。见 [Bark tutorial](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md)。

### 💡 使用习惯

- 交易、研究、复盘前应先读取项目上下文与项目记忆，**不要只依赖当前聊天窗口**。
- 长期记忆写入必须有明确用户意图；一次性问题和普通编码偏好**不要**进入交易系统记忆。
- 日常批量盘后信号默认不开多 Agent，避免 25+ 股票池线性消耗 runtime LLM token。

---

## 📚 更多文档

| 文档 | 内容 |
|---|---|
| [PROJECT.md](PROJECT.md) | 项目索引、里程碑和关键文件导航 |
| [STATUS.md](STATUS.md) | 当前快照、信号权重、调度、测试和启动命令 |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑和重要变更 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中任务、未来规划和后置事项 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、测试要求和贡献流程 |
| [AGENTS.md](AGENTS.md) | Codex / Claude Code / MCP 本地 agent 使用说明 |

---

## ⚖️ 风险声明

StockSage 是个人研究和辅助决策工具，**不构成投资建议**。系统不会自动下单，LLM 不做价格预测，止盈止损由 ATR 公式和风险约束生成。**任何交易决策和资金风险均由使用者自行承担**。
