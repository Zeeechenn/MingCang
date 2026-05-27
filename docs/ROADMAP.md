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
- [x] 新增测试 `tests/test_m9_audit_wiring.py`（9 用例）；当时全套通过（2026-05-19 历史计数，不作为当前测试规模）。
- [x] ChatPage 写入接入**延后**到 M9.4（优先保证对话写记忆的二次确认和可审计性）。
      已在 M9.4 ✅（2026-05-19）落地：`ai.py:_detect_action` 扩 `memory.write` +
      `pending_ai_actions` 二次确认 + `confirm_action` 调 `ai_memory.remember(force=True)`。

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
- [x] 测试：`tests/test_m9_chat_memory_write.py`（8 用例）；当时全套通过（2026-05-19 历史计数，不作为当前测试规模）。

### M9.横向 反偏差与备份（与 M9.0–M9.2 并行可做）
- [x] `ai_memory` 增 `category='bias_override'`，召回链路在 Piotroski 输出后注入（2026-05-19）。
      - `backend/memory/bias_override.py` 提供 `lookup_caveat / set_caveat / seed_default_overrides`。
      - `piotroski_analyst.analyze()` 末尾查一次；命中时把 caveat 加到 `key_findings[0]` 并写入 `raw["bias_caveat"]`；**不覆盖 `label_vote`**，让 LLM 决策链看到原始投票 + 提示后自行判断。
      - 默认种子（`piotroski:规避`）由 `init_db()` 自动幂等写入；生产 DB 已种子完成。
      - `should_remember` 白名单已在 M9.0 扩 `bias_override`，确保写入不被拦截。
      - 测试：`tests/test_m9_bias_override.py`（7 用例），当时全套通过（2026-05-19 历史计数，不作为当前测试规模）。
- [x] 每日 dump `ai_memory` 到 `~/.stock-sage/memory/backups/ai_memory_{date}.json`（2026-05-19）。
      - `backend/memory/backup.py`：`dump_ai_memory` / `cleanup_old_backups`（默认保留 30 天）/ `run_daily_backup`，备份**含已过期行**便于误删恢复；每次执行写一笔 `memory.backup` audit。
      - `scheduler.py` cron `daily_memory_backup` 每天 00:30 触发；首次 dump 已对生产 DB 执行（3 行）。
      - `decision_memory_layered` 文件**暂不**进入备份——M9.1 把分层记忆迁 DB 后再扩。
      - 测试：`tests/test_m9_backup.py`（6 用例）；当时全套通过（2026-05-19 历史计数，不作为当前测试规模）。
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

### M10.4 本地验证统计（已转本地维护）
- [x] 本地验证材料不进入 GitHub；公开仓库只保留生产代码、回测、复盘和质量检查入口。

### M10.5 长期工程基础（后置 / P3）
- [ ] 数据库迁移体系：先保留 `create_all + runtime patch`，中期引入 Alembic baseline。
- [ ] 前后端契约：从 OpenAPI 生成 TypeScript types/client，先覆盖高频页面。
- [x] Qlib 恢复路线只走离线实验：因子版本、训练窗口、验证窗口、IC/ICIR、分层单调性、交易成本后收益。
      已通过 M25.5（2026-05-27）落地：`backend/backtest/alphalens_qlib.py --json-output`
      输出 `experiment_config` + `promotion_gate` + 分层成本后收益 + 权益曲线 + 最大回撤。
- [ ] 只有多个窗口验证通过后，才允许小权重灰度，例如 quant 0.1；默认生产继续 `weight_quant=0.0`。
      （首轮 walk-forward `IC=-0.0058 / ICIR=-0.025` 分层非单调，未达 promotion 门槛；
      继续保持 `weight_quant=0.0`，等多窗口稳定通过后再启动灰度。）

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
- [x] `AGENTS.md` 升级为本地 agent 操作手册：本地 Codex / Claude Code 默认信任，可直接跑测试、查 DB、运行验证、调用已配置的项目 API。
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
- [x] `pyproject.toml` 新增可选依赖组 `agent`，本地可用 `pip install -e ".[agent]"` 后启动 `PYTHONPATH=. python3 -m backend.agent.mcp_server`。

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
- [x] 从 `a-stock-data` 只挑 1 个证据型数据集试点：先选两融 `margin_trading`，
      仅作为 observe-only evidence trial 暴露字段、PIT 要求、失败策略和 promotion gate；
      不联网、不写库、不进入买卖评分。
- [ ] 对任何新端点先补 provider health / PIT 时间戳 / 字段归一化 / 测试，再考虑写入 SQLite。
- [x] TickFlow 经实测可提供更新的 A 股日线；默认仍关闭，但配置 `TICKFLOW_ENABLED=true` 和 key 后，以 `forward_additive` 口径作为 CN 优先 provider，原 fallback 保留在后。

---

## M13 pi Shell + Agent Kernel 双入口 MVP ✅（2026-05-23）

### M13.0 本地 Agent CLI 桥 ✅
- [x] 新增 `backend/agent/cli.py`：`health`、`project-context`、`memory-snapshot`、`stock-context` 和 `action` 子命令。
- [x] 读操作默认 JSON 输出；remote mode 复用 `STOCKSAGE_AGENT_API_KEY` 校验。
- [x] 写操作默认 dry-run，只返回 action metadata、schema、风险等级和 payload；只有显式 `--confirm` 才调用 Action Registry 执行。

### M13.1 pi 项目本地配置 ✅
- [x] 新增 `.pi/SYSTEM.md`，定义 StockSage pi 终端 agent 的研究边界、金融风险边界和写操作确认规则。
- [x] 新增 `.pi/skills/stock-sage-research/SKILL.md`，覆盖健康检查、个股研究、记忆工作、复盘和 confirmed action workflow。
- [x] 新增 `.pi/prompts/`：个股研究、健康检查、记忆快照模板。

### M13.2 启动入口与文档 ✅
- [x] `make agent-setup`：检查 Python、安装 agent extra、创建 `.env`、初始化 DB，并提示 pi 安装与 provider key 配置。
- [x] `make agent` / `make agent-dev`：启动 StockSage pi 终端 shell。
- [x] `make agent-mcp` / `make agent-mcp-config`：保留并强化 Claude Desktop / Claude Code / Cursor / Codex 类 MCP 接入。
- [x] README / README_EN / AGENTS 记录 Claude/Codex 双入口与 pi terminal quickstart。

### M13 后续可选
- [ ] 将 `.pi/` 目录封装为可安装 pi package。
- [ ] 增加 TypeScript pi extension，提供更漂亮的工具状态、schema 展示和确认 UI。
- [ ] 如需普通用户桌面分发，再评估 Electron / Tauri / Web 控制台产品化，不把 pi 误描述为桌面 App。

---

## M14 股票长期记忆与跨入口召回 ✅（2026-05-23）

### M14.0 结构化股票记忆层 ✅
- [x] 新增 `stock_memory_items`：按 symbol / type / status / importance 记录 thesis、risk、event、judgment、outcome、lesson、user_preference、research_pointer。
- [x] 新增统一召回入口 `build_memory_context()`：合并用户规则/偏好、股票长期记忆、研究索引和分层决策记忆，并写 `stock_memory.recall` audit。
- [x] 深度研究写入 `research_pointer` 和低风险 thesis/risk/event 候选股票记忆；盘后决策写入 `judgment` 股票记忆；每日记忆维护补 outcome / lesson。

### M14.1 跨入口接入 ✅
- [x] ChatPage 普通回答和长期研究团队模式读取股票长期记忆，不只依赖当前窗口摘要。
- [x] Agent CLI / MCP 新增 `memory-context` / `stock_sage_memory_context`，`project-context` / `stock-context` 增加统一记忆摘要。
- [x] 后端新增 `/api/memory/stock/{symbol}/context` 与 `/api/memory/stock-items` 读接口，以及归档 / 删除 / 元数据 patch 写接口。
- [x] Admin 记忆管理新增股票长期记忆视图，支持 symbol、type、status、关键词过滤和受控元数据编辑。

### M14.2 自然语言记忆激活 ✅（2026-05-25）
- [x] 新增 `stock_memory.write` confirmed action，支持从聊天确认写入 thesis / risk / event / research_pointer / user_preference。
- [x] ChatPage 识别“调研过 / 研究过 / 结论是 / 投资逻辑是 / 风险是 / 有事件或催化”等句式，普通问句不写记忆。
- [x] `watchlist.add` 同步写入“用户主动关注”股票记忆，后续研究能区分系统自选与用户主动兴趣。
- [x] 单股召回收敛无关全局偏好，减少项目规则污染个股上下文。

### M14 后续可选
- [ ] 记忆规模足够后，再评估 embedding / reranker；v1 继续保持 SQLite + 结构化筛选。
- [ ] 为高重要度用户偏好增加更细的二次确认 UI，而不是使用浏览器 prompt。

---

## M15 记忆系统与影子副驾驶评审修复 ⏳

> 来源：2026-05-23 对记忆系统（`stock_memory` / `memory_layered` / `ai_memory` /
> `audit_log` / `research_memory`）和研究影子副驾驶（`research/copilot.py`）的全局评审。
> 原则：先修污染记忆数据本身和安全边界的问题（P1），再做读写副作用与增长治理（P2），
> 最后做记忆质量与健壮性（P3）。
> 明确不做：影子副驾驶在 `veto_reason` 存在时只设 `risk_conflict=True`、不强制清零
> `shadow_position_pct` —— 这是 `_bounded_shadow_position` 的有意设计，本轮保留不改。

### M15.0 记忆数据完整性（必做 / P1）✅（2026-05-23）
- [x] **重复 judgment 记忆**：`create_stock_memory` 改为 upsert —— 提供 `source_ref` 且已存在
      同 ref 行时原地 UPDATE（保留 id / created_at），不再 INSERT 重复行。新增
      `_id_by_source_ref` 替换原 `_existing_source_ref`，audit content 标 `mode=insert/upsert`。
- [x] **outcome 记忆过早定格**：`update_judgment_outcomes` 把 `len(prices) < 2` 改为
      `< 11`，即必须凑齐 10 个交易日 horizon 才写 outcome，1d/3d/5d/10d 一次性成形后
      才冻结为 `validated`，`lesson` 也基于完整 10d 收益判断。
- [x] 回归测试：`test_create_stock_memory_upserts_on_source_ref` /
      `test_create_stock_memory_without_source_ref_always_inserts` /
      `test_update_judgment_outcomes_waits_for_full_horizon`。

