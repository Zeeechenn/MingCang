# Reference

这页收集命令、API、配置和文件入口。功能解释请看 [Feature Map](FEATURE_MAP.md)。

## 1. CLI

| 命令 | 说明 |
|---|---|
| `mingcang help` | 查看 launcher 帮助。 |
| `mingcang doctor` | 健康检查。 |
| `mingcang demo` | 启动 demo。 |
| `mingcang stock <symbol>` | 查看单股上下文。 |
| `mingcang project` | 查看项目上下文。 |
| `mingcang memory` | 查看记忆摘要。 |
| `mingcang premarket` | 盘前 workflow 合同。 |
| `mingcang intraday --symbol <symbol>` | 盘中只读 workflow 合同。 |
| `mingcang postmarket` | 盘后 workflow 合同。 |
| `mingcang weekend` | 周末 workflow 合同。 |

底层 CLI：

| 命令 | 说明 |
|---|---|
| `python3 -m backend.agent.cli health --pretty` | 读取 agent health。 |
| `python3 -m backend.agent.cli project-context --pretty` | 读取项目上下文。 |
| `python3 -m backend.agent.cli stock-context 300308 --pretty` | 读取单股上下文。 |
| `python3 -m backend.agent.cli memory-snapshot --pretty` | 读取记忆摘要。 |
| `python3 -m backend.agent.cli memory-context --symbol 300308 --query "风险" --pretty` | 读取 prompt-ready 记忆。 |
| `python3 -m backend.agent.cli global-data 300308 --market CN --intent daily_ohlcv --pretty` | 读取 global data envelope。 |
| `python3 -m backend.agent.cli actions --pretty` | 列出 action registry。 |
| `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty` | action dry-run。 |
| `python3 -m backend.agent.cli action <name> --payload-json '<json>' --confirm --pretty` | 确认执行 action。 |

## 2. Frontend Routes

| Route | 页面 |
|---|---|
| `/` | 脉冲 / 自选首页。 |
| `/stock/:symbol` | 单股详情。 |
| `/reviews` | 复盘中心。 |
| `/positions` | 持仓设置。 |
| `/chat` | AI 聊天。 |
| `/admin` | 系统配置。 |

## 3. API Groups

| Group | Representative paths |
|---|---|
| Watchlist | `/api/watchlist`, `/api/long-term/{symbol}` |
| Stocks | `/api/stocks/search` |
| Signals | `/api/signals/{symbol}/latest`, `/api/signals/{symbol}`, `/api/signals/eval/{symbol}`, `/api/signals/{symbol}/evidence` |
| Prices | `/api/prices/{symbol}` |
| News | `/api/news/{symbol}` |
| Research | `/api/research/{symbol}`, `/api/research/{symbol}/dossier`, `/api/research/*` |
| Reviews | `/api/reviews`, `/api/reviews/latest`, `/api/reviews/{id}` |
| Positions | `/api/positions` |
| Memory | `/api/memory/overview`, `/api/memory/list`, `/api/memory/l0/*`, `/api/memory/stock/*` |
| AI | `/api/ai/sessions`, `/api/ai/chat`, `/api/ai/chat/stream`, `/api/ai/actions/{id}` |
| System | `/api/system/runtime-config`, `/api/system/status`, `/api/system/health`, `/api/system/data-coverage`, `/api/system/global-data` |
| Exports | `/api/export/postmarket-review.html`, `/api/export/signals.csv`, `/api/export/positions.csv`, `/api/export/reviews.csv`, `/api/export/coverage.csv` |
| Model | `/api/model/status`, `/api/model/train` |
| Skills | `/api/skills/*` |

## 3.1 Maintainer CLI

| Command | Purpose |
|---|---|
| `mingcang evidence lookahead-check` | Run the standing read-only lookahead trust check. It writes no DB rows, calls no LLM/API provider, and reports pass / warning / blocked without changing official signals. |

## 4. Important Config

| Config | 默认 | 说明 |
|---|---|---|
| `AI_PROVIDER` | `local_cli` | LLM provider。 |
| `DATABASE_URL` | local SQLite | DB 地址。 |
| `WEIGHT_QUANT` | `0.0` | 当前量化不进正式信号。 |
| `WEIGHT_TECHNICAL` | `0.6` | 技术信号权重。 |
| `WEIGHT_SENTIMENT` | `0.4` | 情绪信号权重。 |
| `TRAILING_STOP_ENABLED` | `true` | ATR 移动止损启用。 |
| `TRAILING_ATR_MULT` | `2.5` | 移动止损 ATR 倍数。 |
| `TAKE_PROFIT_EXIT_ENABLED` | `false` | 固定止盈不强平。 |
| `SCHEDULER_ENABLED` | `false` | 默认不自动跑 scheduler。 |
| `KRONOS_ENABLED` | `false` | Kronos 默认关闭。 |
| `ATLAS_ENABLED` | `false` | Atlas 架构默认 dormant。 |
| `TAVILY_API_KEY` | empty | 新闻/搜索补充。 |
| `ANSPIRE_API_KEY` | empty | deep research 搜索。 |
| `TUSHARE_TOKEN` | empty | 可选 Tushare 数据。 |
| `BARK_KEY` | empty | iOS 推送。 |
| `MINGCANG_AGENT_MODE` | `local` | agent guard 模式。 |
| `MINGCANG_AGENT_REMOTE_WRITE_ENABLED` | `false` | 远程写默认关闭。 |

## 5. Key Files

| Path | Purpose |
|---|---|
| `backend/main.py` | FastAPI app。 |
| `backend/config.py` | 配置入口。 |
| `backend/api/routes/` | REST routes。 |
| `backend/data/` | 行情、新闻、财务、provider、DB。 |
| `backend/analysis/` | 技术、情绪、量化分析。 |
| `backend/decision/` | 信号聚合和决策证据。 |
| `backend/research/` | dossier、copilot、deep research、thesis。 |
| `backend/memory/` | ai_memory、stock_memory、audit。 |
| `backend/agent/` | CLI、action registry、MCP、安全边界。 |
| `backend/jobs/` | 盘前/盘中/盘后/周末工作流。 |
| `backend/backtest/` | 回测和统计验证。 |
| `frontend/src/App.jsx` | 前端路由。 |
| `frontend/src/api.js` | 前端 API client。 |
| `frontend/src/pages/` | 前端页面。 |
| `docs_public/FEATURE_MAP.md` | 功能目录。 |
| `STATUS.md` | 当前状态。 |

## 6. Verification

| Command | Purpose |
|---|---|
| `git diff --check` | 检查空白和 patch 基础问题。 |
| `make verify` | 完整验证。 |
| `make frontend-lint` | 前端 lint。 |
| `make frontend-format-check` | 前端格式检查。 |
| `pytest` | 后端测试。 |
