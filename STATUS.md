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
| M4 | 多 Agent 决策深化 | 🟡 部分（长期团 + risk_manager 已上线） |
| M5 | 自动化执行 | 🔲 后置 |
| M6 | 持续迭代与扩展 | 🔲 持续 |
| M7 | 工程化与开源就绪 | 🔲 进行中（A ✅ B1 B2 ✅ C ✅ / B3 B4 进行中） |

---

## 信号权重（Decision Layer）

| Profile | quant | technical | sentiment | entry_threshold | 触发条件 |
|---|---|---|---|---|---|
| `test1_legacy_qlib` | 0.45 | 0.40 | 0.15 | 20 | 测试 1 期间 2026-05-13 ~ 05-20 |
| `new_framework` | 0.0 | 0.6 | 0.4 | 25 | 测试 2 起 / 生产默认 |

综合评分范围：-100（规避）→ +100（可小仓试错）

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
| 周日 11:00 | 长期团 | 长期分析师团 label 生成 |

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

- `PYTHONPATH=. pytest -q` → **103 passed**（2026-05-16 复验）
- `python3 -m compileall backend tests` → 通过
- `cd frontend && npm run build` → 通过（47 modules，347 KB / gzip 111 KB）

---

## 环境准备

```bash
cp .env.example .env                   # 填入 ANTHROPIC_API_KEY（必填）和 BARK_KEY（可选）
pip install -r backend/requirements.txt
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
PYTHONPATH=. python3 -m backend.backtest.walk_forward --start 2024-01-01 --end 2026-05-15
curl http://localhost:8000/api/system/health
curl -X POST http://localhost:8000/api/system/kill-switch/reset
curl http://localhost:8000/api/signals/eval/600519?days=60
```
