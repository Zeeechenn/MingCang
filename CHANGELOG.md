# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。
各里程碑按完成时间倒序排列。

---

## [M6.3] 前端操作台与复盘/AI 助手增强 ✅（2026-05-19）

### Added
- 前端新增并接入独立页面：
  - `/reviews`：每日复盘 / 长期复盘中心，支持自动 ensure、历史记录和完整报告详情展开。
  - `/positions`：手动持仓设置，支持股票联想、持仓汇总、平仓记录、永久删除已平仓记录。
  - `/chat`：项目内 AI 对话助手，支持通用助手 / 长期研究团队模式、左侧会话窗口、新建与归档。
- 后端新增拆分路由：
  - `backend/api/routes/positions.py`
  - `backend/api/routes/stocks.py`
  - `backend/api/routes/reviews.py`
  - `backend/api/routes/ai.py`
- `positions` 表：记录真实/模拟持仓、平仓价、平仓日期、已实现盈亏和收益率。
- `review_runs` 表：记录每日复盘与长期复盘，支持读取报告全文。
- `chat_sessions` / `chat_messages` 表：AI 对话窗口与窗口内消息，默认窗口隔离。
- 股票搜索 API：`GET /api/stocks/search`，本地股票优先，支持代码/名称联想。
- AI 操作动作：添加/删除自选股、添加持仓、更新配置、触发复盘，写操作均先生成待确认动作。
- 后端根路径 `/` 返回 API 说明，避免直接打开后端只看到 `{"detail":"Not Found"}`。

### Changed
- 首页“系统脉冲”区域替换为真实持仓情况；无持仓时显示空状态，不再展示假数据。
- 首页新增大盘情况卡片；事件时间线统一优先显示股票名称。
- 顶部导航从小文字斜杠改为分段按钮，当前页高亮。
- 配置页分区按钮真正切换内容；配置页可编辑综合分权重、单股/板块/总仓位上限、数据补充参数、每日/长期复盘触发日期与时间。
- 长期研究团队调度从固定周日 11:00 改为两组可配置周内时间，默认周一 09:00 / 周五 15:00。
- 复盘页真实记录和临时示例记录可同时展示；真实每日复盘读取 Markdown 全文，长期复盘将长期标签整理为 Markdown 内容存入 `payload.content`。
- 复盘中心在真实历史较少时以前端示例历史补足展示，覆盖每日复盘、长期复盘、信号明细、持仓复核、异动监控、长期标签变化和记忆写入等完整内容。
- 复盘详情区从纯文本 `<pre>` 展示升级为本地 Markdown 渲染，支持标题、无序/有序列表、表格、段落和行内代码。
- 聊天回答逻辑读取当前窗口最近消息摘要，不跨窗口读取聊天历史，同时仍可调取 StockSage 自选股、持仓、信号、复盘、研究等项目资源。
- 聊天窗口归档改为二次确认流程，首次点击进入“确认归档 / 取消”状态，再次确认才执行归档。

### Fixed
- 修复综合评分双向条只显示红线的问题。
- 修复个股情感进度条数值归一化异常。
- 修复配置页 toggle 白色圆点位置异常。
- 修复复盘页开发模式重复触发 daily ensure 时唯一索引竞争导致的 500。
- 修复平仓接口运行旧后端时出现 404 的可见问题；新增后端路由并重启后生效。

### Notes
- 记忆系统管理建议报告已移出项目仓库，放在 Codex 工作区：
  `/path/to/codex/2026-05-19/s-2/StockSage-memory-system-management-report.md`
- 验证：
  - `pytest tests/test_frontend_expansion_api.py tests/test_memory.py` → **10 passed, 1 warning**
  - `node --test frontend/src/pages/chatArchive.test.js frontend/src/pages/reviewContent.test.js` → **4 passed**
  - `cd frontend && npm run build` → 通过
  - Playwright / 浏览器检查首页、配置、持仓、复盘、聊天页面 → 无控制台错误；复盘 Markdown 表格/列表和聊天归档确认流程可见正常

---

## [M8] 深度研究与来源审计层 ✅（2026-05-17）

