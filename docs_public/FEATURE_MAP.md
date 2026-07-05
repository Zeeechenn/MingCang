# Feature Map

这页是明仓的功能目录。每个功能都说明：它是什么、从哪里进入、会不会写入、是否影响正式信号、需要什么配置。

状态含义：

- **常用**：普通用户可直接使用。
- **需确认**：会写 DB、调外部服务、跑重任务或改配置。
- **只读**：只查看，不改状态。
- **影子**：研究参考，不覆盖官方信号。
- **休眠**：代码存在，但默认不参与生产决策。
- **维护者**：主要给开发、验证、排障和发布使用。

## 1. 启动与运行

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Demo 启动 | 创建示例数据库并启动后端与前端，让用户不用配置 key 就能体验首页信号、行情、示例持仓、复盘和记忆候选。 | `make demo`, `mingcang demo` | 常用 | 写 demo DB；不影响真实信号；不需要 key。 |
| 安装脚本 | 安装命令行入口和本地运行环境。 | `scripts/install.sh` | 常用 | 写本机环境；不写交易数据。 |
| 开发启动 | 启动 FastAPI 后端和 Vite 前端。 | `make dev`, `cd frontend && npm run dev` | 维护者 | 本地服务；不改信号。 |
| 健康检查 | 检查 DB、agent mode、watchlist、positions、memory 摘要是否可读。 | `mingcang doctor`, `backend.agent.cli health` | 常用/只读 | 不写入；不需要 key。 |
| 项目上下文 | 一次性读取项目概况，包括自选、持仓、记忆、配置摘要。 | `mingcang project`, `project-context` | 常用/只读 | 不写入。 |
| 单股上下文 | 读取单只股票的信号、新闻、研究、记忆上下文。 | `mingcang stock <symbol>`, `stock-context` | 常用/只读 | 不写入；不改信号。 |
| 全局数据上下文 | 按 market/symbol/intent 读取 A/HK/US global data envelope。 | `global-data` CLI, `/api/system/global-data` | 只读 | HK/US observe-only；不进 CN 官方信号。 |

## 2. 前端页面

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| 脉冲页 | 自选和候选池首页，显示关注标的、最新状态、搜索入口和进入单股详情的路径。 | `/` | 常用 | 添加/移除自选会写 DB；不改信号。 |
| 单股详情页 | 单票研究主界面，聚合价格、信号、新闻、证据、长期标签、research copilot 和记忆。 | `/stock/:symbol` | 常用 | 主要只读；刷新研究类操作需确认。 |
| 复盘页 | 展示每日复盘、长期复盘、历史复盘和复盘详情。 | `/reviews` | 常用 | ensure review 会写 review；不直接改信号。 |
| 持仓页 | 记录和查看持仓、成本、市值、浮盈亏、closed/open 状态和市场分组。 | `/positions` | 常用/需确认 | 写 positions；不自动交易。 |
| 聊天页 | 项目内 AI 助手，支持会话、流式回答、项目证据读取和 pending action。 | `/chat` | 常用/需确认 | 生成候选动作；确认后才写入。 |
| 配置页 | 展示和编辑系统配置草稿，包括权重、阈值、LLM、数据覆盖、kill switch。 | `/admin` | 需确认 | 部分操作可能影响正式信号。 |
| 回测入口 | 导航中预留的未来页面，当前回测主要在 backend tools。 | nav placeholder | 休眠 | 不可作为已上线 UI 功能宣传。 |

