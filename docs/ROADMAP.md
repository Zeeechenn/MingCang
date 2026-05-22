# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情见 `CHANGELOG.md`。此文件只追踪 M2 及以后的未完成任务。

---

## M8 深度研究与来源审计层 ✅（2026-05-17）

### M8.1 新闻来源审计层 ✅
- [x] `backend/data/news_audit.py`：按来源、URL、时效、重复标题打分。
- [x] `backend/data/news.py::get_recent_news_items()`：保留完整证据字段。
- [x] 盘后情感分析前执行轻量审计；审计结果写入 `DecisionRun.input_snapshot.news_audit`。

### M8.2 金融 Agent 模板增强 ✅
- [x] `backend/research/agents.py`：行业研究员 / 公司研究员 / 风险复核员 / 来源审计员 / 研究写作员五段模板。
- [x] 深度研究报告按研究员分工、主题观察、个股快照、基本面快照、风险复核、来源审计、待验证问题组织。
- [x] 该流程只服务专题研究，不改变 `agents/pipeline.py` 的日常信号路径。

### M8.3 记忆质量改进 ✅
- [x] `backend/memory/research_memory.py`：深度研究报告以结构化 JSON 指针写入 `ai_memory`。
- [x] 研究记忆使用 `scope="research"` 与交易/规则记忆隔离。

### M8.4 周末深度研究 / 行业专题研究 ✅
- [x] CLI：`PYTHONPATH=. python3 -m backend.research.deep_research --topic "AI算力产业链" --symbols 300308,300394`
- [x] API：`POST /api/research/deep/run`
- [x] 默认输出：`docs/research/YYYY-MM-DD-主题.md`
- [x] 明确不创建 `Signal`，不接入 `job_postmarket()`，不影响日常复盘信号。

---

## M9 记忆系统接入与治理 ⏳

> 规划背景已收敛到本节：目标是把盘后分层记忆、深度研究索引、聊天窗口、`should_remember`、`ai_memory.remember()` 和 `audit_log` 串成可审计、可治理、可回滚的统一记忆链路。

### M9.0 死代码接电（无 UI，最高优先级）✅（2026-05-19）
- [x] `audit_write` 全链路埋点：`memory_layered.{save_decision_layered,get_layered_context}`、`research_memory.remember_deep_research`（自动）、`ai_memory.{remember,recall,forget}`。
- [x] `should_remember()` 接入 `ai_memory.remember()`，未通过时 `audit_write("memory.skipped", ...)` 记原因；新增 `force=True` 留口子；`should_remember` 白名单扩 `deep_research`/`bias_override`。
- [x] `save_decision_layered` 加可选 `db=None`；`scheduler.py:278` 调用方已传入 db。
- [x] 新增测试 `tests/test_m9_audit_wiring.py`（9 用例）；246 项全套通过。
- [ ] ChatPage 写入接入**延后**到 M9.4（优先保证对话写记忆的二次确认和可审计性）。

### M9.1 修正数据存储事实错误 ✅（2026-05-19）
- [x] 新表 `decision_memory_layered(symbol, layer, content, updated_at)`；layer='long' 全局行用 `__GLOBAL__` sentinel 规避 SQLite `NULL ≠ NULL`。
- [x] 一次性迁移：`migrate_layered_files_to_db()` 扫 `~/.stock-sage/memory/medium_{symbol}.md` + `long_term_reflection.md` 入表，幂等；由 `init_db()` 自动触发；生产 DB 已迁入 80 行 medium。
- [x] `save_medium_term` 双写文件 + DB；`get_long_term_context` 优先读 DB、文件兜底；旧 .md 保留 30 天只读兜底。
- [x] 只读 API：`GET /api/memory/{overview,list,audit,layered}`。
- [x] 测试：`tests/test_m9_layered_db.py`（11 用例）。

