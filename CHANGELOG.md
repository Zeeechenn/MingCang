# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。
各里程碑按完成时间倒序排列。
历史条目中的测试数量只记录当时验证输出；当前套件规模与最新通过状态以 `STATUS.md` 的 `make verify` 摘要为准。

---

## [Unreleased] M50 research source-gate follow-up（local）

### Added
- `ai_supply_chain` template now preserves `chain_layers`, `source_tier`,
  `substitute_risk`, and `source_freshness` while keeping
  `observe_only=True`, `signal_impact=none`, and `not_a_buy_score=True`.
- M45 importer / hook-update / falsification-scoreboard source gates now carry
  `source_tier` and `evidence_level`, and execute mode refuses social-only
  evidence or `needs_check` evidence.

### Safety
- No official signal, scheduler, test2, position, production-weight, or trusted
  memory behavior was changed; the new fields remain non-promoting metadata.

---

## [v0.3.3] 产品化收尾 + 证据可复现 + 稳定性硬化（2026-06-09）

> **收尾 0.4–1.0 计划遗留项,不改信号。** 把产品化、可复现证据、社区入口和
> 稳定性门禁里仍空缺的部分补齐。生产信号零漂移(技术 0.6 + 情感 0.4 + ATR 2.5,
> `WEIGHT_QUANT=0.0`);`make verify` 无回归(后端 1101→1115,前端 19→33,
> mypy 226 文件 clean),并新增 `make reproduce-evidence` 离线复现路径。

### Added
- **首次启动引导**(`FirstRunWizard`):5 步上手向导(选模式→导入标的→只读研究→示例复盘→免责),
  localStorage 持久化,短屏竖向滚动防溢出。
- **数据健康页**(`/health`):provider 回退链、freshness 策略、数据质量警告,复用现有 coverage 接口。
- **per-signal 可追溯**:`SignalOut` 暴露 `rule_version`,前端信号卡显示规则版本 +「受 LLM 影响 / 纯规则」徽章。
- **可复现证据**:`make reproduce-evidence` + `scripts/reproduce_evidence.py`(离线确定性复现 demo 闭环);
  `docs/evidence/`(quant 关闭证据 + 闭环案例 + 前向验证方法论)。
- **社区入口**:`examples/provider_plugin/` 示例 + `docs_public/CONTRIBUTING_GUIDE.md`(provider 插件 + action registry 指南);
  `docs_public/EVIDENCE.md`、`docs_public/ARCHITECTURE.md` 调用关系图、mkdocs 导航。
- `docs/API_CONTRACT.md`:公开端点、`X-Correlation-ID`、读写/确认边界。

### Changed
- ChatPage 移动端修复:去掉 `min-w-[760px]`,改 `flex-col` / `lg:grid` 响应式,375px 不再横向溢出;
  pending action 由裸 JSON 改为 key/value 友好卡。
- Watchlist / Reviews 空状态升级为可操作的下一步引导。
- CI `dependency-audit` 去掉 `continue-on-error` 改为硬门禁 + step summary。
- mypy 增量收紧:`backend.config` / `observability` / `tools.registry` 开启 `disallow_untyped_defs` + `warn_return_any`(全局默认仍保持宽松)。
- 版本源统一到 `0.3.3`(package + pyproject)。

### Evidence note
- `docs/evidence/m29_quant_off.md` 记录 DSR 校正 caveat:裸用 IC<0.04 阈值已知有偏(N=12797 下 IC=0.0228 实际显著),
  「quant 归零」结论靠分层非单调、regime sign-flip、残差≈0 等独立证据保留。

---

## [v0.3.2] Reliability, traceability, and release hygiene（2026-06-09）

> **补地基，不改信号。** 这一版把 v0.3.1 之后的工程地基、证据可信度、
> 前端可靠性和工具治理收口到公开 release。生产信号零漂移：`WEIGHT_QUANT=0.0`、
> Kronos off、技术/情绪权重与 ATR 规则保持不变。

### Added
- GitHub Pages 文档站与公开 docs 入口，README / repo About 可直接跳到在线文档。
- P0/P1/P2 工程地基：Alembic baseline + reconciliation 迁移、runtime index 迁移、
  FastAPI 依赖注入边界、CORS 环境变量化、structlog 统一日志、Zustand 与渐进式
  TypeScript 前端脚手架。