## 3. 自选、股票和持仓

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| 股票搜索 | 按代码或名称搜索股票，辅助添加自选。 | `/api/stocks/search` | 常用/只读 | 不写入。 |
| 添加自选 | 将标的加入关注列表，并记录用户关注的 stock memory。 | `watchlist.add`, `/api/watchlist` POST | 常用/需确认 | 写 Stock 和 stock_memory；不买入。 |
| 移除自选 | 将标的从 active watchlist 中移除。 | `watchlist.remove`, `/api/watchlist/{symbol}` DELETE | 常用/需确认 | 写 Stock.active；不改信号。 |
| 自选列表 | 展示当前 active 股票和每只股票的摘要。 | `/api/watchlist`, 脉冲页 | 常用/只读 | 不写入。 |
| 添加持仓 | 记录用户持仓或模拟持仓，包括数量、成本、市场、止损止盈。 | `position.add`, `/api/positions` POST | 常用/需确认 | 写 positions；高风险；不接券商。 |
| 修改持仓 | 更新数量、成本、状态、备注、止损止盈。 | `/api/positions/{id}` PATCH/POST | 常用/需确认 | 写 positions；不自动交易。 |
| 关闭持仓 | 把持仓改为 closed 并记录已实现盈亏相关字段。 | positions API | 常用/需确认 | 写 positions；不下单。 |
| 删除 closed 持仓 | 清理已关闭持仓记录。 | positions API | 需确认 | 写 DB；不影响信号。 |
| 组合汇总 | 汇总 CN/HK/US 市值、成本、浮盈亏和持仓数。 | 持仓页 | 常用/只读 | 不写入。 |

## 4. 信号系统

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| 最新信号 | 返回单股最新建议、综合分、分项分、止损止盈。 | `/api/signals/{symbol}/latest` | 常用/只读 | 读 signals；正式信号展示。 |
| 历史信号 | 返回单股历史信号列表。 | `/api/signals/{symbol}` | 常用/只读 | 不写入。 |
| 信号评估 | 回看信号表现，用于理解历史命中和偏差。 | `/api/signals/eval/{symbol}` | 常用/只读 | 不改生产。 |
| 证据链 | 展示生成信号时的 decision run 和 evidence。 | `/api/signals/{symbol}/evidence` | 常用/只读 | 不写入。 |
| 技术信号 | 用 MACD、RSI、趋势、成交量等技术因子生成技术分。 | `backend/analysis/technical.py` | 常用 | 当前正式权重 0.6。 |
| 情绪信号 | 用新闻情绪和事件分类生成 sentiment score。 | `backend/analysis/sentiment.py` | 常用/需 Key 或缓存 | 当前正式权重 0.4。 |
| 量化信号 | Qlib/LightGBM 因子路径。 | `backend/analysis/qlib_engine.py` | 休眠/维护者 | 当前权重 0.0，不进正式信号。 |
| 信号聚合 | 将技术、情绪、量化分聚合成最终建议和分数。 | `backend/decision/aggregator.py` | 常用 | 影响正式信号。 |
| 信号语言 | 统一 buy/watch/avoid 等建议文案和阈值解释。 | `backend/decision/signal_policy.py` | 常用 | 影响用户理解。 |
| 决策 harness | 组织 decision run、research state、evidence、复盘归因。 | `backend/decision/harness.py` | 常用/维护者 | 可能写 run/evidence。 |