### M9.2 AdminPage 记忆管理 ✅（2026-05-19）
- [x] AdminPage 新增"07 · 记忆管理"分区，组件 `frontend/src/pages/MemorySection.jsx`。
- [x] 概览：总数 / 分层行数 / by scope / by category / 最近更新；列表过滤；分层决策记忆只读面板；召回日志 FTS5 搜索。
- [x] 每行操作：删除 / 固定 / 改 TTL / 改 category（`confirm() / prompt()` 二次确认）；**不**暴露 raw value 编辑。
- [x] 后端 `DELETE / POST pin / PATCH` 路由，所有写操作 audit 留痕（`memory.forget/pin/patch`）。
- [x] `npm run build` 通过；风格与现有 AdminPage 一致。

### M9.3 治理 ✅（2026-05-19）
- [x] **窗口摘要器**新模块 `backend/memory/summarizer.py`：超阈值（默认 50）压缩老消息到 `chat_sessions.summary` + `summary_until_id`；再次触发时只压增量；写 `chat.summary` audit。`chat_sessions` 新增 `summary` / `summary_until_id` 列（幂等 ALTER）；接入 `ai.py:_record_message` 末尾，失败不阻塞。
- [x] 过期清理：`expire_stale_memories()` 删超 TTL 行，audit 留完整 value 便于恢复；scheduler cron `daily_memory_expire` 每天 01:00。
- [x] 深度研究召回压缩**天然满足**——`research_memory.remember_deep_research` 只存 indexed JSON `{topic, summary, symbols, report_path}`，从未存原文。
- [x] 测试：`tests/test_m9_governance.py`（9 用例，stub LLM provider）。

### M9.4 对话改写 + ChatPage 接入 ✅（2026-05-19）
- [x] `ai.py:_detect_action` 扩 `memory.write`：识别 "记住/记下来/存进记忆/保存为记忆 X"，按关键词分类 rule/preference/risk，key 用 sha1 自动生成。
- [x] **不直接落库**：候选写入已有 `pending_ai_actions`，AIChatResponse.pending_action 返回前端。
- [x] 前端 ChatPage `pending_action` 二次确认 UI 已通用（line 197-201），memory.write 自动复用，**零前端改动**。
- [x] `confirm_action` 扩 `memory.write` 分发：调 `ai_memory.remember(..., force=True)`（用户已二次确认）。
- [x] 仍**禁止** LLM 改 raw value——元数据修改只走 M9.2 AdminPage。
- [x] 测试：`tests/test_m9_chat_memory_write.py`（8 用例）；全套 287 项通过。

### M9.横向 反偏差与备份（与 M9.0–M9.2 并行可做）
- [x] `ai_memory` 增 `category='bias_override'`，召回链路在 Piotroski 输出后注入（2026-05-19）。
      - `backend/memory/bias_override.py` 提供 `lookup_caveat / set_caveat / seed_default_overrides`。
      - `piotroski_analyst.analyze()` 末尾查一次；命中时把 caveat 加到 `key_findings[0]` 并写入 `raw["bias_caveat"]`；**不覆盖 `label_vote`**，让 LLM 决策链看到原始投票 + 提示后自行判断。
      - 默认种子（`piotroski:规避`）由 `init_db()` 自动幂等写入；生产 DB 已种子完成。
      - `should_remember` 白名单已在 M9.0 扩 `bias_override`，确保写入不被拦截。
      - 测试：`tests/test_m9_bias_override.py`（7 用例），全套 253 项通过。
- [x] 每日 dump `ai_memory` 到 `~/.stock-sage/memory/backups/ai_memory_{date}.json`（2026-05-19）。
      - `backend/memory/backup.py`：`dump_ai_memory` / `cleanup_old_backups`（默认保留 30 天）/ `run_daily_backup`，备份**含已过期行**便于误删恢复；每次执行写一笔 `memory.backup` audit。
      - `scheduler.py` cron `daily_memory_backup` 每天 00:30 触发；首次 dump 已对生产 DB 执行（3 行）。
      - `decision_memory_layered` 文件**暂不**进入备份——M9.1 把分层记忆迁 DB 后再扩。
      - 测试：`tests/test_m9_backup.py`（6 用例）；全套 259 项通过。
- [ ] TTL 默认值上线后读 `audit_log_fts` 命中率回写校准，不硬编码（占位项，需 ≥ 2 周数据积累才能动）。