### Added
- `backend/data/news_audit.py`：轻量新闻来源审计，按来源可信度、URL 可追溯性、时效性和重复标题打分。
- `backend/data/news.py::get_recent_news_items()`：保留 `title/url/source/published_at`，供情感分析前做证据审计。
- `backend/scheduler.py`：盘后情感路径先审计本地 24h 新闻，再按原逻辑用 Tavily 补足标题；审计结果写入 `DecisionRun.input_snapshot.news_audit`。
- `backend/research/deep_research.py`：手动专题研究流程，支持 CLI：
  `PYTHONPATH=. python3 -m backend.research.deep_research --topic "AI算力产业链" --symbols 300308,300394`
- `backend/research/agents.py`：专题研究角色模板（行业研究员、公司研究员、风险复核员、来源审计员、研究写作员）。
- `POST /api/research/deep/run`：同步生成专题研究报告，返回报告路径、摘要、来源数量和风险标记。
- `backend/memory/research_memory.py`：将深度研究报告以结构化 JSON 指针写入 `ai_memory(scope="research", category="deep_research")`。
- 新增测试：
  - `tests/test_news_audit.py`
  - `tests/test_deep_research.py`

### Changed
- 深度研究写入 `DecisionRun(run_type="deep_research")` 和 `ResearchState`，但不创建 `Signal`，不进入日常盘后信号流水线。
- 新闻情感输入从“纯标题列表”升级为“审计后的可用标题 + 可追溯审计记录”，不增加 LLM 成本。

### Notes
- 深度研究默认输出到 `docs/research/YYYY-MM-DD-主题.md`。
- 当前深度研究为本地数据库优先的确定性流程；后续如接入 OpenAI `web_search` 或 Local Deep Research MCP，应保持手动触发，不接入 `job_postmarket()`。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_audit.py tests/test_deep_research.py` → **8 passed, 1 warning**
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider` → **217 passed, 1 warning**

---

## [M6.1] 量化升级第一阶段 ✅（2026-05-16）

### Added
- `backend/data/qlib_data.py`：LightGBM 特征列加入 point-in-time 基本面因子：
  `roe` / `revenue_yoy` / `net_profit_yoy` / `gross_margin` / `asset_turnover`
- `build_training_data()`：按价格日期只合并当时已知的最近一期 `FinancialMetric`，避免直接使用未来季度数据
- `build_inference_features(df, symbol, db)` 与 `qlib_score(df, symbol, db)`：推理侧可使用同一套基本面特征口径
- `backend/analysis/qlib_engine.py`：新增可选 LambdaRank 训练入口
  - `daily_rank_groups()`：按交易日生成 LightGBM rank group
  - `make_rank_labels()`：按交易日生成横截面排序标签
  - `train(..., model_type="ranker")` / CLI `--ranker`
- `backend/data/universe.py`：新增 `filter_universe()`，支持按市值和日均成交额过滤候选股票池
- `backend/data/market.py`：新增 `yfinance_cn` A 股日线 fallback（`.SZ` / `.SS` 后缀），用于东方财富接口断连时继续回填工程验证样本
- `backend/data/quality.py`：新增数据覆盖报表，统计 active 股票、价格覆盖、2 年价格覆盖、财报覆盖、24h 新闻覆盖和 provider health
- `backend/data/providers.py`：新增 provider health 计数（成功、失败、最近错误）
- `backend/data/database.py`：新增 `FinancialMetric.disclosure_date` 和 `MarketSnapshot` 日频市值/股本/资金流快照表
- `backend/data/market_features.py`：新增 point-in-time 市值/资金流 join helper
- `backend/backtest/alphalens_qlib.py`：新增 `build_validation_report()` 标准化验证报告和 `--json-output`
- `GET /api/system/data-coverage`：返回数据覆盖与 provider 可靠性摘要
- 前端 `EvidenceCard`：展示数据覆盖摘要和当前标的数据覆盖
- 新增测试：
  - `tests/test_qlib_ranker.py`
  - `tests/test_qlib_validation_panel.py`
  - `tests/test_m6_data_quality.py`
  - `tests/test_m6_market_features.py`
  - `tests/test_m6_backtest_report.py`
  - `tests/test_m6_api.py`

