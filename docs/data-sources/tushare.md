# Tushare 手册

> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

素材来源：`docs/dev/DATA_AUDIT_EXTERNAL.md` §3。本手册只做重排，权限实测数据不重复验证
（token 权限短期内不会变化，重跑意义低）。

## 1. 一句话定位

Tushare **基本放弃**。当前 `.env` 里的 token 是低积分/免费档，六类基准（新闻/盘口/公告/F10/财务/
研报）+ 资金流 + 龙虎榜**全部无权限**，只有行情四件套（日线/复权因子/每日指标/股票列表）可用。
明仓对它的定位：**仅作 CN 日线的第 5 优先级 fallback 备源**，不作任何六类数据的信号来源，也不建议
花钱升级付费档（M61 §10 已明确拒绝）。

## 2. 权限实测表（本地 token 一手结果，来自审计原文）

```
[OK]   daily            rows=21  （日线行情）
[OK]   adj_factor       rows=21  （复权因子）
[OK]   daily_basic      rows=1   （每日行情指标，PE/PB/换手率等）
[OK]   stock_basic      rows=5534（股票基础列表）

[FAIL] fina_indicator   无接口访问权限
[FAIL] moneyflow        无接口访问权限
[FAIL] anns_d           无接口访问权限
[FAIL] top_list         无接口访问权限
[FAIL] report_rc        无接口访问权限
[FAIL] forecast         无接口访问权限
[FAIL] express          无接口访问权限
[FAIL] news             无接口访问权限（此前已知，复测一致）
```

失败提示统一为："抱歉，您没有接口(xxx)访问权限，权限的具体详情访问：
https://tushare.pro/document/1?doc_id=108。"——即积分/套餐门槛，不是代码或参数问题。

| 分类 | 接口 | 状态 | 说明 |
|---|---|---|---|
| 行情 | `daily` | OK | 日线行情，明仓在用 |
| 行情 | `adj_factor` | OK | 复权因子，配合 `daily` 做前复权重算 |
| 行情 | `daily_basic` | OK | PE/PB/换手率等每日指标 |
| 基础 | `stock_basic` | OK | 股票基础列表 |
| 财务 | `fina_indicator` | FAIL | 财务指标，无权限 |
| 资金流 | `moneyflow` | FAIL | 无权限 |
| 公告 | `anns_d` | FAIL | 无权限 |
| 龙虎榜 | `top_list` | FAIL | 无权限 |
| 研报 | `report_rc` | FAIL | 无权限 |
| 财务 | `forecast` | FAIL | 业绩预告，无权限 |
| 财务 | `express` | FAIL | 业绩快报，无权限 |
| 新闻 | `news` | FAIL | 无权限（历史已知） |

**官方接口目录**（Tavily extract 拿到分类导航，未逐页展开权限细节）：沪深基础数据（股票列表/
上市公司信息/交易日历/沪深股通成份股/曾用名/IPO新股）、行情（日线/分钟/Tick/大单成交/复权因子/
停复牌/每日指标）、财务（三大报表/业绩预告/业绩快报/分红送股/财务指标/审计意见/主营构成）；
研报 `report_rc`、公告 `anns`/`anns_d`、龙虎榜 `top_list`/`top_inst`、资金流 `moneyflow*`、新闻
`news` 属于细分页面，本次未逐页展开，以上方接口级实测为准。

## 3. 能力目录（仅列明仓可用的 4 个行情接口）

| 接口 | 入参(含日期参数) | 返回字段 | 限制 |
|---|---|---|---|
| `pro.daily(ts_code, start_date, end_date)` | `ts_code`(必填,`600519.SH`格式)，`start_date`/`end_date`(可选,`yyyyMMdd`) | 未复权日线OHLCV+成交量额+涨跌幅 | 免费档可用，明仓封装于 `backend/data/market_sources.py:fetch_cn_daily_tushare`（L119） |
| `pro.adj_factor(ts_code, start_date, end_date)` | 同上 | 复权因子序列 | 配合 `daily` 做前复权，封装于 `backend/data/tushare_qfq.py` |
| `pro.daily_basic(ts_code, trade_date)` | `ts_code`，`trade_date`(可选,`yyyyMMdd`) | PE/PB/换手率/总市值/流通市值等每日指标 | 明仓未接（仅审计探针验证有权限） |
| `pro.stock_basic(exchange, list_status)` | 均可选 | 股票代码/名称/上市日期/所属行业等基础列表 | 明仓未接 |

## 4. PIT 判定

| 能力 | 判定 | 理由 |
|---|---|---|
| `daily`/`adj_factor` | **PIT干净** | 按 `start_date`/`end_date` 精确取历史日线，复权因子按日归档，无前视风险 |
| `daily_basic` | **PIT干净（未接线）** | 按 `trade_date` 归档，理论可回放，但明仓未使用 |
| `stock_basic` | **快照类** | 当前股票列表快照，历史某日的"曾用名"需专门查询字段，不适合直接当历史口径 |
| 其余(财务/资金流/公告/龙虎榜/研报/新闻) | **不适用** | 当前 token 无权限，无法验证 |

## 5. 明仓接线现状

- `backend/data/market_sources.py:fetch_cn_daily_tushare`（L119-132）：调用 `pro.daily(...)`，
  是 CN 日线 fallback 链的一环。
- `backend/data/tushare_qfq.py:fetch_tushare_qfq_daily`（L155）：`daily` + `adj_factor` 组合做
  前复权重算，`external_sources.py` 明确注释"Do not register raw pro.daily output as a
  production provider"——即裸 `daily` 不直接作生产 provider，只配合 qfq 使用。
- 优先级：`backend/data/market.py` 的 provider 注册表里，`tushare_qfq_cn` priority=50，是全表
  **最低优先级**（数字越小越先尝试；对比 `akshare_sina_cn=0`、`efinance_cn=10`、
  `eastmoney_cn=20`、`akshare_em_cn=30`），即 Tushare 是 CN 日线的**最后一道 fallback**，不是
  信号来源，不承担任何六类数据。
- `backend/data/external_sources.py`（L144-167）登记为候选源，条目里写"Quota and point
  requirements depend on the Tushare account"——即登记时已知权限受限。

## 6. 坑与注意

1. **不要假设权限会自动扩展**——免费档权限表短期内不会变，涉及财务/公告/资金流/龙虎榜/研报/
   新闻的任何"用 Tushare 做 X"想法，先查本手册 §2，大概率是 FAIL。
2. **`ts_code` 格式必须带交易所后缀**（`600519.SH`/`000001.SZ`），明仓已有 `cn_tushare_ts_code`
   辅助函数（`backend/data/market_sources.py`）做转换，不要手拼。
3. **裸 `pro.daily` 是未复权数据**，直接用会导致价格跳变，必须配合 `adj_factor` 走
   `tushare_qfq.py` 的前复权路径，不要绕过。
4. **付费升级不在 M61 计划内**（§10 明确拒绝），已有源（akshare/东财/iFinD）能覆盖免费档缺口，
   不要为了 Tushare 单独付费。
5. **`pro.daily` 的历史 rows 探针只有 21 行**（约1个月），说明这只是权限探针样本，不代表接口
   本身有条数上限——正式取数按需传 `start_date`/`end_date` 即可拿更长历史。