---

## M10 运行可靠性与产品化优化 ✅（2026-05-20 完成 M10.0-M10.4）

> 来源：2026-05-20 两份项目 review 核验后的优化计划。
> 原则：先修“运行事实是否可信”和“系统是否真的在跑”，再做体验和长期架构升级。
> 明确不做：不立刻恢复 Qlib 生产权重，不立刻迁 PostgreSQL，不为状态管理而引入前端全局 store。

### M10.0 运行事实与文档口径校准（必做 / P0）
- [x] 新增一条覆盖快照生成命令或脚本，输出 active 股票数、价格覆盖、2 年价格覆盖、财报覆盖、24h 新闻覆盖、最新价格日、signals 日期范围。
- [x] `STATUS.md` / `README.md` 不再手写易过期的覆盖数字；改为引用 `GET /api/system/data-coverage` 或生成时间明确的快照。
- [x] 统一验证口径：扩展 `make check` 或新增 `make verify`，覆盖后端 pytest、前端 node tests、frontend build。
- [x] 清理测试结果口径不一致：`STATUS.md` 的 217 passed、`README.md` 的 225 passed 改成同一来源。
- [x] 加轻量入库防线：pre-commit 阻止 `.db` / `.env` / 模型 pickle 等敏感或大文件进入 Git。

### M10.1 调度与通知可靠性（必做 / P0-P1）
- [x] System Health / AdminPage 展示 scheduler 是否启用、最近一次任务、最近一次状态、最近错误。
- [x] 盘前、盘后、止损检查、周训练、每日 memory backup/expire 都记录 `last_run / last_status / last_error`。
- [x] Bark 推送抽出 notification client，增加 timeout、retry、backoff 和结构化结果。
- [x] Bark 失败只写 warning/audit，不影响信号保存、复盘写入和 postmarket 主流程。
- [x] 中期预留独立 worker 入口，例如 `python -m backend.scheduler_worker`，供 launchd/systemd/supervisor 使用。

### M10.2 后端核心模块降复杂度（强烈建议 / P1）
- [x] 拆分 `scheduler.py::job_postmarket`：
      `build_postmarket_context` / `analyze_stock` / `persist_signal` / `notify_signal` / `run_postmarket_batch`。
- [x] `job_postmarket` 输出批处理统计：成功数、跳过数、失败数、推送数。
- [x] 拆分 `database.py` 第一阶段：`session.py` / `models.py` / `schema_runtime.py` / `seed.py`，保留 `database.py` 兼容导出。
- [x] `backend/llm/factory.py` 增加 `reset_provider()`；测试 fixture 自动 reset，避免 provider 单例跨测试污染。

### M10.3 前端关键体验修复（建议 / P1-P2）
- [x] `frontend/src/api.js` 增加 timeout、GET 短重试、错误分类（network / timeout / http / validation）。
- [x] StockDetail 改为渐进加载：主图和最新信号优先，新闻、证据、复盘、长期标签异步补上；辅助接口失败不阻塞首屏。
- [x] Watchlist 管理区增加本地搜索和筛选：symbol / name / industry / 最新信号 / 长期标签 / 持仓中。
- [x] AI Chat 增加 SSE 流式输出；长回复 1 秒内有首字反馈。
- [x] Chat 消息支持 Markdown 渲染，优先复用 `reviewContent.js` 或引入轻量 renderer。

### M10.4 Paper Trading 自动统计（必做 / P1）
- [x] 统一 paper trade 结构：entry、exit、reason、fees、gross/net pnl、holding_days、signal_snapshot。
- [x] 自动计算胜率、平均收益、盈亏比、最大回撤、单笔最大亏损、手续费后收益。
- [x] 按 profile / recommendation / exit_reason 分组统计 test1/test2 表现。
- [x] 每个交易日更新后自动生成 test summary，减少手工维护误差。
- [x] 测试 2 积累 20+ 交易日后，再讨论阈值、exit、权重是否需要调整。