### M15.1 安全层接线修正（必做 / P1）✅（2026-05-23）
- [x] **vetter 接反**：`vet_skill_output` 此前只在 `daily_review.py` 调用、且喂入确定性 summary。
      已让 `generate_symbol_copilot` 返回前对 `summary_opinion / event_read / technical_read /
      position_note` 等 LLM 字段过 vetter，结果写入 `card["vetter"]`，命中自动交易类表述时
      强制 `shadow_position_pct=0`。实现时确认 `deep_research` 报告由 `research/agents.py`
      确定性模板生成、无 LLM 自由文本，故不接 vetter —— copilot 是当前唯一的 LLM 自由文本输出。
- [x] **research / skills 写路由漏挂 agent guard**：`POST /api/research/{symbol}/copilot`、
      `POST /api/research/deep/run`、`POST /api/skills/daily-review/run` 分别挂上
      `agent_write_guard("research.copilot" / "research.deep.run" / "skill.daily_review.run")`，
      `.env.example` 的 `STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS` 示例补齐三个 action 名。
- [x] 回归测试：`tests/test_m15_route_guards.py` 覆盖 remote 缺 key 拒绝、action allowlist、
      本地信任模式放行。

### M15.2 读写副作用与增长治理（建议 / P2）
- [x] **读操作带写副作用**：`build_memory_context` 召回时 `UPDATE last_used_at` + `audit_write`
      各 commit 一次，且挂在 `GET /api/memory/stock/{symbol}/context`；postmarket 88 股一次
      ≈ 176 commit + 88 audit 行。把召回 audit 降级为采样 / 可选，`last_used_at` 改批量或
      异步更新，GET 路由不带写副作用 —— 与 `ai_memory.recall`“miss 不审计”的既定原则对齐。
- [x] **audit_log_fts 无清理**：全仓库无 audit 保留 / 滚动任务，FTS5 表无限增长
      （`expire_stale_memories` 注释假设的“audit 保留窗口”并不存在）。新增按时间或行数的
      audit 滚动清理（建议并入 `daily_memory_expire` 或独立 cron），并明确保留窗口。
- [x] **copilot official / signal 日期错配（2026-05-27）**：`_official_context` 新增
      `signal_date` / `decision_date` / `decision_date_mismatch` 三字段；日期不一致时
      `_build_prompt` 在 prompt 开头写入警告，告知 LLM 保守处理 position_pct；
      card 透出 `decision_date` / `decision_date_mismatch` 给调用方展示。

### M15.3 记忆质量与健壮性（排期 / P3）
- [x] **medium-term 记忆无上限**：`save_medium_term` 保留全部历史，每次 postmarket 把不断
      增长的 markdown 整体 read + upsert 进 `decision_memory_layered.content`。改为只留最近 N 笔。
- [x] **outcome 用裸收益判成败**：`update_judgment_outcomes` / `weekly_long_term_reflect`
      用 `pct<0` 判失败，A 股高 beta 下大盘下跌日会系统性”全失败”，长期反思偏空。
      至少减去沪深 300 同期收益或用 ATR 归一。
      2026-05-27 已修：(a) `stock_memory.py:update_judgment_outcomes` 读 `index_prices`
      sh000300 同期收盘，在 1d/3d/5d/10d 各 horizon 计算 `excess_returns = stock - HS300`，
      evidence 同时存原始 `returns` 与 `excess_returns`，lesson 触发改用超额收益
      （无基准数据时回退裸收益）；(b) `memory_layered.weekly_long_term_reflect` 用同样
      逻辑判断”失败信号”，失败行附 `(vs HS300 X%, 超额 Y%)`。
- [x] **deep research 候选记忆质量低**：`remember_deep_research` 对每个 symbol 用同一段
      `clipped_summary` 写 research_pointer + thesis + risk + event，最多 4×N 行近乎重复；
      “risk” 条目并不含真实风险点，`_RISK_HINTS` 仅靠”摘要含’风险’二字”触发。改为让 LLM
      结构化产出独立的 thesis / risk / event 字段。2026-05-25 已先修 per-symbol source_ref
      互相覆盖与 summary/evidence 缺少 symbol 的问题，独立字段生成仍待后续接 LLM 结构化输出。
      2026-05-27 已收口噪声：删除 `_RISK_HINTS` / `_EVENT_HINTS` 关键词触发的 thesis /
      risk / event 候选写入，每个 symbol 只保留 1 行 `research_pointer` 索引。
      真正的 thesis / risk / event 等后续接 LLM 结构化输出后再补；本模块不再生成
      候选噪声。回归测试 `test_deep_research_memory_writes_stock_research_pointer`
      已更新断言只剩 research_pointer。
- [x] **audit_search FTS 注入**：`GET /api/memory/audit?q=` 直接把 q 传给 `MATCH`，FTS5
      语法字符（`"` `*` `:` `NEAR`）会抛 500。对 q 做短语转义或捕获异常返回 400。
- [x] 收尾 nits：`stock_sage_memory_context`（`agent/context.py`）补 try/except，对齐 M11.4
      “未初始化返回空状态”；`patch_stock_memory` 改 importance 不应顺带刷新 `updated_at`
      （TTL 按 `updated_at` 算，会意外给快过期记忆续命）；`build_memory_context` 的
      `_ai_memory_context` 对 symbol 召回时仍全量塞 preference/rule/risk，考虑按相关性收敛。

### M15 最小交付包
- [x] M15.0 judgment 去重 + outcome horizon 修正。
- [x] M15.1 vetter 接到 copilot + 三个写路由挂 guard。
- [x] M15.2 召回写副作用降级 + audit 滚动清理。

---

## M16 全项目分层评审 ⏳

> 来源：2026-05-23 完成 M15（记忆系统 + 影子副驾驶评审）后，确认首轮只覆盖了
> `memory/*` + `research/copilot.py` + 直接接线，项目其余部分尚未逐文件评审。
> 性质：这是评审任务清单，不是功能开发。每完成一级输出一份分级评审结论，
> 确认的缺陷参照 M15 模式转为 M-numbered 修复里程碑。
> 与 M15 的关系：M15 是“已发现缺陷的修复计划”，M16 是“尚未评审区域的评审计划”。

### 评审方法（六级通用）
每一级按同一套方法执行：
1. **静态走查** — 逐文件精读，对照四个维度打标：正确性与 bug / 架构与设计 /
   金融逻辑合理性 / 安全与边界。
2. **调用链追踪** — 从入口（route / scheduler job / CLI）追到落库，确认数据流与
   副作用，重点查重跑幂等、commit 边界、异常被静默吞没。
3. **失败路径** — 空数据 / 缺表 / provider 失败 / LLM 返回空 / 并发，确认降级
   而非崩溃或静默写脏数据。
4. **测试核对** — 对照 `tests/` 现有覆盖，标注缺口；P1 缺陷必须能写出复现测试。
5. **运行核实** — 必要时跑 `make verify`、覆盖快照、回测脚本，用真实输出核对结论，
   不只靠读代码。
6. **产出** — 每级一份按维度 + 严重度（P1/P2/P3）分级的结论；确认项追加为修复里程碑。

### M16.0 决策链与多 Agent（最高优先级）
- 评审内容：`decision/aggregator.py`（`aggregate` / `aggregate_v2` / `save_signal`）、
  `decision/harness.py`、`decision/decision_memory.py`、
  `agents/{pipeline,director,researcher,risk_manager,portfolio_manager,analyst,trader}.py`。
- 评审重点：
  - 综合分公式、双 profile 权重、`entry_threshold` 与 `score_to_recommendation` 是否一致；
  - 一票否决 / veto 在 `aggregate_v2 → portfolio_manager` 全链是否一致传递、不被覆盖；
  - 多轮辩论降级路径、Director 注入 `debate_topic`、组合层裁剪（单股/板块/总仓）边界；
  - `position_pct` vs `trader_position_pct` 写入与 evidence 一致性；
  - LLM 失败时是否退回纯规则路径，而非静默给 0 分。
> 评审完成 2026-05-23：复核通过 LLM 失败降级；确认 1×P1 / 2×P2 / 7×P3，修复项转入 M17。

### M16.1 回测与统计口径
- 评审内容：`backtest/walk_forward.py`、`backtest/statistics/*`（DSR / PBO / IC 显著性）、
  `backtest/compare_paths.py`、`sweep_threshold.py`、`exit_sweep.py`、`backtrader_eval.py`。
- 评审重点：
  - 手续费 0.20% + 滑点 0.10% 是否在所有路径一致计入；
  - 是否有前视偏差（用未来数据选参 / IS-OOS 泄漏）；
  - DSR / PBO 实现与论文口径核对，“数据不足”样本量门槛；
  - STATUS.md 验证摘要（Sharpe 1.36 / 回撤 8.60% / 盈亏比 2.78）能否由脚本复现。

### M16.2 数据层与 Point-in-Time
- 评审内容：`data/{market,providers,universe,qlib_data,market_features,fundamentals,
  qfii_holdings,point_in_time,news,quality,external_sources}.py`。
- 评审重点：
  - PIT `as_of` 拦截层是否真的挡住未来数据（`disclosure_date` vs `report_date` join）；
  - provider fallback 链（efinance / AkShare / yfinance_cn / Tushare）的重试、断连、对齐；
  - universe 市值/流动性过滤、批量回填幂等；
  - 复权口径一致性、新闻去重与时区。

### M16.3 量化与分析层
- 评审内容：`analysis/{factors,technical,sentiment,qlib_engine}.py`、
  `analysis/timing/{rsrs,diffusion,regime}.py`。
- 评审重点：
  - 技术因子 / ATR / 止盈止损公式与 STATUS.md 公式逐项核对；
  - regime 过滤层的触发与降级；
  - sentiment LLM 调用的成本、缓存、失败降级；
  - `FEATURE_COLS` 维度守护，训练 / 推理特征口径一致。

### M16.4 前端
- 评审内容：`frontend/src/{api.js,pages/*,components/*}`。
- 评审重点：
  - API 层 timeout / 重试 / 错误分类；
  - 渐进加载与辅助接口失败不阻塞首屏；
  - 影子副驾驶 / 记忆管理新组件的状态管理与二次确认 UI；
  - 金融数字展示口径（综合分双向条、仓位、止盈止损）与后端一致。