- M46/M46.5/M47/M48：no-key demo 首屏路径、lookahead one-time audit、
  evidence trust CLI/API/export visibility、前端关键数值格式化测试、Signal/Evidence
  TSX 可靠性切片与 `StatusBadge` UI primitive。
- M49 tools registry：`python3 -m backend.agent.cli tools` 暴露 retained tools 的
  stable / maintenance / evidence / attic 分类、用途、读写边界与推荐入口。
- API/export/memory-candidate correlation id：`X-Correlation-ID` 在请求、导出响应、
  盘后 HTML metadata 与 memory-candidate audit log 中可追踪。

### Evidence note
- M46.5 lookahead one-time audit（`backend.tools.m46_5_lookahead_one_time_audit`，
  2026-06-09，只读 immutable SQLite）结论：整体 `warning`、无 `blocked`。
  Pass：signal `data_timestamp` 未晚于信号日、每条信号在信号日及之前有价格、
  财务 `disclosure_date` 不早于 `report_date`、review case 未引用未来信号、
  无 trusted memory-promotion 候选缺 review case、PIT guard 覆盖
  Price/Signal/LongTermLabel/FinancialMetric/IndexPrice/NewsItem。
  Warning（转为 M47 常驻检查，不自动改生产）：501 `signals.date` 行用 timestamp 串而非
  `YYYY-MM-DD`；223 条情感信号有同标的次日新闻需 lineage 复核；395 财务行缺确切
  `disclosure_date`；843,391 价格行缺完整 `source`/`fetched_at`/`adjustment` provenance；
  2 条 review case 创建早于其 `as_of`，未复核前保持 non-promoting。
  无 blocked，故未触发信号冻结或 memory-promotion 暂停。

### Changed
- package/API/frontend 版本源统一到 `0.3.2`。
- `make verify` 继续作为发布质量门槛；前端 lint summary 保持 advisory，不阻塞构建。
- M46-M49 文档状态收口为 complete，明确无信号、scheduler、production profile 或 memory
  promotion 行为变更。

### Fixed
- CI/local verify 兼容本地 paper-trading baseline 与 uv lock / ruff backend lint。
- 修正已提交栈里的 EOF whitespace blocker，确保 `git diff --check origin/main..HEAD` 通过。

---

## [v0.3.1] 可信度补丁 / Trust patch（2026-06-06）

> **收口，不加新能力。** 这一版只做产品化收口：清理命名/版本不一致、补一条「必定成功」的
> 演示路径、把首屏从内部术语改成用户视角。生产信号零改动（技术 0.6 + 情感 0.4 + ATR 2.5，
> `WEIGHT_QUANT=0.0`），`make verify` 改动前后无回归（后端 1101 passed / 前端 19 passed / build 绿）。

### Added
- `make demo`：用 mock 数据跑一轮完整演示，**无需真实 API Key 或网络**。配套
  `scripts/demo_seed.py` 幂等种子（3 支股票 + 1 `ForwardThesis` + 1 `ReviewCase` +
  1 pending `MemoryPromotionCandidate`）写入独立 demo DB，真实 `mingcang.db` 不受影响。
- `docs/ARCHITECTURE.md`：L0–L4 分层、Case 类型与融合逻辑的完整说明（从 README 首屏下沉）。
- `docs/WHY_NOT_AI_STOCK_PICKER.md`：解释「为什么明仓不是 AI 选股器」（LLM 边界、ATR 纪律、记忆门控）。
- `docs/dev/BASELINE_2026-06.md`：`make verify` 基线与改动后对照。
- README 首屏「3 分钟上手」与前端界面预览截图（`docs/assets/screenshot-watchlist.png`）。
- `frontend/src/version.js`：前端版本号单一来源（从 `package.json` 读取）。
- Makefile 新增 `frontend-lint-summary`（非阻塞 ESLint 汇总）并纳入 `verify`。

### Changed
- README 首屏改为用户视角：用例表 → 不替你做主声明 → demo → 截图 → 架构一句话概括 + 链接。
- 前端 `WatchlistPage` 版本条从写死的 `v0.2.1 / M27 / M28 / M29` 改为读取 `APP_VERSION`，统一显示 `v0.3.0`。
- 清理 ROADMAP 标题、CHANGELOG、ATLAS 文档与 backend 注释/docstring 里的 StockSage 用户可见残留。

### Kept (compat)
- `_LEGACY_STOCKSAGE_DB_PATH`、`STOCKSAGE_AGENT_*` 环境变量、`.pi` MCP 工具名等载荷型兼容别名保留不动。