## 5. 研究系统

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Research State | 单股研究状态，连接 dossier、copilot、case 和记忆。 | `/api/research/{symbol}` | 常用/影子 | 研究态；不直接改信号。 |
| Dossier | 生成个股案卷，整理股票信息、新闻、证据和研究上下文。 | `/api/research/{symbol}/dossier` | 常用/影子 | 读多写少；不改信号。 |
| Research Prepare | 准备某只股票的研究上下文和基础记录。 | `research.prepare` | 需确认 | 可能写 research state。 |
| Research Copilot | 单股研究助手，提出风险、反问、下一步研究建议。 | `research.copilot` | 影子/需确认 | 可调用 LLM；不覆盖信号。 |
| Deep Research | 对公司、主题或赛道做深度研究，生成本地研究输出和来源审计。 | `research.deep.run` | 需确认 | 可能调用搜索/LLM；写研究结果；不改信号。 |
| 多空辩论 | bull/bear 多轮观点、反驳和裁定，用于暴露分歧。 | `backend/agents/researcher.py` | 影子 | LLM 成本；不进正式信号。 |
| Research Director | 评估研究质量、指出缺口、下达辩论议题。 | `backend/agents/director.py` | 影子 | 不直接改信号。 |
| Risk Manager | 从风险角度审查信号、数据不足、市场环境和记忆风险。 | `backend/agents/risk_manager.py` | 常用/影子 | 可影响建议约束，但不能制造 alpha。 |
| Trader Agent | 交易视角 agent，辅助解释入场/观察/回避。 | `backend/agents/trader.py` | 影子 | 不自动下单。 |
| Portfolio Manager Agent | 组合层视角，辅助看集中度、仓位和组合风险。 | `backend/agents/portfolio_manager.py` | 影子/常用 | 不自动调仓。 |
| Long-term Team | 长期分析师团队聚合慢变量标签。 | `long_term.run` | 需确认/影子 | 需要数据/LLM；默认不直接改信号。 |
| track-analyst Analyst | 把 track-analyst 类外部判断作为 imported thesis 的输入。 | long-term / M45 importer | 影子/需确认 | 需要来源和失效条件。 |
| 景气 Analyst | 用行业景气位置辅助长期判断。 | `jingqi_analyst.py` | 影子 | 不直接买入。 |
| Piotroski Analyst | 用财务质量评分辅助长期判断。 | `piotroski_analyst.py` | 影子 | 依赖财务数据。 |
| QFII Flow Analyst | 用 QFII 减仓等作为反向规避参考。 | `qfii_flow_analyst.py` | 影子 | 只做风险参考。 |
| ForwardThesis | 记录外部/人工论题、失效条件、跟进指标和复盘节奏。 | research routes, M45 importer | 影子/需确认 | 写 draft thesis；不改信号。 |
| Thesis Ledger | 轻量论题账本，适合简单 symbol/title/kill_conditions/status。 | `thesis_ledger.py` | 影子/维护者 | 形状较薄，复杂论题优先 ForwardThesis。 |
| Theme Hypothesis | 主题/赛道假设和受益标的分层。 | `theme_hypothesis_engine.py` | 休眠/影子 | 不进正式信号。 |
| Stress Test | 对研究结论做证据约束下的压力测试。 | `stress_test.py` | 影子 | 不直接写正式建议。 |
| Review Loop | 把研究结果接到 ReviewCase 和记忆促进。 | `review_loop.py` | 影子/需确认 | 写 ReviewCase 或候选。 |
| Universe Guard | 防止动态股票池和幸存者偏差误导验证。 | `universe_guard.py` | 维护者 | 验证/研究边界。 |
| Gate-B Tracker | prospective tracker 实验路径。 | config `gate_b_tracker_enabled` | 休眠 | 默认关闭，不影响决策。 |

## 6. 记忆系统

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Memory Overview | 展示记忆概况、数量、健康和最近记录。 | `/api/memory/overview` | 常用/只读 | 不写入。 |
| AI Memory | 保存全局偏好、规则、风险提醒和项目级记忆。 | `memory.write`, `backend/memory/ai_memory.py` | 需确认 | 写记忆；不自动 trusted。 |
| Stock Memory | 保存某只股票相关的经验、风险、研究指针和用户偏好。 | `stock_memory.write`, stock memory API | 需确认 | 写 stock_memory；可进入上下文。 |
| Memory Context | 按 symbol/query/task_type 取 prompt-ready 记忆上下文。 | `memory-context`, `/api/memory/stock/{symbol}/context` | 常用/只读 | 不写入。 |
| L0 Atoms | 原子记忆，带 trust_state、source、scope、evidence。 | `/api/memory/l0/atoms` | 常用/需确认 | 写入需确认；可信度分层。 |
| L0 Context | 根据任务取 L0 相关上下文。 | `/api/memory/l0/context` | 只读 | 不写入。 |
| Memory Scenarios | 场景化记忆，用于把经验绑定到类似市场或研究场景。 | memory layered | 影子/维护者 | 不直接改信号。 |
| Audit Log | 记录记忆写入、使用和修改历史，支持排查记忆污染。 | `/api/memory/audit` | 维护者/只读 | 不改信号。 |
| Promotion Candidate | 从复盘产生待确认记忆候选。 | `/api/research/memory-candidates` | 需确认 | 用户确认后才升级。 |
| Memory Backup | 备份记忆，避免本地数据丢失。 | `backend/memory/backup.py` | 维护者 | 写备份文件。 |
| Memory Summarizer | 对记忆进行摘要，降低上下文膨胀。 | `backend/memory/summarizer.py` | 维护者/影子 | 可能写摘要。 |
| Bias Override | 对已知偏差做显式覆盖或提醒。 | `backend/memory/bias_override.py` | 影子 | 用于风险提醒。 |
| Should Remember | 判断某条内容是否值得记忆。 | `backend/memory/should_remember.py` | 影子 | 不直接写入，辅助候选。 |
| Evolution Trace | 记忆自进化轨迹：三时间戳双时间轴 + 七仓 namespace，记录记忆从产生到确认/归档的演进。 | `backend/memory/evolution_trace.py` | 维护者/影子 | 治理=LLM 初审 + 人工复核。 |
| Task Capsule | 盘后自动落任务胶囊，沉淀当日决策上下文供后续检索。 | 盘后链 | 维护者 | 写胶囊；不改信号。 |
| Context Governor | 常驻 + 检索两层记忆治理：预算裁剪、注入去重，控制上下文膨胀。 | `backend/memory/context_governor.py` | 维护者/影子 | 只治理注入，不改信号。 |

