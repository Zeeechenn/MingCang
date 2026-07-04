# 外部数据源审计（iFinD 之外）

日期：2026-07-04
范围：akshare / 东方财富(直连) / Tushare / TickFlow / a-stock-data / Anspire+Tavily
方法：只读代码 grep + 本地 python 内省 + 官方文档 WebFetch/Tavily extract + 极轻量 API 探针（无落库、无生产调用）
六类基准：新闻、盘口、公告、简况F10、财务、研报；外加资金流、龙虎榜、行业数据。

诚实声明：
- akshare 官方文档页 WebFetch 一次返回的函数名中，`stock_individual_research_em`
  `stock_zh_a_fund_flow_sina` `stock_zh_a_dragon_tiger_em` 经本地验证**不存在**于已安装的
  1.18.60 包中（`hasattr(ak, name)` 为 False），判断为小模型摘要幻觉，已剔除，不采信。
  下文 akshare 能力清单以本地 `dir(akshare)` + `inspect.signature` 内省结果为准（一手、可复核）。
- Tushare 官方文档页 WebFetch 两次报 "Socket is closed"，改用 Tavily extract 成功拿到目录页
  （只有分类导航，无逐接口权限说明），逐接口权限用本地 token 实测替代（见下）。
- 没有拿到的信息一律写"未拿到"，不编造。

---

## 1. akshare（已装 1.18.60）

### 1.1 明仓实际使用（grep 全仓一手结果）

用到的文件：`backend/data/fundamentals.py` `market_sources.py` `market_capabilities.py`
`market_utils.py` `market.py` `universe.py` `news.py` `models/market.py` `qfii_holdings.py`
`api/routes/stocks.py` `tools/m26_expand_universe.py`

实际调用的 akshare 函数（全集，12 个）：

| 函数 | 用途 | 归属六类/其他 |
|---|---|---|
| `ak.stock_zh_a_hist` | 个股历史日线 | 行情(非六类) |
| `ak.stock_zh_a_hist_tx` | 腾讯源历史日线（备用） | 行情 |
| `ak.stock_zh_a_daily` | 新浪源历史日线（备用） | 行情 |
| `ak.stock_zh_index_daily` | 指数历史日线 | 行情 |
| `ak.stock_info_a_code_name` | 全市场代码-名称表 | 行情/universe |
| `ak.index_stock_cons` / `ak.index_stock_cons_csindex` | 指数成分股 | universe |
| `ak.stock_individual_info_em` | 个股基本信息 | **F10** |
| `ak.stock_financial_abstract` | 财务关键指标摘要 | **财务** |
| `ak.stock_financial_analysis_indicator` | 财务分析指标（新浪源） | **财务** |
| `ak.stock_gdfx_free_top_10_em` | 十大流通股东 | F10（股东，QFII 持仓模块用） |
| `ak.stock_news_em` | 个股新闻（东财，正文兜底，仅作直连搜索失败后的 fallback） | **新闻** |
| `ak.stock_report_disclosure` | 巨潮资讯预约披露日历 | **公告**（仅"预约披露时间"，非公告正文） |

覆盖六类情况：新闻(有，兜底)、F10(有)、财务(有)、公告(有，弱-仅预约日历)、**研报(无)**、
**盘口(无)**。资金流/龙虎榜/行业分类：**全部未用**。

### 1.2 akshare 能力目录（本地内省，1133 个函数中按六类/资金流/龙虎榜/行业筛选）

研报：
- `stock_research_report_em(symbol)` — 东财个股研报列表（无日期范围参数，返回全部历史列表，含标题/机构/评级/PDF链接，不含正文全文）

公告：
- `stock_notice_report(symbol='全部', date='20220511')` — 东财公告大全，**date 参数按天查询**，可回溯历史某天的全市场/个股公告
- `stock_report_disclosure(market, period)` — 巨潮预约披露日历（已用）
- `stock_zh_a_disclosure_report_cninfo` / `stock_zh_a_disclosure_relation_cninfo` — 巨潮资讯公告/关联方
- `stock_individual_notice_report` — 个股公告

