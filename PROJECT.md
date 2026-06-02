# StockSage — Project Index

StockSage is a personal A-share research and decision-support application. This
file is a compact public index for the repository; operational details live in
the linked documents.

---

## 项目定位

个人 A 股辅助决策工具。默认生产路径融合技术因子和 LLM 新闻情感，输出可审计的研究建议，用户自行最终决策。

**核心约束**：止盈止损由 ATR 公式计算；默认用 ATR 2.5 移动止损保护浮盈，固定止盈作提醒/分批参考；LLM 不做价格预测，不做自动交易。

---

## 快速导航

| 文件 | 内容 |
|------|------|
| [STATUS.md](STATUS.md) | 当前公开快照（默认权重 / 调度 / 验证 / 启动命令） |
| [CHANGELOG.md](CHANGELOG.md) | 已完成里程碑详情（M0–M28，按时间倒序） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中与待做（当前重点 M29，后置 M24.3 / M25.5 等） |
| [README.md](README.md) | 项目门面（Quick Start / 架构图） |
| [AGENTS.md](AGENTS.md) | Codex / Claude Code / MCP 本地 agent 使用说明 |

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
| **M2** | 本地验证材料 | 🏠 本地维护，不进入 GitHub |
| **M3** | 可信度审计层（DSR/PBO/WF/PIT/KillSwitch） | ✅ 完成 |
| **M4** | 多 Agent 决策深化 | 🟡 大部分（M4.1/4.2/4.3/4.6 已落地，M4.4/4.5 暂缓） |
| **M5** | 自动化执行 | 🔲 后置 |
| **M6** | 持续迭代与扩展 | ✅ M6.1 / M6.3 当前范围完成，持续迭代 |
| **M7** | 工程化与开源就绪 | ✅ 完成 |
| **M8** | 深度研究与来源审计层 | ✅ 完成（新闻审计 + 手动专题研究 + 研究记忆） |
| **M9** | 记忆系统接入与治理 | ✅ 大部分完成（M9.0–M9.4 + 横向备份/反偏差） |
| **M10** | 运行可靠性与产品化优化 | ✅ M10.0-M10.4 完成 |
| **M11** | Agent-Ready 本地/远程双模式接口 | ✅ 初版完成（AGENTS/CLAUDE 契约 + 本地 MCP 只读上下文工具） |
| **M12** | 外部数据源扩展治理 | ⏳ 剩余项观察中 |
| **M13** | pi Shell + Agent Kernel | ✅ 完成 |
| **M14** | 股票长期记忆与跨入口召回 | ✅ 完成 |
| **M15** | 记忆系统与影子副驾驶修复 | ✅ 完成 |
| **M16** | 全项目分层评审 | ✅ 完成 |
| **M17-M21** | 决策链 / 回测 / 数据 / 量化 / 基础设施评审修复 | ✅ 完成 |
| **M22** | 持仓完整性与状态隔离 | ✅ 完成 |
| **M23** | 信号证据链、回测口径与运行硬化 | ✅ 完成 |
| **M24** | 长期标签隔离与约束观察 | ✅ M24.0-M24.2 完成；M24.3 观察中 |
| **M25** | 综合改进路线图 | ✅ M25.0-M25.4 主体完成；M25.5/M25.6 后置 |
| **M26** | 量化层重估 | ✅ M26.0-M26.2 完成；M26.3 暂停 |
| **M27** | Alpha 根治工程 | ✅ 证据闭环完成但未晋升；生产 quant 继续关闭 |
| **M28** | 调研模块整合与实时搜索接入 | ✅ 完成（deep_research / copilot / debate 信息流打通） |
| **M29** | Alpha Reset / Forward Evidence Engine | ⏳ 当前重点：readiness guard + M29.5 residual attribution，等待完整 fresh forward 覆盖 |
| **M31** | 工程化与产品化借鉴（StockInsight 对标） | 🧰 P2/P3：三级缓存+延迟基准 / 有序容灾链 / 交易节奏命令 / 一键多端报告 |
| **M32** | Forward 预测层 / 复盘→假设桥 | 🧭 设计立场已定（拒绝价格预测+Strong Buy；做可证伪赛道论点），启动待复盘数据变厚 |

---

## 关键文件索引

```
backend/config.py                            配置入口（环境变量、路径、调度时间、Bark、双 profile）
backend/data/database.py                     数据库模型 + 轻量幂等迁移
backend/data/market.py                       行情数据拉取（TickFlow 可选优先，免费源 fallback，Tushare qfq 可选后置）
backend/data/providers.py                    行情 Provider registry + fallback
backend/data/universe.py                     股票池候选 / 去重 / 市值流动性过滤 / 批量回填
backend/data/qlib_data.py                    Qlib 特征构建（技术 + PIT 基本面 + price provenance）
backend/data/quality.py                      数据覆盖报表 + provider 可靠性摘要（M6.1）
backend/data/market_features.py              市值/股本/资金流 PIT 特征 join（M6.1）
backend/data/external_sources.py             外部数据源候选目录 + 显式可达性探针（默认不进生产信号）
backend/data/ifind_mcp.py                    同花顺 iFinD MCP observe-only 客户端 + Markdown/JSON 解析
backend/data/tushare_qfq.py                  Tushare daily + adj_factor 前复权 OHLCV fallback（默认关闭）
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
backend/agent/                               Codex / Claude Code 本地 agent 上下文与 MCP 工具桥
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
backend/tools/m29_evidence_ledger.py         M29.1 只读 alpha evidence ledger 聚合器
backend/tools/m29_hypothesis_registry.py     M29.2 新 alpha 假设预注册清单
backend/tools/m29_shadow_validation.py       M29.2/M29.3 只读预注册 shadow validation 包装器
backend/tools/m29_provenance_audit.py        M29.3 只读 price/artifact provenance audit
backend/tools/m29_forward_readiness.py       M29.3 只读 forward shadow readiness guard
backend/tools/m29_price_coverage_refresh.py  M29.3 close-confirmed price/provenance refresh（默认 dry-run，--execute 写 prices）
backend/portfolio/combo_weights.py           组合候选权重分配
backend/portfolio/single_position.py         单信号仓位映射
backend/portfolio/trailing_stop.py           Trailing stop 持仓追踪（M1.7）
backend/ops/kill_switch.py                   Kill switch（M3.4）
frontend/src/pages/                          页面组件
frontend/src/components/SignalEvalCard.jsx   信号复盘卡片（M1.8）
frontend/src/components/EvidenceCard.jsx     决策证据链 + research state（M6.1）
```
