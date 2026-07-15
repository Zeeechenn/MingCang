# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。
各版本按完成时间倒序排列。
历史条目中的测试数量只记录当时验证输出；当前套件规模与最新通过状态以 `STATUS.md` 的 `make verify` 摘要为准。

---

## [Unreleased]

### Added / 新增

- **M68 新闻金字塔生产镜像**：新增独立 `news_shadow_runs` / `news_shadow_feedback`
  契约、有界手动 CLI 与 M63 盘后 step；同日并排保存正式 legacy、pyramid、
  机械只替换情绪腿的反事实与 `would_change_action`，不写正式 `signals`。
- **可诊断试用面**：新增 `/api/news-shadow/*` 只读查询/健康端点、`/news-shadow`
  前端页和专用反馈端点；可同屏查看价量输入、触发、AttributionCard、证据清单、
  链路错误与中文降级说明，反馈可绑定具体 evidence id。
- **三桶复核**：默认优先审查全部动作分歧、全部高重要性未触发与重启稳定的
  对照抽样；反馈类型固定到漏抓/时效/重复/关联/分类/方向/重要性/触发/融合/解释层。

### Changed / 变更

- M54 日常采集增加 per-symbol `success | failed | not_run` 结果，M68 因而能区分
  已核验无新闻、本轮未采集与抓取失败。金字塔 L1 触发接入真实单日涨跌与
  完整 20 日量比，并将进程缓存按 namespace/tier 隔离，避免 M54/M68 或模型层级串数据。
- M63 盘后报告增加事件关注镜像，展示等级、主因、置信、thesis recheck、触发/降级
  flags；该等级只表示复核优先级，不表示涨跌预测。

### Safety / 安全边界

- M68 落实的判断是：A 股情绪/事件证据先用于解释波动幅度与事件风险；尚不支持
  “单靠情绪稳定预测方向”。事件镜像可先试用，方向替换仍必须另过 M54 统计门与
  owner 显式确认。本批不改正式权重、止盈止损、仓位、scheduler 时序或 test2。

### Verification / 验证

- M68/M54/M63 聚焦后端回归 `51 passed`；schema golden 幂等重生成并通过。
  完整初始化临时库下的全量后端 `1730 passed / 12 skipped`，ruff、发布卫生和 mypy
  （315 个 source files）全绿。前端 TypeScript、26 项 Vitest、production build、零 warning
  ESLint 通过；Playwright smoke 覆盖 14 个桌面路由与 11 个移动路由（含 M68），
  console/page error 均为 0。

---

## [v0.7.0] A/HK/US multi-market integration & gray validation / A/HK/US 多市场接入与灰度验证（2026-07-16）

### Added / 新增

- **A/HK/US 多市场完整接入**：新增 market-scoped `asset_key` 身份与 schema、CN/HK/US 独立
  market profile、港美股行情/财务/新闻/公告适配器、全球长期研究、分市场收盘调度、灰度 bootstrap、
  价格重同步和同池等权回放工具。港股 `00700/09988` 与美股 `AAPL/MSFT/NVDA` 已进入小池影子灰度。

### Changed / 变更

- A 股 production 规则保持不变；HK 灰度使用 `0.65 technical / 0.35 sentiment`，US 使用
  `0.75 / 0.25`，两者均不复用 CN 训练 quant（`quant=0`）。API、持仓、信号、前端筛选与长期标签
  全部识别市场身份，灰度卡片明确显示“影子 · 不下单”。
- 前端股票路由、缓存、列表 key、K 线、新闻、财务和归因全部按 `market + symbol` 隔离；持仓和盈亏
  按 CNY/HKD/USD 分组展示，不再跨币种求和。个股页展示本市场权重、结算、手数、价格保护、时区和
  gray/observe 边界，并通过新财务接口读取带披露日与来源的 PIT 记录。
- 回放分别使用 CN/HK/US 的交易、结算、手数、价格约束、复权与成本规则；截至 2026-07-14，五股
  等权策略成本后 `+127.97%`，同池等权持有 `+1232.93%`，最大单票贡献 `50.77%`，晋升裁决 **HOLD**。

### Safety / 安全边界

- 港美股灰度只写研究/模拟信号，仓位固定为 0，不发提醒、不接券商、不创建订单，也不改变 CN 正式链。
  US 公告 403、实时单源、正式交易所日历与情绪模型退化均显式记录为晋升阻断项，未过门不得扩池。

### Verification / 验证

- `make verify` 全绿：backend pytest `1757 passed / 5 skipped`；ruff、release hygiene、mypy（321 个
  source files，0 error）通过；前端 typecheck、27 项 Vitest、build、零 warning ESLint、15 个桌面 / 13 个
  移动端 Playwright smoke 与 source-truth 检查全绿。另以真实浏览器确认港股 2/2、美股 3/3 筛选和
  “影子 · 不下单”标识，console error/warning 为 0。

---

## [v0.6.3] Research trust closure & repository structure governance / 研究可信度收口与仓库结构治理（2026-07-15）

### Added / 新增

- **M65 研究可信度 Phase 0-2**：ResearchReportGate 增加稳定、机器可读的检查明细；前端 Evidence
  Card 严格区分发布时间与抓取时间，并显式展示 `as_of`、新鲜度、来源层级、可用性、风险标记和
  缺失原因。M57 增加真实 deep-research trace 捕获、过滤 miner 和 Phase 2 评估工具，所有候选继续
  默认 `pending`，自动 `trusted` 保持为 0。