### M16.5 其余后端基础设施
- 评审内容：`config.py`、`data/database.py`、`scheduler.py` 剩余 job、`ops/kill_switch.py`、
  `llm/{factory,base,*_provider}.py`、`agent/{cli,mcp_server,action_registry,security}.py`、
  其余 `api/routes/*`。
- 评审重点：
  - 配置项默认值与 `.env.example` 一致性、敏感项不入库；
  - database 轻量迁移幂等、并发与 WAL；
  - kill switch 覆盖的 job 是否齐全；
  - LLM provider 单例与测试隔离、`model_tier` 映射；
  - Action Registry 的 `risk_level` / `allowed_modes` / `requires_confirmation` 与 `http_guard` 是否自洽。

### M16 交付节奏
- [x] M16.0 决策链与多 Agent 评审 ✅（2026-05-23）→ 结论 + 修复项见 M17
- [x] M16.1 回测与统计评审 ✅（2026-05-23）→ 结论 + 修复项见 M18
- [x] M16.2 数据层与 PIT 评审 ✅（2026-05-23）→ 结论 `docs/reviews/2026-05-23-m16.2.md`、修复项见 M19
- [x] M16.3 量化与分析评审 ✅（2026-05-23）→ 结论 `docs/reviews/2026-05-23-m16.3.md`、修复项见 M20
- [x] M16.4 前端评审 ✅（2026-05-25）→ 补危险写操作确认；EvidenceCard 展示
      trader / risk / portfolio 三层仓位；前端 node tests + build 通过。
- [x] M16.5 基础设施评审 ✅（2026-05-23）→ 结论 `docs/reviews/2026-05-23-m16.5.md`、修复项见 M21
> 每级独立可交付；P1 缺陷即时升级为修复里程碑，不等整轮评审结束。

---

## M17 决策链评审修复 ⏳

> 来源：2026-05-23 完成 M16.0（决策链与多 Agent）评审的确认缺陷。
> 评审范围：`decision/{aggregator,harness,decision_memory,signal_policy}.py`、
> `agents/{pipeline,director,researcher,risk_manager,portfolio_manager,analyst,trader}.py`，
> 并追踪 `scheduler.py` 全链。P1 已构造 bearish regime 调 `aggregate_v2` 实跑复现。
> 原则：先修会污染最终建议与推送的 P1，再做金融逻辑与证据一致性 P2，最后做 P3。
> 已核实通过、本轮不改：`complete_structured` 三 provider 全 try/except 返回 `{}`，
> LLM 失败正确退回 `quick_consensus` 纯规则路径；`save_signal` 按 `(symbol,date)` upsert
> 幂等；harness `record_decision_run` 被 try/except 包裹，写失败不阻塞信号。

### M17.0 regime 过滤层覆盖风控否决（必做 / P1）✅（2026-05-23）
- [x] **缺陷**：`decision/aggregator.py:324-333`。`aggregate_v2` 末尾 regime 兜底
      `apply_regime_filter` 后用衰减分 `_score_to_recommendation(new_score)` 重算
      `recommendation`/`confidence`，丢弃 `risk_manager` 已下达的降级。`run_pipeline`
      返回时 `recommendation` 是风控 `final_recommendation`（否决为「观望」），但
      `composite_score` 始终是 trader 原始分（`risk_manager` 从不下调 composite）。
      trader 原始分够高时，衰减后仍 > `entry_threshold`(25)，`recommendation` 被升回
      「可小仓试错」。
- [x] **触发面非边缘**：`rsrs_bearish_z=-0.7`、`diffusion_threshold=0.3`，
      `regime.dampen_score = market_bearish or sector_weak`。风控否决线 `rsrs_z<-1.0`、
      板块降级线 `diffusion<0.2` 严格落在 dampen 阈值内 → 每次 RSRS 否决、每次板块
      降级都必然伴随 `dampen_score=True`，本 bug 必触发。
- [x] **危害**：(a) RSRS 否决变体——`veto_reason` 已置、`position_pct=0`，但
      `recommendation` 翻成「可小仓试错」→ `should_send_signal_alert` 为真，
      给被风控否决的票推送买入提醒、Signal 表自相矛盾；(b) 板块降级变体——风控
      降级为「可关注」且 `position×0.7` 仍为正，regime 把它升回入场信号且保留正仓位，
      `_apply_portfolio_decision` 据此对该票实际分配资金。
- [x] **修复方向**：regime 衰减只改 `composite_score`，不重算覆盖
      `recommendation`/`confidence`；若需重算须按严重度向下钳制
      （`min(当前建议, score 重算建议)`），且 `veto_reason` 存在时强制保留「观望」；
      同步衰减后的 `position_pct`。更彻底方案：把 regime 衰减并入 `risk_manager` 之前。
- [x] **回归测试**：补 `aggregate_v2` 在 bearish regime + 否决 / 板块降级下，
      `recommendation` 不被升级、`veto_reason` 与 `recommendation` 自洽；
      现有 `tests/integration/test_long_term_pipeline.py` 全部传 `regime=None`，
      是本缺陷长期漏网的主因。
- 复现脚本（评审 2026-05-23 实跑确认，两个变体均复现）：
  ```python
  from backend.config import settings
  from backend.analysis.timing.regime import RegimeReport
  settings.regime_filter_enabled = True
  settings.risk_manager_enabled = True
  settings.multi_round_debate_enabled = False
  settings.long_term_team_enabled = False
  settings.position_sizing_enabled = True
  from backend.decision.aggregator import aggregate_v2

  tech = {"score": 75, "raw_score": 75,
          "latest": {"rsi14": 58, "close": 10.0, "atr14": 0.3}, "limit": {}}
  quant = {"score": 75, "model": "lgbm"}
  sent = {"sentiment": 0.75, "key_events": ["公司中标大额订单"],
          "summary": "利好", "impact": "short"}

  # 变体 A — RSRS 否决：rsrs_z=-1.5 触发 risk_manager 一票否决
  regime_a = RegimeReport(rsrs_z=-1.5, diffusion=0.5,
      market_bullish=False, market_bearish=True, sector_strong=False,
      sector_weak=False, dampen_score=True, reason="RSRS看空")
  ra = aggregate_v2(quant_result=quant, technical_result=tech, sentiment_result=sent,
                    close=10.0, atr=0.3, regime=regime_a, long_term_label=None)
  # 实测：recommendation='可小仓试错'，veto_reason 已置，position_pct=0.0
  assert ra.get("veto_reason") and ra["recommendation"] == "观望", ra

  # 变体 B — 板块降级：diffusion=0.15 触发 risk_manager 降级为「可关注」
  regime_b = RegimeReport(rsrs_z=-0.5, diffusion=0.15,
      market_bullish=False, market_bearish=False, sector_strong=False,
      sector_weak=True, dampen_score=True, reason="板块扩散弱")
  rb = aggregate_v2(quant_result=quant, technical_result=tech, sentiment_result=sent,
                    close=10.0, atr=0.3, regime=regime_b, long_term_label=None)
  # 实测：recommendation='可小仓试错'，position_pct≈0.105 被保留
  assert rb["recommendation"] == "可关注" and (rb.get("position_pct") or 0) == 0, rb
  ```

### M17.1 金融逻辑与证据一致性（建议 / P2）
- [x] **无新闻事件时 sentiment 信号被腰斩**：`agents/trader.py:62`
      `sent_combined = sent.score*0.5 + news.score*0.5`，而 `news_analyst` 在
      `key_events` 为空时返回 `score=0`（`analyst.py:124-131`）。无事件时
      `sent_combined = 0.5*sent.score`，`weight_sentiment=0.4` 的标称权重实际只兑现
      ~20%（无事件）~ ~36%（有事件），随 LLM 是否抽出离散事件漂移；且
      `breakdown["sentiment"]` 写完整 `sent.score`，与真实贡献对不上。确认是否设计意图——
      若是，文档化并让 breakdown 反映实际贡献；若否，改为稳定权重分配。
      2026-05-25 已改为无事件时使用 `sentiment_only_no_news_events`，有事件时才
      sentiment/news 50:50 blend；`breakdown.sentiment` 表示实际入权重的有效分，
      `sentiment_raw` 保留原始情绪分。
- [x] **证据链仓位归属错位**：`scheduler.py:476-477` 把 `trader_position_pct` 赋成
      `result["position_pct"]`，但此值已是风控调整后仓位（trader 原始
      `proposal.position_pct` 在 `run_pipeline` 被 `final_pos` 覆盖，从未持久化）。
      `harness.py:108-122` 的 trace 把这个风控值标成 "trader"、把组合层 target 标成
      "risk_manager `approved position`"——真正的 trader 提案仓位无处可查。另外
      `aggregate_v2` regime 衰减更新了 score 却未同步 `position_pct`。让 pipeline
      显式透传 trader 原始仓位，trace 三步（trader/risk/portfolio）各自标对来源。
      2026-05-25 已新增 `trader_position_pct` / `risk_position_pct` / 最终
      `position_pct` 三层留痕，PortfolioManager 继续消费风控后仓位。

### M17.2 健壮性与清理（排期 / P3）
- [x] **分析师重复计算**：`aggregate_v2` 为分歧检测构建一次 4 路 report，
      `run_pipeline` 内再建一次（纯规则、不影响正确性，仅浪费）。
      2026-05-27 已修：`pipeline.run_pipeline` 接收 `_precomputed_reports` 参数，
      `aggregator.aggregate_v2:348` 显式传入分歧检测阶段已构建的 `reports`；
      `pipeline.py:131-143` 仅在未传入时才本地构建，避免四路分析师重复执行。
- [x] **分歧口径不一致**：`_bull_bear_debate` 硬编码 `stdev<20` 且只用 3 路（无 news）；
      `has_divergence`/director/`multi_round_debate` 用 `multi_round_debate_min_divergence`
      且 4 路。`has_divergence` 用 `>`，director/multi_round 用 `>=`，边界不一致。统一口径。
      2026-05-27 已统一：`director.py:89` / `researcher.py:75-76,244` 均用
      `stdev >= settings.multi_round_debate_min_divergence`，注释标 M17.2 口径统一。
- [x] `aggregate_v2` 调 `_bull_bear_debate` 传 `stop_loss=0, take_profit=0`，
      辩论 prompt 显示假的「止损：0 止盈：0」。改为传真实值或省略该行。
      2026-05-27 已修：`aggregator.py:329-336` 调用前先 `calc_stop_take(close, atr,...)`
      算出真实止损/止盈再传入。
