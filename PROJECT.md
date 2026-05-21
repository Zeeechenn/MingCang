# StockSage — Project Index

StockSage is a personal A-share research and decision-support application. This
file is a compact public index for the repository; operational details live in
the linked documents.

---

## 项目定位

个人 A 股辅助决策工具。默认生产路径融合技术因子和 LLM 新闻情感，输出可审计的研究建议，用户自行最终决策。

**核心约束**：止盈止损由 ATR 公式计算，LLM 不做价格预测，不做自动交易。

---

## 快速导航

| 文件 | 内容 |
|------|------|
| [STATUS.md](STATUS.md) | 当前公开快照（默认权重 / 调度 / 验证 / 启动命令） |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑详情（M0 / M1 / M3 / M7 / M8） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中与待做（M2 / M4 / M5 / M6 / M8） |
| [README.md](README.md) | 项目门面（Quick Start / 架构图） |
| [AGENTS.md](AGENTS.md) | Agent 使用说明占位，后续补充 |

---

## Agent-Ready Boundary

StockSage can be used as regular software and as an agent-ready codebase. Public
agent instructions belong in `AGENTS.md`; private local notes, generated reports,
runtime databases and personal trading records stay outside Git tracking.

---

## 里程碑总览

| 里程碑 | 名称 | 状态 |
|---|---|---|
| **M0** | 系统骨架 | ✅ 完成 |
| **M1** | 严肃化与质量门槛 | ✅ 完成 |
| **M2** | 纸上交易验证 | ⏳ 进行中 |
| **M3** | 可信度审计层（DSR/PBO/WF/PIT/KillSwitch） | ✅ 完成 |
| **M4** | 多 Agent 决策深化 | 🟡 大部分（M4.1/4.2/4.3/4.6 已落地，M4.4/4.5 暂缓） |
| **M5** | 自动化执行 | 🔲 后置 |
| **M6** | 持续迭代与扩展 | ✅ M6.1 / M6.3 当前范围完成，持续迭代 |
| **M7** | 工程化与开源就绪 | ✅ 完成 |
| **M8** | 深度研究与来源审计层 | ✅ 完成（新闻审计 + 手动专题研究 + 研究记忆） |
| **M9** | 记忆系统接入与治理 | ✅ 大部分完成（M9.0–M9.4 + 横向备份/反偏差） |
| **M10** | 运行可靠性与产品化优化 | ✅ M10.0-M10.4 完成 |

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
backend/api/routes/                          REST API 路由（含 health / kill-switch）
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