- **M66 AI 开发治理规则**：`AGENTS.md` 固化 canonical-first、tools 仅作 CLI/维护/评估/兼容层、
  最小能力随改随迁、旧入口至少保留一个发布周期等规则；架构测试增加 workflow tools 允许清单
  只减不增和前端生产代码必须使用 `src/services/` 的棘轮守卫。

### Changed / 变更

- **M65 四臂裁决归档**：20 个真实可读案例、19 个行业标签完成 Base / Memory / Serenity / Both
  共 80 份输出与 20 次单盲评分。Both 相对 Base 的来源忠实率、事实覆盖、矛盾处理和可证伪性均
  下降，幻觉/事实错误率由 7.10% 升至 9.70%，裁决 `HOLD_STOP_PHASE_3_4`。保留通用 Evidence
  Card 与结构化 Gate；Serenity 维持默认关闭的人工方法镜头，后续只有重新预注册才能复测。
- **M66 仓库结构治理首批落地**：路线图从 217 行压缩到活跃工作、触发待命和一行归档索引；资金流、
  Tavily、lookahead 审计、量化基线/IC 统计、研究 reference/watchtower path 和 M63 编排获得领域
  canonical path，旧 `backend.tools.*` 入口保留兼容。稳定 core 的静态 core→tools 依赖由架构测试
  禁止新增，M63 workflow 内部的维护工具调用留待对应领域门面成熟后再迁。
- **M66 测试与前端首批归位**：8 个关联测试迁入 architecture/backtest/data/evidence/workflows；前端
  API/live runtime 收进 `src/services/`，生产 import 使用 canonical path，旧平铺入口保留 re-export
  和兼容测试。真实浏览器验证主页、日报页均正常，控制台无 error/warning。

### Safety / 安全边界

- M65 评估与 M66 结构治理均不改变官方 signal、position、止盈止损、生产权重、scheduler、test2
  或数据库 schema；旧 CLI/import 入口在结构迁移期间保留兼容。

### Verification / 验证

- `make verify` 全绿：backend pytest `1728 passed / 5 skipped`；ruff、release hygiene、mypy（310 个
  source files，0 error）通过；前端 typecheck、24 项 Vitest、build、零 warning ESLint 通过。
- Playwright smoke 覆盖 13 个桌面路由、10 个移动端路由及 live/degraded 数据真相，console/page
  error 均为 0；另以 Playwright CLI 实看主页与日报页，服务迁移后正常连接本地后端。
- Python lock 校验通过；`pip-audit` 报告无已知依赖漏洞。

---

## [v0.6.2] Frontend trust closure & guarded workflow hardening / 前端可信闭环与受控工作流加固（2026-07-15）

本版以真实用户流程为验收单位，补齐 Web 前端与后端能力的接线、数据真相、操作确认、移动端和无障碍体验，同时收紧 live/model 工作流的人工晋升边界。明仓仍不连接券商、不自动下单，production quant weight 保持 `0.0`。

### Added / 新增
- **真实浏览器发布门**：Playwright 覆盖 13 个桌面路由、10 个移动端主页面、首次使用流程、demo/live/degraded 数据状态、标的检索和控制台错误；CI 将前端 ESLint 与浏览器 smoke 设为阻断门。
- **Live Track M64 安全漏斗**：新增 fail-closed、只读的 live funnel 脚手架，状态与产物限制在本机私有目录；没有券商执行、自动交易或隐式生产晋升入口。
- **候选模型人工晋升**：训练任务只生成 candidate 与验证报告，生产 promotion 必须由独立、显式的人类确认动作触发并重新校验完整合同。

### Fixed / 修复
- **真实数据与 demo 真相**：首页不再在 live/degraded 模式生成硬编码“研究结论”；demo 持续显示快照日期与模式，300308 示例的评分、证据、仓位和结论自洽。
- **前后端接线补齐**：标的搜索可查询关注列表外的新股票；个股复盘、副驾驶、深度研究、长期团队、模型训练、kill switch、持仓新增和导出均接到真实后端能力。
- **移除假成功**：浏览器不再假装保存 API key、`.env`、provider、scheduler 或试验比例；只读配置明确标注需在本机配置并重启，运行时配置成功提示明确仅作用于当前后端进程。
- **危险操作确认**：治理类工作流与持仓新增均在展示目标和影响后要求二次确认；demo 模式不会伪造持久化写入。
- **日常页与导出真相**：日常页明确为四类只读报告，并把研究/观点录入引导到真实聊天入口；覆盖率 CSV 在 live 模式走真实导出 API，在 demo 模式生成可下载的快照文件。
- **CI 跨平台截图目录**：browser smoke 不再硬编码 macOS `/private/tmp`，改用系统临时目录并支持 `MC_SMOKE_SHOTS_DIR` 覆盖，可在 GitHub Ubuntu runner 上落截图。
- **干净检出测试隔离**：仅依赖本机、被 `.gitignore` 排除的 `paper_trading` replay helper 与 watchlist seed 测试在 GitHub 干净检出中精确 skip；不依赖私有数据的 M58 静态边界测试仍照常执行。