- [x] **死代码**：`aggregator.py:19` 的 `RECOMMENDATION_MAP` 已删除（2026-05-23）；
      入场分继续走 `signal_policy.score_to_recommendation` 读 `entry_threshold`。
      同步把 `technical.py` 模块级 `LIMIT_THRESHOLD` 改为私有 `_MAIN_BOARD_LIMIT_THRESHOLD`，
      避免被误 import 当作"全市场涨跌停阈值"——主板/创业板/科创板/北交所走 `_limit_threshold(symbol)`。
- [x] **非幂等写**：`record_decision_run` 每次新插 row（uuid），同日重跑产生重复
      `DecisionRun`；`decision_memory.save_decision` 无条件 append，重跑在
      `~/.stock-sage/memory/<symbol>.md` 留重复行。改为按 `(symbol,as_of)` 去重 / upsert。
      2026-05-27 已修：`harness.py:143-230` 按 `(run_type, symbol, as_of)` 查既有
      row，存在则原地更新，不存在才 INSERT；标 M17.2 幂等。
- [x] 多轮辩论第 1 轮失败回 `quick_consensus(used_llm=False)` → `aggregate_v2` 又补一次
      `_bull_bear_debate` LLM 调用，失败时成本翻倍。失败应直接走纯规则、不再补 LLM。
      2026-05-27 已修：`aggregator.py:321-322` 注释标 M17.2，无论多轮是否成功都采用
      其结论，不再回退到单轮 LLM；多轮失败由 `researcher.py` 的 `quick_consensus`
      纯规则路径承接，不重复 LLM 调用。
- [x] `risk_manager` 文档头把「跌停日卖出信号」列为否决条件，代码只加 note
      （`risk_manager.py:93-94`）。订正文档或补否决逻辑。
      2026-05-27 已订正文档：`risk_manager.py:1-18` 把 docstring 拆为「否决」/
      「降级」/「执行约束提示（仅 note）」三段；跌停日卖出与涨停日买入归入执行
      约束提示段，与代码 `notes.append(...)` 行为一致；保留"否决条件"段只包含
      RSRS 极度看空、组合回撤超 -8%、长期"规避"标签。

### M17 最小交付包
- [x] M17.0 regime 过滤层不再覆盖风控否决 + 回归测试。

---

## M18 回测与统计口径修复 ⏳

> 来源：2026-05-23 完成 M16.1（回测与统计口径）评审的确认缺陷。
> 评审范围：`backtest/walk_forward.py`、`backtest/statistics/{deflated_sharpe,
> probability_overfitting,significance}.py`、`backtest/{compare_paths,sweep_threshold,
> exit_sweep,backtrader_eval,exit_logic_experiment,backfill_signals}.py`。
> 原则：先修会让对外验证结论失真的 P1，再做口径一致性与统计误用 P2，最后做接线与清理 P3。
> 已核实通过、本轮不改：DSR 闭式公式与 Bailey & López de Prado (2014) 口径一致
> （分母用非超额峰度 `(γ4-1)/4`、`z` 用 `√(T-1)`）；`_norm_ppf` Beasley-Springer
> 逼近、`pbo` 的 CSCV 切块与组合数收缩、`run_walk_forward` 对 evaluator 异常的
> try/except 降级均正确；`exit_logic_experiment.walk_forward_eval` 的退出选择
> （train 段选 → test 段评）本身无 IS-OOS 泄漏。

### M18.0 对外验证指标失真（必做 / P1）✅（2026-05-23）
- [x] **缺陷 A — 滑点从未建模，STATUS 标注不实**：`backtest/backtrader_eval.py:38-52`
      `AShareCommission` 仅含往返 0.20%（买 0.05% + 卖 0.05%+0.10% 印花税），
      `cerebro.broker` 无 `set_slippage_perc`，全 backend `grep slippage` 零命中。
      `STATUS.md:81`「Sharpe（含 0.20% 手续费 + 0.10% 滑点）」中滑点部分为不实标注，
      1.36 实为无滑点结果。
- [x] **缺陷 B — 头条指标是 N=2 单股回测的逐股平均**：`CHANGELOG.md:240` 明载
      「M1.3 Sharpe=1.36（N=2）」。`run_suite`（`backtrader_eval.py:309-323`）的
      `avg_sharpe/avg_dd/avg_pf` 是逐只单名回测指标的截面算术平均，非组合权益曲线
      的 Sharpe/最大回撤；`STATUS.md:77-83` 以「最低标准 / 实际」阈值表呈现，未披露
      N=2、未说明「逐股平均 ≠ 组合」。数字还依赖当前 DB 的 `active` universe 与
      `settings` 当时值，二者均未固化，重跑必变。
- [x] **危害**：「M1 验收标准全部达成」结论失去支撑——按 STATUS 所述口径
      （含滑点、系统级 Sharpe）无法用任何脚本复现。
- [x] **修复方向**：(a) `backtrader_eval` 加 `cerebro.broker.set_slippage_perc(0.001)`
      或在成交价上显式滑点，与 STATUS 标注对齐；(b) 改 STATUS 验证摘要——要么给出
      组合级权益曲线的真实 Sharpe/最大回撤，要么明确标注「N=2 单股回测逐股均值」
      并写清 universe + 区间 + 关键 settings；(c) 固化一份带 universe/区间/settings
      的回测配置，使头条数字可被一条命令复现。
- [x] **回归测试**：补 ① 断言 `backtrader_eval` 成交计入滑点的测试（修复前应为红）；
      ② 固定 universe + 区间 + settings 跑 `backtrader_eval` 锁定头条数字的快照回归。

### M18.1 口径一致性与统计误用（建议 / P2）
- [x] **成本只进了一条路**：`compare_paths`/`sweep_threshold`/`exit_sweep`/
      `exit_logic_experiment` 全部用毛收益 `(exit_close-entry_close)/entry_close`
      （`compare_paths.py:349`、`sweep_threshold.py:114-117`、`exit_sweep.py:213`、
      `exit_logic_experiment.py:170`），零手续费零滑点。阈值扫描与退出策略选择基于
      零成本毛收益，系统性偏向高换手策略（短止损 / `fixed_3d`），选出的「最优档位 /
      最优退出」在真实成本下可能反转。统一加成本扣减，与 `backtrader_eval` 对齐。
      2026-05-25 新增 `backend/backtest/costs.py`，按 0.20% 往返手续费/印花税
      + 买卖各 0.10% 滑点扣减净收益。
- [x] **Sharpe 年化口径三套并存**：`exit_logic_experiment.py:82` 用 `√252`
      （把每笔多日交易当 1 天，严重过度年化）、`compare_paths.py:166` 与
      `sweep_threshold.py:57` 用 `√(252/5)`、`exit_sweep.py:118` 用 `√(252/avg_hold)`。
      同一策略换模块跑出不同 Sharpe。统一为按实际平均持仓天数年化。
      2026-05-25 `annualized_sharpe(..., avg_hold_days=...)` 已接入上述四条路径。
- [x] **DSR 的 trial 数语义误用**：`walk_forward.py:139-141` 把
      `expected_max_sharpe(metric_values, n_trials=窗口数)`——窗口是同一策略的顺序
      评估，不是 multiple-testing 的 N 个竞争策略；`backtrader_eval.py:329-330` 把
      股票数当 trial 数（N=2 时阈值由 2 点方差驱动仍打印「✅ 跨越多试验阈值」）。
      `expected_max_sharpe` 的 N 必须是参数/策略扫描的实际试验次数；修正调用处，
      或把该输出改名为非 DSR 口径的「跨窗口离散度」指标。
      2026-05-27 已修：`expected_max_sharpe(trial_sharpes, n_trials=...)` 接受
      显式 `n_trials` 覆盖参数，调用处显式传入真实参数/策略试验次数，不再用窗口数
      或股票数；docstring 明确语义。
- [x] **IC 显著性忽略相关性**：`significance.py:65-67` `t ≈ IC×√N` 把每个
      (stock,date) 当 IID，重叠前向收益 + 同日截面相关使有效 N 远小于名义 N，
      t 值与「极显著」过度自信。改用独立周期数或对截面/序列相关做修正。
      2026-05-27 已修：`significance.py:60-66` docstring 加【M18.1 局限性说明】，
      明确 IID 前提、t-stat 高估风险，并指向 Newey-West / Hansen-Hodrick；严格
      场景必须用调整后标准误。代码保留简化版以兼容现有调用，调用方需自行选择。
- [x] **backfill quant 维度前视**：`backfill_signals.py:86` `qlib_score` 用全历史
      训练的生产 LightGBM 对历史日期打分。`new_framework`(quant=0) 下不传导，但
      `test1_legacy_qlib`(quant=0.45) profile 跑 `sweep`/`exit_sweep` 时污染结果。
      回测路径需用「截到 as_of 训练的模型」，或在 quant 权重>0 时显式标注前视。
      2026-05-27 已加 backfill 专用量化守卫：历史回填按 as_of profile 判断 quant 权重；
      `quant=0` 直接返回 `disabled_quant_weight_zero`，`quant>0` 默认返回
      `disabled_lookahead_guard` 并拒绝当前生产模型；只有显式 `--allow-lookahead-quant`
      才调用当前 Qlib 模型，并写入 `lookahead_warning=true`。
- [x] **DSR 无有效最小样本门槛**：`deflated_sharpe.py:165` 仅挡 `n_obs<2`，3 笔
      交易也会返回像样的 dsr/p_value。加交易笔数下限（如 <30 标「数据不足」）。
      2026-05-27 已修：`deflated_sharpe.py:181-185` 增加 `n_obs<30` 早返回带
      `note="样本量 {n_obs} < 30，DSR 不可靠，建议收集更多交易"`。

### M18.2 接线与清理（排期 / P3）
- [x] **统计交付物未接线**：`pbo()` 与 `ic_significance()` 已实现且有
      `tests/test_statistics.py` 覆盖，但全项目除 `statistics/__init__.py` 导出外
      无任何调用方（grep 核实）。要么接入回测产出报告，要么注明「仅库函数、未投产」。
      2026-05-27 已接线：`backtrader_eval.py:369` import `pbo` / `ic_significance`
      并接入 statistics 报告。