### M10.5 长期工程基础（后置 / P3）
- [ ] 数据库迁移体系：先保留 `create_all + runtime patch`，中期引入 Alembic baseline。
- [ ] 前后端契约：从 OpenAPI 生成 TypeScript types/client，先覆盖高频页面。
- [ ] Qlib 恢复路线只走离线实验：因子版本、训练窗口、验证窗口、IC/ICIR、分层单调性、交易成本后收益。
- [ ] 只有多个窗口验证通过后，才允许小权重灰度，例如 quant 0.1；默认生产继续 `weight_quant=0.0`。

### M10 最小交付包
- [x] 覆盖快照命令 + 文档口径修正。
- [x] scheduler last_run / last_error 状态。
- [x] Bark 重试与失败隔离。
- [x] `job_postmarket` 拆分。
- [x] 前端 API request 层错误分类。
- [x] StockDetail 渐进加载。

---

## M11 Agent-Ready 本地/远程双模式接口 ✅（2026-05-21）

### M11.0 Agent 文档契约 ✅
- [x] `AGENTS.md` 升级为本地 agent 操作手册：本地 Codex / Claude Code 默认信任，可直接跑测试、查 DB、运行纸上交易统计、调用已配置的项目 API。
- [x] `CLAUDE.md` 通过 `@AGENTS.md` 复用共享规则，只保留 Claude Code 特有说明。
- [x] 明确 Codex/Claude 自身 LLM 调用与 StockSage `.env` 中项目运行时 LLM/API key 分离。

### M11.1 项目记忆入口 ✅
- [x] 新增 `backend/agent/context.py`：`stock_sage_context` / `stock_sage_memory_snapshot` / `stock_sage_stock_context`。
- [x] 启动上下文汇总 `ai_memory`、`decision_memory_layered`、`audit_log_fts`、ChatPage 使用情况、`~/.stock-sage/memory` 文件记忆、持仓与自选状态。
- [x] Agent 规则要求交易、测试、研究、复盘前优先读取项目内记忆，而不是只依赖 Codex/Claude 自己的会话记忆。

### M11.2 本地/远程模式保护 ✅
- [x] 新增 `backend/agent/security.py`：本地模式默认放行；远程模式必须显式 `STOCKSAGE_AGENT_MODE=remote`。
- [x] 远程模式要求 `STOCKSAGE_AGENT_API_KEY`；远程写操作默认禁止，只有 `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=true` 才可放行。
- [x] stdio MCP 工具在 remote 模式下要求显式传入 `api_key` 参数；未传或不匹配时拒绝调用。
- [x] `.env.example` 只提供远程 agent 变量占位，不提交真实 key。

### M11.3 MCP 本地工具桥 ✅
- [x] 新增 `backend/agent/mcp_server.py`，通过 MCP 暴露 `stock_sage_project_context`、`stock_sage_memory_snapshot`、`stock_sage_stock_context`、`stock_sage_health`。
- [x] `pyproject.toml` 新增可选依赖组 `agent`，本地可用 `pip install -e ".[agent]"` 后启动 `PYTHONPATH=. python -m backend.agent.mcp_server`。

### M11.4 Agent 运行硬化 ✅
- [x] 未初始化数据库时，agent context / health 返回空 memory、positions、watchlist 和 symbol context，不因缺表退出。
- [x] CI 后端安装 `.[test,agent]`，pytest 覆盖真实 MCP stdio 列工具与 health 调用。
- [x] README / README_EN 记录免费、试用和促销 API key 限额快照，并标注以平台控制台为准。

### M11.5 Portfolio Manager 批处理闭环 ✅（2026-05-22）
- [x] `run_postmarket_batch` 改为先完成当日单股分析，再按当日候选统一调用 `PortfolioManager`，执行单股 / 板块 / 总仓位裁剪。
- [x] 组合层结果不覆盖原始单股证据：`position_pct` 表示最终建议仓位，`trader_position_pct` 保留 Trader/RiskManager 原始仓位，`portfolio_decision` 记录动作和裁剪原因。
- [x] `DecisionRun.final_action` 追加组合层字段；EvidenceCard 展示最终仓位、单股原始仓位和裁剪原因，旧 evidence 记录保持兼容。
- [x] Bark 提示沿用最终 `position_pct`，因此会优先显示组合层裁剪后的建议仓位。

