# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。
各里程碑按完成时间倒序排列。

---

## [M7] 工程化与开源就绪（进行中，2026-05-16 ~）

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