## 7. 新闻和数据

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| 行情数据 | 读取和缓存 A 股价格，用于图表、技术信号和回测。 | `backend/data/market.py`, `/api/prices/{symbol}` | 常用 | 写 prices；影响信号。 |
| Provider Registry | 管理 provider 顺序、fallback 和 metadata。 | `backend/data/providers.py` | 常用/维护者 | 影响数据来源。 |
| 数据覆盖 | 展示价格、新闻、provider、新鲜度和覆盖率。 | `/api/system/data-coverage` | 常用/只读 | 不写入。 |
| Evidence Lookahead Check | 常驻反穿越 / 证据可信度检查，区分 pass、warning、blocked。 | `mingcang evidence lookahead-check` | 维护者/只读 | 不写入、不调用 LLM/API；warning 只披露，blocked 不自动 promotion。 |
| 外部数据源目录 | 显示可选外部源和可达性探针。 | `/api/system/external-data-sources` | 只读/维护者 | 探针可能触网。 |
| 新闻抓取 | 抓取股票相关新闻并入库。 | `backend/data/news.py`, `/api/news/{symbol}` | 常用/需 Key 或 provider | 写 news；情绪会影响信号。 |
| 新闻审计 | 给新闻来源、标题、时效和质量打审计标签。 | `backend/data/news_audit.py` | 常用/维护者 | 影响新闻可信度。 |
| 新闻缓存 | 回测或批处理用新闻缓存。 | `backend/backtest/news_cache.py` | 维护者 | 写缓存；不直接生产。 |
| 情绪缓存 | 保存 LLM 新闻情绪结果，避免重复调用。 | sentiment cache tools | 常用/维护者 | 情绪分影响信号。 |
| Tavily 补充 | DB 新闻不足时补充实时搜索。 | `TAVILY_API_KEY` | 需 Key/需确认 | 可能触网和花费。 |
| Anspire 搜索 | deep research 或严格新闻抓取使用。 | `ANSPIRE_API_KEY` | 需 Key/需确认 | 可能触网和花费。 |
| 财务指标 | 提供长期研究、Piotroski 和质量判断所需财务数据。 | `backend/data/fundamentals.py` | 常用/研究 | 影响长期研究。 |
| QFII 持仓 | 读取 QFII 前十大流通股东变化，做反向规避参考。 | `backend/data/qfii_holdings.py` | 影子 | 不做正向加分。 |
| PIT Guard | 确保研究和验证不使用未来数据。 | `backend/data/point_in_time.py` | 维护者 | 保护验证可信度。 |
| Tushare QFQ | 可选前复权行情 fallback。 | `TUSHARE_TOKEN`, `tushare_qfq_enabled` | 可选/默认关闭 | 可能影响价格口径。 |
| TickFlow | 可选行情/数据 provider。 | TickFlow config | 可选/默认关闭 | 需 key。 |
| iFinD MCP | observe-only iFinD MCP 客户端和探针。 | iFinD config | 可选/observe-only | 需 token；默认不进生产。 |
| Global Data | CN/HK/US 七层数据能力目录和 envelope。 | `/api/system/global-data`, `global-data` CLI | 只读 | HK/US 不进官方信号。 |
| Universe | 股票池候选、去重、流动性过滤和批量回填。 | `backend/data/universe.py` | 维护者 | 影响扫描范围。 |

