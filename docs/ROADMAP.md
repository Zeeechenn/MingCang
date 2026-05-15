# StockSage — 路线图（进行中与待做）

> 已完成里程碑详情见 `CHANGELOG.md`。此文件只追踪 M2 及以后的未完成任务。

---

## M2 纸上交易验证 ⏳（旧 Phase 6.5 + 执行计划 D + 测试1/测试2）

详细规则与持仓见 `PAPER_TRADING.md` 索引及 `paper_trading/` 拆分文件。

### M2.1 测试 1（用户主导，2026-05-13 ~ 05-20）
宽撒网验证系统完整性。

### M2.2 测试 2（Claude 主导，2026-05-21 ~ 06-03）
精选 7 股，阈值 25，10 个交易日。

### M2.3 测试1 收盘后汇总（2026-05-20）
- [ ] 汇总持仓 / 信号准确率 / 与系统建议的对照

### M2.4 测试2 启动 checklist（2026-05-21）
- [ ] 启动当日执行 checklist（详见 `paper_trading/test2.md`）

> 测试 2 收尾时（约 2026-06-03）会有真实样本可与 M1 严肃回测交叉验证。

---

## M4 多 Agent 决策深化 🟡（旧 路线图阶段 C）

**已部分完成**：
- [x] 长期分析师团（M1.3）— 4 路投票 + 一票否决
- [x] `risk_manager.py` — 风险经理对最终建议有否决权
- [x] `memory_layered.py` — FinMem 风格分层记忆

**待做**：
- [ ] fork TradingAgents-CN，做 7 角色多 Agent 决策（researcher 辩论 / trader 仓位 / portfolio manager）
- [ ] FinMem 完整替换 `decision_memory.py`
- [ ] 与 M3.2 walk-forward 配合：多 Agent 路径 vs 单 aggregate 路径并排回测

---

## M5 自动化执行 🔲（旧 路线图阶段 D，最不关键）

QMT/miniQMT 券商对接；盘中实时止损；半自动→全自动渐进。

**门槛**：M2 测试 1/2 通过 + M3.2 walk-forward 在独立 holdout 上验证通过。

---

## M6 持续迭代与扩展 🔲（旧 路线图阶段 E + Phase 7 美股）

### M6.1 自动因子挖掘 + 周复盘自动化
- RD-Agent 集成
- Tushare 财报 / 资金流接入

### M6.2 美股扩展（旧 Phase 7，已降级）
- yfinance 接入 / 美股新闻源 / 双市场调度
- 仅在主线稳定后考虑

---

## M7 工程化与开源就绪 🔲（2026-05-16 新增）

### 立即组 A ✅（2026-05-16 完成）
- [x] M7.A1 README.md
- [x] M7.A2 LICENSE（MIT）
- [x] M7.A3 pyproject.toml（ruff + mypy）
- [x] M7.A4 删除冗余代码（-5 活动文件 / -4 极薄文档 / -3 legacy 目录）

### 中期组 B（2026-05-16 进行中）
- [x] M7.B1 PROJECT.md 拆分为 PROJECT（索引）/ CHANGELOG / docs/ROADMAP / STATUS
- [x] M7.B2 `.github/workflows/test.yml` — CI 自动跑 pytest + npm build
- [x] M7.B3 补 docstring 到 70%+（完成 99%，290/291，2026-05-16）
- [x] M7.B4 补 return type 注解到 90%+（完成 91%，267/291，2026-05-16）

### 长期组 C（2026-05-16 完成）
- [x] M7.C1 `.pre-commit-config.yaml`（ruff + pre-commit-hooks）
- [x] M7.C2 `Dockerfile` + `docker-compose.yml`（backend + frontend + nginx + sqlite volume）
- [x] M7.C3 `frontend/README.md`
- [x] M7.C4 `CONTRIBUTING.md`（代码规范 / 测试 / 核心约束 / PR 流程）
- [x] M7.C5 CHANGELOG.md 按 Keep a Changelog 规范（与 B1 同步完成）

---

## 历史决策点（不再阻塞）

**Qlib 命运决策**（M1.1）：IC=0.0228，分层非单调 → Qlib 权重归零（详见 CHANGELOG.md M1.1）

**跨市场信号（已移除）**：美股 ETF（COPX/GLD/UUP 等）作为领先指标，全板块回测无显著收益改善，已移除。