---

## [v0.3.0] Research-to-decision loop rebuild + MingCang rebrand（2026-06-06）

> **Headline: the research model was rebuilt.** This release lands a case-based
> research-to-decision loop, reframes the whole system around an auditable
> import → falsify → review → memory loop, and renames StockSage to MingCang —
> all with **zero production-signal drift**.

### Architecture (the main story)
- **Rebuilt the research model into a case-based loop.** Research, signal,
  position, and review are now four linkable, auditable cases — `ResearchCase →
  SignalCase → PositionCase → ReviewCase` — over five layers (L0 memory/KB, L1
  evidence, L2 thesis, L3 signal/position, L4 review/promotion/calibration).
- **Landed dormant, behavior-equivalent.** The new architecture ships dormant by
  default; official signals, scheduler, postmarket, stops, sizing, and
  production scoring are byte-for-byte unchanged while it activates layer by
  layer as evidence gates clear.
- **Positioning shift: amplifier-primary, source-gated.** Offense comes from
  imported human judgment plus the user's filter/veto/sizing, not a manufactured
  price oracle. Added the structured thesis-import channel (`ForwardThesis` draft
  + pending memory), the falsification scoreboard, and a breadth / falsification /
  short-term-risk module triage.
- **Effect: a big architecture change proven safe.** Verified via `make verify`,
  replay/regression zero-diff, DB copy-smoke, dormant-context guard, and the
  official-signal fixture — large architecture, zero behavior drift.

### Changed
- Public identity moved from StockSage to MingCang / 明仓 across the README,
  English README, project index, package metadata, install path, and
  agent-facing project description.
- The homepage was rewritten to state the project's purpose, vision, feature map,
  and future direction, and to explain where single-stock vs. long-term research
  live and how data + memory fuse through the loop.
- The architecture diagram was redrawn to show the four-case loop (inputs →
  ResearchCase → SignalCase → PositionCase → ReviewCase → outcome-gated memory)
  instead of a generic component map.
- Documented the built-in `mingcang` Pi terminal shell as the default
  ready-to-use entry point for non-developers.

### Decision
- Legacy `stocksage`, `stock_sage_*`, `STOCKSAGE_AGENT_*`, and `~/.stock-sage`
  compatibility paths remain available during the transition; new public installs
  and docs should use MingCang naming.
- This release does **not** change production signal weights, quant/Kronos
  promotion status (quant stays off), trading automation boundaries, or HK/US
  read-only constraints. The new architecture stays dormant until forward
  evidence and explicit human confirmation promote it.

## [v0.2.3] M42 qfq/hfq price-contamination guard（2026-06-04）

### Added
- M42 写入时复权口径污染护栏：`backend.data.price_quality.check_adjustment_basis_jump` 会在历史中位数口径下拦截 close > 3x 的疑似 hfq 跳变，`backfill_if_needed` 写库前跳过污染行，等待后续 qfq 重抓。
- 一次性修复 CLI `backend.tools.m42_remediate_hfq_contamination`：默认 dry-run，执行前备份 DB，拒绝生产路径，使用原生 sqlite3 删除已识别的 2026-05-25/26 hfq 污染行，并支持复跑到 0 残留。
- 33 个 hermetic M42 测试覆盖污染判据、dry-run/execute 行为、备份保护和级联收敛。

### Decision
- M42 只处理 qfq/hfq 跳变污染，不改变 production signal profile、量化权重或 HK/US observe-only 边界；600519/600601/600602 整条价格序列口径问题仍作为独立遗留数据项处理。

## [v0.2.2] M41 A/HK/US read-only data facade（2026-06-03）

### Added
- M41 三市场七层数据能力闭环：HK/US daily price bridge、A/HK/US capability catalog、explicit external probes、probe summary、global-data read-only envelope、canonical schema/PIT gate 和 `/private/tmp` probe health ledger 聚合器。
- `GET /api/system/global-data` 与 `python3 -m backend.agent.cli global-data` 提供 `market + symbol + intent` 路由，输出 source、fetched_at、currency/timezone、freshness、missing fields、write policy 与 signal impact。

### Changed
- Production coverage checks 与 PortfolioManager 当前持仓权重改用 CN production 分母；HK/US watchlist/manual positions 保持 observe-only，不稀释 A 股官方组合决策。
- Positions 页面按 CN/HK/US 原币分组展示，不自动合并 HKD/USD/CNY 总值。