- [x] **PBO 为简化变体**：`probability_overfitting.py:119-125` 用「OOS 排名落入
      后半 → 过拟合」判据，非 Bailey & López de Prado 论文的 logit(λ) 分布口径；
      docstring 标注论文出处但实现为简化版，应在 docstring 注明差异。
      2026-05-27 已修：`probability_overfitting.py:18` docstring 明确「未实现原论文
      logit(λ) 变换，本实现为简化变体」。
- [x] **入场价无滞后**：`compare_paths.py:348-349` 入场价取生成信号那根 bar 的
      收盘价，无 1-bar 滞后，偏乐观。改为下一根 bar 开盘价入场。
      2026-05-27 已修：`compare_paths.py:348-350` 入场价改为 `prices[1].open`
      （信号 bar 0 收盘生成，bar 1 开盘入场），消除同 bar 隐含未来信息；
      `len(prices) < 2` 守卫已确保 bar 1 存在；454 tests 全绿无回归。
- [x] **「盈亏比」两套定义混用**：`backtrader_eval.py:264` 用 Σ盈利/Σ亏损
      （profit factor），其余模块用 平均盈利/平均亏损。统一口径，或在 STATUS
      「净盈亏比 2.78」处标明用的是哪一个。
      2026-05-27 已澄清：`backtrader_eval.py:292-305` 注释明确"盈利总额/亏损总额
      （Profit Factor），不是平均单笔盈亏比"，列标"盈亏比"指 Profit Factor。
- [x] **跨窗口 t-stat 用总体标准差**：`walk_forward.py:128,134-135` 用
      `statistics.pstdev`，小样本下 t 值偏大，应改样本标准差。
      2026-05-27 已修：`walk_forward.py:128-129` 改用 `statistics.stdev`（无偏，
      n-1），注释标 M18.2。
- [x] **`compute_tech_scores` O(n²)**：`backtrader_eval.py:170-192` 每根 bar 重算
      全切片评分（性能，非正确性）。改增量计算。
      2026-05-27 已修：`backtrader_eval.py:199-227` 各 score 函数只取最近
      `max(WARMUP=80, 20)` 行，切片大小固定上界，由 O(n²) 降为 O(n)。

### M18 最小交付包
- [x] M18.0 滑点建模 + STATUS 验证摘要订正为可复现口径 + 两条回归测试。

---

## M19 数据层与 PIT 评审修复 ⏳

> 来源：2026-05-23 完成 M16.2（数据层与 Point-in-Time）评审的确认缺陷。
> 评审范围：`data/{point_in_time,providers,market,universe,qlib_data,
> market_features,fundamentals,qfii_holdings,news,quality,external_sources}.py`。
> 完整结论见 `docs/reviews/2026-05-23-m16.2.md`。
> 原则：先修会污染回测与已部署模型的 P1/P2，再做数据口径一致性 P2，最后做 P3。
> 已核实通过、本轮不改：PIT 对 `Price/Signal/LongTermLabel/IndexPrice/NewsItem`
> 拦截正确；`qlib_data._attach_point_in_time_fundamentals` 口径正确（优先
> `disclosure_date` + `merge_asof` backward）；provider fallback 有 cooldown +
> health 计数；`sync_financial_metrics`/`sync_index_to_db`/`save_news_to_db` 幂等。

### M19.0 PIT 拦截层对财报用错时间列（必做 / P1）✅（2026-05-23）
- [x] **缺陷**：`data/point_in_time.py:37` `_PIT_DATE_FIELDS["FinancialMetric"]`
      用 `report_date`（财报期末日）过滤。公司实际披露晚约 4 周，
      `PITSession` 在 `as_of=2024-10-01` 会放行 `report_date=2024-09-30` 的 Q3
      财报——披露滞后型 look-ahead，正是模块 docstring 引 Benhenda 2026
      Look-Ahead-Bench 声称要拦的 bug。`qlib_data` 路径已正确用 `disclosure_date`，
      两套 PIT 机制矛盾。
- [x] 改 `_PIT_DATE_FIELDS["FinancialMetric"]` 用 `disclosure_date`；NULL 时回退
      `report_date + 披露滞后偏移`，不得回退裸 `report_date`。
- [x] 修正 `tests/integration/test_no_look_ahead.py:93`：现测试种子
      `report_date="2024-09-30"` 配 `as_of="2024-10-01"` 固化了错误行为。

### M19.1 Q1/Q3 披露日 100% 缺失（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`data/fundamentals.py:561` 循环用 `("年报","三季报","半年报","一季报")`，
      但 `_PERIOD_SUFFIX`（line 527）键为 `("年报","三季","半年报","一季")`，
      `三季报`/`一季报` → `_period_to_report_date` 返 `None` → `continue`。
      数据库核实：Q1 439/439、Q3 438/438 行 `disclosure_date` 全为 NULL。
      经 `build_training_data → _attach_point_in_time_fundamentals` 的
      `disclosure_date or report_date` 回退，半数季度提前约 4 周可见，污染已部署
      的 LightGBM 训练集。
- [x] 循环元组改为 `("年报","三季","半年报","一季")`；重跑
      `backend/data/backfill_disclosure_dates.py` 并核实 Q1/Q3 覆盖。

### M19.2 复权口径不一致（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`data/market.py` 7 个 daily provider 口径不统一——efinance /
      eastmoney(curl) / akshare×3 为前复权 qfq，`tushare`（`pro.daily`）为不复权
      （docstring line 208 自述 "unadjusted"），`yfinance`（`auto_adjust=True`）
      为后复权含分红再投。`fetch_daily_with_fallback` 命中不同源 → 同股价格序列
      在除权日断层 → ATR14 / 技术因子 / ATR 派生止损止盈被污染。
- [x] 统一所有 provider 输出 qfq，或对非 qfq provider 做口径转换 / 禁用 tushare
      作为日线 provider。Tushare 与 yfinance（auto_adjust=True 为后复权含分红再投）
      均不再注册到 CN fallback，函数保留供调试。
- [x] TickFlow `forward_additive` 口径按官方文档与东方财富/同花顺对齐；实测时间戳需按
      `Asia/Shanghai` 转交易日，修正后才允许作为显式启用的 CN fallback。

### M19.3 QFII 失败结果被永久缓存为空（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`data/qfii_holdings.py` `_fetch_single_quarter` 异常与"确无 QFII
      股东"都返回 `[]`，`get_qfii_history` 用 `if d in cache` 跳过 → 一次抓取失败
      或季报尚未披露即把 `[]` 永久写死，无 TTL、无重试、无区分。
- [x] 区分"抓取失败"与"确无 QFII"（失败不写缓存或写带过期标记）；缓存条目加
      报告期 TTL（披露窗口 120 天内空结果按 7 天 TTL 过期，窗口外稳定永久缓存）。

### M19.4 P3 收尾 ✅（2026-05-27）
- [x] 新闻时区统一：东财 `published_at` 为北京时间 naive，`get_recent_*` /
      `quality` cutoff 用 `utcnow()`，8h 偏移使 24h 窗口实际约 32h；Anspire 无
      日期回退也用 `utcnow`。统一为同一时区基准。
      2026-05-27 已修：`news.py:10-15` 加 CST→UTC naive 转换，存储统一为 UTC
      naive；`get_recent_*` 与 cutoff 全部基于 UTC，注释标 M19.4。
- [x] `point_in_time.py` docstring 明示拦截仅覆盖 `.query(Model)`，列查询与裸
      SQL 绕过。
      2026-05-27 已修：`point_in_time.py:68` 明确"列查询" `db.query(Signal.date)` 等
      不被拦截。
- [x] `get_hs300_constituents` 的 `ak.index_stock_cons_csindex` 加 try/except +
      retry 降级。
      2026-05-27 已修：`universe.py:51` 函数签名加 `max_retries=3, retry_delay=2.0`，
      失败带回退 + 日志。
- [x] 新闻去重跨源失效（东财直连 / AkShare fallback / hash 三种 URL 形态）——
      评估按标题+日期补充去重键。
      2026-05-27 已修：`news.py:272-281` 新增 `seen_title_hashes`（title MD5 前 12 位）
      做跨源标题去重。

### M19 最小交付包
- [x] M19.0 + M19.1 + M19.2 + M19.3，各配一条复现/回归测试。

---

## M20 量化与分析层评审修复 ⏳

> 来源：2026-05-23 完成 M16.3（量化与分析层）评审的确认缺陷。
> 评审范围：`analysis/{factors,technical,sentiment,qlib_engine}.py`、
> `analysis/timing/{rsrs,diffusion,regime}.py`。完整结论见
> `docs/reviews/2026-05-23-m16.3.md`。
> 原则：先修会污染最终建议与推送的 P1，再做仓位/止损相关 P2，最后做 P3。
> 已核实通过、本轮不改：`factors.calc_atr` 用 Wilder ewm、`calc_stop_take`
> 与 STATUS.md 止盈止损公式一致；`qlib_engine._load_model` FEATURE_COLS 维度
> 守护到位；`sentiment.analyze_news` 在 `has_runtime_llm_provider` 假时返回
> `_DISABLED_FALLBACK` 不崩溃；`apply_regime_filter` 本身正确（其被
> `aggregate_v2` 误用是 M17.0）。

### M20.0 RSRS 大盘择时输出浮点噪声（必做 / P1）✅（2026-05-23）
- [x] **缺陷**：`scheduler._build_regime`（`scheduler.py:218-220`）因
      `IndexPrice` 表只存 `close`，对 HS300 用 `high=close×1.005`、
      `low=close×0.995` 合成 OHLC。`_rolling_beta`（`analysis/timing/rsrs.py:16`）
      对完全共线的点求 OLS，理论斜率恒为 `1.005/0.995≈1.01005`、截距 0；
      实际浮点误差让 β 序列在第 ~15 位小数抖动，`rolling(600).std()` 仍为
      ~1e-15，于是 `rsrs_z=(β-mean)/std` 把噪声除以噪声放大成 ±2 量级随机数。
- [x] **触发面**：实跑 40 个随机 seed → 14 次（35%）`rsrs_z` 越过 ±0.7 阈值，
      `market_bullish`/`market_bearish` ≈ 1/3 概率随机点亮 → `dampen_score`
      随机给正向综合分打 0.7 折 → 污染最终 recommendation 和 Bark 推送。
      `STATUS.md` 与 `config.py:regime_filter_enabled=True` 都把这层当作已启用
      阶段A 风控宣传。