## 8. 风控、组合和公式

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| ATR 固定止损 | 用 ATR period 和 multiplier 计算止损参考线。 | config / signal output | 常用 | 影响风险建议。 |
| ATR 移动止损 | 用 trailing ATR 保护趋势浮盈。 | `backend/portfolio/trailing_stop.py` | 常用 | 默认启用；不自动卖出。 |
| 固定止盈参考 | 用 risk/reward ratio 展示止盈参考。 | config / signal output | 常用 | 默认不强制平仓。 |
| 单股仓位上限 | 限制单只股票最大仓位。 | `max_position_per_stock` | 常用 | 影响组合建议。 |
| 行业仓位上限 | 限制同一行业集中度。 | `max_position_per_sector` | 常用 | 影响组合建议。 |
| 总权益上限 | 限制股票总仓位。 | `max_total_equity_pct` | 常用 | 影响风险暴露。 |
| 新信号试错仓 | 给新信号映射初始小仓位。 | `new_signal_trial_pct` | 常用 | 影响建议仓位。 |
| Regime Filter | 根据市场环境对信号做过滤或衰减。 | `regime_filter_enabled` | 常用 | 影响正式信号。 |
| RSRS | 用 RSRS z-score 判断市场强弱。 | `analysis/timing/rsrs` | 常用 | 可影响风控。 |
| Diffusion | 用板块/市场扩散度判断风险环境。 | `analysis/timing/diffusion` | 常用 | 可影响衰减。 |
| ADX Filter | 震荡市过滤器。 | `adx_filter_enabled` | 可选/默认关闭 | 开启后影响信号。 |
| Kill Switch | 手动触发系统熔断，阻止风险动作继续。 | `/api/system/kill-switch/*`, 配置页 | 常用/需确认 | 写系统状态；保护边界。 |
| Bark 推送 | iOS 推送提醒。 | `BARK_KEY` | 可选 | 需 key；可能发送通知。 |
| LLM 预算报警 | 监控 LLM usage，超过预算可提醒。 | `/api/system/llm-usage`, config | 常用/维护者 | 不改信号。 |

## 9. AI Chat、Agent 和自动化

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| AI Chat | 项目内问答助手，读取项目证据和上下文。 | `/chat`, `/api/ai/chat` | 常用/需 Key 或 local CLI | 不自动执行动作。 |
| Streaming Chat | 流式返回准备、运行、证据读取和 token 阶段。 | `/api/ai/chat/stream` | 常用 | 不写入，除非 action。 |
| Chat Sessions | 保存/读取/归档 AI 对话会话。 | `/api/ai/sessions` | 常用 | 写 chat session。 |
| Pending Action | AI 只生成候选动作，等待用户确认。 | `/api/ai/actions/{id}` | 常用/需确认 | 确认前不执行。 |
| Confirm Action | 用户确认后执行 action registry 里的写操作。 | `/api/ai/actions/{id}/confirm` | 需确认 | 取决于 action 风险。 |
| Action Registry | 统一定义可执行动作、schema、风险和权限。 | `backend/agent/action_registry.py` | 维护者 | 是写入动作总闸。 |
| Agent CLI | 给 Codex/Claude/Cursor/Pi 等本地 agent 的命令桥。 | `backend.agent.cli` | 常用/维护者 | 读写取决于命令。 |
| MCP Server | 将明仓上下文和工具暴露给 MCP 客户端。 | `backend/agent/mcp_server.py` | 维护者 | 受安全策略约束。 |
| HTTP Guard | 控制 remote agent HTTP access。 | `backend/agent/http_guard.py` | 维护者 | 防误写。 |
| Local/Remote Security | 区分本地可信模式和远程 API key / allowlist。 | `backend/agent/security.py` | 常用/维护者 | 远程写必须显式允许。 |