### M11.6 Agent 内核闭环补齐 ✅（2026-05-22）
- [x] 新增 `backend/agent/action_registry.py`，Chat pending action / confirm 执行统一走 registry；每个 action 暴露 `input_schema`、`risk_level`、`requires_confirmation`、`allowed_modes`、`schema_version`。
- [x] HTTP 写路由接入 `backend/agent/http_guard.py`；remote 模式要求 API key，写操作要求 `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=true`，并可用 `STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS` 做 action allowlist。
- [x] `DecisionRun` evidence 追加 step trace：analysts、director、researcher、trader、risk_manager、portfolio_manager；trace 写入失败不阻断主信号路径。
- [x] Chat fallback context 改为 `chat_sessions.summary + summary_until_id 之后的消息 tail`，避免只依赖最近 6 条消息。
- [x] `weekly_long_term_reflect` 接入 APScheduler，默认使用 `SCHEDULE_LONGTERM_DOW/TIME`。

### M11 后续可选
- [ ] 如果需要公网或局域网远程 agent 服务，再单独增加 HTTP/SSE transport、header 鉴权、限流、审计与只读 allowlist。
- [ ] 将更多项目动作封装为明确命名的 MCP 写工具，但保持本地默认信任、远程默认只读。

---

## M12 外部数据源扩展治理 ⏳

### M12.0 候选源可观测接入 ✅（2026-05-22）
- [x] 新增 `backend/data/external_sources.py`：记录 `a-stock-data` / `ftshare-market-data` 的高价值数据集、推荐接入阶段、风险说明和治理策略。
- [x] 新增 `GET /api/system/external-data-sources`：默认只返回 catalog，不联网、不写库、不影响调度和生产信号。
- [x] 显式 `probe=true` 时只运行 side-effect-free 可达性探针；当前先覆盖 `ftshare` 股票列表，用于衡量远端可用性，不注册为行情 provider。
- [x] 测试：`tests/test_external_data_sources.py` 覆盖 observe-only policy、默认离线行为和显式 probe 挂载。

### M12 后续可选
- [ ] 从 `a-stock-data` 只挑 1 个证据型数据集试点，例如两融、龙虎榜或解禁；先进入 evidence / risk review，不进入买卖评分。
- [ ] 对任何新端点先补 provider health / PIT 时间戳 / 字段归一化 / 测试，再考虑写入 SQLite。
- [ ] 连续观测稳定后，再决定是否加入定时任务；默认仍不改变现有 efinance / AkShare / yfinance 行情 fallback 链路。

---

## M2 纸上交易验证 ⏳（旧 Phase 6.5 + 执行计划 D）

详细规则与持仓作为本地验证材料维护，不进入 GitHub。

### M2.1 测试 1（用户主导，2026-05-13 ~ 05-20，1 周）
宽撒网验证系统完整性。**含 5 个交易日强平规则**（仅本测试适用）。

### M2.2 测试 2（人工 / AI 辅助，2026-05-21 ~ 2026-07-21，2 个月强测试）
精选 7 股，阈值 25。**无 5 日强平** — 让趋势完整运行。中期复盘节点：6/3、6/20、7/4。

### M2.3 测试 1 收盘后汇总（2026-05-20）
- [ ] 汇总持仓 / 信号准确率 / 与系统建议的对照

### M2.4 测试 2 启动 checklist（2026-05-21）
- [ ] 启动当日执行 checklist

> 测试 2 收尾时（约 2026-07-21）会有 ≥20 笔真实交易样本，可与 M1 严肃回测、M4.6 多 Agent 对比、M4.8 阈值扫描、M4.9 exit 实验交叉验证。

---

## M4 多 Agent 决策深化 🟡（旧 路线图阶段 C）