- [x] **修复**：本轮先走退化为 None 路径；后续如需真实 RSRS，再让
      `IndexPrice` 增 `open/high/low` 列并由 `sync_index_to_db`
      落真实 OHLC（替代 ±0.5% 合成）。在拿不到真实 high/low 时
      `_build_regime` 让 `rsrs_z` 退化为 `None`（regime 中性），绝不能喂合成
      等比 high/low；`latest_rsrs_z` 加共线守卫——β 序列窗口方差 <
      epsilon 时返回 `None`。
- [x] **复现测试**：构造 40 条 close-only 数据 + 合成 high/low，断言
      `latest_rsrs_z` 返回 `None`（修复后）；同步删除任何固化噪声 z 值的
      旧测试。

### M20.1 涨跌停阈值忽略板块差异（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`analysis/technical.py:10` `LIMIT_THRESHOLD=9.5`，
      `check_limit_status` 对所有 A 股一律 ±9.5%。创业板（300xxx）/
      科创板（688xxx）实际涨跌停 ±20%，HS300 含数十只此类成分股
      （宁德 300750、中芯 688981 等）。
- [x] **触发面**：创业板/科创板单日 10%~19% 正常大跌被误判 `limit_down=True`
      → `risk_manager.py:93` 追「跌停板无法卖出」提示 + `stop_loss_executable`
      置 False；单日 10%~19% 正常大涨被误判 `limit_up=True` → `risk_manager.py:90-92`
      `adjusted_pos *= 0.5` 直接砍掉一半 LONG 仓位 → 污染 `position_pct`。
      `aggregator.py:119-122` 同步往 LLM prompt 注错误提示。
- [x] **修复**：`check_limit_status` 按 symbol 前缀分桶查阈值
      （`30`/`688` → 20%、`8`/`4`（北交所）→ 30%、其余主板 → 9.5%）；
      `Stock` 表已有 `industry` 字段，可一并保留 ST 检测的扩展位。
- [x] **回归测试**：300750 / 688981 涨跌 12% 时分别断言 `limit_up=False`
      / `limit_down=False`；主板 +10% 仍判 `limit_up=True`。

### M20.2 P3 收尾
- [x] **sentiment 缓存**：`sentiment._cache` 加上限 + LRU；命中返回 `dict(...)`
      副本；缓存键改 `_titles_hash(sorted(titles[:15]))`，与实际 prompt 对齐；
      失败结果按短 TTL 缓存以免持续重试。2026-05-25 已先完成 LRU 上限和副本返回；
      失败短 TTL 仍可后续补。
- [x] **qlib 训练质量门槛**：`qlib_engine.train` 在落盘前比对 IC，
      `ic < settings.qlib_train_ic_floor`（建议默认 0.02）时保留旧模型并
      只写一份 `lgbm_alpha_candidate.pkl`，留 promotion 步骤；当前
      `weight_quant=0` 限制爆炸半径，但周训仍会把劣质模型固化。
      2026-05-27 已落地：训练产物先写 `lgbm_alpha_candidate.pkl`，再用
      validation report 检查 `qlib_train_ic_floor` / `qlib_train_icir_floor` /
      `qlib_train_require_monotonic`；未过门保留旧生产模型，过门才覆盖
      `lgbm_alpha.pkl`。
- [x] **diffusion docstring**：`analysis/timing/diffusion.py` 改文档为
      「数据不足的股票跳过、对其余股票算扩散值，全部不足时返回 None」。
      2026-05-27 已修：`diffusion.py:1-12` docstring 加 M20.2 阈值说明 +
      跳过/计算逻辑。
- [x] **regime 阈值对称**：把 `rsrs_bullish_z` / `diffusion_strong_threshold`
      也提进 `settings`，删除 `regime.py:61,63` 的硬编码 `0.7` / `0.6`。
      2026-05-27 已修：`config.py:97,99` 增加 `rsrs_bullish_z=0.7` /
      `diffusion_strong_threshold=0.6`；`regime.py:61-64` 改读 settings，注释标
      M20.2。

### M20 最小交付包
- [x] M20.0（含真实 OHLC 落库或退化为 None）+ M20.1，各配一条复现/回归测试。

---

## M21 基础设施评审修复 ⏳

> 来源：2026-05-23 完成 M16.5（其余后端基础设施）评审的确认缺陷。
> 评审范围：`config.py`、`data/database.py`、`scheduler.py` 剩余 job、
> `ops/kill_switch.py`、`llm/{factory,base,*_provider}.py`、
> `agent/{cli,mcp_server,action_registry,security,http_guard}.py`、
> 其余 `api/routes/*`。完整结论见 `docs/reviews/2026-05-23-m16.5.md`。
> 原则：先修远程模式下安全闸被绕开的 P1，再做契约失效 / 配置不校验 P2，
> 最后做 P3。
> 已核实通过、本轮不改：WAL + pysqlite 默认 5s busy_timeout 覆盖并发写；
> `hmac.compare_digest` 用于 API key 比较；MCP 5 个工具全 read-only + 鉴权；
> kill switch 在 3 个交易/信号 job 接线；`get_provider` 单例 + `reset_provider`
> 暴露给测试；多数变更路由（memory / positions / watchlist / reviews / skills
> / research.copilot / research.deep / system.runtime-config / ai.actions.confirm）
> 已挂 `agent_write_guard`。

### M21.0 远程写守卫覆盖不全（必做 / P1）✅（2026-05-23）
- [x] **缺陷**：`grep` 全量核对 `@router.post/patch/delete` vs
      `agent_write_guard` / `require_http_agent_write*`，以下变更/敏感路由
      **无任何守卫**——`remote` 模式下未鉴权可调：
      - `POST /api/system/kill-switch/trigger` (`routes/system.py:256`)
      - `POST /api/system/kill-switch/reset` (`routes/system.py:265`)
        ——等同未鉴权清除安全闸；
      - `POST /api/model/train` (`routes/model.py:25`)；
      - `POST /api/system/initialize` (`routes/system.py:370`)；
      - `POST /api/ai/chat`、`POST /api/ai/chat/stream` (`routes/ai.py:428,464`)
        ——未鉴权消耗 LLM token；
      - `POST /api/ai/sessions`、`/sessions/{id}/archive` (`routes/ai.py:391,417`)；
      - `POST /api/research/{symbol}/review` (`routes/research.py:26`)。
- [x] **触发面**：仅 `STOCKSAGE_AGENT_MODE=remote` 时生效（默认 `local`，
      本地 guard 直通）；但远程模式正是 guard 唯一发挥作用的场景，本条挖空
      了整层 guard。`kill-switch/reset` 是 P1 中的 P1，必须最先修。
- [x] **修复**：给每条加 `dependencies=[Depends(agent_write_guard("<name>"))]`；
      `kill-switch.trigger` / `kill-switch.reset` / `model.train` 同步加入
      默认 `STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS` 推荐配置示例（非空 allowlist
      生效，避免随意调用）。`/ai/actions/{id}/confirm` 已示范在 body 内调
      `require_http_agent_write_key`，新接线统一用 route dep 形式。
- [x] **回归测试**：静态覆盖每个修补路由均挂 `agent_write_guard`；guard 单测覆盖
      `remote` 模式无 key 返回 401 / allowlist 外返回 403；本地模式与现有行为不变。

### M21.1 `model_tier` 在所有 provider 失效（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`llm/base.py` 接口契约 `fast→Haiku/gpt-4o-mini`、
      `capable→Sonnet/gpt-4o`，但：
      - `anthropic_provider._MODELS` `{fast,capable}` 都映射到
        `claude-sonnet-4-6`；
      - `openai_provider._MODELS` 都映射到 `anthropic/claude-sonnet-4.6`
        （OpenRouter 别名，官方 OpenAI / DeepSeek / Moonshot / Azure 都不
        识别——与该 provider docstring 自述兼容的 endpoint 直接冲突）；
      - `local_cli_provider.complete_structured` 不给 `claude -p` 传
        `--model`，完全忽略 tier。
- [x] **触发面**：`sentiment.analyze_news` 显式传 `model_tier="fast"` 期望走
      Haiku-级价位，实际全部走 Sonnet；盘后批量 ≥88 只股票一次=88 次
      Sonnet 调用，与项目记忆中的 token 暴涨证据吻合。
- [x] **修复**：恢复 fast/capable 真实分层（如
      `claude-haiku-4-5-20251001` / `claude-sonnet-4-6`）；OpenAIProvider
      `_MODELS` 去掉 `anthropic/` 前缀，并允许 `settings.openai_model_fast`
      / `_capable` 覆盖；LocalCLIProvider 接受 tier 时显式传 `--model`。
- [x] **回归测试**：mock provider 客户端，断言不同 `model_tier` 入参导致
      不同的 `model` 出参；OpenAIProvider 不再在默认配置下发出包含
      `anthropic/` 的 model id。

### M21.2 runtime-config 不校验值/类型（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`routes/system.py:128-138` 白名单 key 但
      `setattr(settings, key, value)` 不校验值；`Settings` 没开
      `validate_assignment=True`，可写入字符串到数值字段、写入超界仓位、
      写入加权和 ≠ 1.0 的权重组合——下次计算综合分时 TypeError 或静默错。
      该路由同被 `config.update` registered action 复用，schema
      `_object_schema([], {})` 任意 payload 通过。
- [x] **修复**：(a) `Settings.model_config` 改为
      `SettingsConfigDict(env_file=..., validate_assignment=True)`，让
      `setattr` 走 pydantic 校验；(b) 给 `weight_quant/_technical/_sentiment`
      与 test1 对应权重加 `model_validator(mode="after")` 验证三者各自 ∈ [0,1]
      且 sum=1.0；(c) `config.update` action 的 `input_schema` 明确列必填
      properties 与类型，`execute_registered_action` 用 jsonschema 校验
      payload。

### M21.3 Action Registry `allowed_modes` / `requires_confirmation` 死字段（必做 / P2）✅（2026-05-23）
- [x] **缺陷**：`ActionDefinition.allowed_modes` 字段在 7 个 action 全部设为
      `("local","remote")`，但 `execute_registered_action` /
      `get_action_definition` / `action_metadata` / CLI / `http_guard` 全程
      不读；`requires_confirmation` 同样仅出现在 metadata，CLI 用
      `--confirm` 命令行 flag 硬编码门、不查字段。`ROADMAP M16.5` 重点直接
      点名「与 `http_guard` 是否自洽」——不自洽。
