# StockSage

个人 A 股辅助决策工具——量化信号 + LLM 情感分析 + 多 Agent 风控，输出建设性择股建议，用户自行最终决策。

![Tests](https://img.shields.io/badge/tests-99%20passed-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

---

## Quick Start

```bash
# 1. 克隆 & 安装依赖
git clone <repo-url> && cd stock-sage
pip install -r backend/requirements.txt

# 2. 配置环境变量
cp .env.example .env          # 填入 ANTHROPIC_API_KEY（必填）和 BARK_KEY（可选）

# 3. 初始化数据库
python3 backend/data/database.py

# 4. 启动后端
PYTHONPATH=. uvicorn backend.main:app --reload

# 5. 启动前端（新终端）
cd frontend && npm install && npm run dev
```

浏览器访问 http://localhost:5173 打开看板。

---

## 项目状态

| 里程碑 | 名称 | 状态 |
|---|---|---|
| M0 | 系统骨架 | ✅ 完成 |
| M1 | 严肃化与质量门槛 | ✅ 完成（Sharpe 1.36 / 回撤 8.6% / 盈亏比 2.78） |
| M2 | 纸上交易验证 | ⏳ 进行中 |
| M3 | 可信度审计层（DSR/PBO/WF/PIT/KillSwitch） | ✅ 完成 |
| M4 | 多 Agent 决策深化 | 🟡 部分（长期团 + risk_manager 已上线） |
| M5 | 自动化执行 | 🔲 后置 |
| M6 | 持续迭代与扩展 | 🔲 持续 |
| M7 | 工程化与开源就绪 | 🔲 进行中 |

详细进度见 [PROJECT.md](PROJECT.md)。

---

## 系统架构

```
Data Layer:   AkShare（A股行情 + 个股新闻 + 指数）→ SQLite
              ↓
Analysis:     技术指标（ATR/RSI/MA/RSRS）
              + LLM 情感（Claude Haiku，新闻摘要→评分）
              + Qlib 量化（LightGBM，权重已归零等待 M3.2 复验）
              ↓
Decision:     多 Agent 流水线（长期分析师团 + 研究员 + 风险经理）
              → 三路信号融合（技术 60% + 情感 40%）
              → ATR 止盈止损 + 综合建议
              ↓
Notify:       Bark iOS 推送（买入信号 + 14:30 止损预警）
Dashboard:    FastAPI + React + TradingView Charts
```

### 数据流

AkShare/补充新闻源写入 SQLite，盘后任务读取价格、新闻、长期标签，生成技术、情感和量化输入。

### 决策流

`backend/decision/aggregator.py` 为聚合入口，默认多 Agent 路径依次经过分析师团（`backend/agents/long_term/`）、研究员、交易员、风险经理（`backend/agents/pipeline.py`）。

### 记忆系统

| 层 | 位置 | 内容 |
|---|---|---|
| 项目事实源 | `PROJECT.md` / `stock-sage.db` / `config.py` | 每次决策的基础事实 |
| AI Memory | `ai_memory` 表 / `backend/memory/ai_memory.py` | 可主动召回的长期规则、持仓、风险、偏好 |
| Audit Log | `audit_log_fts` / `backend/memory/audit_log.py` | SQLite FTS5 可检索审计事件 |
| Remember Decision | `backend/memory/should_remember.py` | 轻量启发式判断是否值得写入长期记忆 |

---

## 项目结构

```
stock-sage/
├── PROJECT.md                     进度追踪（每次工作前先读）
├── PAPER_TRADING.md               纸上交易索引
├── paper_trading/                 测试1 / 测试2 记录
├── backend/
│   ├── config.py                  配置入口（环境变量、路径、信号 profile）
│   ├── main.py                    FastAPI 应用入口
│   ├── scheduler.py               定时任务（APScheduler）
│   ├── data/                      行情 / 新闻 / 财报 / QFII 数据拉取
│   ├── analysis/                  技术因子 / Qlib / 情感 / regime 过滤
│   ├── decision/                  信号聚合 / 记忆 / 信号策略
│   ├── agents/                    长期分析师团 / 流水线 / 风险经理
│   ├── backtest/                  严肃回测 / walk-forward / 统计显著性
│   ├── portfolio/                 仓位计算 / trailing stop
│   ├── memory/                    ai_memory / audit_log 接口
│   ├── ops/                       kill switch（M3.4）
│   ├── notification/              Bark iOS 推送
│   └── api/                       REST API 路由 + schemas
├── frontend/
│   └── src/
│       ├── pages/                 Watchlist / StockDetail / SignalHistory
│       └── components/            Chart / SignalBadge / SignalEvalCard
└── tests/                         pytest 测试套件（99 passed）
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + Uvicorn |
| 前端 | React 18 + Vite + TailwindCSS + TradingView Lightweight Charts |
| 量化 | Microsoft Qlib + LightGBM |
| 数据 | AkShare（A股全覆盖） |
| LLM | Anthropic SDK — Claude Haiku（情感）/ Sonnet（仲裁） |
| DB | SQLite + SQLAlchemy |
| 调度 | APScheduler（集成进 FastAPI lifespan） |
| 推送 | Bark（iOS） |

---

## 核心约束

- **止盈止损由 ATR 公式计算，LLM 不做价格预测，不做自动交易。**
- `止损价 = 收盘价 - ATR(14) × 2.0`
- `止盈价 = 收盘价 + (收盘价 - 止损价) × 2.0`（1:2 风险收益比）

---

## 调度时间表

| 时间 | 任务 |
|------|------|
| 08:30 工作日 | 盘前同步（行情 + 新闻 + 指数） |
| 14:30 工作日 | 止损预警 Bark 推送 |
| 16:00 工作日 | 盘后信号聚合 + Bark 推送 |
| 周六 09:00 | LightGBM 模型重训 |
| 周日 11:00 | 长期分析师团 label 生成 |

> 所有任务运行在 FastAPI 进程内（APScheduler），服务不运行则任务不触发。