资金流：
- `stock_individual_fund_flow(stock, market)` — 个股资金流向（东财，主力/超大单/大单/中单/小单净流入，近期数据）
- `stock_individual_fund_flow_rank(indicator='5日')` — 全市场资金流排名
- `stock_main_fund_flow(symbol)` — 主力净流入排名
- `stock_sector_fund_flow_rank` / `stock_sector_fund_flow_hist` / `stock_sector_fund_flow_summary` — 板块资金流
- `stock_concept_fund_flow_hist` / `stock_fund_flow_concept` / `stock_fund_flow_industry` — 概念/行业资金流
- `stock_hsgt_fund_flow_summary_em` — 北向资金

龙虎榜（东财+新浪双源，共 16 个函数，最全的一类）：
- `stock_lhb_detail_em(start_date, end_date)` — **支持日期范围**，龙虎榜详情（个股+营业部）
- `stock_lhb_stock_statistic_em` / `stock_lhb_jgmmtj_em(start_date, end_date)` — 机构买卖每日统计
- `stock_lhb_jgstatistic_em` / `stock_lhb_traderstatistic_em` / `stock_lhb_yyb*_em` — 营业部/机构统计
- 新浪源镜像：`stock_lhb_detail_daily_sina` `stock_lhb_ggtj_sina` `stock_lhb_jgmx_sina` `stock_lhb_jgzz_sina` `stock_lhb_yytj_sina`

盘口：
- `stock_bid_ask_em(symbol)` — 东财实时五档报价（**仅当前快照，无历史盘口**）
- `stock_zh_a_tick_tx_js(symbol)` — 腾讯历史分笔成交（真正的历史盘口/逐笔数据源）

F10/简况：
- `stock_individual_info_em`（已用）、`stock_zh_a_gdhs`/`stock_zh_a_gdhs_detail_em`（股东户数）、
  `stock_profile_cninfo`（巨潮公司概况）、`stock_gpzy_profile_em`（股权质押）

财务：
- `stock_financial_analysis_indicator_em` / `_ths`、`stock_balance_sheet_by_report_em`、
  `stock_profit_sheet_by_report_em`、`stock_cash_flow_sheet_by_report_em`（东财三大报表，按报告期）、
  `stock_profit_forecast_em`/`_ths`（盈利预测）

行业：
- `stock_board_industry_name_em`（行业板块名录）、`stock_board_industry_cons_em`（成分股）、
  `stock_board_industry_hist_em`（行业指数历史行情）、东方财富Choice(ths)镜像同名系列

免费限制：akshare 本身不需要 key（东财/新浪/腾讯/巨潮公开页面爬取），限制主要是各上游站点的
反爬/频率限制（未做压测，仅签名内省，未逐个实测限流阈值——这点如实说明，未验证）。

### 1.3 使用率

已用 12 个 / 六类+资金流+龙虎榜+行业相关候选函数约 70+ 个（上表枚举），**粗略使用率 ~17%**，
且资金流、龙虎榜、盘口、研报四类候选池**使用数为 0**。

---

## 2. 东方财富（直连，非经 akshare）

### 2.1 明仓直连了什么

只找到**一个**直连东财接口，在 `backend/data/news.py`（约 L150-180）：

```
GET https://search-api-web.eastmoney.com/search/jsonp
```