- [x] **修复**：
      - `execute_registered_action` 入口取 `agent.security.agent_mode()`，
        如 mode 不在 `definition.allowed_modes` 抛 `AgentSecurityError`；
      - `requires_confirmation` 若确实只给前端用，从 dataclass 删字段、
        只保留在 metadata 返回；如要服务端强制，CLI / chat 链路均按字段值
        决定是否要 `--confirm`；
      - dispatch 前用 jsonschema 对 payload 做一次校验，缺字段 → 400 而非
        500。

### M21.4 P3 收尾
- [x] **kill switch 状态文件原子化**：`ops/kill_switch._write_state` 改为
      写临时文件 + `os.replace`；`_read_state` 区分「不存在 / 读失败」两种
      情形——读失败时不可默认未激活，应记 warning 且保守视为激活
      （或返回特定哨兵让上层决定）。2026-05-25 已完成。
- [x] **schema 管理单一化**：`database._ensure_runtime_schema` 改为对比
      `Base.metadata.tables` 的列集合与 `PRAGMA table_info` 的差异自动补
      ALTER；或接入 Alembic。删掉重复的 `CREATE TABLE IF NOT EXISTS` 段。
      2026-05-27 已修：`database.py:616` 新增 metadata-vs-PRAGMA diff 自动补列
      机制，注释标 M21.4 schema 单一化。
- [x] **`datetime.utcnow` 残留迁移**：`database.py` 全部 `default=datetime.utcnow`
      / `kill_switch.py:89,168` / `routes/system.py:202` 替换为 timezone-aware
      调用（如 `lambda: datetime.now(UTC)`）。
      2026-05-27 已修：`database.py:8-10` 加 `_naive_utcnow()` 助手
      （`datetime.now(timezone.utc).replace(tzinfo=None)`），全 backend grep
      `datetime.utcnow` 仅剩该助手 docstring 一处；存储格式保持 naive UTC 不变。
- [x] **`system_health` entry 列表对齐**：硬编码
      `["可小仓试错","买入","强买"]` 改为
      `entry_recommendations(include_legacy=True)`。2026-05-25 已完成。
- [x] **`test1_end_date` 默认值订正**：从 `2026-05-17` 改回 `2026-05-20`
      与 `STATUS.md` / docstring 一致；`.env.example` 补 `TEST1_START_DATE`
      / `TEST1_END_DATE` 条目。（2026-05-25 完成；`test_signal_policy` 边界用例同步到 05-21）
- [x] **`cli action --confirm` 跳过冗余 `init_db`**：仅当探测到关键表缺失
      时才跑迁移，否则直接打开 session。
      2026-05-27 已修：`agent/cli.py:20-36` 加 `_init_db_done` 进程级 flag，
      `ensure_schema` 路径只在首次调用时 `init_db()`，后续 confirmed action 直接
      复用，注释标 M21.4。
- [ ] **ATR 窄止损统计分析**：在测试1+测试2 全部 `closed` 仓位上统计
      `ATR / 买入价` 分布，重点看 ATR 占比 <0.5% 的样本是否系统性触发"假止损"
      （盘中跌穿幅度 <0.5% 即被切）。如果该子集胜率明显低于整体且未止损时
      多数能回正，则评估两种修正：① 加 ATR 下限
      `max(ATR×2, 买入价×3%)`；② 改用 trailing ATR×2.5（test2 已在用）。
      触发条件：测试2 跑满 2 个月（≥2026-07-18）后启动。先出统计报告，
      不直接改测试1（规则已冻结）。来源：300308 中际旭创 2026-05-13 开仓，
      ATR≈0.48% × 买入价导致止损线只低 0.95%，05-19 盘中跌穿 0.13% 即触发；
      如果不止损，05-22 收盘 +2.56%（n=1 不足以改规则，需聚合统计）。

### M21 最小交付包
- [x] M21.0（全部漏挂路由 + 回归测试）+ M21.1 + M21.2 + M21.3，各配一条
      复现/回归测试。

---

## M24 长期标签可信度与测试隔离 ⏳

> 来源：2026-05-26 测试1/2运行复核。当前长期标签批次大量出现
> `LLM 调用失败，默认观望`，后续又被 Piotroski / 景气 / QFII 流向聚合成
> 「规避」，若直接接入 `research_constraints` 会把测试1/2入场信号误降级。
> 原则：测试1/2规则冻结期只做隔离，不把未验证长期标签接入对照实验；长期团
> 可靠性修复完成并重建标签后，再评估是否进入下一轮架构测试。

### M24.0 测试期长期约束隔离（必做 / P1）✅（2026-05-26）
- [x] `paper_trading/test1_runner.py` 强制 `settings.long_term_team_enabled=False`，
      测试1继续只按 `test1_legacy_qlib` 的 Qlib / 技术 / 情感权重运行。
- [x] `paper_trading/test2_signal_runner.py` 强制 `settings.long_term_team_enabled=False`，
      测试2继续只按 `new_framework` 运行；不读取当前坏长期标签，不污染
      `test2_ab_runner.py` 的对照结果。

### M24.1 A老师 runtime 可靠性修复（必做 / P1）
- [x] 复现并定位 `AI_PROVIDER=local_cli` 下 `claude -p` 子进程在 agent 会话内
      90s 超时的问题，明确支持的运行方式：独立终端批处理、云 provider，或
      可配置超时/降级策略。
- [x] 单股验收：`300308` 重跑长期团时 A老师输出真实五层分析，`key_findings`
      不再出现 `LLM 调用失败，默认观望`。
- [x] 批量验收：25 支 test2 universe 重跑完成后，记录 A老师成功率、失败清单、
      标签分布和高风险标签原因；失败样本不得直接作为「规避」硬约束参与测试。
      2026-05-27 使用 `LOCAL_CLI_PREFER_CODEX=true PYTHONPATH=. python3 paper_trading/build_longterm_labels.py --force --timeout 180`
      重跑完成：成功 25 / 跳过 0 / 失败 0；无 `LLM 调用失败` 残留；标签分布
      `规避=17`、`观望=5`、`估值偏高=2`、`值得持有=1`；质量分布
      `trusted=22`、`degraded=3`，3 条 degraded 均 `constraint_eligible=false`。

### M24.2 长期标签质量门（建议 / P2）
- [x] 为 `LongTermLabel` / `research_constraints` 增加质量判定：当核心 LLM 分析师失败、
      证据不足或标签过期时，标签只能作为展示/待复核信息，不能阻断入场信号。
- [x] 增加回归测试：`key_findings` 含 `LLM 调用失败` 或质量标记不足时，
      `apply_research_constraints` 不得把正向信号降为「观望」或 0 仓。
- [x] 前端 dossier / StockDetail 明示「长期标签待复核」，避免用户把失败兜底标签
      当成有效研究结论。
- [x] PR #2 合并后补保险丝：新增 `LONG_TERM_CONSTRAINTS_ENABLED=false` 作为
      长期标签联动总开关。默认只展示标签、质量门和约束记录，不改官方推荐/分数/仓位；
      通过实证验证后再显式开启可信标签约束。

### M24.3 长期约束重新接入验证（后置 / P2）
- [ ] 测试2冻结期结束后（≥2026-07-18），用重建后的可信标签回放历史信号，
      对比「无长期约束」与「有长期约束」在假阳性、漏买和收益回撤上的变化。
- [ ] 只有当长期约束降低假阳性且不显著误杀有效入场时，才把
      `LONG_TERM_CONSTRAINTS_ENABLED=true` 重新纳入下一轮测试架构。

---

## M25 综合改进路线图校准 ⏳

> 来源：2026-05-27 对 WorkBuddy 评估建议的二次核验。该评估提出
> AI 流式输出、Zustand、拆分 `database.py`、恢复 Qlib、WebSocket、社区材料等
> 28 条建议；本轮按当前仓库事实重新排序。
> 原则：不重复已完成事项，不为抽象而引入新抽象；先修会污染研究/信号的风险，
> 再补验证口径和运行可靠性，最后做体验升级与战略扩展。

### M25.0 基线冻结（必做 / P1）
- [x] 跑一次当前主线验证并记录真实输出：`make verify`、
      `python3 -m backend.agent.cli health --pretty`、`make coverage-snapshot`、
      固化配置下的 `backtrader_eval`。
- [x] **基线通过判据**（缺一不可，否则归类到对应 M 修复后再继续）：
      1. `make verify` 全绿（后端 pytest + 前端 node tests + frontend build）；
      2. `coverage_snapshot` 输出与 `STATUS.md` 的覆盖数字一致，不一致则改
         `STATUS.md` 而不是改快照；
      3. `backtrader_eval` 在 M18.0 固化的 universe/区间/settings 下跑出与
         `STATUS.md` 标注一致的 Sharpe / 最大回撤 / 盈亏比，不一致则订正 STATUS。
- [x] 校准文档口径：任何测试数量、覆盖数字、最新日期均以命令输出或
      `GET /api/system/data-coverage` 为准。本次基线跑完后，清理 ROADMAP /
      CHANGELOG / STATUS 中残留的硬编码 pytest 计数（如「246 项」「287 项」），
      改为「as of YYYY-MM-DD」标注或引用快照命令。
      2026-05-27 已完成：ROADMAP 早期全套测试数量改成历史计数说明；CHANGELOG
      顶部声明历史验证记录不代表当前套件规模；当前全量验证以 STATUS 的
      `make verify` 输出为准。
- [x] 在基线未通过前不新增 M25.2 之后的大型功能项。

### M25.1 决策污染风险优先收敛（必做 / P1）
- [x] 优先完成 M24.1 / M24.2：长期团队核心 LLM 失败、证据不足、标签过期时，
      标签只能展示为待复核，不能阻断入场或清零仓位。
- [x] **M24.1 排查时窗 → 已定位并修复（2026-05-27）**：根因为
      `_cli_retry` 在 `subprocess.TimeoutExpired` 后仍重试，把单次 90s 超时
      放大为 3×90s = 270s/call（批处理后期日配额/限速时触发）。
      修复：引入 `_FatalResult` 哨兵，超时时走 Codex 兜底一次后立即返回，
      不再触发重试。`local_cli_provider.py` 已修复，454 tests 全绿。
- [x] 为 `research_constraints` 增加质量门回归测试：`key_findings` 含
      `LLM 调用失败` 或质量标记不足时，不得把正向信号降为「观望」或 0 仓。
- [x] StockDetail / dossier 明示长期标签质量与约束资格，避免失败兜底标签被用户
      误读为有效研究结论。

