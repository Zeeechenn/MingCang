# StockSage — 当前快照

> 此文件记录当前可操作状态，由 PROJECT.md 链接。历史详情见 CHANGELOG.md，未来计划见 docs/ROADMAP.md。

---

## 里程碑状态

| 里程碑 | 名称 | 状态 |
|---|---|---|
| M0 | 系统骨架 | ✅ 完成 |
| M1 | 严肃化与质量门槛 | ✅ 完成 |
| M2 | 纸上交易验证 | ⏳ 进行中 |
| M3 | 可信度审计层 | ✅ 完成 |
| M4 | 多 Agent 决策深化 | 🟡 大部分（M4.1/4.2/4.3/4.6 完成 2026-05-16；M4.4/4.5 暂缓） |
| M5 | 自动化执行 | 🔲 后置 |
| M6 | 持续迭代与扩展 | ✅ M6.1 / M6.3 当前范围完成，Qlib 暂不恢复权重 |
| M7 | 工程化与开源就绪 | ✅ 完成（A/B/C 全 + .editorconfig + Makefile + pyproject 单一真理源） |
| M8 | 深度研究与来源审计层 | ✅ 完成（轻量新闻审计 + 手动专题研究，不进入日常信号） |

---

## 信号权重（Decision Layer）

| Profile | quant | technical | sentiment | entry_threshold | 触发条件 |
|---|---|---|---|---|---|
| `test1_legacy_qlib` | 0.45 | 0.40 | 0.15 | 20 | 测试 1 期间 2026-05-13 ~ 05-20 |
| `new_framework` | 0.0 | 0.6 | 0.4 | 25 | 测试 2 起 / 生产默认 |

综合评分范围：-100（规避）→ +100（可小仓试错）

> Qlib 量化层已加入 point-in-time 基本面因子与可选 LambdaRank 训练入口。2026-05-16 工程扩容验证（70 只 / 51,439 行面板）显示 walk-forward IC=+0.0026、ICIR=+0.009、分层非单调，因此生产默认 quant 权重继续保持 0，暂不启用 Ranker。

当前数据覆盖快照：active 70 / 价格覆盖 70 / 2 年价格覆盖 69 / 财报覆盖 10 / 24h 新闻覆盖 0。覆盖报表 API：`GET /api/system/data-coverage`。

专题研究入口：`POST /api/research/deep/run` 或
`PYTHONPATH=. python3 -m backend.research.deep_research --topic "AI算力产业链" --symbols 300308,300394`。
专题研究只在明确触发时运行，不创建 `Signal`，不参与日常复盘信号。

---

## 止盈止损公式

```
止损价 = 收盘价 - ATR(14) × 2.0
止盈价 = 收盘价 + (收盘价 - 止损价) × 2.0   # 1:2 风险收益比
```

---

## 调度时间表

| 时间 | 任务 | 说明 |
|------|------|------|
| 08:30 工作日 | 盘前同步 | 行情回填 + 个股新闻 + 沪深 300 指数 |
| 14:30 工作日 | 止损预警 | 检查买入信号止损线，触及则 Bark 推送 |
| 16:00 工作日 | 盘后信号 | 三路信号聚合 → 写 Signal 表 → Bark 推送 |
| 周六 09:00 | 模型重训 | LightGBM Alpha 模型周训练 |
| 周一 09:00 / 周五 15:00 | 长期团 | 长期分析师团 label 生成；日期与时间可在配置页调整 |

> 所有任务跑在 FastAPI 进程内（APScheduler），服务不运行则任务不触发。
> M3.4 kill switch 激活时，premarket / postmarket / stoploss_check 自动跳过。

---

## M1 验收结果（10 只股 × 6 个月，含长期标签）

| 指标 | 最低标准 | 实际 |
|------|---------|------|
| Sharpe（含 0.20% 手续费 + 0.10% 滑点） | > 0.8 | **1.36** ✅ |
| 最大回撤 | < 15% | **8.60%** ✅ |
| 净盈亏比 | ≥ 1.3 | **2.78** ✅ |

---

## 测试套件

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider` → **217 passed**（2026-05-17 M8 完成后）
- `python3 -m compileall backend tests` → 通过
- `cd frontend && npm run build` → 通过（M6.3 后 52 modules，约 427 KB / gzip 134 KB）

### M6.3 当前前端/API 快照（2026-05-19）

- 首页：真实持仓情况、大盘情况、股票名称优先的活动流水。
- 复盘中心：每日复盘 / 长期复盘 ensure、历史记录、示例历史补足、Markdown 完整报告详情展开。
- 持仓设置：股票联想、持仓汇总、平仓记录、永久删除已平仓记录。
- AI 对话：左侧会话窗口、新建/二次确认归档、窗口内记忆隔离、通用助手 / 长期研究团队模式。
- 配置页：综合分权重、仓位上限、数据补充参数、复盘触发日期与时间可运行时调整。
- 后端新增表：`positions`、`review_runs`、`pending_ai_actions`、`chat_sessions`、`chat_messages`。
- 验证：`pytest tests/test_frontend_expansion_api.py tests/test_memory.py` → **10 passed, 1 warning**。
- 验证：`node --test frontend/src/pages/chatArchive.test.js frontend/src/pages/reviewContent.test.js` → **4 passed**。
- 验证：`cd frontend && npm run build` → 通过（2026-05-19 复盘 Markdown / 归档确认增强后）。

---

## 环境准备

```bash
cp .env.example .env                   # 填入 ANTHROPIC_API_KEY（必填）和 BARK_KEY（可选）
pip install ".[dev]"                   # pyproject 单一真理源，含 dev 工具链
python3 backend/data/database.py       # 初始化 DB
cd frontend && npm install
```

### 启动

```bash
PYTHONPATH=. uvicorn backend.main:app --reload   # 后端（根目录执行）
cd frontend && npm run dev                        # 前端（另开终端）
```

### 常用命令

```bash
PYTHONPATH=. python3 -m backend.analysis.qlib_engine --train
PYTHONPATH=. python3 -m backend.analysis.qlib_engine --train --ranker
PYTHONPATH=. python3 -m backend.backtest.walk_forward --start 2024-01-01 --end 2026-05-15
curl http://localhost:8000/api/system/health
curl -X POST http://localhost:8000/api/system/kill-switch/reset
curl http://localhost:8000/api/signals/eval/600519?days=60
```