**已完成**：
- [x] M4.0 长期分析师团（前 M1.3）— 4 路投票 + 一票否决
- [x] M4.0 `risk_manager.py` — 风险经理对最终建议有否决权
- [x] M4.0 `memory_layered.py` — FinMem 风格分层记忆（部分）
- [x] **M4.1 多轮辩论（2026-05-16）** — `agents/researcher.py::multi_round_debate`
      3 轮 bull→bear→bull-final + adjudicator 裁定；任一轮失败自动降级。
      `settings.multi_round_debate_enabled`（默认 True）/ `multi_round_debate_min_divergence=20.0`。
      12 测试覆盖。辩论 rounds 自动随 Signal.llm_rationale 落地。
- [x] **M4.2 Research Director（2026-05-16）** — `agents/director.py::assess`
      纯规则评估器：检查 4 路 confidence + key_findings → 输出 quality_notes + weak_roles + debate_topic。
      8 测试覆盖。debate_topic 在分歧达标时注入 Round 1 prompt 引导辩论焦点。
- [x] **M4.3 Portfolio Manager（2026-05-16）** — `agents/portfolio_manager.py::manage`
      统筹候选 + 现有持仓 → 按综合分降序贪心分配 → 单股/板块/总仓约束。
      13 测试覆盖。EXIT 平仓、回撤冻结、极小仓位归零、disabled passthrough 全验证。
- [x] **M4.6 并排回测（2026-05-16）** — `backend/backtest/compare_paths.py`
      框架完整（12 测试），CLI 可跑；初次跑 DB（11 信号样本）触发 "数据不足"。
- [x] **任务1 回填 key_events（2026-05-16）** — `backend/backtest/news_cache.py`
      OpenAI 实际回填 21 信号 → 19 成功 / 2 无新闻 / 100% coverage。7 测试覆盖。
      持久 JSON 缓存避免重复 LLM 成本。CLI 新增 `--backfill-news` / `--no-cache`。
- [x] **M4.7 修复 news_analyst（2026-05-16）** — `backend/agents/analyst.py`
      回填后发现 path B 0 trades，根因：news_analyst 关键词稀释（"突破千元"只得 +20，
      而 LLM sentiment +92）。修复：以 LLM sentiment×80 为基线，关键词 ±10 微调；
      扩充关键词表覆盖 新高/新低/净流入出/订单/受益 等常见 A 股语料。13 测试覆盖。
      修复后 path B trades: 0 → 2（与 path A 一致）。
- [x] **任务2 重跑 M4.6（2026-05-16）** — path A 和 path B 综合分差距收敛到 ±1.5 内，
      结构性偏差消除。11 信号样本仍触发"数据不足"，需更多历史样本。

**待做**：
- [ ] **M4.4 LangGraph 重构 pipeline** —— 暂缓。
      M4.7 修复后两路结果几乎一致，多 Agent 架构在此样本上不显优势。
      触发条件：测试2 结束（~6/3）拿到 ≥10 笔真实交易 + path B 显示 Sharpe ≥ path A + 0.3。
- [ ] **M4.5 FinMem 完整替换 `decision_memory.py`** —— 暂缓。
      memory_layered 已部分实现，重写需 ≥30 笔样本证明"记忆深度 → Sharpe 改善"。
- [x] **回填历史 signals（2026-05-16）** — `backend/backtest/backfill_signals.py`
      460 SignalInput / 70 有新闻 / 15.2% 覆盖。结论：M4.7 修复后 path A 和 path B
      在 460 信号上完全等价（35 trades / Sharpe 2.46 / total +280% / drawdown -49%）。
      52 信号 |A-B| > 0.5 但全部 < 3 分，从未翻转 entry 判定。
      → **M4.4 LangGraph / M4.5 FinMem 暂缓**，无数据支持。
- [x] **M4.8 entry_threshold 扫描（2026-05-16）** — `backend/backtest/sweep_threshold.py`
      在 460 信号上扫 9 档阈值（5–45），Sharpe 单调上升到 25 (3.12) 后崩塌（trades→1）。
      最优档 = **25**（19 trades / 57.9% win / Sharpe 3.12 / drawdown -39%）。
      验证 `new_framework_entry_threshold=25` 正确；`test1_entry_threshold=20` 偏低，
      但已无影响（测试 1 收盘 5/20，未在生产开新仓）。7 测试覆盖。
