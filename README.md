# StockSage

个人 A 股辅助决策系统：用本地数据底座、量化/技术指标、LLM 新闻情感、多 Agent 风控和记忆治理，给出可审计的择股与持仓建议。系统只做研究和辅助决策，不做价格预测，不自动下单，最终决策由用户自行负责。

![Tests](https://img.shields.io/badge/tests-293%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[产品预览](#产品预览) · [功能特性](#功能特性) · [快速开始](#快速开始) · [系统架构](#系统架构) · [文档中心](#文档中心) · [未来规划](#未来规划)

[简体中文](#中文版) | [English](#english-version)

---

## 中文版

### 项目概览

StockSage 是一个面向个人使用的 A 股研究与决策工作台。它把行情、新闻、财务、QFII、指数和持仓等信息写入本地 SQLite，再通过技术指标、新闻情感、长期分析师团、风险经理和组合层约束生成信号。前端提供看板、复盘、持仓、AI 对话和配置管理，后端通过 FastAPI 暴露可追溯 API，并由 APScheduler 执行盘前、盘中、盘后和周度任务。

当前默认生产路径是 `new_framework`：技术信号权重 60%，LLM 新闻情感权重 40%，Qlib 量化权重暂为 0。Qlib/LightGBM 工程链路已经打通，但最近扩容验证未通过 alpha 门槛，因此暂不把量化模型接回生产权重。

### 产品预览

![StockSage 系统架构](docs/assets/architecture.svg)

### 系统架构

1. 数据源：AkShare、财报/QFII、市值资金流、新闻源、手动持仓与配置。
2. 数据底座：SQLite 保存行情、新闻、信号、持仓、复盘、聊天与记忆；point-in-time 层防止未来函数。
3. 分析层：技术指标、新闻来源审计、LLM 情感、Qlib 离线验证、长期分析师团和手动深度研究。
4. 决策层：`backend/decision/aggregator.py` 聚合信号，多 Agent 流水线补充研究、交易、风险和组合约束。
5. 交付层：FastAPI + React 前端展示结果，Bark 推送买入信号和 14:30 止损预警。
6. 治理层：ai_memory、分层决策记忆、audit_log_fts、聊天摘要、TTL 清理和每日备份。

### 当前状态

| 里程碑 | 名称 | 状态 |
|---|---|---|
| M0 | 系统骨架 | 完成 |
| M1 | 严肃化与质量门槛 | 完成，Sharpe 1.36 / 回撤 8.6% / 盈亏比 2.78 |
| M2 | 纸上交易验证 | 进行中，测试 1 收尾，测试 2 准备启动 |
| M3 | 可信度审计层 | 完成，DSR / PBO / walk-forward / PIT / kill switch |
| M4 | 多 Agent 决策深化 | 大部分完成，LangGraph 与完整 FinMem 替换暂缓 |
| M5 | 自动化执行 | 后置，等待纸上交易与 holdout 验证 |
| M6 | 持续迭代与扩展 | 当前范围完成，含量化基础设施与前端操作台 |
| M7 | 工程化与开源就绪 | 完成，CI、Docker、Makefile、pyproject、文档体系 |
| M8 | 深度研究与来源审计层 | 完成，手动专题研究不进入日常信号 |
| M9 | 记忆系统接入与治理 | 大部分完成，含记忆管理、审计、摘要、备份 |
| M10 | 运行可靠性与产品化优化 | M10.0-M10.4 完成，M10.5 后置 |

详细进度见 [PROJECT.md](PROJECT.md)、[STATUS.md](STATUS.md) 和 [docs/ROADMAP.md](docs/ROADMAP.md)。

### 功能特性

**数据与覆盖**

- A 股行情、个股新闻和指数数据同步。
- 财务指标、QFII 持仓、市值、流通市值、资金流等补充数据。
- Provider registry 与 fallback，记录成功/失败次数和最近错误。
- 数据覆盖快照：active 股票数、价格覆盖、2 年价格覆盖、财报覆盖、24h 新闻覆盖、signals 日期范围。
- Point-in-time 数据读取：训练/推理按 `as_of` 或披露日约束，降低未来函数风险。

**信号与分析**

- 技术因子：ATR、RSI、MA、RSRS、regime 过滤等。
- 新闻情感：LLM 对新闻摘要/标题评分，输出情感分与理由。
- 新闻来源审计：按来源、URL、时效、重复标题等评估证据质量。
- Qlib/LightGBM：支持技术 + PIT 基本面 + 市值资金流特征，保留 regression 与 LambdaRank 训练入口。
- 严肃验证：Backtrader、walk-forward、holdout、DSR、PBO、IC 显著性、阈值扫描、exit 实验。

**多 Agent 决策**

- 长期分析师团：赛道分析、Piotroski 财务质量、景气投资指标、QFII outflow 规避。
- Researcher：看多/看空多轮辩论，失败时可降级。
- Research Director：检查长期标签和证据质量，提出辩论主题。
- Trader：把综合证据转成交易建议。
- Risk Manager：执行风险否决、ATR 止盈止损和 kill switch 约束。
- Portfolio Manager：组合层候选分配，处理单股、板块、总仓位限制。

**决策输出与风控**

- 综合评分范围：-100 到 +100。
- 默认生产权重：技术 60% + 情感 40% + 量化 0%。
- Entry threshold 默认 25。
- ATR 风险收益约束：

```text
止损价 = 收盘价 - ATR(14) × 2.0
止盈价 = 收盘价 + (收盘价 - 止损价) × 2.0
```

- Kill switch：连续亏损、单日回撤、数据陈旧和手动触发均可阻断调度任务。
- Bark 推送：买入信号、14:30 止损预警；推送失败写日志/审计，不阻塞信号保存。

**前端操作台**

- 脉冲看板：自选股、最新信号、大盘情况、真实持仓和活动流水。
- 个股详情：K 线、最新信号、新闻、证据链、复盘、长期标签，支持渐进加载。
- 复盘中心：每日复盘、长期复盘、历史记录、Markdown 报告展开。
- 持仓设置：手动持仓、股票联想、持仓汇总、平仓记录、永久删除已平仓记录。
- AI 对话：通用助手/长期研究团队模式、会话隔离、归档确认、Markdown 回复、SSE 流式输出。
- 配置页：综合分权重、仓位上限、数据补充参数、复盘触发时间、记忆管理。

**记忆与审计**

- `ai_memory`：保存长期规则、风险偏好、研究索引、持仓偏好等。
- 分层决策记忆：中期标的记忆与长期全局反思。
- `audit_log_fts`：SQLite FTS5 检索记忆、研究、召回、备份和操作事件。
- `should_remember()`：轻量启发式判断是否值得写入长期记忆。
- 聊天记忆写入采用二次确认，避免 LLM 直接修改长期记忆。
- TTL 过期清理、每日备份和聊天窗口摘要。

**专题研究**

- 手动深度研究 CLI/API：行业研究员、公司研究员、风险复核员、来源审计员、研究写作员协作生成报告。
- 默认报告输出到 `docs/research/YYYY-MM-DD-主题.md`。
- 专题研究写入研究记忆，但不创建 `Signal`，不参与日常盘后信号。

**工程化**

- FastAPI 拆分路由：watchlist、positions、stocks、signals、prices、model、system、dashboard、news、research、reviews、skills、ai、memory。
- Makefile 封装安装、测试、lint、typecheck、验证、开发、构建、Docker 等命令。
- pyproject 作为 Python 依赖和工具配置单一真理源。
- Dockerfile + docker-compose + nginx proxy。
- CI / pre-commit / ruff / mypy / pytest / frontend build。
- 敏感文件入库防线，阻止 `.db`、`.env` 和模型 pickle 等误提交。

### 快速开始

```bash
# 1. 克隆 & 安装依赖
git clone <repo-url> && cd stock-sage
pip install ".[dev]"

# 2. 配置环境变量
cp .env.example .env
# 填入 ANTHROPIC_API_KEY（必填）和 BARK_KEY（可选）

# 3. 初始化数据库
python3 backend/data/database.py

# 4. 启动后端
PYTHONPATH=. uvicorn backend.main:app --reload

# 5. 启动前端（新终端）
cd frontend && npm install && npm run dev
```

浏览器访问 http://localhost:5173 打开操作台。后端 API 文档位于 http://localhost:8000/docs。

### 常用命令

| 命令 | 用途 |
|---|---|
| `make install` | 安装 Python dev 依赖和前端依赖 |
| `make dev` | 启动后端开发服务 |
| `make build` | 构建前端 |
| `make test` | 运行后端 pytest |
| `make frontend-test` | 运行前端 node:test |
| `make verify` | lint + typecheck + 后端测试 + 前端测试 + 构建 |
| `make coverage-snapshot` | 输出当前数据覆盖快照 |
| `make paper-stats` | 统计纸面交易结果 |
| `make docker-up` | docker compose 启动服务 |

### 调度时间表

| 时间 | 任务 | 说明 |
|---|---|---|
| 08:30 工作日 | 盘前同步 | 行情回填、个股新闻、沪深 300 指数 |
| 14:30 工作日 | 止损预警 | 检查买入信号止损线，触发 Bark 推送 |
| 16:00 工作日 | 盘后信号 | 聚合信号，写入 Signal，触发推送 |
| 周六 09:00 | 模型重训 | LightGBM Alpha 模型周训练 |
| 周一 09:00 / 周五 15:00 | 长期分析师团 | 生成长期 label，时间可在配置页调整 |
| 每日 00:30 / 01:00 | 记忆维护 | 备份 ai_memory，清理过期记忆 |

所有任务运行在 FastAPI 进程内。服务不运行时，APScheduler 不会触发任务；kill switch 激活时，盘前、盘后和止损检查会自动跳过。

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、Uvicorn、SQLAlchemy |
| 前端 | React 18、Vite、TailwindCSS、TradingView Lightweight Charts |
| 数据 | SQLite、AkShare、efinance、yfinance、pandas |
| 量化 | LightGBM、scikit-learn、Backtrader、Qlib 兼容数据链路 |
| LLM | Anthropic SDK、OpenAI SDK、本地 CLI provider 抽象 |
| 调度 | APScheduler |
| 推送 | Bark |
| 工程 | pytest、ruff、mypy、pre-commit、Docker、GitHub Actions |

### 文档中心

| 文档 | 内容 |
|---|---|
| [PROJECT.md](PROJECT.md) | 项目索引、里程碑和关键文件导航 |
| [STATUS.md](STATUS.md) | 当前快照、信号权重、调度、测试和启动命令 |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑和重要变更 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中任务、未来规划和后置事项 |
| [PAPER_TRADING.md](PAPER_TRADING.md) | 纸上交易测试规则和记录索引 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、测试要求和贡献流程 |

### 项目结构

```text
stock-sage/
├── PROJECT.md                     项目索引
├── STATUS.md                      当前运行快照
├── CHANGELOG.md                   已完成里程碑
├── docs/ROADMAP.md                进行中与未来规划
├── docs/assets/architecture.svg   README 架构图
├── PAPER_TRADING.md               纸上交易索引
├── paper_trading/                 纸上交易测试记录与统计
├── backend/
│   ├── api/                       FastAPI 路由与 schemas
│   ├── data/                      行情、新闻、财报、QFII、质量、PIT 数据层
│   ├── analysis/                  技术因子、情感、Qlib、timing/regime
│   ├── decision/                  信号聚合、记忆上下文、策略语言
│   ├── agents/                    长期团、多 Agent 流水线、组合与风控
│   ├── backtest/                  回测、walk-forward、统计显著性、实验脚本
│   ├── memory/                    ai_memory、audit_log、摘要、备份、反偏差
│   ├── portfolio/                 仓位、组合权重、trailing stop
│   ├── research/                  手动深度研究
│   ├── notification/              Bark 推送
│   ├── ops/                       kill switch
│   ├── scheduler.py               APScheduler 任务
│   └── main.py                    FastAPI 入口
├── frontend/
│   └── src/
│       ├── pages/                 看板、个股、复盘、持仓、聊天、配置
│       └── components/            图表、证据卡、信号卡、新闻侧栏
└── tests/                         pytest 测试套件
```

### 未来规划

**近期**

- 完成 M2 纸上交易测试 1 收盘汇总，并启动测试 2 两个月强验证。
- 用真实交易样本对比系统建议、人工操作、止盈止损和持仓周期。
- 持续校准 entry threshold、exit 逻辑、trailing stop 和仓位上限。

**中期**

- 只有在 M2/M3 独立验证通过后，才考虑小权重恢复 Qlib，例如 quant 0.1 灰度。
- Qlib 恢复路线坚持离线实验：因子版本、训练窗口、验证窗口、IC/ICIR、分层单调性和交易成本后收益。
- 引入 Alembic baseline，逐步替代当前 `create_all + runtime patch` 的轻量迁移方式。
- 从 OpenAPI 生成 TypeScript types/client，优先覆盖高频前端页面。
- 调度可进一步迁出 FastAPI 进程，使用 `backend.scheduler_worker` 配合 launchd/systemd/supervisor。

**后置**

- LangGraph 重构多 Agent pipeline，触发条件是测试 2 有足够样本且 path B 明显优于 path A。
- 完整 FinMem 替换旧决策记忆，触发条件是记忆深度对收益/回撤有可验证改善。
- 美股扩展保持后置，等待 A 股主线稳定且用户明确需要。
- QMT/miniQMT 自动化执行保持后置，只有纸上交易和 holdout 通过后再讨论半自动或自动交易。

### 风险声明

StockSage 是个人研究和辅助决策工具，不构成投资建议。系统不会自动下单，LLM 不做价格预测，止盈止损由 ATR 公式和风险约束生成。任何交易决策和资金风险均由使用者自行承担。

---

## English Version

[Overview](#overview) · [Features](#feature-highlights) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Docs](#documentation) · [Roadmap](#roadmap)

### Overview

StockSage is a personal A-share research and decision-support workstation. It stores market data, news, fundamentals, QFII holdings, index data and manual positions in local SQLite, then combines technical signals, LLM news sentiment, long-term analyst labels, risk management and portfolio constraints into auditable trading suggestions.

The system is intentionally advisory only. It does not predict prices, does not place orders and does not make the final investment decision for the user.

The current default production profile is `new_framework`: 60% technical signal, 40% LLM sentiment and 0% Qlib quant weight. The Qlib/LightGBM engineering pipeline is available, but recent expanded validation did not pass the alpha gate, so quant remains disabled in production.

### Product Preview

![StockSage System Architecture](docs/assets/architecture.svg)

### Architecture

1. Data sources: AkShare, fundamentals/QFII, market-cap and flow snapshots, news feeds, manual positions and runtime config.
2. Storage: SQLite keeps prices, news, signals, positions, reviews, chat history and memory. Point-in-time access reduces look-ahead bias.
3. Analysis: technical indicators, news source audit, LLM sentiment, offline Qlib validation, long-term analyst team and manual deep research.
4. Decision: `backend/decision/aggregator.py` merges signals; the multi-agent pipeline adds research, trading, risk and portfolio constraints.
5. Delivery: FastAPI and React expose the dashboard; Bark sends buy-signal and 14:30 stop-loss alerts.
6. Governance: ai_memory, layered decision memory, audit_log_fts, chat summaries, TTL cleanup and daily backups.

### Current Status

| Milestone | Name | Status |
|---|---|---|
| M0 | System skeleton | Done |
| M1 | Serious validation gates | Done, Sharpe 1.36 / max drawdown 8.6% / profit-loss ratio 2.78 |
| M2 | Paper trading validation | In progress |
| M3 | Credibility audit layer | Done, DSR / PBO / walk-forward / PIT / kill switch |
| M4 | Multi-agent decision layer | Mostly done; LangGraph and full FinMem replacement are deferred |
| M5 | Automated execution | Deferred until paper trading and holdout validation pass |
| M6 | Iteration and expansion | Current scope done, including quant infrastructure and frontend workspace |
| M7 | Engineering and open-source readiness | Done, with CI, Docker, Makefile, pyproject and documentation |
| M8 | Deep research and source audit | Done, manual-only and outside daily signals |
| M9 | Memory integration and governance | Mostly done, including memory admin, audit, summaries and backups |
| M10 | Reliability and product polish | M10.0-M10.4 done; M10.5 deferred |

### Feature Highlights

**Data and Coverage**

- A-share market data, stock news and index synchronization.
- Fundamentals, QFII holdings, market cap, float market cap and fund-flow features.
- Provider registry with fallback and health tracking.
- Data coverage snapshot for active stocks, price coverage, two-year price coverage, fundamentals coverage, 24h news coverage and signal date range.
- Point-in-time reads for training and inference to reduce look-ahead risk.

**Signals and Analysis**

- Technical factors: ATR, RSI, MA, RSRS and regime filters.
- LLM news sentiment scoring with rationale.
- News source audit by source, URL traceability, freshness and duplicate titles.
- Qlib/LightGBM pipeline with technical, PIT fundamental and market-flow features.
- Backtrader, walk-forward, holdout, DSR, PBO, IC significance, threshold sweep and exit experiments.

**Multi-Agent Decision Making**

- Long-term analyst team: sector thesis, Piotroski quality, prosperity indicators and QFII outflow veto.
- Researcher: bull/bear multi-round debate with graceful fallback.
- Research Director: quality review and debate-topic selection.
- Trader: converts evidence into trading suggestions.
- Risk Manager: risk veto, ATR take-profit/stop-loss and kill-switch constraints.
- Portfolio Manager: allocation under single-stock, sector and total exposure limits.

**Frontend Workspace**

- Pulse dashboard with watchlist, latest signals, market snapshot, real positions and activity feed.
- Stock detail page with chart, latest signal, news, evidence, reviews and long-term labels.
- Review center for daily and long-term reviews with Markdown report rendering.
- Position manager with stock search, open/closed positions and realized PnL.
- AI chat with session isolation, confirmation workflow, Markdown replies and SSE streaming.
- Admin page for weights, exposure limits, data backfill parameters, review schedules and memory management.

**Memory and Audit**

- `ai_memory` for long-term rules, risk preferences, research indexes and user preferences.
- Layered decision memory for symbol-level medium-term notes and global long-term reflections.
- `audit_log_fts` for searchable memory, research, recall, backup and action events.
- `should_remember()` heuristic before long-term memory writes.
- User confirmation before chat-triggered memory writes.
- TTL cleanup, daily backup and chat-window summarization.

**Manual Deep Research**

- CLI/API deep research flow with industry researcher, company researcher, risk reviewer, source auditor and report writer.
- Default report path: `docs/research/YYYY-MM-DD-topic.md`.
- Deep research writes an indexed memory pointer but does not create a `Signal` or participate in daily postmarket signals.

### Quick Start

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd stock-sage
pip install ".[dev]"

# 2. Configure environment variables
cp .env.example .env
# Fill ANTHROPIC_API_KEY and optionally BARK_KEY

# 3. Initialize database
python3 backend/data/database.py

# 4. Start backend
PYTHONPATH=. uvicorn backend.main:app --reload

# 5. Start frontend in another terminal
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 for the dashboard. API docs are available at http://localhost:8000/docs.

### Common Commands

| Command | Purpose |
|---|---|
| `make install` | Install Python dev dependencies and frontend packages |
| `make dev` | Start backend dev server |
| `make build` | Build frontend |
| `make test` | Run backend pytest suite |
| `make frontend-test` | Run frontend node:test suite |
| `make verify` | Run lint, typecheck, backend tests, frontend tests and frontend build |
| `make coverage-snapshot` | Print current data coverage snapshot |
| `make paper-stats` | Compute paper trading statistics |
| `make docker-up` | Start services with docker compose |

### Documentation

| Document | Description |
|---|---|
| [PROJECT.md](PROJECT.md) | Project index, milestones and key file map |
| [STATUS.md](STATUS.md) | Current snapshot, signal weights, schedules, tests and startup commands |
| [CHANGELOG.md](CHANGELOG.md) | Completed milestones and major changes |
| [docs/ROADMAP.md](docs/ROADMAP.md) | In-progress work, roadmap and deferred items |
| [PAPER_TRADING.md](PAPER_TRADING.md) | Paper trading rules and record index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, test expectations and contribution flow |

### Roadmap

**Near term**

- Finish the M2 test-1 closing summary and start the two-month test-2 validation.
- Compare real paper-trading results against system suggestions, manual actions, stop rules and holding periods.
- Keep calibrating entry threshold, exit logic, trailing stop and exposure limits.

**Mid term**

- Consider a small Qlib weight such as 0.1 only after M2/M3 independent validation passes.
- Keep Qlib restoration offline-first: factor versioning, train/validation windows, IC/ICIR, monotonic buckets and cost-adjusted returns.
- Add an Alembic baseline to gradually replace `create_all + runtime patch`.
- Generate TypeScript types/client from OpenAPI for high-traffic frontend pages.
- Move scheduling out of the FastAPI process via `backend.scheduler_worker` and launchd/systemd/supervisor.

**Deferred**

- LangGraph pipeline rewrite only if test-2 provides enough samples and path B clearly beats path A.
- Full FinMem replacement only if memory depth shows verified improvement in return or drawdown.
- US market expansion stays deferred until the A-share path is stable and explicitly needed.
- QMT/miniQMT execution stays deferred until paper trading and holdout validation pass.

### Disclaimer

StockSage is a personal research and decision-support tool, not investment advice. It does not place trades automatically. LLMs do not predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. Users are responsible for all trading decisions and financial risks.