## 10. Action 列表

| Action | 功能说明 | 风险 | 是否确认 | 写入内容 |
|---|---|---|---|---|
| `watchlist.add` | 添加自选，并记录用户关注记忆。 | medium | 是 | Stock / stock_memory |
| `watchlist.remove` | 移除 active 自选。 | medium | 是 | Stock.active |
| `position.add` | 添加持仓记录。 | high | 是 | Position |
| `config.update` | 更新运行配置。 | high | 是 | Runtime config |
| `review.daily.ensure` | 确保每日复盘存在。 | low | 是 | Review |
| `review.long_term.ensure` | 确保长期复盘存在。 | low | 是 | Review |
| `memory.write` | 写通用项目记忆。 | high | 是 | AI memory / optional stock memory |
| `stock_memory.write` | 写股票相关记忆。 | high | 是 | Stock memory |
| `research.prepare` | 准备单股研究状态。 | medium | 是 | Research state |
| `research.copilot` | 刷新研究 copilot。 | high | 是 | Research state / LLM output |
| `research.deep.run` | 运行深度研究。 | high | 是 | Research artifacts |
| `long_term.run` | 运行长期分析师团队。 | high | 是 | Long-term label / research output |

## 11. 复盘、报告和导出

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| 每日复盘 | 生成当天信号、新闻、持仓、行动和异常总结。 | `review.daily.ensure`, `/api/reviews/daily/ensure` | 常用/需确认 | 写 Review。 |
| 长期复盘 | 总结长期论题、慢变量和周度/阶段性变化。 | `review.long_term.ensure` | 常用/需确认 | 写 Review。 |
| 复盘历史 | 浏览历史 review 列表和详情。 | `/api/reviews`, `/api/reviews/{id}` | 常用/只读 | 不写入。 |
| 盘后 HTML 报告 | 导出可读盘后 HTML。 | `/api/export/postmarket-review.html` | 常用 | 不改信号。 |
| 盘后 Word 报告 | 导出 Word 兼容报告。 | `/api/export/postmarket-review.html?format=word` | 常用 | 不改信号。 |
| 信号 CSV | 导出 signals。 | `/api/export/signals.csv` | 常用 | 只读导出。 |
| 持仓 CSV | 导出 positions。 | `/api/export/positions.csv` | 常用 | 只读导出。 |
| 复盘 CSV | 导出 reviews。 | `/api/export/reviews.csv` | 常用 | 只读导出。 |
| 覆盖率 CSV | 导出 coverage、warning count、warning codes 和 CN 日线 fallback 链。 | `/api/export/coverage.csv` | 常用 | 只读导出。 |

## 12. Scheduler 和工作流

说明：盘前/盘中/盘后/周末的日常操作现由 M63 六命令编排（见 §16）；`backend/jobs/*` 为其底层 job，`m63_daily --mode postmarket` 内部已编排盘后链。

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Scheduler | 定时注册和管理盘前/盘后/周末 job。 | `backend/scheduler.py` | 维护者 | 默认关闭。 |
| Premarket Job | 盘前同步/检查数据、新闻、指数和覆盖率。 | `backend/jobs/premarket.py` | 需确认 | 可能写 prices/news/index。 |
| Intraday Job | 盘中只读缓存、快速检查单股和止损。 | `backend/jobs/intraday.py` | 常用/只读 | 默认不触网。 |
| Postmarket Job | 盘后全市场信号、复盘、导出、通知。 | `backend/jobs/postmarket.py` | 需确认 | 写 signals/reviews/memory。 |
| Weekend Job | 周末长期标签、周度反思和报告。 | `backend/jobs/weekend.py` | 需确认 | 写 long-term/reviews/memory。 |
| Workflow CLI | 输出各工作流的 side effects 和 operator command。 | `premarket/intraday/postmarket/weekend` CLI | 常用 | 默认 dry-run 合同。 |