- [x] **M4.9 exit 逻辑实验（2026-05-16）** — `backend/backtest/exit_sweep.py`
      在 19 个 entries（threshold=25）上跑 8 种 exit。Sharpe 排名：
      trailing_atr_2_5x (3.38) > fixed_5d (3.12) > fixed_10d (2.97) > atr_1_5x_3x (2.85) >
      fixed_3d (2.89) > atr_2x_4x (2.73) > atr_2x_3x (2.62) > trailing_atr_2x (2.51)。
      最优 = **trailing_atr_2_5x**（63.2% win / 平均持仓 11.2 天 / total +1067%）。
      但需注意：drawdown -46.8% 比 fixed_5d (-38.5%) 大；总收益的"美"来自长持有 + 复利。
      推荐方案：**生产升级 fixed_5d → trailing_atr_2_5x**，但保留 ATR 止损硬约束防极端波动。10 测试。

---

## M5 自动化执行 🔲（旧 路线图阶段 D，最不关键）

QMT/miniQMT 券商对接；盘中实时止损；半自动→全自动渐进。

**门槛**：M2 纸上交易验证通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

---

## M6 持续迭代与扩展 ✅（当前范围完成；旧 路线图阶段 E + Phase 7 美股）

### M6.1 量化与研究基础设施升级 ✅
- [x] **量化升级第一阶段（2026-05-16）**
      `qlib_data.py` 加入 point-in-time 基本面因子（ROE / 收入同比 / 利润同比 / 毛利率 / 资产周转率）；
      训练与推理共享同一特征口径；`alphalens_qlib.py` 复用训练面板；`qlib_engine.py`
      新增可选 LambdaRank 训练入口；`universe.py` 新增市值/流动性过滤规则。200 测试通过。
- [x] **股票池扩容工程验证（2026-05-16）**
      已用当前 HS300 成分股扩到 active CN 70 只，其中 69 只满足 ≥480 行 2 年覆盖；
      面板规模 51,439 行 × 23 特征。东方财富直连在批量回填中大量断连，已加入 `yfinance_cn`
      A 股 fallback 完成补数。验证结果：80/20 IC=-0.0074、ICIR=-0.034；
      walk-forward IC=+0.0026、ICIR=+0.009、Top-Bottom=-0.0011，分层非单调。
      结论：工程链路打通，但 Qlib alpha 仍未通过；暂不恢复 quant 权重，暂不启用 Ranker。
- [x] **M6.1.A 数据源可靠性与覆盖报表（2026-05-16）**
      `providers.py` 记录 provider 成功/失败/最近错误；`quality.py` 输出 active 股票、价格、2 年价格、
      财报、24h 新闻覆盖；API `GET /api/system/data-coverage`；当前快照：
      active 70 / 价格覆盖 70 / 2 年价格覆盖 69 / 财报覆盖 10 / 24h 新闻覆盖 0。
- [x] **M6.1.B 真实 PIT / 市值 / 资金流数据底座（2026-05-16）**
      `FinancialMetric.disclosure_date` 已加入；若披露日存在，Qlib 训练/推理按 disclosure date 做 PIT join，
      否则回退 `report_date`。新增 `MarketSnapshot` 表与 `market_features.py`，支持市值、流通市值、股本、
      北向净买入、融资余额、大单净流入 point-in-time join。`FEATURE_COLS` 已加入 log 市值和资金流特征位。
- [x] **M6.1.C 标准化回测报告（2026-05-16）**
      `alphalens_qlib.py::build_validation_report()` 输出样本规模、IC、ICIR、IC>0、Top-Bottom、
      分层结果、gate 和 recommendation；CLI 支持 `--json-output`。
- [x] **M6.1.D 前端证据链增强（2026-05-16）**
      单股 `EvidenceCard` 展示数据覆盖摘要和当前标的价格/财报覆盖。
