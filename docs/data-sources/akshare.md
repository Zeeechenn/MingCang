> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

# akshare 使用手册

## ① 一句话定位

akshare（本地已装 1.18.60，`pip show akshare` 免 key）是一个爬 东财/新浪/腾讯/巨潮 公开页面的
免费 Python 库，1133 个函数覆盖行情/财务/公告/研报/资金流/龙虎榜/公司事件/新闻/F10/行业十大类，
明仓目前只用了其中 12 个（~17%），资金流/龙虎榜/研报/盘口四类候选使用数为 0——是明仓性价比最高
的"免费扩容"数据源。

本手册所有签名均为本地实测（`inspect.signature`，1.18.60），返回列名来自 2026-07-04 的 10 次
真实网络调用（预算 ≤10 次，间隔 1s，见各类"实测"标注；未实测的标 unknown）。

## ② 能力目录 + 实测结果

### 1. quotes 行情（非六类基准，但明仓核心依赖）

| 函数 | 签名 | 日期范围 | 返回字段（实测/已知） | 备注 |
|---|---|---|---|---|
| `stock_zh_a_hist` | `(symbol='000001', period='daily', start_date='19700101', end_date='20500101', adjust='', timeout=None)` | **支持**，start/end_date | 实测(000001,20240101-20240110,7行): 日期/股票代码/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率 | 明仓主日线源 |
| `stock_zh_a_hist_tx` | `(symbol='sz000001', start_date='19000101', end_date='20500101', adjust='', timeout=None)` | 支持 | 未本次实测(已用,列名类似腾讯源OHLCV) | 备用源 |
| `stock_zh_a_daily` | 新浪源 | 支持 | 未本次实测 | 备用源 |
| `stock_zh_index_daily` | `(symbol='sh000922')` | **不支持**，只有 symbol，返回全部历史 | 未本次实测 | 指数日线 |

### 2. financials 财务

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_financial_abstract` | `(symbol='600004')` | 不支持独立日期参数，一次性返回该股**全部历史季度列** | 实测(600519): 80行×104列，行=指标(归母净利润/营业总收入等)，列=报告期字符串(20260331…19981231)，宽表 | 明仓已用 `fundamentals.py:142` |
| `stock_financial_analysis_indicator` | `(symbol='600004', start_year='1900')` | 支持 start_year 起点筛选 | 未本次实测 | 明仓已用 `fundamentals.py:149`（新浪源ROE等衍生指标） |
| `stock_financial_analysis_indicator_em` | `(symbol='301389.SZ', indicator='按报告期')` | indicator 可切换 按报告期/按年度 | 未本次实测 | 东财源，明仓未用 |
| `stock_balance_sheet_by_report_em` / `stock_profit_sheet_by_report_em` / `stock_cash_flow_sheet_by_report_em` | `(symbol='SH600519')` | 按报告期返回全部历史，无独立日期参数 | 未本次实测 | 东财三大报表，明仓未用；symbol 需带 SH/SZ 前缀 |

### 3. announcements 公告

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_notice_report` | `(symbol='全部', date='20220511')` | **date 按天查询，支持历史回溯 → PIT clean** | 实测 `symbol='000001', date='20240115'` 报 **`KeyError('000001')`** — symbol 参数实际语义可能是"全部"或分类名，不接受个股代码；需换用下方 `stock_individual_notice_report` 或先 `symbol='全部'` 再自行按代码过滤 | 未接入 |
| `stock_individual_notice_report` | `(security, symbol='全部', begin_date=None, end_date=None)` | 支持 begin/end_date 范围 | 未本次实测 | 注意 `security` 是必填位置参数（个股代码），与 `stock_notice_report` 的 `symbol` 含义不同——本次实测踩坑就是把两者搞混了 |
| `stock_report_disclosure` | `(market='沪深京', period='2021年报')` | 按期次(季度)批量，非任意日期 | 未本次实测 | 明仓已用 `fundamentals.py:568`，仅"预约披露日历"非公告正文 |
| `stock_zh_a_disclosure_report_cninfo` | `(symbol='000001', market='沪深京', keyword='', category='', start_date='20230618', end_date='20231219')` | **支持** start/end_date + keyword + category | 未本次实测 | 巨潮资讯公告，功能最全但未验证稳定性 |

