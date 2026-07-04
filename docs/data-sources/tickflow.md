# TickFlow 手册

> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

素材来源：`docs/dev/DATA_AUDIT_EXTERNAL.md` §4。

## 1. 一句话定位

**名字带 "flow"，但与资金流完全无关**——TickFlow 只是一个日K线行情源，目前是明仓 CN 日线
provider 链里的**最高优先级**（当前 `.env` 状态下最先被尝试）。历史上 M54 大面积出现的
`FLOW_MISSING` 告警与 TickFlow **零关系**，纯粹是英文命名巧合造成的误判，务必不要再混淆。

## 2. 能力目录

明仓代码只实现了**一个**端点：

| 端点 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `GET /v1/klines` | `symbol`（TickFlow 格式，如 `600519.SH`）、`period`(固定`1d`)、`count`(条数)、`adjust`(固定`forward_additive`) | 日线 OHLCV | 仅日K，无分钟线/盘口/资金流/新闻/公告接口代码；`count` 上限 10000（客户端强制 `min(days, 10000)`） |

代码位置：`backend/data/tickflow.py`：
- `tickflow_symbol(symbol, market)`（L16）：明仓 symbol/market → TickFlow 交易所后缀格式的映射
  （CN 按代码前缀分 SH/SZ/BJ，US 加 `.US`，HK 补零加 `.HK`）。
- `fetch_tickflow_daily(symbol, market, days=365, ...)`（L66）：请求封装，鉴权走 header
  `x-api-key`（`settings.tickflow_api_key`）。
- `probe_tickflow_daily(symbol="600519", market="CN", days=30)`（L96）：只读探针，不落库。

`external_sources.py` 登记条目里 TickFlow 的 `high_value_datasets` 写了
`daily_kline/realtime_quote/minute_kline/market_depth/financial_metrics/cross_market_universes`
（即"作为产品理论上可能有这些能力"），但**明仓代码只接了 `daily_kline` 一项**，其余 5 项是登记时
的想象空间，不是已验证能力，不要照单全收。

## 3. 问法/调用模板

非自然语言接口，直接传结构化参数：

```python
from backend.data.tickflow import fetch_tickflow_daily

df = fetch_tickflow_daily("600519", "CN", days=365)
```

或只读探针（不落库、不改信号）：

```python
from backend.data.tickflow import probe_tickflow_daily

probe_tickflow_daily(symbol="600519", market="CN", days=30)
```

## 4. PIT 判定

**PIT干净**：`/v1/klines` 按交易日归档，`adjust=forward_additive` 前复权，可按历史日期回放，
无前视风险。仅日K粒度，不涉及财务/事件类前视问题。

## 5. 明仓接线现状

- `backend/data/market.py` L61：
  `register_daily_provider("tickflow_cn", {"CN"}, fetch_cn_daily_tickflow, priority=-10, cooldown_seconds=30)`，
  仅当 `settings.tickflow_enabled and settings.tickflow_api_key` 同时满足才注册（L60）。
- `backend/data/providers.py` L71：`_DAILY_PROVIDERS.sort(key=lambda p: p.priority)`（**升序**，
  数字越小越先尝试）。TickFlow 的 `priority=-10` 是全表最低数字，对比
  `akshare_sina_cn=0`/`efinance_cn=10`/`eastmoney_cn=20`/`akshare_em_cn=30`/
  `tushare_qfq_cn=50`——**只要开关打开，TickFlow 就是当前被最先尝试的 CN 日线 provider**（模块
  docstring 也明写"registers it as the preferred CN daily provider"）。
- **已用满**：唯一实现的端点（日K线）已经接入生产 fallback 链，没有"待接入"的剩余能力。

## 6. 坑与注意

1. **不要被名字误导去查资金流问题**——`FLOW_MISSING` 告警的真正根因是 `news_fusion.py` 里独立的
   资金流通道试图 `import backend.tools.m52_flow_floor`，该模块在仓库里**根本不存在**，异常被
   静默吞掉返回 `None`，与 TickFlow 是否启用、是否有数据完全无关（详见
   `docs/dev/DATA_AUDIT_EXTERNAL.md` §4.3 完整证据链，或 M61 计划 D1）。修复 `FLOW_MISSING`
   要去修 `m52_flow_floor`/`news_fusion.py`，跟本文件无关。
2. **只有日K，没有分钟线/盘口/资金流/新闻/公告**——`external_sources.py` 里登记的其余 5 项
   `high_value_datasets` 是理论候选，不是已验证/已实现能力，若要真的用需要先补代码+走 P1 体检。
3. **priority 数字越小越优先**，改 `.env` 里 `TICKFLOW_ENABLED`/`TICKFLOW_API_KEY` 会直接影响
   CN 日线取数的默认来源，改动前确认这一点，避免误以为改的是"某个可选备源"。