- [x] **Ranker / RD-Agent / 扩到 100–300 只的门槛决策**
      已保留 `--ranker` 与 RD-Agent 后续入口，但当前 70 股工程验证未通过 alpha 门槛；
      因此不启用 Ranker，不恢复 quant 权重，不继续盲目扩大弱因子样本。后续只有在新增强因子后，
      再做 100–300 只 × 3–5 年可信验证。

### M6.2 美股扩展（旧 Phase 7，已降级/后置）
- 当前已有 `yfinance_us` 数据入口；美股新闻源和双市场调度保持后置。
- 触发条件：A 股主线 M2/M6.1 稳定，且用户明确需要美股纳入同一决策流。

### M6.3 前端操作台与 AI 助手增强 ✅（2026-05-19）
- [x] 首页展示真实持仓情况和大盘情况，活动流水统一优先显示股票名称。
- [x] 复盘中心：每日复盘 / 长期复盘 ensure、历史列表、完整报告详情展开；长期复盘内容写入 `payload.content`。
- [x] 持仓设置：手动持仓、股票联想、平仓记录、整体盈亏、永久删除已平仓记录。
- [x] 配置页：综合分权重、仓位上限、数据补充参数、复盘触发日期与时间可运行时调整。
- [x] AI 对话：左侧会话窗口、新建/归档、窗口内记忆隔离、项目内资源问答、长期研究团队模式。
- [x] 前端显示修复：综合评分双向条、情感进度条、toggle 圆点、顶部导航按钮化。
- [x] 记忆管理可视化入口：已拆入 **M9 记忆系统接入与治理**，见 M9.2。

---

## M7 工程化与开源就绪 ✅（2026-05-16 完成）

### 立即组 A ✅
- [x] M7.A1 README.md
- [x] M7.A2 LICENSE（MIT）
- [x] M7.A3 pyproject.toml（ruff + mypy）
- [x] M7.A4 删除冗余代码（-5 活动文件 / -4 极薄文档 / -3 legacy 目录）

### 中期组 B ✅
- [x] M7.B1 PROJECT.md 拆分为 PROJECT（索引）/ CHANGELOG / docs/ROADMAP / STATUS
- [x] M7.B2 `.github/workflows/test.yml` — CI 自动跑 pytest + npm build
- [x] M7.B3 补 docstring：**函数级 99%（290/291）**，含 class+method 口径 91.6%（306/334）
- [x] M7.B4 补 return type 注解：**函数级 91.8%（267/291）**

### 长期组 C ✅
- [x] M7.C1 `.pre-commit-config.yaml`（ruff + pre-commit-hooks）
- [x] M7.C2 `Dockerfile` + `docker-compose.yml`（backend + frontend + nginx + sqlite volume）
- [x] M7.C3 `frontend/README.md`
- [x] M7.C4 `CONTRIBUTING.md`（代码规范 / 测试 / 核心约束 / PR 流程）
- [x] M7.C5 CHANGELOG.md 按 Keep a Changelog 规范

### 收尾（2026-05-16 补）
- [x] 切方案 B：删除 `backend/requirements.txt`，pyproject 成为依赖唯一真理源；修正 `build-backend` 错配（`setuptools.backends.legacy:build` → `setuptools.build_meta`，否则 `pip install .` 直接失败）
- [x] 拆分 `[project.optional-dependencies]` 为 `test` + `dev` 两组，dev 继承 test
- [x] Dockerfile / CI / README / STATUS 全部从 `pip install -r requirements.txt` 切到 `pip install ".[dev]"`
- [x] 删 3 个 legacy 空目录（`backend/{analysis,backtest,data}/legacy`）
- [x] 加 `.editorconfig`（统一换行/缩进/编码）
- [x] 加 `Makefile`（封装 install / test / lint / fmt / typecheck / check / dev / build / clean / docker-* 12 个常用命令）

---

## 历史决策点（不再阻塞）

**Qlib 命运决策**（M1.1）：IC=0.0228，分层非单调 → Qlib 权重归零（详见 CHANGELOG.md M1.1）

**跨市场信号（已移除）**：美股 ETF（COPX/GLD/UUP 等）作为领先指标，全板块回测无显著收益改善，已移除。