### M25.2 验证与统计口径补债（强烈建议 / P1-P2）

> 本节是优先级聚合，不再平铺新 todo。具体修复项已在 M18 / M19 / M20 列出；
> M25 只负责排序、声明何者阻塞 M25.5 Qlib 灰度，并在完成后回勾。

**阻塞 M25.5 Qlib 灰度**（必须先做）：
- [x] `backfill_signals` quant>0 前视修复 → 见 M18.1「backfill quant 维度前视」。
- [x] Qlib 训练 promotion gate（IC / ICIR / 分层单调性）→ 见 M20.2「qlib 训练
      质量门槛」。
  - 在以上两项落地前，任何 `weight_quant>0` 的回测/灰度结果不进入验收。

**统计语义订正**（P2，不阻塞 M25.5 但影响对外指标可信度）：
- [x] DSR trial 数误用（窗口数 / 股票数误当 multiple-testing trial）→ 见 M18.1。
- [x] IC 显著性有效样本（重叠前向收益 + 同日截面相关）→ 见 M18.1。

**数据口径**（P2）：
- [x] 新闻时区统一（东财北京时间 naive vs `utcnow()`）→ 见 M19.4。

### M25.3 运行可靠性与 schema 管理（建议 / P2）

> 同 M25.2，本节聚合指针 + 新增 M25 特有项；具体修复条目在 M10.5 / M21.4。

**接续既有未完成项**（直接复用 M-编号，不复述）：
- [x] Alembic baseline 或 metadata-vs-PRAGMA 单一 schema 机制 → 见 M21.4
      「schema 管理单一化」✅（2026-05-27 已落 metadata-vs-PRAGMA diff 自动补列）。
      Alembic 仍后置在 M10.5。
- [x] `datetime.utcnow` → timezone-aware 迁移 → 见 M21.4「`datetime.utcnow` 残留迁移」
      ✅（2026-05-27 完成，仅留 `_naive_utcnow` 助手）。
- [x] `cli action --confirm` 跳过冗余 `init_db` → 见 M21.4 同名条目
      ✅（2026-05-27 完成，`_init_db_done` 进程级 flag）。
- [x] `scheduler.py` 剩余 job 拆分 + 统一 `last_run / status / error / result_summary`
      口径。2026-05-27 复核：`scheduler.py` 已经将 postmarket 拆为
      `_load_postmarket_context` / `_postmarket_news_sentiment` /
      `_analyze_postmarket_stock` / `_persist_postmarket_stock` /
      `_maybe_send_postmarket_alert` / `run_postmarket_batch`；所有 job 由
      `run_tracked_job` / `@tracked_job` 装饰器统一记录 last_run / last_status /
      last_error / result_summary，AdminPage scheduler 状态面板已对齐。

**M25 新增**：
- [x] **LLM 成本/天可观测性（2026-05-27）**：新增 `llm_usage_log` DB 表 +
      `backend/ops/llm_usage.py`（token 估算 + 每日汇总 + 预算报警）；
      在 sentiment / copilot / debate / deep_research / chat(summarizer) 5 个
      调用点挂 `log_llm_usage`；`GET /api/system/llm-usage` 返回 7 天每日明细
      和 bucket 分桶；`/system/health` 超预算时写 audit + Bark；
      AdminPage 新增「LLM 成本」标签页展示总计/分桶/每日表格；
      `LLM_DAILY_BUDGET_CNY` 配置项（默认 1.0 CNY/天）。
- [x] **跨入口契约回归测试**：为 pi / MCP / Agent CLI / Web 四个入口的关键
      读契约（`project-context` / `stock-context` / `memory-snapshot` /
      `health` / `/api/system/data-coverage`）增加快照测试，schema 字段缺失
      或类型漂移立即失败。背景：M11/M13/M14 完成多入口后，目前没有任何一处
      回归能挡住 schema 改动割裂某一入口。
      2026-05-27 已新增 `tests/test_cross_entry_contracts.py`：锁定 pi/context
      直连、Agent CLI、MCP health、Web system health/data-coverage 的顶层字段契约，
      并对关键嵌套字段做类型/存在性断言。

### M25.4 产品体验升级（建议 / P2）
- [x] **Chat SSE 真实阶段事件流（2026-05-27）**：`chat_stream` 从”算完再分块”
      升级为生成器内逐阶段 yield：`prepare`（< 50ms）→ `running`（session 就绪）
      → `evidence`（context 读取）→ `token` 流 → `done` / `error`。
      前端 `api.js` 新增 `onPrepare / onRunning / onEvidence / onError` 回调；
      ChatPage 在 answer 为空时显示阶段状态脉冲指示器（已收到请求 / 处理中 / 读取证据）。
- [ ] 不为引入 Zustand 而重构全局状态。优先做页面级请求去重、局部缓存和 loading /
      error 状态收敛；只有跨页面共享状态持续重复时，再评估轻量 store。
- [x] StockDetail 高频数据改为聚合/渐进接口组合：主图和最新信号优先，新闻、证据、
      复盘、长期标签失败不阻塞首屏。
      2026-05-27 已改为核心主图/最新信号先行，新闻、研究档案、证据链、研究状态、
      覆盖、长期标签、历史信号各自独立 loading/error；任一次级接口失败只降级对应区域。
- [x] 增加导出能力：信号、持仓、复盘、覆盖快照支持 CSV；Excel 作为后续增强。
      2026-05-27 已落地：新增 `backend/api/routes/exports.py`，4 个 GET 端点
      `/api/export/{signals,positions,reviews,coverage}.csv`；UTF-8 BOM CSV、中文表头、
      attachment Content-Disposition；signals 支持 `symbol`/`limit` 过滤、positions
      支持 `status=open|closed`、reviews 支持 `kind`/`limit`、coverage 直接读
      `build_data_coverage_snapshot`。回归测试 `tests/test_export_csv.py` 覆盖 4 个
      端点的 status/header/body；458 tests 全绿。Excel (.xlsx) 仍按规划后续做。
- [ ] 自选股规模达到 200+ 且出现卡顿后，再上虚拟列表；当前先保留本地搜索/筛选。
- [ ] 移动端先保障 Watchlist / StockDetail / Chat 三条核心路径可用，不急于做完整
      桌面级功能复刻。

### M25.5 Qlib 离线恢复路线（后置 / P2-P3）

> **前置依赖（缺一不可）**：
> - M18.1 `backfill_signals` quant>0 前视修复完成；
> - M20.2 Qlib promotion gate（IC / ICIR / 分层单调性门槛）落地；
> - M25.0 基线通过判据 3 项全绿。
> 任何 `weight_quant>0` 的灰度在以上前置完成前一律不启动。

- [x] Qlib 不直接恢复生产权重；继续保持默认 `weight_quant=0.0`，直到离线实验通过
      promotion gate。
- [x] 固化离线实验配置：universe、训练窗口、验证窗口、PIT 数据版本、成本口径、
      入场/退出规则和随机种子。
- [x] 每轮输出 IC / ICIR、分层单调性、交易成本后收益、组合权益曲线、最大回撤和
      数据覆盖缺口。
      2026-05-27 已把 `backend/backtest/alphalens_qlib.py --json-output` 扩展为
      M25.5 离线报告：写入 `experiment_config`、默认/活跃 quant 权重、promotion gate、
      panel coverage、成本后分层收益和 top-quantile 权益曲线/最大回撤。首轮
      `--walk-forward` 真实验证结果：single split `IC=0.0372` 但 `ICIR=0.229`
      且分层非单调；walk-forward `IC=-0.0058` / `ICIR=-0.025` / 分层非单调，
      因此保持 `weight_quant=0.0`。
- [ ] 只有多个窗口稳定通过后，才允许小权重灰度，例如 `quant=0.1`；灰度仍需
      kill switch 与复盘闭环。

### M25.6 社区与战略项（后置 / P3）
- [ ] 社区缺口不再按“缺 Issue/PR 模板”处理：仓库已有 issue templates 和
      PR template。下一步重点是 README demo 截图/GIF、release notes、真实 quickstart
      验证路径和典型研究案例。
- [ ] PostgreSQL / pgvector 只在 SQLite schema 迁移、并发或记忆规模成为真实瓶颈后启动；
      不作为当前阶段默认升级。
- [ ] HK/US 多市场支持等 A 股主线验证稳定后再做；优先保证 provider 口径、时区、
      交易成本和调度日历可分市场配置。
- [ ] Tauri / 桌面客户端放到 Web 控制台稳定、有明确高频使用路径之后再评估。

### M25 明确降级或修正的外部建议
- [x] AI 流式输出 + Markdown 已在 M10.3 落地；后续只做真实事件流与体验打磨。
- [x] `database.py` 已完成第一阶段拆分；后续重点是迁移体系和 schema 单一化，
      不是继续机械拆文件。
- [x] Issue / PR 模板已存在；社区改进重点转为 demo、案例和 release 质量。
- [ ] WebSocket 实时推送不作为近期默认方案；止损预警和信号主动通知优先复用现有
      scheduler + Bark，只有需要浏览器内实时多用户状态时再引入。

### M25 最小交付包

**冲刺包（M25-sprint-1，聚焦"基线 + 不污染官方动作"）**：
- [x] M25.0 基线通过判据 3 项全绿，输出归档到 `STATUS.md`。
- [x] M24.1 完成（或在 2026-06-10 走云 provider 兜底分支） + M24.2 完成；
      `apply_research_constraints` 不再被失败兜底标签拉成「观望/0 仓」。

**后续 M25-sprint-2（在 sprint-1 通过后才启动）**：
- [x] M18.1 backfill 前视 ✅ + M20.2 promotion gate（解锁 M25.5）。
- [x] M25.3 新增的 LLM 成本可观测性 + 跨入口契约回归测试落一项。
- [x] M25.4 中 Chat 真实事件流 / StockDetail 聚合加载二选一，配套前端测试或
      手动验收记录。

> 体验项不与 sprint-1 同包：信号污染未收敛前不投入产品体验工作量。

---

## M2 本地验证材料 🏠

本地验证材料、个人记录和临时统计不进入 GitHub。公开仓库只维护可复现的生产代码、回测工具、质量检查和通用复盘入口。

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
      触发条件：本地验证拿到 ≥10 笔样本 + path B 显示 Sharpe ≥ path A + 0.3。
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
      验证 `new_framework_entry_threshold=25` 正确。7 测试覆盖。
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

**门槛**：本地验证通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

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
