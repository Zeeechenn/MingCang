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

## M2 纸上交易验证 ⏳（旧 Phase 6.5 + 执行计划 D + 测试1/测试2）

详细规则与持仓见 `PAPER_TRADING.md` 索引及 `paper_trading/` 拆分文件。

### M2.1 测试 1（用户主导，2026-05-13 ~ 05-20，1 周）
宽撒网验证系统完整性。**含 5 个交易日强平规则**（仅本测试适用）。

### M2.2 测试 2（Claude 主导，2026-05-21 ~ 2026-07-21，2 个月强测试）
精选 7 股，阈值 25。**无 5 日强平** — 让趋势完整运行。中期复盘节点：6/3、6/20、7/4。

### M2.3 测试 1 收盘后汇总（2026-05-20）
- [ ] 汇总持仓 / 信号准确率 / 与系统建议的对照

### M2.4 测试 2 启动 checklist（2026-05-21）
- [ ] 启动当日执行 checklist（详见 `paper_trading/test2.md`）

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

**门槛**：M2 测试 1/2 通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

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