### Changed
- `backend/backtest/alphalens_qlib.py`：验证面板改为复用 `build_training_data()`，确保 IC/ICIR/分层回测与训练管线使用同一套特征
- `backend/scheduler.py` / `backend/backtest/backfill_signals.py`：调用 `qlib_score()` 时传入 `symbol` 和 `db`
- `qlib_data.py`：若 `FinancialMetric.disclosure_date` 存在，则训练/推理按披露日做 point-in-time join；缺失时才回退 `report_date`
- `FEATURE_COLS` 加入市值/资金流派生特征：`log_market_cap`、`log_float_market_cap`、`north_net_buy`、`margin_balance`、`large_order_net_inflow`
- Qlib 默认训练模式仍保持 regression；Ranker 需要显式 `--ranker`，避免未验证前改变生产行为

### Notes
- 当前 schema 只有 `FinancialMetric.report_date`，尚无真实披露日字段；后续如接入披露日，应把 point-in-time join 从报告期切到披露日
- 由于 `FEATURE_COLS` 变化，旧本地 LightGBM 模型需重训；在重新验证前，生产默认 quant 权重仍保持 0
- 工程验证样本扩容（当前 HS300 成分股，存在幸存者偏差）：active CN 70 只，其中 69 只满足 ≥480 行；验证面板 51,439 行 × 23 特征，股票数 70
- 扩容后 Qlib regression 验证未通过：80/20 IC=-0.0074、ICIR=-0.034；walk-forward IC=+0.0026、ICIR=+0.009，Top-Bottom=-0.0011，分层非单调
- 决策：暂不恢复 quant 权重，暂不启用 Ranker；先补真实披露日/资金流/市值等更强因子，再考虑 100–300 只 × 3–5 年可信验证
- 数据覆盖快照：active 70 / price covered 70 / two-year price covered 69 / financial covered 10 / news 24h covered 0
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider` → **208 passed, 1 warning**
- 验证：`PYTHONDONTWRITEBYTECODE=1 python3 -m compileall backend tests` → 通过
- 验证：`cd frontend && npm run build` → 通过

---

## [M7] 工程化与开源就绪 ✅（2026-05-16）

### Changed / Fixed — 收尾（2026-05-16）
- **方案 B 切换**：`backend/requirements.txt` 删除，`pyproject.toml` 成为依赖唯一真理源
- **修关键 bug**：`pyproject.toml` 原 `build-backend = "setuptools.backends.legacy:build"` 模块不存在，`pip install .` 直接失败；改为标准 `setuptools.build_meta`
- `[project.optional-dependencies]` 拆 `test` + `dev` 两组（dev 继承 test），支持 `pip install ".[test]"` / `pip install ".[dev]"` 分级安装
- `Dockerfile` / `.github/workflows/test.yml` / `README.md` / `STATUS.md` 全部从 `pip install -r requirements.txt` 切到 `pip install ".[*]"`
- 文档间 M7 状态对齐：PROJECT / STATUS / ROADMAP 三处统一为 ✅ 完成
- Docstring 口径标注：函数级 99%（290/291）vs 含 class+method 91.6%（306/334）

### Added — 收尾（2026-05-16）
- `.editorconfig`：统一换行（lf）/ 缩进（py 4 空格 / js 2 空格 / Makefile tab）/ 编码（utf-8）
- `Makefile`：封装 12 个常用命令（install / test / lint / fmt / typecheck / check / dev / build / clean / docker-build / docker-up / docker-down）

### Removed — 收尾（2026-05-16）
- `backend/requirements.txt`（被 `pyproject.toml` 替代）
- 3 个 legacy 空目录（`backend/{analysis,backtest,data}/legacy`，源文件早已 git rm 但目录残留）

### Added — B + C 组（2026-05-16）
- `STATUS.md`：当前快照（权重 / 调度 / 验证 / 启动命令），从 PROJECT.md 拆出
- `CHANGELOG.md`（此文件）+ `docs/ROADMAP.md`（精简后的未完成里程碑），PROJECT.md 精简为 < 100 行索引
- `.github/workflows/test.yml`：CI 自动跑 pytest + frontend npm build
- `.pre-commit-config.yaml`：ruff lint + format + pre-commit-hooks（trailing-whitespace / yaml / large-files / debug-statements）
- `Dockerfile` + `docker-compose.yml` + `docker/nginx.conf`：backend + frontend 两阶段 build，nginx proxy，sqlite volume
- `frontend/README.md`：前端开发命令 / 页面结构 / 关键组件
- `CONTRIBUTING.md`：环境准备 / 代码规范 / 测试要求 / 核心约束 / PR 流程
- Docstring 覆盖率：52% → **99%**（290/291 函数，agent 批量补全）
- Return type 覆盖率：65% → **91%**（267/291 函数）

### Added — A 组（2026-05-16）
- `README.md`：仓库门面，含项目定位、状态徽章、Quick Start、架构图、调度表
- `LICENSE`：MIT License
- `pyproject.toml`：项目元数据 + ruff（lint/format）+ mypy（类型检查）配置
- `STATUS.md`：当前快照（信号权重 / 调度 / 验证结果）
- `CHANGELOG.md`（此文件）+ `docs/ROADMAP.md`（未完成里程碑）+ PROJECT.md 精简为索引

### Removed — A 组（2026-05-16）
- 5 个零引用活动代码文件：`realtime.py` / `portfolio_backtest.py` / `signal_stats.py` / `signal_stats_universe.py` / `stock_picker.py`
- 4 个极薄占位文档：`paper_trading/results.md` / `paper_trading/watchlist.md` / `docs/ARCHITECTURE.md` / `docs/MEMORY_DESIGN.md`
- 3 个 legacy 目录：`backend/analysis/legacy/` / `backend/backtest/legacy/` / `backend/data/legacy/`

---

## [M3] 可信度审计层 ✅（2026-05-15）

> 旧 Tier 1–4（DSR/PBO/WF/PIT/kill-switch）

### M3.1 DSR + PBO + IC 显著性

**背景**：M1 扫描时用了裸 IC 阈值 0.03，忽略了样本量。M3.1 用学术工具回算，补统计严肃性。

**新模块** `backend/backtest/statistics/`：
- `deflated_sharpe.py` — Bailey & López de Prado 2014 DSR 闭式公式 + SR_0 多试验阈值估计
- `probability_overfitting.py` — CSCV 切分 + IS/OOS 排名 → PBO
- `significance.py` — IC 标准误 / t-stat / 双尾 p

**历史回算结论**：
- IC=0.0228（N=12797）：t=2.58，p=0.0099（极显著）。当时"不合格"是错误的，但分层非单调是独立判否证据，Qlib 归零决策保留
- F 方案 Sharpe=0.72：SR_0(N=8)=0.233，跨越多试验阈值 ✅
- M1.3 Sharpe=1.36（N=2）：跨越多试验阈值 ✅，但样本量小，M3.2 复验后固化

### M3.2 Walk-Forward + Holdout

**新模块**：
- `backend/backtest/walk_forward.py` — `generate_windows` / `run_walk_forward` / `holdout_window`
- `HOLDOUT_START = 2026-01-01`，holdout 仅做一次

### M3.3 Point-in-Time as_of 拦截层

**新模块** `backend/data/point_in_time.py`：
- `PITSession` 包装 db session，按 model 字段自动加 `<= as_of` 过滤
- 受管 model：Price / Signal / LongTermLabel / FinancialMetric / IndexPrice / NewsItem
- 不修改 ORM 本体，主流程裸 SessionLocal 不变

### M3.4 Kill Switch + 健康检查

**新模块** `backend/ops/kill_switch.py`：
- 四类自动检查：连续亏损 N 笔 / 单日回撤 ≥ X% / 数据陈旧 / 手动触发
- `_kill_switch_guard()` 在 scheduler 各 job 入口拦截
- API：`GET /api/system/health`、`POST /api/system/kill-switch/{trigger,reset}`

**评级提升**（与外部评测对照）：回测严肃性 C→A-，统计显著性 C→A-，总评 B+→A-

---

## [M1] 严肃化与质量门槛 ✅（2026-05-15）

> 旧 重构轨阶段 A/B + 执行计划 A/B/C + 长期分析师团 first batch

### M1.1 backtrader + alphalens 迁移

**核心交付**：
- `backend/backtest/backtrader_eval.py` — Backtrader 严肃回测
- `backend/backtest/alphalens_qlib.py` — Qlib IC + ICIR + 分层回测
- `backend/analysis/timing/{rsrs,diffusion,regime}.py` — regime 过滤层
- aggregator 集成 `regime_filter_enabled` 控制

**Qlib 验证**（2020-04 ~ 2026-05，12797 行）：IC=0.0228，分层非单调 → **Qlib 权重归零**，融合切换到「技术 60% + 情感 40%」

### M1.2 8 方案参数扫描 + 默认值固化

**8 方案扫描结论**（按 Sharpe 降序，最优 F：仅持仓 10 天，Sharpe=0.72）：
- 关键洞察：`max_hold_days` 5→10 唯一确认 +0.16 Sharpe；ADX 过滤反而拖累；多改动叠加灾难

**最终默认值**（已写入 `config.py`）：`max_hold_days=10` / `weight_technical=0.6` / `weight_sentiment=0.4` / `weight_quant=0.0` / `trailing_stop_enabled=False` / `adx_filter_enabled=False`

| 指标 | Legacy | 新默认 | 差值 |
|------|-------|--------|------|
| 胜率 | 51.6% | 54.1% | +2.6% |
| Sharpe | 0.56 | **0.72** | **+0.16** |
| 最大回撤 | 17.59% | 17.19% | -0.40% |

### M1.3 长期分析师团 first batch（2026-05-15）

**三位分析师 + QFII 规避**：
- A 老师赛道分析师（光通信/存储等硬件赛道，via A 老师小红书更新）
- Piotroski 财务质量评分（F-Score 9 因子，高分=财务健康）
- 景气投资 Δ 类指标（边际变化 + 同行业分位，判断景气拐点）
- QFII Outflow 反向规避（连续 ≥2 季减仓且累计 ≥20% → 一票否决）

**手工标注回测结果**（含长期标签 vs 不含）：

| 指标 | 无标签 | 含标签 | 改善 |
|------|--------|--------|------|
| Sharpe | 0.72 | **1.36** | **+0.64** 🚀 |
| 最大回撤 | 17.19% | **8.60%** | **-8.60%** 🎉 |
| 胜率 | 54.1% | 58.9% | +4.8% |

**M1 验收标准全部达成**：Sharpe 1.36 ✅ / 最大回撤 8.60% ✅ / 盈亏比 2.78 ✅

### M1.4 修阻断 bug + 记忆骨架

RSI NaN 修复 / 聚合层 NaN 回退 / 仓位计算修复 / 长期标签缺失降级 / ai_memory + audit_log_fts + should_remember()

### M1.5 文件结构整理

legacy 归档 / position_sizer → combo_weights / position_sizing → single_position / 文档新增

### M1.6 信号语言 + 仓位上限 + 退出实验

新信号语言：`可小仓试错 / 可关注 / 观望 / 规避` / 仓位约束：单股 15%、单板块 30%

### M1.7 测试1/测试2 双 profile 切换系统

`SignalWeights` dataclass + `active_signal_weights(as_of)` / `paper_trading_profile` auto 模式 / `signal_policy.py` / `trailing_stop.py`

### M1.8 前端复盘卡片

`SignalEvalCard.jsx`：胜率/平均次日收益 + 分方向收益 + 信号明细 + 30/60/90/180 天窗口切换

---

## [M0] 系统骨架 ✅

> 旧 Phase 0–6

数据/技术/情感/量化/Web/复盘 全链路打通。

- AkShare 数据管道（行情 + 新闻 + 指数，含退避重试）
- ATR/RSI/MA 技术因子 + 止盈止损计算
- Qlib 量化引擎（LightGBM Alpha 模型）
- LLM 新闻情感（Claude Haiku）
- 信号聚合层（三路加权 → 综合建议）
- FastAPI + React Web 看板 + TradingView K 线
- APScheduler 定时任务（盘前/盘后/止损预警）
- Bark iOS 推送