### Changed / 变更
- **首次使用收敛**：5+12 步引导压缩为 3 步，保留目标选择并将用户送到对应真实页面；导航巡游与 10 个主入口一一对应。
- **移动端与无障碍**：移动端持续显示页面导航和数据模式，触控目标至少 44px；补齐跳转主内容、键盘焦点、对话框 focus trap / Esc、`aria-current`、toast live region 与 reduced-motion。
- **加载性能**：路由改为 `React.lazy` 分包，首包由约 501KB / gzip 153KB 降至约 322KB / gzip 108KB。
- **公开说明同步**：中英文 README 将 Web 从“重构后仍在打磨的预览”更新为经过桌面/移动端流程验证的本地工作台，并继续强调 demo 与真实数据严格隔离。

### Safety / 安全边界
- Web 不写入密钥或本机 `.env`，不通过前端静默改变 provider、scheduler、production weights 或交易风险规则。
- 模型训练不等于生产晋升；promotion 继续要求显式人工确认，production quant weight 保持 `WEIGHT_QUANT=0.0`。
- Live Track 保持 fail-closed、只读和本机私有；明仓不连接券商、不自动下单，也不提供投资建议。
- test2 v2 的 LLM treatment boundary override 仅作用于该实验臂并记录越界理由；机械 control 与全局真实持仓校验保持原边界。

### Verification / 验证
- `make verify` 全绿：backend pytest `1708 passed / 5 skipped`，ruff、release hygiene、mypy（297 个 source files，0 error）通过。
- 前端 typecheck、20 项 Vitest、build、零 warning ESLint 全绿；Playwright 桌面/移动端 smoke 无 console error / page error。

---

## [v0.6.1] CI green & README quickstart consolidation / CI 转绿与 README 快速开始收敛（2026-07-06）

紧随 v0.6.0——首次把 `main` 推上 GitHub 后，CI 首跑暴露并修复一批既存的本地/CI 环境差异（此前 `main` 从未 push，CI 从未真正跑绿），并顺手收紧了首页。均不改任何官方信号、仓位、scheduler、production weights 或研究裁量逻辑。

### Fixed / 修复
- **CI 首次公开跑绿**（4 类既存红全清）：
  - 前端 `package-lock.json` 缺跨平台可选依赖（`@emnapi/*` 等）→ CI 严格 `npm ci` 校验失败；删 `node_modules`+lock 全新重生成，本地 `npm ci` 通过。
  - `test_core_paths_worker_d` 硬编码 `assert version == "0.5.2"` → 改断言 `APP_VERSION` 常量（随版本走，不再每次发版都断）。
  - 依赖 `paper_trading/` 本地基线（个人纸上交易数据，`.gitignore` 不入库）的 8 个测试 → 加 `pytest.importorskip` 守卫，CI 无此目录时优雅 skip（沿用仓库既有模式）。
  - `backend-tests` 未先建库直接跑 `make coverage` → 依赖 runtime-schema 表（`forward_theses` 等）的测试报 `no such table`；CI 增 `python backend/data/database.py` bootstrap 步（与 `AGENTS.md` 一致）。
- **依赖安全**：6 个已知漏洞升级到修复版——`cryptography` 48.0.0→49.0.0、`msgpack` 1.1.2→1.2.1、`pydantic-settings` 2.14.1→2.14.2、`python-multipart` 0.0.30→0.0.32、`starlette` 1.2.1→1.3.1（pip-audit 转 "No known vulnerabilities found"）。

### Changed / 变更
- **README（中英双版）收紧**：三个并列的上手段（`3 分钟上手` / `新手快速开始` / `快速开始`）合并为单个 `快速开始`，重组为「零配置试用 / 安装 mingcang 长期用 / 开发模式」三个子段，去掉重复的 `clone`/`make demo` 样板；`30 秒看懂` 段与开头 tagline 重复的两条压成一条。信息不丢、截图与诚实红线保留，`README.md` 与 `README_EN.md` 同步。

### Verification / 验证
- GitHub CI 四 job 全绿（Backend lint/typecheck、Backend tests、Security & dependency audit、Frontend test/build）；本地 `make verify` 通过；`mypy` 0 error；`pip-audit` 无已知漏洞。

---

## [v0.6.0] Trading operation loop, review orchestration, memory self-evolution & release hardening / 买卖操作闭环、复盘编排、记忆自进化与发布加固（2026-07-05）

### Upgrade notes / 升级说明
- 本版明确 `init_db()`（`Base.metadata.create_all` + `_ensure_runtime_schema`）为唯一 schema 权威路径；Alembic 已显式退役（`alembic/DORMANT.md`，启动链与 CI 均不调用 `alembic upgrade`，保留仅作历史）。schema 漂移由 `tests/test_schema_authority.py` 的 golden 快照守卫强制把关：任何 ORM 或 runtime DDL 改动都会让它变红，须显式重生成 golden。Schema 初始化仍由 `python3 backend/data/database.py` 幂等执行。
- 本次补齐的环境变量均已有 `backend/config.py` 默认值；`.env.example` 仅补公开配置面和占位符，未要求新增必填 key。
- 已核对本次公开入口说明：`mingcang stock` 仍是只读 `stock-context`；M63 日常入口仍由 `m63_daily` 三个 mode 加 `m63_weekly` / `m63_research` / `m63_opinion` 承载，未发现破坏性 CLI 变更。