### 4. research_reports 研报

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_research_report_em` | `(symbol='000001')` | **不支持**，返回该股全部历史研报列表，需自行按"日期"列过滤 | 实测(000001): 225行×16列 — 序号/股票代码/股票简称/报告名称/东财评级/机构/近一月个股研报数/2026-盈利预测-收益/2026-盈利预测-市盈率/2027-.../2028-.../行业/日期/报告PDF链接。**不含正文**，仅标题+评级+盈利预测+PDF链接 | 零成本可用，owner 点名类目当前完全空白 |
| `stock_profit_forecast_em` | `(symbol='')` | 不支持独立日期，symbol='' 默认全市场 | 未本次实测 | 盈利预测（一致预期） |

### 5. fund_flow 资金流

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_individual_fund_flow` | `(stock='600094', market='sh')` | 不支持任意范围，返回近期滚动数据 | **本次实测失败**：`ProxyError` 连 `push2his.eastmoney.com` 被沙箱代理拦截，未拿到真实列名（unknown，需在无代理网络下重跑） | 审计文档称返回主力/超大单/大单/中单/小单净流入 |
| `stock_individual_fund_flow_rank` | `(indicator='5日')` | indicator 枚举 今日/3日/5日/10日 等 | 未本次实测 | 全市场排名 |
| `stock_main_fund_flow` | `(symbol='全部股票')` | 不支持 | 未本次实测 | 主力净流入排名 |
| `stock_sector_fund_flow_rank` | `(indicator='今日', sector_type='行业资金流')` | 不支持 | 未本次实测 | 板块资金流 |
| `stock_hsgt_fund_flow_summary_em` | `()` | 无参数 | 未本次实测 | 北向资金 |

### 6. lhb 龙虎榜

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_lhb_detail_em` | `(start_date='20230403', end_date='20230417')` | **支持日期范围 → PIT clean** | 实测(20240401-20240410): 469行×21列 — 序号/代码/名称/上榜日/解读/收盘价/涨跌幅/龙虎榜净买额/龙虎榜买入额/龙虎榜卖出额/龙虎榜成交额/市场总成交额/净买额占总成交比/成交额占总成交比/换手率/流通市值/上榜原因/上榜后1日/2日/5日/10日 | owner 点名类目当前完全空白，零成本起点 |
| `stock_lhb_jgmmtj_em` | `(start_date='20240417', end_date='20240430')` | 支持范围 | 未本次实测 | 机构买卖每日统计 |
| `stock_lhb_stock_statistic_em` | `(symbol='近一月')` | symbol 是周期字符串，非股票代码 | 未本次实测 | 个股上榜统计 |
| `stock_lhb_detail_daily_sina` | `(date='20240222')` | 按单日查询 | 未本次实测 | 新浪源镜像 |

### 7. corporate_events 公司事件（分红/回购/解禁/股本变动）

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_fhps_em` | `(date='20231231')` | date 为报告期(季度末)，非任意交易日 | 实测(date=20231231): 3857行×18列 — 代码/名称/送转股份-送转总比例/送转比例/转股比例/现金分红-现金分红比例/现金分红-股息率/每股收益/每股净资产/每股公积金/每股未分配利润/净利润同比增长/总股本/**预案公告日/股权登记日/除权除息日**/方案进度/最新公告日期 | 含三个真实时间戳字段，天然适合 as-of 过滤（见 PIT 节） |
| `stock_restricted_release_queue_em` | `(symbol='600000')` | 未标注 | 未本次实测 | 限售解禁批次 |
| `stock_repurchase_em` | `()` | 无参数 | 未本次实测 | 股份回购 |
| `stock_share_change_cninfo` | `(symbol='002594', start_date='20091227', end_date='20241021')` | **支持范围** | 未本次实测 | 股本变动，巨潮源 |