## 13. 量化、回测和验证

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Qlib Engine | 量化因子训练/预测路径。 | `backend/analysis/qlib_engine.py` | 休眠/维护者 | 当前不进正式信号。 |
| Qlib Data | 构建 Qlib 特征，包括技术和 PIT 基本面。 | `backend/data/qlib_data.py` | 维护者 | 验证用途。 |
| Kronos | 可选时序模型路径，需要额外依赖/GPU。 | `kronos_enabled`, M26/M27 tools | 休眠 | 默认关闭。 |
| Kronos Losses | 记录或评估 Kronos loss。 | `backend/analysis/kronos_losses.py` | 维护者 | 不进生产。 |
| Backtrader Eval | 回测策略表现。 | `backend/backtest/backtrader_eval.py` | 维护者 | 不改生产。 |
| Walk-forward | 滚动前向验证。 | `backend/backtest/walk_forward.py` | 维护者 | 不改生产。 |
| Exit Sweep | 扫描止损/止盈/退出参数。 | `backend/backtest/exit_sweep.py` | 维护者 | 只给证据。 |
| Threshold Sweep | 扫描入场阈值。 | `backend/backtest/sweep_threshold.py` | 维护者 | 只给证据。 |
| Portfolio Eval | 组合层回测和风险评估。 | `backend/backtest/portfolio_eval.py` | 维护者 | 不改真实持仓。 |
| Compare Paths | 比较不同决策路径。 | `backend/backtest/compare_paths.py` | 维护者 | 不改生产。 |
| Alphalens/Qlib | 因子分析和显著性辅助。 | `backend/backtest/alphalens_qlib.py` | 维护者 | 不改生产。 |
| DSR / PBO / IC | 统计显著性、过拟合和信息系数验证。 | `backend/backtest/statistics/` | 维护者 | 验证用。 |
| M29 Evidence Ledger | 汇总 alpha evidence ledger。 | `backend/tools/m29_evidence_ledger.py` | 维护者/只读 | non-promoting。 |
| M29 Hypothesis Registry | 预注册 alpha 假设。 | `backend/tools/m29_hypothesis_registry.py` | 维护者 | 不直接 promotion。 |
| M29 Shadow Validation | 跑只读 shadow validation。 | `backend/tools/m29_shadow_validation.py` | 维护者 | 不改正式信号。 |
| M29 Provenance Audit | 审计 price/artifact provenance。 | `backend/tools/m29_provenance_audit.py` | 维护者/只读 | 不改生产。 |
| M29 Forward Readiness | 判断是否 ready 追加 forward shadow。 | `backend/tools/m29_forward_readiness.py` | 维护者/只读 | 不改生产。 |
| M29 Price Refresh | 刷新 close-confirmed price/provenance，默认 dry-run。 | `backend/tools/m29_price_coverage_refresh.py` | 需确认 | `--execute` 才写 prices。 |
| Paper Trading Stats | 纸面交易统计和归因。 | `paper_trading/` | 维护者 | 不接真实券商。 |

## 14. 系统配置和模型

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Runtime Config | 读取/更新当前运行配置。 | `/api/system/runtime-config` | 常用/需确认 | 更新可能影响信号。 |
| System Status | 系统状态、权重、scheduler、provider 等摘要。 | `/api/system/status` | 常用/只读 | 不写入。 |
| System Health | DB、数据、记忆、关键组件健康。 | `/api/system/health` | 常用/只读 | 不写入。 |
| Initialize Status | 初始化状态检查。 | `/api/system/initialize/status` | 维护者/只读 | 不写入。 |
| Model Status | 模型训练/可用状态。 | `/api/model/status` | 维护者/只读 | 不写入。 |
| Train Model | 触发模型训练。 | `/api/model/train` | 维护者/需确认 | 可能写模型 artifact。 |
| LLM Provider | local_cli / anthropic / openai-compatible provider。 | config | 常用/需 Key | 影响 AI 功能。 |
| Scheduler Config | 定时任务开关和时间。 | config/admin | 维护者/需确认 | 可能启用自动写入。 |