东财 CMS 新闻搜索接口（未文档化/逆向），返回 `cmsArticleWebOld` 数组，字段映射为
标题/链接/发布时间/来源/**正文全文**。这是 `fetch_stock_news_cn` 的一级路径，失败后
retry 3 次，仍失败则 fallback 到 `ak.stock_news_em`（该函数本质也是包一层东财接口）。
`backend/data/news_adapters/eastmoney.py` 的 `EastmoneyAdapter` 直接调用这个
`fetch_stock_news_cn`，供 M54 news-adapter 层用。

其余所有 "eastmoney" 字样命中（`market_capabilities.py` `market.py` `market_sources.py`
`market_utils.py` `market_snapshots.py` `cache_policy.py` `models/market.py`）都是**经 akshare
的 `_em` 后缀函数**（行情/F10/股东），不是直连。

### 2.2 东财公开接口生态里，明仓没接的高价值口子

东财 push2/f10 系公开接口生态（业界广泛使用，非明仓已验证，基于公开知识列出，标注"未验证"）：
- `push2.eastmoney.com/api/qt/stock/fflow/kline/get` — 个股资金流历史K线（分钟/日级主力净流入曲线）——**akshare 的 `stock_individual_fund_flow` 底层大概率就是这个**，明仓完全没接
- `data.eastmoney.com/notices` 公告频道接口 — 全文公告（含 PDF 链接），明仓只接了"预约披露日历"，没接公告正文
- `data.eastmoney.com/report/` 研报频道接口 — 个股/行业研报全文摘要+评级，**明仓完全没接**（owner 点名的研报类目前是空白）
- 龙虎榜 `data.eastmoney.com/stock/lhb` 系列 — 明仓完全没接（只能经 akshare 的 `stock_lhb_*_em` 拿到，但这些也没被调用）

结论：明仓对东财的"直连"极窄（仅一个新闻搜索口子），六类中的公告全文、研报、资金流、龙虎榜
都不在直连范围内，且经 akshare 的对应函数也未被调用——这是双重空白，不是"接口不存在"。

---

## 3. Tushare（.env 已配 TUSHARE_TOKEN，token 长度 56）

### 3.1 官方接口目录（Tavily extract 拿到的目录页，只有分类导航无逐接口权限说明）

沪深股票基础数据：股票列表/上市公司信息/交易日历/沪深股通成份股/股票曾用名/IPO新股列表
行情：日线行情/分钟行情/Tick级行情/大单成交数据/复权因子/停复牌信息/每日行情指标
财务：利润表/资产负债表/现金流量表/业绩预告/业绩快报/分红送股/财务指标数据/财务审计意见/主营业务构成
（研报 `report_rc`、公告 `anns`/`anns_d`、龙虎榜 `top_list`/`top_inst`、资金流 `moneyflow*`、
新闻 `news` 未在目录首页列出，属于"左侧菜单里"的细分页面，本次未逐页展开，只做了下方的接口级实测）

### 3.2 本地 token 实测权限结果（一手，原文照抄）

```
[OK]   daily            rows=21  （日线行情）
[OK]   adj_factor       rows=21  （复权因子）
[OK]   daily_basic      rows=1   （每日行情指标，PE/PB/换手率等）
[OK]   stock_basic      rows=5534（股票基础列表）

[FAIL] fina_indicator   抱歉，您没有接口(fina_indicator)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] moneyflow        抱歉，您没有接口(moneyflow)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] anns_d           抱歉，您没有接口(anns_d)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] top_list         抱歉，您没有接口(top_list)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] report_rc        抱歉，您没有接口(report_rc)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] forecast         抱歉，您没有接口(forecast)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] express          抱歉，您没有接口(express)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。
[FAIL] news             抱歉，您没有接口(news)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。（此前已知，本次复测一致）
```

结论：当前 token 是低积分/免费档，**只有基础行情四件套（daily/adj_factor/daily_basic/
stock_basic）有权限**，财务指标、资金流、公告、龙虎榜、研报、新闻**全部无权限**，六类中
只有"财务"能通过其他渠道部分覆盖（明仓实际也没直接用 tushare 财务接口），其余五类
（新闻/盘口/公告/F10/研报）+ 资金流 + 龙虎榜在 Tushare 侧目前都是**权限阻塞**，不是代码没写。

### 3.3 明仓实际使用

仅 `backend/data/market_sources.py` 一处：`pro.daily(...)`，且 `external_sources.py` 注释明确
"Do not register raw pro.daily output as a production provider" —— 用途是配合 `adj_factor` 在
`tushare_qfq.py` 里做前复权重算，作为 CN 日线的第 5 优先级 fallback provider（见 §4 优先级表），
不是任何六类数据的信号来源。

---

## 4. TickFlow（.env `TICKFLOW_ENABLED=true`，base `https://api.tickflow.org`）

### 4.1 它提供什么

代码（`backend/data/tickflow.py`）只实现了**一个**端点：`GET /v1/klines`，入参
`symbol/period=1d/count/adjust=forward_additive`，返回 OHLCV 日线。仅此而已——没有资金流、
没有盘口、没有新闻、没有公告接口代码。`external_sources.py` 的登记条目里 TickFlow 的
`high_value_datasets` 写的是 `daily_kline / realtime_quote / minute_kline / market_depth /
financial_metrics / cross_market_universes`（即它作为一个产品**理论上**可能有这些能力），
但明仓代码只接了 daily_kline 一项。

### 4.2 明仓怎么用的（重要更正）

`backend/data/market.py` L61：`register_daily_provider("tickflow_cn", {"CN"}, ..., priority=-10, ...)`。
`providers.py` L71：`_DAILY_PROVIDERS.sort(key=lambda p: p.priority)`（**升序**，数字越小越先尝试）。
对比同表其他优先级：`akshare_sina_cn=0` `efinance_cn=10` `eastmoney_cn=20` `akshare_em_cn=30`
`tushare_qfq_cn=50`。TickFlow 的 `-10` 是全场**最低数字**，即**当前 .env 状态下它是被最先尝试
的 CN 日线 provider**（模块 docstring 也明写"registers it as the preferred CN daily provider"）。
这与最初任务描述里"盘口/资金流数据源"的猜测无关——TickFlow 只是一个（目前是优先）日线价格源。

### 4.3 M54 FLOW_MISSING 大面积出现的根因（查透，附证据）

**根因结论：TickFlow 与 FLOW_MISSING 无关，二者只是英文都含 "flow" 造成的命名巧合。**
FLOW_MISSING 的真正来源是 `backend/data/news_fusion.py` 里一个独立的"资金流通道"，与
TickFlow 完全无关联代码路径。证据链：

1. `news_fusion.py` `_default_flow_provider()`（L239-261）：
   ```python
   try:
       module = import_module("backend.tools.m52_flow_floor")
   except Exception:
       return None
   ```
   试图动态 import `backend.tools.m52_flow_floor`，任何异常（含 `ModuleNotFoundError`）被
   **静默吞掉**，直接返回 `None`。

2. 全仓 `grep -rn "m52_flow_floor"` 只有 2 处命中，都在 `news_fusion.py` 内部（一处 docstring
   引用，一处上面的 import 语句）——**`backend/tools/m52_flow_floor.py` 这个模块在仓库里根本
   不存在**（`find . -iname "*m52_flow_floor*"` 零结果）。

3. 生产/回测的真实调用路径（`backend/tools/m54_daily_accrual.py` L156、
   `backend/tools/m54_news_v2_oos.py` L789）调用 `news_v2_score_from_db(symbol, as_of,
   lookback_days, active_db, tier=tier)` 时**都没有传 `flow_value` 参数**。
   `news_layer_v2.py` 里 `score_news_v2` / `news_v2_score_from_db` 的 `flow_value` 参数
   默认值都是 `None`，全仓搜索没有任何调用方传入过非 None 的 `flow_value`。

4. 于是链路是：调用方不传 flow_value(None) → `fuse_signal` 走 `_resolve_flow_score` →
   `flow_provider` 也是 None → 落到 `_default_flow_provider` → import 不存在的模块 →
   异常被吞 → 返回 None → `fuse_signal` L99-100 `if flow_score is None: _append_flag(flags,
   FLOW_MISSING)`。**这条路径对每一次调用都成立，等于 FLOW_MISSING 会 100% 触发**，与任何
   具体股票/日期的真实资金流数据是否存在无关。

5. 设计文档 `docs/dev/M54_NEWS_LAYER_V2_DESIGN.md` L147/L177 写着 "flow_score = s_flow_data
   （复用 m52_flow_floor 真实资金流,独立通道）" 且标注"已有真实数据底座,边际成本低"——
   即设计时**假设** M52 阶段已经把真实资金流数据打好了地基，但对照代码，这个地基从未被
   实际建出来（模块不存在），M54 只是在文档层面"复用"了一个不存在的东西。

**结论一句话**：FLOW_MISSING 不是"没有资金流数据"，而是"资金流通道从设计到实现都是空的
（模块缺失+调用方从不传参），是集成缺口，不是数据源缺口。要修，需要先把 `m52_flow_floor`
（或等价资金流计算，可以用 akshare 的 `stock_individual_fund_flow` 之类，见 §1.2）实现出来，
再让 `m54_daily_accrual.py` / `m54_news_v2_oos.py` 显式传 `flow_value`。

---

## 5. a-stock-data（github.com/simonlin1212/a-stock-data）

### 5.1 README 描述的能力（WebFetch 成功）

一个面向 AI coding assistant 的 "Skill 文件"（Markdown+内嵌 Python），直连 13 个源
（mootdx、腾讯、东财、百度、新浪、巨潮、iwencai 等）的 HTTP 接口，零第三方 wrapper 依赖。
覆盖：实时行情/多周期K线/盘口深度/PE-PB、个股&行业研报(含PDF)/一致预期EPS、热股/板块归因/
北向资金/板块成分、融资融券余额/大宗交易/股东人数/分红、公司新闻/全球财经、季度快照/F10/
财务报表、全市场公告、涨跌停/连板、ETF期权(含Greeks/IV)、投资者问答/热度排行/概念分类。
大多数源免 key，仅 iwencai 语义搜索需要注册申请。

六类覆盖对照：新闻(有)、盘口(有,含深度)、公告(有,全市场)、F10(有)、财务(有)、
**研报(有,含PDF)**——六类全覆盖，且资金流(融资融券)、龙虎榜(限售解禁/大宗交易相关但未直接确认"龙虎榜"字样)、
行业(板块归因/概念分类)也都有。是六源里**理论能力覆盖面最广**的一个。

### 5.2 明仓接入状态（grep 确认）

`backend/data/external_sources.py` L55-85：登记为 `ExternalSource(id="a_stock_data", ...
recommended_stage="evidence_trial")`，只是一个**描述性 catalog 条目**，`high_value_datasets`
列了 7 项（margin_trading/limit_up_lhb/unlock_calendar/announcements/research_reports/
shareholder_count/block_trades），**没有任何对应的 fetch 函数实现**。

`_evidence_trials()`（L314+）里只有 1 条具体化的试验：`a_stock_data.margin_trading`
（融资融券），且明确 `write_policy="no_database_writes"`、`signal_impact="none"`——纯设计阶段，
未落地任何代码。

`market_capabilities.py` L191：`"providers": [..., "a_stock_data_candidate"]`，也只是一个
**字符串占位符**，混在能力清单里表示"候选"，没有实际 provider 注册。

全仓 grep 未发现任何 `import` 或 HTTP 调用指向 a-stock-data 的 13 个上游域名。

**结论：a-stock-data 目前 100% 未接入，仅存在于设计/登记文档层。**

### 5.3 接入成本判断

`M54_NEWS_LAYER_V2_DESIGN.md` L178 把"公告/龙虎榜"标为"二期(可能最高价值)"，并写明前提是
"需先接 M53 a-stock-data"。`external_sources.py` 的 integration_notes 提示：13 个源要"一次
只引入一个数据集"、且要在接入时补 PIT 时间戳、要用明仓自己的 adapter 包一层而不是照抄
skill 代码。成本主要在于：（1）13 个逆向接口各自的稳定性未知，需要逐个探针验证；
（2）公告/研报类需要做实体去重和 PIT 校验（防止用未来才披露的信息回测）。

---

## 6. Anspire + Tavily（一句话带过）

现状不变：Anspire（`ANSPIRE_API_KEY` 已配）是主新闻源（`fetch_stock_news_anspire`），
Tavily（`TAVILY_API_KEY` 已配）是标题级兜底搜索（`search_titles_tavily`/`fetch_titles_tavily`，
只返回标题不含正文），两者定位未变，本次未深挖。

---

## 7. 六源能力矩阵（√=有能力, ~=弱/间接, ×=无, ●=明仓已用, ○=有能力但明仓未用）

| 类目 | akshare | 东财直连 | Tushare(当前token) | TickFlow | a-stock-data | Anspire/Tavily |
|---|---|---|---|---|---|---|
| 新闻 | √● (兜底) | √● (一级路径) | ×(无权限) | × | √○ | √●(Anspire主)/~●(Tavily标题) |
| 盘口 | √○ (bid_ask/tick分笔) | ×(未直连) | ×(无此接口) | ×(只有K线) | √○(含深度) | × |
| 公告 | ~● (仅预约披露日历) / √○(notice_report全文) | ×(未直连公告口) | ×(无权限anns_d) | × | √○(全市场) | × |
| F10/简况 | √● | ~●(经ak) | ×(未用) | × | √○ | × |
| 财务 | √● | ~●(经ak) | ○(fina_indicator无权限;实际未用) | × | √○ | × |
| 研报 | √○ (stock_research_report_em) | ×(未接研报口) | ×(无权限report_rc) | × | √○(含PDF) | × |
| 资金流 | √○ (个股/板块/北向,多函数) | ×(未接push2资金流口) | ×(无权限moneyflow) | ×(名字巧合,非真资金流) | √○(融资融券) | × |
| 龙虎榜 | √○ (16个函数,东财+新浪双源) | ×(未接) | ×(无权限top_list) | × | √○(limit_up_lhb) | × |
| 行业数据 | √○ (板块行情/资金流/成分) | ~(经ak) | ×(未用) | × | √○(概念分类) | × |

## 8. 使用率汇总

- **akshare**：已用 12 个函数 / 六类+资金流+龙虎榜+行业相关候选 ~70+ 个，**~17%**，且资金流/
  龙虎榜/盘口/研报四类候选使用数为 0。
- **东财直连**：1 个接口（新闻搜索），六类里只覆盖新闻一项；公告/研报/资金流/龙虎榜的东财
  公开接口生态完全没碰。
- **Tushare**：当前 token 权限只覆盖行情四件套（非六类核心），六类中新闻/公告/研报 + 资金流/
  龙虎榜权限全部 FAIL；已用 1 个接口(`pro.daily`)且仅用于复权换算，非信号源。
- **TickFlow**：只有 1 个日线K线接口且已全用（当前是优先 provider），六类/资金流/龙虎榜/
  研报/公告/新闻/盘口全部不提供，不是这些类目的候选。
- **a-stock-data**：README 声称六类全覆盖 + 资金流 + 龙虎榜 + 行业，明仓侧 0% 接入（仅登记，
  无代码）。
- **Anspire/Tavily**：现状不变，未深挖。

## 9. 高价值未用能力排序（Top 5）

1. **FLOW_MISSING 集成缺口修复**（不是"新接口"而是"补齐设计与实现的断层"）——
   实现或替换 `backend.tools.m52_flow_floor`（可用 akshare `stock_individual_fund_flow` /
   `stock_individual_fund_flow_rank` 起步），并让 `m54_daily_accrual.py` / `m54_news_v2_oos.py`
   显式传 `flow_value`。这是 M54 打分链路里唯一一个"文档说有、代码没有"的断层，修复后
   news_fusion 的置信度惩罚（当前每条都被 ×0.75 或更低）才可能被真实资金流数据支撑而非
   永久触发。
2. **akshare 研报接口** `stock_research_report_em`——owner 点名的研报类目前六源里唯一
   真正接了正文级数据的候选是 a-stock-data（未接），akshare 这个函数零成本（已装、免key）
   即可先出个股研报列表+评级，作为研报类目从 0 到 1 的最低成本起点。
3. **akshare 公告全文** `stock_notice_report(symbol, date)`——按日期回溯查询，比现有的
   "巨潮预约披露日历"（只是日历，不含正文）价值高得多，且支持 PIT（按天查询天然带
   as-of 语义），零成本。
4. **akshare 龙虎榜** `stock_lhb_detail_em(start_date, end_date)`——owner 点名的龙虎榜类
   目前六源零覆盖，这个函数支持日期范围、东财+新浪双源互验，是最低成本的起点。
5. **东财资金流 push2 接口 / akshare `stock_individual_fund_flow`**——如果 §9.1 的
   m52_flow_floor 修复要落地真实数据，这是最直接的免费数据来源（akshare 已装，
   `stock_individual_fund_flow(stock, market)` 直接返回主力/超大单/大单净流入）。

其后可考虑 a-stock-data 的公告+研报+限售解禁能力（六类覆盖面最全，但接入成本是 13 个
逆向接口逐个验证，属于中期工程，M54 设计文档已定性为"二期"）。