### Decision
- HK/US 仍是 read-only research context：不生成 official signals、不进入 postmarket batch、stop-loss check、long-term constraints、position sizing 或 composite_score。任何升级仍需 M29/M41 evidence gate 与人工确认。

## [v0.2.1] M29/M30 质量补丁与 iFinD 新闻补充链路（2026-06-02）

### Added
- M29 Forward Evidence Engine 工具链进入公开主线：read-only evidence ledger、hypothesis registry、forward readiness guard、close-confirmed price coverage refresh、post-event shadow validation 与 quant residual attribution。
- M30 工程质量收敛进入公开主线：Python lock / frozen sync、CI job 拆分、coverage snapshot、低噪声安全扫描、dependency audit、核心路径专项测试和前端 advisory lint / format 入口。

### Changed
- 盘后新闻情绪补充链路从 Anspire 主力切换为 iFinD MCP `search_news` / `search_notice`（仅在 `IFIND_MCP_ENABLED=true` 且配置 token 时启用），仍不足时再走 Tavily；Anspire 保留给显式 deep research / 手动严格事件型新闻抓取。
- `efinance` 从默认依赖改为 optional extra，默认 CN 日线与指数 fallback 不再带入 `retry -> py` dependency audit debt；安装 `pip install -e ".[efinance]"` 后可重新参与 fallback。
- AdminPage 拆出 UI primitives、常量与 panels，主页面保留 state/API 容器职责。

### Decision
- 生产量化层结论不变：`WEIGHT_QUANT=0.0`、`kronos_enabled=false`，M29/M29.5 证据均保持 non-promoting。
- iFinD MCP 只参与新闻/公告补充，不作为 A 股 OHLCV 行情写库源。

### Tests
- Release gate：`make verify` 通过；前端 lint / node tests / Vite build 通过，Python lock check、dependency audit 与核心路径专项测试可复现。

## [v0.2.0] Agent-ready research runtime 与 Alpha evidence release（2026-05-31）

### Added
- 原生 `stocksage` Pi 终端、项目内 `.pi` prompts/skills/extensions、安装脚本与本地 agent launcher 进入公开主线。
- M26 / M27 工具链公开：量化 baseline、Kronos 零样本/finetuned 评估、alpha diagnostic、label/objective search、forward shadow、sentiment cache backfill plan/runner 与 production-profile A/B。
- M28 research runtime 整合：dossier、deep research、copilot validation questions、多轮辩论 research_context 与结构化 IC Memo sections 串联。
- 可选数据源扩展：Tushare qfq late fallback 与 iFinD MCP observe-only adapter，默认均关闭，不写入生产信号。

### Changed
- 公开版本号统一到 `0.2.0`，README / README_EN / Web 首页补充当前 release 摘要。
- 生产 promotion gate 保持严格：未通过 IC / ICIR / monotonic / multiple-comparison 检查前，量化层与 Kronos 不进入生产配置。

### Decision
- M27 证据闭环结论为 `keep_quant_disabled`：`WEIGHT_QUANT=0.0`、`kronos_enabled=false`、signal profile 不变。
- 下一阶段切入 M29 Forward Evidence Engine：只读证据账本、预注册 alpha 假设、样本门与停止条件优先。

### Tests
- 当前 release 以 `STATUS.md` 中 2026-05-31 `make verify` 摘要为准；本条仅记录 release 面向用户的聚合范围。

## [M28] 调研模块整合与实时搜索接入（2026-05-30）

### Added
- `ResearchSection` 升级为 IC Memo schema，结构化保存 `catalysts` / `risks` / `valuation_anchor` / `evidence_snippets` / `stance` / `confidence`。
- `run_deep_research` 支持 Tavily 纯内存 `web_search` 与 `seed_queries`，末轮搜索结果会重新审计后进入报告。
- 多轮辩论支持注入 `research_context`，盘后路径可从持久化 `research_pointer.sections` 恢复 catalysts / risks / evidence。
- dossier 新增 `pending_questions`，承接 copilot `validation_questions`，打通 copilot → deep_research 的问题流。

### Changed
- Tavily 搜索结果不写 DB、不创建 `Signal`、不进入日常信号，仅在显式 deep research / dossier / debate 场景作为研究上下文使用。
- M28 完成后，路线图重心曾回到 M27 Alpha 根治工程；2026-05-31 M27 证据闭环未晋升后，当前活跃重点已转入 M29。