### 8. news 新闻

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_news_em` | `(symbol='603777')` | 不支持，固定返回近期若干条 | 实测(000001): 10行×6列 — 关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接。**新闻内容含正文全文，非空** | 明仓已用，见 §⑤ |

### 9. f10/简况

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_individual_info_em` | `(symbol='603777', timeout=None)` | 不支持，当前快照 | **本次实测失败**：`JSONDecodeError`（同一沙箱网络问题，疑非函数缺陷；生产已在用见 §⑤） | 总股本/流通股/所属行业/上市时间等 |
| `stock_zh_a_gdhs` | `(symbol='20230930')` | symbol 实为报告期字符串，非股票代码 | 未本次实测 | 股东户数 |
| `stock_profile_cninfo` | `(symbol='600030')` | 不支持 | 未本次实测 | 巨潮公司概况 |

### 10. sector 行业

| 函数 | 签名 | 日期范围 | 返回字段 | 备注 |
|---|---|---|---|---|
| `stock_board_industry_name_em` | `()` | 无参数 | **本次实测失败**：`ProxyError` 连 `17.push2.eastmoney.com` 被沙箱代理拦截（unknown，需无代理环境重跑） | 行业板块名录 |
| `stock_board_industry_cons_em` | `(symbol='小金属')` | 不支持，symbol 是行业名非代码 | 未本次实测 | 成分股 |
| `stock_board_industry_hist_em` | `(symbol='小金属', start_date='20211201', end_date='20220401', period='日k', adjust='')` | **支持范围** | 未本次实测 | 行业指数历史行情 |

## ③ 调用示例

```python
import akshare as ak

# quotes：个股日线，支持日期范围
df = ak.stock_zh_a_hist(symbol="000001", period="daily",
                         start_date="20240101", end_date="20240110", adjust="")

# announcements：巨潮公告，按日期范围+关键词过滤（个股公告用 stock_individual_notice_report）
df = ak.stock_individual_notice_report(security="000001",
                                        begin_date="20240101", end_date="20240301")

# research_reports：个股研报列表（无日期参数，自行按"日期"列筛 <= as_of）
df = ak.stock_research_report_em(symbol="000001")
df = df[df["日期"] <= "2026-06-30"]

# fund_flow：个股资金流（真实环境下可用，本次沙箱代理拦截）
df = ak.stock_individual_fund_flow(stock="000001", market="sz")

# lhb：龙虎榜详情，日期范围查询
df = ak.stock_lhb_detail_em(start_date="20240401", end_date="20240410")

# corporate_events：分红送股，date 是报告期；PIT 过滤要用"预案公告日"而非 date 本身
df = ak.stock_fhps_em(date="20231231")
df = df[df["预案公告日"] <= "2024-01-31"]
```

## ④ PIT 判定

| 类目 | 判定 | 理由 |
|---|---|---|
| quotes | clean | start_date/end_date 范围查询，历史 OHLCV 一经收盘即固定 |
| financials | risky | 无日期范围参数，一次拉全部历史；且财报存在事后更正(restatement)，"最新一次抓取"可能已覆盖了当时的原始披露值 |
| announcements | clean（`stock_notice_report`/`disclosure_report_cninfo`）| date/date-range 回溯查询天然带 as-of 语义；但 `stock_notice_report` 个股筛选行为需先修复实测中发现的 symbol 语义问题 |
| research_reports | risky | 无日期参数，只能整表按"日期"列自行过滤 `<= as_of`；东财页面若对历史研报做过增删/评级回改，会有偷看未来的风险，未验证是否发生 |
| fund_flow | unknown | 本次网络失败未验证返回结构；且资金流类接口通常是"近N日"滚动窗口，是否支持真实历史回溯未知 |
| lhb | clean | start_date/end_date 范围查询，龙虎榜是交易所公开发布后不会变更的历史记录 |
| corporate_events | clean-ish | `stock_fhps_em` 含"预案公告日/股权登记日/除权除息日"三个真实时间戳，PIT 过滤须用这些字段而非查询用的 `date`（date 是报告期，可能早于预案公告日） |
| news | risky | 无历史存档接口，只能拿到"抓取时刻"的近期快照，无法可靠复现某个历史 as_of 时点当时的新闻全貌 |
| f10 | risky | 是当前快照（总股本/行业归属等），历史变更不可追溯 |
| sector | unknown | 本次网络失败未验证；行业分类规则可能随时间调整，历史归属是否可追溯未知 |

## ⑤ 明仓接线现状（file:line）