### Added / 新增
- **买卖操作闭环一期（R1/D0/D1/D2/D6/D7,2026-07-05）**:论点合流(forward_thesis 为唯一权威存储,watchlist 降级主题视图,7主题落库)→论点触发器(条件编译器7模板,40条件36条数据化,thesis_validation 进研究队列/thesis_invalidation 出持仓论点风险警示)→入场条件卡(V1/V2/V3 实算价位量能风险线+单笔风险预算参考股数,单票模式)→入场准备度分(四维透明记点+否决项,三道校准门未过即如实渲染"仅证据清单",校准转前向攒样本)→入场演练场(历史触发 PIT 回放+随机对照臂+分箱校准,零 LLM)→裁量层反方审视步(批量最强反驳,severity=high 强制降档)。分数定位=证据清单可视化,非预测。
- **交易级复盘台账+分散持仓模式(D8/D9)**:开仓自动记 snapshot(准备度/触发器/条件卡),平仓补结局,周报按入场准备度 band 归因;portfolio_mode=diversified 提供等权参考+否决区+集中度(第二套逻辑,focus 单票模式默认不变)。
- **M57 记忆自进化 Phase 1**:EvolutionTrace(三时间戳双时间轴+七仓 namespace)/TaskCapsule(盘后自动落胶囊)/ContextGovernor(常驻+检索两层,预算裁剪,注入去重)/memory.correct+archive 确认制 action;方案附录 A/B 收 MemOS/Mem0/Zep-Graphiti/Letta 机制归口(不引框架)。
- **Web 日常页**:M63 报告四 tab+待研究队列+M59 裁量参考区(仅供参考角标),只读 API 六端点(路径白名单防穿越)。
- **评审修复轮(13项闭环)**:语言守卫全出口统一(strict/sanitize 双档)/m60_second_entry 接线断裂修复/main_net 缺失禁填0/Piotroski 分母归一传导/公司事件 PIT 类型门统一/数据合同全品类+降级 coverage_gap:/failure: 分级止噪/trigger_quality 消费接线;复检 13 项 9PASS 4PARTIAL 全收口。
- **M58 网格 harness 收官**:holdout 冲突显式报错+statistical_gate(DSR/PBO);全量网格(695支×966日×26trials)终局确认价格系无统计可辩护优势(选股位 DSR=0.0/p=1.0)。
- **盲裁验收 harness**(`backend/tools/blind_adjudication.py`):判断类功能的常态化 A/B 验收工具——两臂回答确定性盲化(甲/乙)、DB 真实结局对照、多裁判(claude/codex 跨模型)结构化投票、answer_key 隔离、多数票汇总。M61 P4 判断门以此完成 10 案例×双模型 60 票终裁(净版 full 6 : starved 3 : 平 1,跨模型方向一致 9/10),裁决工件在 `paper_trading/m61_out/adjudication_h1_expansion_20260705.json`(本地运行数据,不入库)。`m61_judgment_gate` 增 `--cases-file` 支持外部历史案例集(半年窗口回放)。
- **M59 裁量层四条硬规则**(规格 `docs/dev/M59_ADJUDICATION_RULES.md`,盲裁证据驱动):R1 每条风险警示强制带确定性保护动作(实算止损位/减仓比例);R2 观望类结论必须带可观测再评估触发,copilot 增 `reentry_trigger` 字段与 `trigger_quality` 降级标记;R3 持仓体检增 `atr14`/`stop_gap_atr`/`stop_flags`(止损贴身 <1.5×ATR 与动量股静态止盈标旗);R4 财务质量旗标(CFO<净利/流动比率<1/毛利率过薄)进候选区与体检并渲染仓位收缩建议。面板保持只读,不改官方信号。

### Fixed / 修复
- **统一上下文构建器公司事件 PIT 语义**:执行记录类事件(回购成交等)禁止出现在早于其发生日的历史上下文(时间穿越,盲裁裁判三票实证捕获);排期类事件(解禁/分红/除权/除息/股东大会,提前公告属时点可知)保留 +90 天前瞻。历史回放与判断门评测自此 PIT 干净。

### Changed / 变更
- 将当前仓库授权从 MIT License 调整为 PolyForm Noncommercial License 1.0.0；当前及后续版本允许非商业使用、修改与分发，不再允许未经授权的商业使用。
- 同步更新 README / README_EN badge 与授权说明、`pyproject.toml` 项目元数据、`CONTRIBUTING.md` 贡献说明。
- 压缩 `docs/ROADMAP.md`：把两个已彻底完成的里程碑（M50、M55）的完整详情段从活跃路线图下沉，活跃表只保留进行中/未启动/触发待命工作线；权威技术详情仍在 `docs/dev/m50_research_report_gate_spec.md` 与 `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md`，里程碑级承重点见下。目的：减少 fresh agent 每次读 ROADMAP 的上下文体积。

### 发布工程与加固 / Release engineering & hardening（外部代码评审收口 + 类型门清零）

本版对照一次外部代码评审做了系统性加固，均未改官方信号 / 仓位 / scheduler / production weights / 研究裁量逻辑（observe-only 与打分口径不变）。

