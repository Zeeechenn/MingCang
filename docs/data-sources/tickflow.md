# TickFlow 手册

> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

素材来源：`docs/evidence/data_source_audit_digest.md`；原始长审计已外部归档。

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

**历史日期不等于历史可见版本**：`adjust=forward_additive` 的当前返回可能随后续公司行动
重新复权。截断到旧交易日只能限制行日期，不能证明当时可见价格；没有当时快照、复权因子
版本和公司行动时点时，只能作调整价格代理诊断，不能宣称 PIT 干净或无前视风险。

2026-09-16 只读核验：同一公开标的 601318、同一 20 个交易日，新浪 volume 与 TickFlow
volume 的比值约为 100（99.999921–100.000093）。现有适配器原样保留 volume，尚未统一
股/手单位。该比值是实测的来源差异，不是完整单位合同；维护或使用量能成交上限前必须
核实单位，不能静默在生产乘 100。官方接口页列出了 volume，但本次核验未取得明确单位说明。
参考：[TickFlow K 线接口](https://docs.tickflow.org/zh-hans/api-reference/k线数据/查询-k线数据)。

### 2026-09-17 固定窗口候选与量纲对照

26 只授权查询中 21 只获得覆盖完整既有日期、截止 09-16 且 OHLCV 合法的候选；4 只 TLS
失败、1 只收到 `10/min` 限频。调整尚未请求标的的间隔后继续，所有已失败标的不重试。
21 只共同日期上的 TickFlow volume / Tushare daily vol 比值为 0.999946–1.000047，
与 Tushare 官方标注的“手”数值接近一致；此为跨源观察，不替代 TickFlow 的正式单位合同，
也不改变前述新浪比值结论。未在生产自动乘 100，未启用量能成交认证。

同批临时库演练中 20 只触发既有漂移判据并重写，1 只保持原样；备份恢复一致。候选生成与
恢复成功不放行生产维护或收益结论，4. 节的当前复权/历史可见性限制继续适用。

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
   静默吞掉返回 `None`，与 TickFlow 是否启用、是否有数据完全无关（本手册已保留
   必要证据链，归档来源见 `docs/evidence/data_source_audit_digest.md`）。修复 `FLOW_MISSING`
   要去修 `m52_flow_floor`/`news_fusion.py`，跟本文件无关。
2. **只有日K，没有分钟线/盘口/资金流/新闻/公告**——`external_sources.py` 里登记的其余 5 项
   `high_value_datasets` 是理论候选，不是已验证/已实现能力，若要真的用需要先补代码+走 P1 体检。
3. **priority 数字越小越优先**，改 `.env` 里 `TICKFLOW_ENABLED`/`TICKFLOW_API_KEY` 会直接影响
   CN 日线取数的默认来源，改动前确认这一点，避免误以为改的是"某个可选备源"。