### Tests
- M28 集成覆盖进入 2026-05-30 M26/M27/M28 聚焦套件与 full suite；当前通过状态以 `STATUS.md` 为准。

## [M26] 量化层重估：扩盘、Kronos 零样本评估与生产边界（2026-05-30）

### Added
- 新增 `backend/tools/m26_quant_baseline.py`：本地生成 M26 量化基线报告，验证当前 LightGBM 模型，并对 `quant_off` / `quant_on` / 固定阈值单变量对照做诊断。
- 新增 `backend/tools/m26_expand_universe.py`：HS300 + CSI500 扩盘回填工具，新股票默认 `active=False`，用于训练面扩容，不污染生产自选股。
- 新增 `backend/tools/m26_kronos_eval.py`：Kronos 零样本 IC/ICIR 同标尺评估工具；Kronos 作为 optional local dependency，不进入默认安装与生产路径。
- 新增 `backend/backtest/portfolio_eval.py`：单账户多标的技术回测，显式披露 survivor bias、technical-only 和非生产全栈回测边界。
- `aggregate_v2` 增加可选 `kronos_result`，仅在 `kronos_enabled=true` 时进入 quant 层混合；默认生产仍不启用。

### Changed
- Qlib 训练入口支持 `--include-inactive`，用于 M26.1 扩盘训练；常规训练和生产自选股路径保持原语义。
- LightGBM label 增加 ±30% 截断，降低复权跳点或异常价格对训练标签的污染。
- M26 诊断结论明确区分“诊断阈值”和“生产 promotion gate”：M26.1 仅通过 IC≥0.02 / ICIR≥0.15 / 不强制单调的诊断阈值，未通过生产 gate。

### Decision
- M26.0/M26.1/M26.2 已完成；M26.3 小权重验证暂停。
- 生产继续 `weight_quant=0.0`，`kronos_enabled=false`。
- Kronos 零样本结果不替代 LightGBM；后续 M27.4 微调路径需基于 M27.2 交易池，并等真实 finetuned checkpoint 同标尺验证后再决定是否重启 M26.3。

### Tests
- 新增 M26 baseline、扩盘重训、Kronos 评估窗口、portfolio eval 与长期约束影响报告聚焦测试。

---

## [M25.3/M25.4/M15.2] LLM 成本观测 + Chat SSE 阶段流 + Copilot 日期修复（2026-05-27）

### Fixed
- **M15.2 copilot 日期错配**：`_official_context` 新增 `signal_date` / `decision_date` /
  `decision_date_mismatch`；回退时 prompt 写入日期警告，card 暴露字段。
- **M25.4 Chat SSE 假流式**：`chat_stream` 改为真实阶段 generator（prepare → running →
  evidence → token… → done/error），前端 `api.js` + `ChatPage.jsx` 接新事件。

### Added
- **M25.3 LLM 成本可观测性**：
  - `llm_usage_log` DB 表（每次调用写入 bucket/tokens_in/tokens_out/cost_cny）
  - `backend/ops/llm_usage.py`：token 估算（≈3 chars/token 中英混合）、持久化、7 天汇总、预算报警
  - 5 个调用点挂 `log_llm_usage`：sentiment / copilot / debate / deep_research / chat
  - `GET /api/system/llm-usage?days=N` 端点
  - `GET /api/system/health` 超 `LLM_DAILY_BUDGET_CNY`（默认 1 CNY）时写 audit + Bark
  - AdminPage 新增「LLM 成本」标签页（7 天总计 + bucket 分桶 + 每日明细表格）

### Tests
- 454 tests 全绿；`test_web_system_contracts_keep_monitoring_fields` 更新加入 `llm_budget_alert`

---

## [M24.1] LocalCLI 超时重试放大修复（2026-05-27）

### Fixed
- **根因定位**：`_cli_retry` 在 `subprocess.TimeoutExpired` 后仍触发重试，把单次 90s 超时放大为 3×90s+6s = 276s/call；触发时机为批处理后期命中 claude 日配额/限速（正常调用 5–20s，远低于 90s 阈值）。
- 引入 `_FatalResult` 哨兵异常：`TimeoutExpired` 时走 Codex 兜底一次后抛出 `_FatalResult`，`_cli_retry` 捕获后直接返回结果，不再重试。
- 超时 warning 日志增加 `prompt_len`，便于未来复查是否因大 prompt 引起。