Added / 新增
- **Schema 单一权威守卫**（`tests/test_schema_authority.py`）：以 golden 快照冻结 `init_db()` 全量 schema（56 张表，PRAGMA 结构化、抗空白/注释），任何 ORM 模型或 runtime DDL 漂移都会让 CI 变红、须显式重生成 golden——补齐此前"三源（ORM `create_all` + runtime 裸 DDL + Alembic）无强制对齐"的缺口。Alembic 同步显式退役（`alembic/DORMANT.md`）。
- **防未来函数（PIT）守卫专项测试**（`tests/test_lookahead_guard.py`）：`evidence/lookahead.py` 覆盖率 0% → 100%（只读契约、status→动作映射、只读开库路径），把量化系统核心安全路径纳入回归网。
- **前端测试与 lint 基建**：接入 vitest + jsdom + @testing-library 端到端冒烟测试（`npm test` 现真正运行单测），ESLint 9 flat config（react-hooks 正确性 + 死代码，advisory 非阻断），playwright 纳入 devDependencies（修复干净检出跑 `npm run smoke` 缺依赖）。
- **CI/工具链**：pre-commit 增 gitleaks 密钥扫描；pytest 增 `slow`/`integration` 分级 marker；pre-commit ruff 版本对齐 `pyproject`（v0.15.20）。

Changed / 变更
- **前端环境化配置**：API baseURL、请求超时、健康轮询间隔改读 `import.meta.env`（`VITE_API_BASE` / `VITE_API_TIMEOUT_MS` / `VITE_HEALTH_POLL_MS`），均以现值兜底，不改默认行为；换环境不再需要改代码。
- **HTTP 边界**：CORS `allow_methods`/`allow_headers` 从通配 `*` 收敛为显式白名单（origins 早已收敛）。
- **数据库连接**：engine 增 `pool_pre_ping` + `pool_recycle`（SQLite 无害，迁 Postgres 防 stale connection）。
- **LLM provider**：新增统一 `LLM_REQUEST_TIMEOUT_SECONDS`（默认 60s）用于 openai/anthropic；补齐 Anthropic 此前缺失的显式请求超时；重复的重试装饰器抽到 `llm/base.py`（`llm_retry` + `LLMFatalResult`），鉴权/非法请求类致命错误不再触发退避重试（避免白烧 3× 退避）。
- **Docker**：新增 `.dockerignore`（把本地数据库、虚拟环境、`node_modules`、个人数据挡在构建上下文外）；后端镜像改以非 root 用户运行；移除把 `.env.example` 烘进镜像的步骤。

Fixed / 修复
- **全局异常处理**：未捕获异常统一转为脱敏 JSON（`{"detail":"Internal Server Error"}`），不再向客户端泄露栈追踪；`/health` 改为真正 ping 数据库（`SELECT 1`），数据库不可用时返回 503/degraded。
- **配置 fail-closed 守卫**：本地 agent 模式（绕过写鉴权）与非本地 CORS origin 的危险组合在启动时 fail-closed（默认 localhost 配置不受影响）。
- **后端类型门清零**：`mypy backend` 由 58 个错误清到 0（补标注 / None 守卫 / 等价改写，零行为回归），CI "Backend lint/typecheck" 门转绿。
- **可审计性**：收口一批 `except Exception` 静默吞错——单一 JSON 解析窄化为具体异常类型，其余静默 fallback 补日志。
- **测试隔离**：M59 裁量层"禁用即无步骤"测试改用显式置 env 为 falsy（不再依赖运行环境的 `.env` 灰度状态）。

Safety / 安全边界
- 以上加固不改任何官方信号、止损止盈、仓位写入、scheduler、production weights 或研究裁量结论；发布前门：后端 `pytest` 全绿、`mypy backend` 0 error、前端 tsc + vitest + build 绿。