已接入的 12 个函数：

| 函数 | 文件:行 |
|---|---|
| `ak.stock_zh_a_hist` | `backend/data/market_sources.py:82` |
| `ak.stock_zh_a_daily` | `backend/data/market_sources.py:96` |
| `ak.stock_zh_a_hist_tx` | `backend/data/market_sources.py:109`；另在 `backend/tools/m26_expand_universe.py:118` |
| `ak.stock_zh_index_daily` | `backend/data/market_sources.py:211` |
| `ak.stock_info_a_code_name` | `backend/tools/m26_expand_universe.py:92`；`backend/api/routes/stocks.py:34` |
| `ak.index_stock_cons` | `backend/tools/m26_expand_universe.py:81` |
| `ak.index_stock_cons_csindex` | `backend/data/universe.py:65` |
| `ak.stock_individual_info_em` | `backend/data/fundamentals.py:118`（签名摘要在 `fundamentals.py:13`） |
| `ak.stock_financial_abstract` | `backend/data/fundamentals.py:142`（摘要 `fundamentals.py:14`） |
| `ak.stock_financial_analysis_indicator` | `backend/data/fundamentals.py:149`（摘要 `fundamentals.py:15`） |
| `ak.stock_gdfx_free_top_10_em` | `backend/data/qfii_holdings.py:106`（模块说明 `qfii_holdings.py:4`） |
| `ak.stock_news_em` | `backend/data/news.py:188`（fallback path，一级路径是东财直连见 `eastmoney.md`） |
| `ak.stock_report_disclosure` | `backend/data/fundamentals.py:568`（说明 `fundamentals.py:16,525,546`）；能力清单登记见 `backend/data/market_capabilities.py:205` |

**未接入但已在 §② 列出的高价值候选**：`stock_notice_report`（公告全文）、`stock_research_report_em`（研报）、
`stock_individual_fund_flow`/`_rank`（资金流）、`stock_lhb_detail_em`（龙虎榜）——四类候选使用数均为 0。

## ⑥ 坑与注意

- **本次沙箱网络会拦截部分 eastmoney 主机**：`push2his.eastmoney.com`（资金流）、`17.push2.eastmoney.com`
  （行业板块）实测均报 `ProxyError`，而 `search-api-web.eastmoney.com`（新闻）、`datacenter-web.eastmoney.com`
  （研报/龙虎榜/分红）能正常访问——同是东财域名，不同子域名代理策略不同，接入新函数前建议先在目标运行环境
  （而非受限沙箱）单独探针一次。
- `stock_individual_info_em` 本次实测报 `JSONDecodeError`（不是 ProxyError），但生产代码
  `fundamentals.py:118` 已在正常使用，说明是本次沙箱环境的偶发问题，不代表函数本身失效。
- **symbol 参数语义不统一，是最大的坑**：同样叫 `symbol`，`stock_notice_report` 期望"全部"或分类名而非个股代码
  （实测 `KeyError('000001')`）；`stock_lhb_stock_statistic_em` 的 symbol 是"近一月"这类周期字符串；
  `stock_zh_a_gdhs` 的 symbol 是报告期字符串（如 `'20230930'`）；`stock_board_industry_cons_em` 的 symbol
  是行业名（如"小金属"）而非股票代码。接入前必须先用 `inspect.signature` 查默认值猜测参数真实含义，不能假设
  "看到 symbol 就传股票代码"。
- akshare 官方文档存在幻觉风险：`docs/dev/DATA_AUDIT_EXTERNAL.md` 记录过 WebFetch 摘要生成的
  `stock_individual_research_em`/`stock_zh_a_fund_flow_sina`/`stock_zh_a_dragon_tiger_em` 经本地
  `hasattr` 验证**不存在**于 1.18.60——任何新函数名必须先本地 `hasattr(akshare, name)` 验证再使用。
- akshare 不需要 key，但限制来自各上游站点的反爬/频率策略，本手册未做压测，未知具体限流阈值。
- `stock_research_report_em`、`stock_fhps_em`、`stock_lhb_detail_em` 等函数调用时会打印 tqdm 进度条
  （`0%|...`），批量调用时注意捕获/静默这部分 stdout。