### Tests
- 454 tests 全绿；`test_local_cli_provider_falls_back_to_codex_when_claude_times_out` 已按新行为更新，语义与预期一致。

---

## [M23] 信号证据链、回测口径与运行硬化（2026-05-25）

### Fixed
- M17.1：无关键新闻事件时不再把 sentiment 有效贡献隐式腰斩；有事件时才与 news 分 50/50，breakdown 同步记录有效分与原始情绪分。
- M17.1：决策证据链拆分 `trader_position_pct`、`risk_position_pct` 与最终 `position_pct`，Portfolio Manager 继续基于风控后仓位裁剪。
- M18.1：`compare_paths`、`sweep_threshold`、`exit_sweep`、`exit_logic_experiment` 统一扣除 A 股标准往返成本，并复用按平均持仓天数年化的 Sharpe helper。
- M16.4：前端危险写操作补确认；EvidenceCard 显示交易员 / 风控后 / 最终三层仓位。
- M20/M21 P3：sentiment cache 加 LRU 上限并返回副本；kill switch 状态写入改原子替换，读坏状态时保守视为已触发；system health 入场建议列表复用统一 helper。

### Added
- M12：`/api/system/external-data-sources` catalog 增加 `a_stock_data.margin_trading` 两融 observe-only evidence trial，明确字段、PIT 要求、失败策略和 promotion gate，不写库、不影响信号。
- Local CLI provider 在 Claude CLI 无 JSON/未登录时回退到 `codex exec`。

### Tests
- 新增/更新 trader evidence、backtest costs、sentiment cache、kill switch、external data source 和前端 evidence summary 覆盖。

---

## [M22] 持仓完整性与本地状态隔离（2026-05-24）

### Fixed
- M22.0：持仓创建/更新 schema 锁定 CN/US 市场枚举、正数仓位/成本/止损/止盈/平仓价，并拒绝重复平仓覆盖 realized PnL。
- M22.1：`position.add` agent action schema 对齐 HTTP API，可确认写入 opened_at、stop_loss、take_profit 和 note，仍拒绝未知字段。
- M22.2：初始化数据库默认不再把本机 `~/.stock-sage/memory` 吸入非默认 SQLite；需显式 `STOCKSAGE_MIGRATE_LOCAL_MEMORY=1` 或默认本地 DB 才迁移。
- M22.3：Dashboard Test2 universe 改为请求时加载并暴露 `universe_available`，缺失 ignored 本地文件时不再以 warning 表示异常；补齐前端 `npm test` 脚本与 deep research mypy 修复。

### Tests
- 新增持仓校验、重复平仓、agent action schema、memory 迁移隔离和 Test2 universe 契约回归。

---

## [M17-M21] 评审修复最小交付包（2026-05-23）

### Fixed
- M17.0：`aggregate_v2` 的 regime 衰减不再覆盖 Risk Manager 的否决/降级 recommendation，并同步衰减正仓位。
- M18.0：Backtrader 回测显式设置 0.10% 成交滑点；`STATUS.md` 验证摘要改为 N=2 逐股均值限定口径。
- M19.0-M19.3：PIT 财报过滤改用 `disclosure_date`，Q1/Q3 披露日回填 period 名称修正，CN 日线 fallback 不再注册不复权 Tushare 与后复权 yfinance（口径统一为 qfq），QFII 抓取失败不再永久缓存为空，披露窗口内空结果按 7 天 TTL 过期。
- M20.0-M20.1：RSRS 对缺失/共线 OHLC 返回中性 `None`，不再放大浮点噪声；涨跌停阈值按主板/创业板/科创板/北交所前缀区分。
- M21.0-M21.3：补齐远程写路由 agent guard，恢复 LLM `model_tier` 分层，runtime config 更新走整体验证，Action Registry 执行前校验 mode 与 payload schema。

### Tests
- 新增/更新 M17-M21 聚焦回归；历史聚焦套件 `54 passed`。

---

## [M14] 股票长期记忆与跨入口召回（2026-05-23）

### Added
- 新增 `stock_memory_items` 结构化股票记忆表，覆盖 thesis、risk、event、judgment、outcome、lesson、user_preference 和 research_pointer。
- 新增统一召回入口 `build_memory_context()`，供 ChatPage、Agent CLI/MCP、项目/个股上下文、盘后信号和深度研究复用项目长期记忆。
- 新增股票记忆 API：上下文召回、列表过滤、归档、删除和元数据 patch。
- Admin 记忆管理新增股票长期记忆视图，支持按 symbol/type/status/关键词过滤和受控治理。