### Completed milestone records / 完成里程碑归档（原在 ROADMAP 活跃段，现下沉）
- **M61 数据基建统筹改造(P0-P4,2026-07-04~05)**:数据源手册库7份+源体检harness+发牌表;中度重构七簇(品类无关注册表+数据合同接线、公告/研报/龙虎榜/公司事件/股东五品类落地、flow腿补建、Piotroski无增发因子修复、声明-验证CI强制关联、静默吞错清剿、统一stock context builder);消费端三件(长期标签/copilot+面板/观察哨)接统一上下文包;判断门盲裁终裁:10案例(半年窗口跨regime)×双模型60票,净版 full-context 6:starved 3:平1,跨模型方向一致9/10,判定=数据价值成立、纪律必须规则化;公司事件PIT语义修复;002821/300759盲区股历史回填;300759复权断点qfq重抓修复(-58%假断崖消除)。
- **M59 裁量层四条硬规则(175623b)**:详见上方 Added 条目。
- **M63 复盘编排全线闭环(16ab4be/54c6da5/59a6677/e0de4ea/d9cb2a4)**:六个工作流入口(盘前看/盘中记/盘后决/周末体检/研究<目标>/喂观点);底层 4 个模块命令(`m63_daily` 三 mode + weekly/research/opinion);三触点+三层研究(随时/触发R1-R6/固定周末体检);触发器进化闭环(周末体检漏网→新触发规则,R6价格异动触发首跑21条入队);人话报告层(术语字典+语义解释行);接线一致性测试(stable工具未接线=CI红);盘后入口甩掉旧LLM全池炸弹。
- **M60 观察哨(0ec9fdd/fe93378/3b83917)**:已实现 Phase 0 观察清单 schema、Phase 1 盘后三类触发检测与面板跟进候选区、Phase 2 触发后带研究上下文的 LLM 确认层；Phase 2b 已新增第二时间入场影子台账，作为高位强势股二次入场盲区的 observe-only 记录面，不改官方信号。
- **M58 出场通道(f7ba7ad/f0c852e/33e0bcc/d78d6b1/e43833b/e22eb86/eb5f297 等)**:已实现 exit_sweep 大样本通道、出场参数影子臂(日常对账现行 ×2.5 vs 候选 ×3.5/dd10)、网格回测 harness v1(T/M 两族 + 11 权重格点 + 门控/串联规则型)、LGBM walk-forward 关门测试，以及复权拼接污染修复工具(dry-run/备份/幂等)。
- **M54 新闻层 v2(75afa70..026cdf9,约32提交)**:已实现 pluggable 多源正文采集、分级 cluster/signal、五层 token 金字塔、预算护栏与每日前向采集 CLI。按 `docs/dev/M54_OOS_PREREGISTER.md` §12-13 与后续 LEADER 口径，三个月 OOS 对纯新闻腿的判定为弱：h3d ICIR 0.167/19 天/分桶不单调，未过绝对门；pyramid 的省 token/触发窗口不损信号结论独立成立，但 v2-vs-legacy 仍需向前采集扩窗口。新闻+资金流融合回测延期至资金流滴灌攒够后再做，不把纯新闻腿结论外推到融合腿。
- **M50 Serenity 瓶颈研究 skill + 强制报告门（Phase 0-3 released / non-promoting）**：交付独立 `SerenityChokepointReport`（不复用 `role="track"`、不进 `LongTermTeam` 聚合、无 score/vote，只出 `chokepoint_layer`/`evidence_tier`/`research_priority_band` 等档位字段）；`ResearchReportGate`（`backend/research/research_report_gate.py`）在 `deep_research.py` `write_text()` **之前**强制执行，blocked 报告物理上不落盘、不 record_decision_run、不建 memory candidate；`source_tier` 枚举 + 禁词表作为 Serenity 与 Gate 共享 module；扩 `ai_supply_chain_template` 加 `chain_layers`/`source_tier`/`substitute_risk`/`source_freshness`；M45 importer/`m45_track_hook_update`/`m45_falsification_scoreboard` 的 source-tier + evidence-level guard 同步增强防旁路漂移。数据覆盖判 warning（永不 blocked），blocked 靠 `DeepResearchReport.gate_status` 区分。70 M50 测试 green、lint/mypy clean、生产 signal 零改。
- **M55 Serenity 收敛进 ATLAS 研究脊柱 + s-skill 优点归口（Phase 0-3 done 2026-07-02 `e45bbb1`）**：把 `serenity_chokepoint.analyze()`（事实休眠：default-off + 零 CLI/web/pipeline 入口）六步降级为跑在既有 ATLAS 脊柱上的**方法论透镜**，消除独立平行 analyzer；三个外部 Serenity skill 优点归口——zad 独立 reviewer→`review_loop`、zad 中文表达规范→`dossier` 全局输出规范、zad 发现硬门+定性/数字分轨→`research_report_gate` 检查项（从 SKILL.md 文字劝导升为门强制、additive）、zad 14 判据/10 红旗→`theme_hypothesis_engine`/`forward_thesis` 选择性吸收、muxuuu 工程打包→ATLAS 自有 test 套件；fadewalk 资金流维度按**层纯度红线弃/隔离**（不入研究层）；zad 估值引擎（PT/仓位/预期空间数字）违反 observe-only 不引入；README 诚实口径修正（公开面「Serenity 灰度中」与代码 default-off 不符 → 改为方法论就绪/待激活）。保持 `test_serenity_chokepoint` 隔离不变量（no score/vote、不 import decision/LongTermTeam）。`PYTHONPATH=. pytest -q` 1274 passed、生产 signal diff=0。

---

## [v0.5.2] De-personalize track analyst and archive M51 plan / 去人格化重命名与 M51 方案归档（2026-06-15）

重构 + 文档，non-promoting，功能行为不变；未改 official signal / 仓位 / scheduler / test2 / production weights。

### Added / 新增
- 新建 `docs/dev/M51_EXTERNAL_BORROWING_PLAN.md`：外部金融开源项目（FinGenius/FinRobot/FinGPT/FinGAIA 研究系 + QuantDinger/alpha101 量化系）统一借鉴详案，含四域归口表、逐项目重复判定、两轨边界与防回归护栏。核心结论：QuantDinger/alpha101 对明仓净增量≈0（回测/统计门/审计/Qlib 因子均已自建），一律 graft 现有模块、不新建平行轨；曾议的 M29.6 新回测 lab 取消，拆为 D1-D4 小 graft。
- `docs/ROADMAP.md` 新增 M51 里程碑级承重点与量化轨 D1-D4 归口（D1→m29_hypothesis_registry、D2/D4→M12、D3→ATLAS）。