## 15. 开发和质量

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| Full Verify | 跑 ruff、mypy、pytest、frontend tests、build、lint。 | `make verify` | 维护者 | 不改业务数据。 |
| Backend Tests | 后端单元/集成测试。 | `pytest` / Makefile | 维护者 | 测试 DB。 |
| Frontend Tests | React/API helper 测试。 | frontend npm scripts | 维护者 | 不改生产。 |
| Frontend Build | Vite production build。 | `npm run build` | 维护者 | 写 build artifact。 |
| Lint/Format | ruff、ESLint、format checks。 | Makefile | 维护者 | 不改业务行为。 |
| Changelog | 记录已完成历史。 | `CHANGELOG.md` | 常用/维护者 | 文档。 |

## 16. 每日操作闭环（M63 复盘编排 + M59 盘后面板）

面向"每日盘后操作"的工作流层：把触发判断、入场时机、持仓纪律和复盘归因编排成一条可读的日常流程。面板与卡片均为**只读展示 + 人工确认**，不改官方信号、不自动下单。

| 功能 | 功能说明 | 入口 | 状态 | 写入/信号/Key |
|---|---|---|---|---|
| M63 日常编排 | 六个工作流入口把盘前/盘中/盘后/周末/随时研究/喂观点统一成人话命令，盘后 mode 内部编排复盘链与触发路由。 | `m63_daily --mode premarket\|intraday\|postmarket`、`m63_weekly`、`m63_research`、`m63_opinion` | 常用 | 盘后可写复盘/触发队列；盘后决策 mode 走 LLM。 |
| M59 盘后面板 | 盘后决策面板：买入候选 + 持仓体检 + 风险警示 + 财务质量旗标，一屏看清当日操作。 | `m63_daily --mode postmarket`、`m59_panel`、Web `/daily` | 常用/只读 | 只读展示；不改官方信号。 |
| 四条硬规则 | R1 每条风险警示带确定性保护动作（实算止损/减仓比例）；R2 观望结论带可观测再评估触发；R3 持仓体检出 `atr14`/`stop_gap_atr`/`stop_flags`（止损贴身<1.5×ATR、动量股静态止盈标旗）；R4 财务质量旗标进候选与体检。 | m59_panel | 常用 | 影响用户理解，不制造 alpha。 |
| LLM 裁量层 | 候选内选股裁量、清仓决断、加减仓时机、复盘归因提炼；带反方审视步。 | `M59_DISCRETION_ENABLED`（默认关，灰度） | 影子/默认关 | 做裁量不打分；不覆盖官方信号。 |
| 入场条件卡 | V1/V2/V3 给出实算价位/量能/风险线 + 单笔风险预算参考股数（单票模式）。 | 面板 / 条件卡 | 常用/只读 | 展示；`ENTRY_ACCOUNT_SIZE` 空时只给公式。 |
| 入场准备度分 | 四维透明记点 + 否决项；三道校准门未过时如实渲染"仅证据清单"，校准转前向攒样本。 | 面板 | 常用/只读 | 不是预测，是证据清单可视化。 |
| 入场演练场 | 历史触发 PIT 回放 + 随机对照臂 + 分箱校准，验证入场机制。 | `m58_entry_arena` | 维护者/只读 | 零 LLM；只给证据。 |
| 论点触发器 | `ForwardThesis` 为唯一权威存储；validation 触发进研究队列，invalidation 触发出持仓论点风险警示。 | 触发路由 / 研究队列 | 影子/常用 | 出警示，不自动交易。 |
| M60 观察哨 | 盘后确定性检测价格/量能/新高/新闻/板块共振触发，带研究上下文的 LLM 确认层；第二时间入场影子台账 observe-only。 | `m60_watchtower` | 常用/影子 | 检测只读；影子台账不改信号。 |
| 交易级复盘台账 | 开仓记 snapshot（准备度/触发器/条件卡），平仓补结局，周报按准备度 band 归因。 | 复盘链 / `m63_weekly` | 常用 | 写台账；不改信号。 |
| 分散持仓模式 | `PORTFOLIO_MODE=diversified` 提供等权参考 + 否决区 + 集中度视图；`focus` 单票模式为默认、不变。 | `PORTFOLIO_MODE` | 可选 | 只给组合参考。 |