### Changed
- 深度研究不只写 `ai_memory` 研究索引，同时为相关股票写入 `research_pointer` 和低风险 thesis/risk/event 候选。
- 盘后决策写入 `judgment` 股票记忆；每日记忆维护会基于后续价格补 outcome / lesson。
- ChatPage 普通回答与长期研究团队模式会读取跨会话股票长期记忆，不再只依赖当前聊天窗口摘要。

### Notes
- v1 不引入 Hermes、mem0、Chroma 或向量库，继续使用 明仓 / MingCang 自研 SQLite + FTS/结构化筛选记忆系统。

---

## [M11] Agent-ready 运行硬化与 API Key 限额说明（2026-05-21）

### Added
- `tests/test_agent_context.py` 增加未初始化数据库、MCP stdio health、remote `api_key` 鉴权 smoke 覆盖。
- README / README_EN 增加 API key 免费、试用和促销额度快照，标明每日可用量估算与控制台优先原则。

### Changed
- `dev` extra 继承 `agent` extra，默认开发安装即可运行完整 pytest 与 MCP smoke。
- GitHub Actions 后端测试安装 `.[test,agent]`，CI 覆盖 MCP 工具桥入口。
- remote 模式下 MCP 工具显式接收 `api_key` 参数并传入安全检查；本地模式保持无需 key。

### Fixed
- `stock_sage_health` / `stock_sage_project_context` 在全新 clone 未初始化 SQLite schema 时返回空状态，不再因 `positions` / `stocks` 等缺表失败。

## [Docs] 软件与 Agent 双用途文档分层（2026-05-21）

### Changed
- `PROJECT.md` 瘦身为公开项目索引，移除本地工作台语气，补充软件/agent-ready 边界说明。
- `STATUS.md` 瘦身为公开运行快照，保留默认权重、调度、验证摘要和启动命令。
- README / README_EN 文档中心补充 `AGENTS.md` 入口。
- Python wheel 打包关闭隐式 package data，避免本地说明、生成报告或运行材料进入发布包。

### Added
- 新增 `AGENTS.md` 占位文件，后续补充 agent 使用说明。

## [Repository Hygiene] GitHub 发布边界收敛（2026-05-21）

### Changed
- 将本地 AI/agent 工作约定、一次性审查报告、内部规划草稿和运行生成的复盘/研究报告移出 Git 追踪范围。
- `.gitignore` 增加本地 agent notes、`REVIEW-*.md`、`docs/reviews/*.md`、`docs/research/*.md` 和内部规划草稿规则，降低误提交风险。
- `docs/ROADMAP.md` 不再引用即将本地化的过程规划文件，M9 背景改为自包含说明。

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
- 聊天回答逻辑读取当前窗口最近消息摘要，不跨窗口读取聊天历史，同时仍可调取 明仓 / MingCang 自选股、持仓、信号、复盘、研究等项目资源。
- 聊天窗口归档改为二次确认流程，首次点击进入“确认归档 / 取消”状态，再次确认才执行归档。

### Fixed
- 修复综合评分双向条只显示红线的问题。
- 修复个股情感进度条数值归一化异常。
- 修复配置页 toggle 白色圆点位置异常。
- 修复复盘页开发模式重复触发 daily ensure 时唯一索引竞争导致的 500。
- 修复平仓接口运行旧后端时出现 404 的可见问题；新增后端路由并重启后生效。

### Notes
- 记忆系统管理建议报告已移出项目仓库，保留在本地私有工作区。
- 历史验证：
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
- 历史验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_audit.py tests/test_deep_research.py` → **8 passed, 1 warning**
- 历史验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider` → **217 passed, 1 warning**

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
- 历史验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider` → **208 passed, 1 warning**
- 历史验证：`PYTHONDONTWRITEBYTECODE=1 python3 -m compileall backend tests` → 通过
- 历史验证：`cd frontend && npm run build` → 通过

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
- 4 个极薄占位文档：本地验证材料 / 本地关注池 / `docs/ARCHITECTURE.md` / `docs/MEMORY_DESIGN.md`
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

### M1.7 双 profile 切换系统

`SignalWeights` dataclass + `active_signal_weights(as_of)` / signal profile auto 模式 / `signal_policy.py` / `trailing_stop.py`

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
