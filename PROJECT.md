# StockSage — 项目索引

> **每次开始工作前先读这个文件。** 详细内容见各链接文档。

---

## 项目定位

个人 A 股辅助决策工具。量化引擎（技术因子 60% + LLM 情感 40%）融合后输出建议，用户自行最终决策。

**核心约束**：止盈止损由 ATR 公式计算，LLM 不做价格预测，不做自动交易。

---

## 快速导航

| 文件 | 内容 |
|------|------|
| [STATUS.md](STATUS.md) | 当前快照（信号权重 / 调度 / 验证结果 / 启动命令） |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑详情（M0 / M1 / M3 / M7 / M8） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中与待做（M2 / M4 / M5 / M6 / M8） |
| [PAPER_TRADING.md](PAPER_TRADING.md) | 纸上交易索引（测试 1/2 规则与持仓） |
| [README.md](README.md) | 项目门面（Quick Start / 架构图） |

---

## 任务编号体系（2026-05-15 起生效）

**统一用里程碑 M0–M8 + 子任务 M{X}.{Y}**。历史叫法见下表（保留为括号别名，新任务一律用 M 编号）。

| 历史叫法 | 归属 |
|---|---|
| Phase 0–6 | **M0** |
| Phase 6.5 / 执行计划 D | **M2** |
| Phase 7（美股扩展） | **M6** |
| 执行计划 A / B / C | **M1.4 / M1.5 / M1.6** |
| 重构轨阶段 A / B | **M1.1 / M1.2** |
| Tier 1 / 2 / 3 / 4 | **M3.1 / M3.2 / M3.3 / M3.4** |

---

## 里程碑总览

| 里程碑 | 名称 | 状态 |
|---|---|---|
| **M0** | 系统骨架 | ✅ 完成 |
| **M1** | 严肃化与质量门槛（Sharpe 1.36 / 回撤 8.6%） | ✅ 完成 |
| **M2** | 纸上交易验证 | ⏳ 进行中 |
| **M3** | 可信度审计层（DSR/PBO/WF/PIT/KillSwitch） | ✅ 完成 |
| **M4** | 多 Agent 决策深化 | 🟡 大部分（M4.1/4.2/4.3/4.6 已落地，M4.4/4.5 暂缓） |
| **M5** | 自动化执行 | 🔲 后置 |
| **M6** | 持续迭代与扩展 | ✅ M6.1 / M6.3 当前范围完成，持续迭代 |
| **M7** | 工程化与开源就绪 | ✅ 完成（A/B/C 全 + .editorconfig + Makefile + 切 pyproject 单一真理源） |
| **M8** | 深度研究与来源审计层 | ✅ 完成（新闻审计 + 手动专题研究 + 研究记忆） |

---

## 关键文件索引

```
backend/config.py                            配置入口（环境变量、路径、调度时间、Bark、双 profile）
backend/data/database.py                     数据库模型 + 轻量幂等迁移
backend/data/market.py                       行情数据拉取（AkShare A 股为主，含重试）
backend/data/providers.py                    行情 Provider registry + fallback
backend/data/universe.py                     股票池候选 / 去重 / 市值流动性过滤 / 批量回填
backend/data/qlib_data.py                    Qlib 特征构建（技术 + PIT 基本面）
backend/data/quality.py                      数据覆盖报表 + provider 可靠性摘要（M6.1）
backend/data/market_features.py              市值/股本/资金流 PIT 特征 join（M6.1）
backend/data/news.py                         新闻抓取（stock_news_em，含重试）
backend/data/fundamentals.py                 财务指标（M1.3）
backend/data/qfii_holdings.py                QFII 前十大流通股东（M1.3）
backend/data/point_in_time.py                PIT as_of 拦截层（M3.3）
backend/analysis/factors.py                  技术因子计算
backend/analysis/qlib_engine.py              Qlib 量化引擎
backend/analysis/technical.py                技术信号生成
backend/analysis/sentiment.py                LLM 新闻情感分析
backend/analysis/timing/{rsrs,diffusion,regime}.py  regime 过滤层（M1.1）
backend/decision/aggregator.py               多信号聚合 → 最终建议
backend/decision/harness.py                  决策 run/evidence/research state/复盘归因
backend/decision/decision_memory.py          历史决策记忆 + 反思上下文注入
backend/decision/memory_layered.py           FinMem 风格分层记忆（M4 前置）
backend/decision/signal_policy.py            信号语言统一（M1.7）
backend/memory/                              ai_memory + audit_log_fts 记忆接口
backend/notification/bark.py                 Bark iOS 推送
backend/api/routes.py                        REST API 路由（含 M3.4 health/kill-switch）
backend/api/schemas.py                       Pydantic response schemas
backend/main.py                              FastAPI 应用入口
backend/scheduler.py                         定时任务（盘前/盘中/盘后/周训练 + M3.4 guard）
backend/agents/long_term/                    长期分析师团（M1.3）
backend/agents/pipeline.py                   多 Agent 决策流水线（M4 编排器，含 Director hook）
backend/agents/risk_manager.py               风险经理（M4.0 前置）
backend/agents/researcher.py                 看多/看空辩论（M4.1 三轮 + 降级）
backend/agents/director.py                   Research Director（M4.2 评估+议题）
backend/agents/portfolio_manager.py          Portfolio Manager（M4.3 组合层）
backend/backtest/compare_paths.py            M4.6 双路径并排回测
backend/backtest/                            严肃回测与实验脚本
backend/backtest/statistics/                 DSR / PBO / IC 显著性（M3.1）
backend/backtest/walk_forward.py             walk-forward harness（M3.2）
backend/portfolio/combo_weights.py           组合候选权重分配
backend/portfolio/single_position.py         单信号仓位映射
backend/portfolio/trailing_stop.py           Trailing stop 持仓追踪（M1.7）
backend/ops/kill_switch.py                   Kill switch（M3.4）
frontend/src/pages/                          页面组件
frontend/src/components/SignalEvalCard.jsx   信号复盘卡片（M1.8）
frontend/src/components/EvidenceCard.jsx     决策证据链 + research state（M6.1）
```