### Changed / 变更
- 压缩 `docs/ROADMAP.md` 当前接手入口表与 `STATUS.md` Current State：已完成项（v0.3.3–v0.5.1、M44–M50）从活跃表下沉到 Completed Milestones Index 与本 CHANGELOG，活跃表只保留进行中/触发待命工作线，便于后续查询。
- 内容收敛为"仅 skill 功能"：`.pi/skills/track-analyst/SKILL.md` 收敛为纯方法框架（5 层 + 6 工具），移除人物身份/外部来源出处/外部文章引用/具名公司数据点等记录。
- 去人格化重命名（明仓 repo 范围）：长期团队 track 角色统一为中性命名——中文显示名 `赛道研究员`，代码标识符 `track_analyst` / `track` / `track-analyst`，配置键 `LONG_TERM_TRACK_*`；相关模块、测试与 skill 目录名同步规整。功能逻辑（长期团队 track 角色、m45 导入工具、registry）行为不变；全量回归 1214 passed / 5 skipped。
- 外部内容来源出处字样从代码/文档中移除。
- 将 Python / API / 前端 package / lockfile / 静态运行时版本面统一到 `0.5.2`。

### Notes / 说明
- 外部抓取的原始内容（帖子/文章/记录）不纳入明仓仓库；本地 skills 另建独立 git 库并以 `.gitignore` 排除原始内容。

## [v0.5.1] Context sanitization and status surface / 上下文脱敏与状态版本面（2026-06-13）

### Fixed / 修复
- Sanitized AI chat, research-memory, and copilot context rendering so local
  paths, `report_path` fields, and raw JSON snippets are not exposed in the UI.
- 研究副驾驶 / 聊天上下文展示增加脱敏与折叠，避免向前端暴露本机路径、
  `report_path` 字段或原始 JSON 片段。
- Stopped the desktop live preload from probing dormant Atlas business routes
  when `atlas_enabled=false`, eliminating expected 503 noise from
  `/research/memory-candidates`.
- 前端 live 预取改为先读取系统状态，Atlas 休眠时不再调用会返回 503 的业务探测路由。

### Changed / 变更
- Added a shared backend version constant and exposed safe `version`,
  `atlas_enabled`, and `ai_provider` fields from `/api/system/status` without
  returning local database URLs or absolute paths.
- 增加共享后端版本常量，`/api/system/status` 只返回安全状态字段，不再返回本机
  database URL 或绝对路径。
- Aligned Python, API, frontend package, lockfile, and static runtime release
  surfaces on `0.5.1`.
- 将 Python / API / 前端 package / lockfile / 静态运行时版本面统一到 `0.5.1`。
- Clarified the desktop terminal fallback as a sample snapshot flow and made
  the built-in demo price dates self-consistent with the snapshot date.
- 桌面首页终端回落语义改为示例快照，并让内置样例价格日期与快照日期一致。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, database,
  or trusted-memory behavior was changed.
- 不改官方信号、scheduler、test2、仓位、生产权重、数据库或 trusted memory 行为。

## [v0.5.0] MingCang naming finalization / 明仓命名收口（2026-06-12）

### Changed / 变更
- Finalized MingCang naming across native Pi assets, installer scripts,
  launcher entrypoints, public READMEs, license, status docs, roadmap, API, and
  frontend/package version surfaces.
- 原生 Pi 资产、安装脚本、launcher 入口、公开 README、许可证、状态文档、路线图、
  API 与前端/package 版本面统一收口到 MingCang / 明仓 与 `0.5.0`。

### Removed / 移除
- Removed the transition compatibility layer for the previous command, MCP tool,
  environment-variable, launcher, and local-path names from this release slice.
- 移除过渡期兼容层：旧命令、旧 MCP 工具别名、旧环境变量回退、旧 launcher 和旧本地路径入口
  不再作为安装器或 Pi 终端公开合同。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, database,
  or trusted-memory behavior was changed.
- 不改官方信号、scheduler、test2、仓位、生产权重、数据库或 trusted memory 行为。

## [v0.4.3] Frontend punctuation and M29 evidence baseline / 前端标点与 M29 证据基线（2026-06-12）

### Fixed / 修复
- Normalized user-visible Chinese frontend copy to use Chinese commas instead of
  ASCII commas.
- 将前端用户可见中文文案中的英文逗号统一改为中文逗号。

### Changed / 变更
- Recorded the M29 1d / 3d / 5d forward baseline artifacts and current
  non-promoting evidence-ops state in `STATUS.md` and `docs/ROADMAP.md`.
- 在 `STATUS.md` 和 `docs/ROADMAP.md` 记录 M29 1d / 3d / 5d forward baseline
  artifacts 及当前 non-promoting evidence ops 状态。
- Aligned package, API, frontend, runtime-demo, and lockfile version surfaces on
  `0.4.3`.
- 将 package / API / frontend / 演示运行时 / lockfile 版本面统一到 `0.4.3`。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, database,
  or trusted-memory behavior was changed.
- 不改官方信号、scheduler、test2、仓位、生产权重、数据库或 trusted memory 行为。

## [v0.4.2] Frontend TypeScript and visibility hardening / 前端 TypeScript 与可见性加固（2026-06-12）

### Added / 新增
- Added a coverage floor to CI, Dependabot configuration, and an explicit
  local-first threat model.
- 增加 CI 覆盖率下限、Dependabot 配置和 local-first 威胁模型说明。

### Changed / 变更
- Migrated the frontend source modules to TypeScript/TSX with real ES module
  imports while keeping runtime compatibility exports.
- 将前端源码迁移到 TypeScript/TSX 和真实 ES module imports，同时保留运行时兼容导出。
- Pinned React type packages to the React 18 runtime line and refreshed stale
  frontend module comments after the migration.
- 将 React 类型包固定到 React 18 运行时系列，并修正迁移后的陈旧前端模块注释。
- Aligned package, API, frontend, runtime-demo, and lockfile version surfaces on
  `0.4.2`.
- 将 package / API / frontend / 演示运行时 / lockfile 版本面统一到 `0.4.2`。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, database,
  or trusted-memory behavior was changed.
- 不改官方信号、scheduler、test2、仓位、生产权重、数据库或 trusted memory 行为。

---

## [v0.4.1] Public-surface polish / 公开展示面修补（2026-06-11）

### Added / 新增
- Restored the original line-chart favicon concept and recolored it for the new
  glass-shell frontend palette.
- 恢复旧版折线网页图标语义,并按新版玻璃拟态前端的蓝色主色重配色。

### Changed / 变更
- Refreshed the GitHub homepage screenshot to show the new decision pulse
  dossier instead of the old watchlist UI.
- 将 GitHub 首页截图更新为新版「今日裁决案卷」界面,替换旧自选页截图。
- Aligned package, API, frontend, runtime-demo, and lockfile version surfaces on
  `0.4.1`.
- 将 package / API / frontend / 演示运行时 / lockfile 版本面统一到 `0.4.1`。
- GitHub release notes are now maintained as bilingual Chinese/English entries.
- GitHub release notes 统一维护为中英文双版本。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, database,
  or trusted-memory behavior was changed.
- 不改官方信号、scheduler、test2、仓位、生产权重、数据库或 trusted memory 行为。

---

## [v0.4.0] Frontend glass-shell refresh（2026-06-11）

### Added / 新增
- Replaced the old Tailwind/react-router frontend with a high-fidelity glass-shell
  UI covering terminal, pulse, stock dossier, reports, chat, positions, health,
  and admin routes.
- 用高保真玻璃拟态前端替换旧 Tailwind / react-router 页面,覆盖终端、今日裁决、个股案卷、
  复盘案卷、聊天、持仓纪律、来源健康和治理台。
- Added live/demo data fallback: the UI shows local backend data when `/api` is
  reachable and falls back to bundled demo data when the backend is unavailable.
- 增加 live/demo 数据回落: `/api` 可达时显示本地后端数据,后端不可达时回落到内置演示数据。
- Added frontend ATLAS ledger surfaces for forward theses, thesis ledger, memory
  candidates, and case loop views; backend `ATLAS_ENABLED=false` dormancy gates
  still control real access.
- 增加 ATLAS 账本前端界面: ForwardThesis、论题账本、记忆候选和 case loop 视图;真实访问仍由
  后端 `ATLAS_ENABLED=false` 休眠门控制。

### Changed / 变更
- Package, API, frontend, and lockfile version surfaces now align on `0.4.0`.
- package / API / frontend / lockfile 版本面统一到 `0.4.0`。
- Frontend CI entrypoint keeps `npm test` available as a Vite build gate for the
  prototype-style frontend, preserving the existing GitHub workflow order.
- 前端 CI 保留 `npm test`,以 Vite build 作为原型式前端的构建门,不改变现有 GitHub workflow 顺序。

### Safety / 安全边界
- No official signal, scheduler, test2, position, production-weight, or trusted
  memory behavior was changed. ATLAS data remains controlled by the existing
  backend dormant guard.
- 不改官方信号、scheduler、test2、仓位、生产权重或 trusted memory 行为;ATLAS 数据仍受后端休眠门控制。

---

## [v0.3.4] Research source-gate hardening（2026-06-10）

### Added
- `ai_supply_chain` template now preserves `chain_layers`, `source_tier`,
  `substitute_risk`, and `source_freshness` while keeping
  `observe_only=True`, `signal_impact=none`, and `not_a_buy_score=True`.
- Research-positioning importer / hook-update / falsification-scoreboard source gates now carry
  `source_tier` and `evidence_level`, and execute mode refuses social-only
  evidence or `needs_check` evidence.

### Changed
- Package, API, frontend, and lockfile version surfaces now align on `0.3.4`.

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
- 清理 ROADMAP 标题、CHANGELOG、ATLAS 文档与 backend 注释/docstring 里的旧品牌用户可见残留。

### Kept (compat)
- 旧数据库路径、旧 agent 环境变量、`.pi` MCP 工具名等载荷型兼容别名当时保留不动。

---

## [v0.3.0] Research-to-decision loop rebuild + MingCang identity（2026-06-06）

> **Headline: the research model was rebuilt.** This release lands a case-based
> research-to-decision loop, reframes the whole system around an auditable
> import → falsify → review → memory loop, and moves the public identity to MingCang —
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
- Public identity moved to MingCang / 明仓 across the README,
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
- Transition compatibility paths remained available in that release; new public
  installs and docs were directed to MingCang naming.
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
- 原生 Pi 终端、项目内 `.pi` prompts/skills/extensions、安装脚本与本地 agent launcher 进入公开主线。
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
- M22.2：初始化数据库默认不再把旧本机记忆目录吸入非默认 SQLite；需显式迁移开关或默认本地 DB 才迁移。
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
- 旧 MCP health / project-context 兼容别名在全新 clone 未初始化 SQLite schema 时返回空状态，不再因 `positions` / `stocks` 等缺表失败。

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
- 赛道研究员（光通信/存储等硬件赛道，供应链驱动框架）
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
