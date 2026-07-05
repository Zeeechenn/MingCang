# iFinD MCP 手册

> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

素材来源：`docs/dev/DATA_AUDIT_IFIND.md`（本次审计原文 + 10 次探针 + 本手册补充 2 次实测验证，
共 12 次真实调用，全部在 QPS=1 限流内完成）。本手册只做"使用者视角"重排，判定结论不重复推导，
详细证据链见审计原文。

## 1. 一句话定位

iFinD 是明仓**能力最全、结构最规整**的数据源——4 个 endpoint、19 个工具，覆盖 A股/新闻公告/
指数板块/港美股六大类中的五类（缺资金流/龙虎榜专项，但 `get_stock_events`/`get_stock_performance`
部分覆盖相邻信息）。目前**新闻/公告是生产主源**（`search_news`/`search_notice`），其余 17 个工具
是**待评估候选源**——按 M61 三车道分工，多数应进②面板/避雷道或③研究裁量道，仅小部分（历史报告期
财务、事件、技术形态）可能进①回测因子道，需逐个走 P1 体检 harness 定角色，不能不经验证直接喂信号。

## 2. 客户端与连接信息

- 代码：`backend/data/ifind_mcp.py`，`IfindMcpClient`（JSON-RPC 2.0 over HTTP，`tools/list` +
  `tools/call`）。
- Token：`.env` 的 `IFIND_MCP_TOKEN`（`settings.ifind_mcp_token`），开关 `IFIND_MCP_ENABLED`
  （`settings.ifind_mcp_enabled`）。
- Base URL：`settings.ifind_mcp_base_url`，默认
  `https://api-mcp.51ifind.com:8643/ds-mcp-servers`。
- **QPS 限流 = 1.0**（`settings.ifind_mcp_qps_limit`，`_respect_qps_limit()` 强制每次调用间隔
  ≥1s）——批量拉取多支股票/多工具时必须串行等待，不能并发绕过。
- 4 个 endpoint 用 `mcp_id` 区分，全部独立限流计时（同一个 `IfindMcpClient` 实例内共享
  `_last_request_at`，换 endpoint 不重置计时器）：

| endpoint (mcp_id) | 工具数 | 覆盖范围 |
|---|---|---|
| `hexin-ifind-ds-stock-mcp` | 10 | A股 |
| `hexin-ifind-ds-news-mcp` | 2 | 新闻/公告（明仓当前唯一在用端点） |
| `hexin-ifind-ds-index-mcp` | 3 | 指数/板块 |
| `hexin-ifind-ds-global-stock-mcp` | 4 | 港美股 |

**核心结构性事实**：19 个工具里 17 个入参只有 `query: string`（自然语言，服务端做语义解析），
只有 `stock_highfreq_quotes`/`index_highfreq_quotes` 两个高频工具是结构化参数
（`symbols`/`indicators`/`data_mode`/`interval`）。这意味着"读说明书"的核心是"喂对自然语言问法"，
不是拼 REST 参数——本手册第 4 节问法模板是使用这 17 个工具的关键。

## 3. 能力目录

### 3.1 hexin-ifind-ds-stock-mcp（A股，10 工具）

| 工具 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `get_stock_summary` | `query`(必填,str) | 摘要卡：估值(PE/PB/PS/PCF/PEG/EV-EBITDA)+最新报告期+股本分布(总股本/流通/限售/自由流通占比) | 快照类，**不支持指定指标/日期筛选**（服务端原话），只做"了解概况" |
| `search_stocks` | `query`(必填,str) | 自然语言智能选股 → 股票代码列表 | 条件范围不宜过大，过宽泛的筛选条件命中质量下降 |
| `get_stock_performance` | `query`(必填,str) | 日频历史行情 + 技术指标(MACD/KDJ等) + 技术形态(涨跌停/连板/创新高/突破反转) + 融资融券/龙虎榜 | 按交易日归档，可指定历史区间 |
| `get_stock_info` | `query`(必填,str) | 证券基本信息(转融通标的/指数成分股) + 公司资料(行业分类/工商注册/主营业务) | 偏静态资料，非行情 |
| `get_stock_shareholders` | `query`(必填,str) | 股本结构(总股本/自由流通/限售解禁/AB股/海外股本) + 股东数据(前N大股东/机构持股) | 可用于补 Piotroski 缺失的 `shares_outstanding`（M61 D2） |
| `get_stock_financials` | `query`(必填,str) | 三表原始数据 + 偿债/盈利/成长/风险/规模/杠杆分析指标 + 估值指标(含历史分位数) + 一致预期/盈利预测 | **财务字段按报告期返回**（可精确到 `yyyymmdd`），一致预期字段只返回当前最新滚动值 |
| `get_risk_indicators` | `query`(必填,str) | alpha/beta/波动率/夏普比率/VAR（基于历史价格序列） | **窗口口径="截止日1年前"到"最新"**（本手册实测确认，见 §5），是滚动窗口非固定历史快照 |
| `get_stock_events` | `query`(必填,str) | IPO/再融资/并购重组/管理层变动/大股东增减持/解禁/股权激励/风险警示/监管问询/司法诉讼 | 事件带精确日期，但样本命中依赖近期确实发生该类事件 |
| `get_esg_data` | `query`(必填,str) | ESG评级与报告数据 | 对A股短线策略参考价值低 |
| `stock_highfreq_quotes` | `symbols`(必填,≤10个逗号拼接)，`indicators`(必填,≤10个)，`data_mode`(必填,`highfreq`/`real_time`)，`interval`(可选,1/3/5/10/15/30/60,默认1) | 实时快照/高频分钟序列 | **仅支持交易日日内数据，不支持历史查询**，唯一结构化参数工具 |

### 3.2 hexin-ifind-ds-news-mcp（新闻/公告，2 工具，生产在用）

| 工具 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `search_notice` | `query`(必填)，`size`(可选,默认5,**上限20**)，`time_start`(必填,`yyyy-MM-dd`)，`time_end`(必填) | A股/基金/港美股公告**段落片段**文本 | `time_start`/`time_end` 必填——天然日期过滤，但单次最多 20 条，长历史窗口需分批 |
| `search_news` | 同上 | 同花顺财经新闻资讯片段 | 同上 |

### 3.3 hexin-ifind-ds-index-mcp（指数/板块，3 工具，明仓完全未用）

| 工具 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `index_data` | `query`(必填,str) | 指数/基金/债券/期货/ESG指数的行情+技术指标+财务+估值(含债券到期收益率) | 按交易日归档 |
| `sector_data` | `query`(必填,str) | 市场分类/行业分类/概念板块成分股+行情+技术指标+财务+估值+股本股东分布 | **板块命名必须用官方分类体系措辞**（申万/中证行业等），随意关键词易返回空，见 §4 教训 |
| `index_highfreq_quotes` | `symbols`/`indicators`/`data_mode`/`interval`（同 §3.1 结构） | 指数实时快照/高频序列 | 仅交易日日内，不支持历史回放 |

### 3.4 hexin-ifind-ds-global-stock-mcp（港美股，4 工具，明仓完全未用）

| 工具 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `global_stock_profile` | `query`(必填,str) | 证券基本信息+上市公司信息+股本股东结构 | — |
| `global_stock_quotes` | `query`(必填,str) | 日频行情+技术指标+技术形态+定量风险(beta/夏普/波动率) | 币种字段随市场变化(如 `USD`) |
| `global_stock_financial` | `query`(必填,str) | 三表原始数据+财务分析衍生指标+估值/盈利预测 | **一次 query 塞多类指标（尤其含"一致预期"）容易超时**，见 §4 教训 |
| `global_stock_events` | `query`(必填,str) | IPO/回购/分红/ESG事件 | 不覆盖非标准公告的热点新闻类事件 |

## 4. 问法模板

标注：**[实测]** = 本次或审计期间真实调用并拿到有效返回；**[示例]** = 审计文档给出的请求样例
（未逐一复测，但语法/措辞符合服务端 description 要求）；**[变体]** = 手册补充的同构问法，供参考、
未实测。

### stock-mcp

- `get_stock_summary`
  - [实测] `"中际旭创最新估值水平与近期股本变化"` → 返回 PE/PB/PS/PEG + 最新报告期 + 股本分布（本手册 2026-07-04 补充验证）
  - [示例] `"同花顺和恒生电子最新估值水平"`
  - [变体] `"贵州茅台的最新估值水平与最新定期报告日期"`
- `search_stocks`
  - [示例] `"汽车零部件行业的市值大于1000亿的股票"`
  - [变体] `"光通信行业市盈率小于30倍的股票"`（条件不宜叠加过多，见 §3.1 限制）
- `get_stock_performance`
  - [实测] `"长飞光纤2024年1月1日至2024年3月31日的收盘价、MACD指标、是否涨停"` → 按交易日返回MACD序列+收盘价，日期精确到日
  - [示例] `"三花智控最近5日的涨跌幅与换手率"`
  - [变体] `"兆易创新过去20个交易日是否有涨停或连板"`
- `get_stock_info`
  - [示例] `"格力电器的上市时间与所属申万行业"`
  - [变体] `"长飞光纤是否为转融通标的、是否为沪深300成分股"`
- `get_stock_shareholders`
  - [示例] `"光明乳业的流通股占比、前5大股东持股占比"`
  - [变体] `"中际旭创的限售解禁股本与自由流通股本占比"`（Piotroski `shares_outstanding` 候选补数源）
- `get_stock_financials`
  - [实测] `"长飞光纤(601869)在2024-09-30的ROE、净利润率、总资产、营业收入"` → 日期精确落在 `20240930`，证明可按历史报告期取值
  - [实测] `"长飞光纤2026年一致预期归母净利润与市盈率"` → 返回"预测归母净利润中值"（前瞻字段，PIT风险高，见 §5）
  - [示例] `"科大讯飞在2025-12-31的ROE、净利润率"`
- `get_risk_indicators`
  - [实测] `"长飞光纤过去1年的beta指标值（以沪深300作为市场基准）"` → Beta=0.7679，附参数`起始交易日期=截止日1年前,截止交易日期=最新`（本手册2026-07-04补充验证，确认为滚动窗口口径）
  - [示例] `"航天电子过去1年的beta指标值（以沪深300作为市场基准）"`
- `get_stock_events`
  - [实测] `"兆易创新(603986)最近的定向增发、股份回购、限售解禁事件"` → 返回`限售解禁日期=20260616`等精确日期字段
  - [示例] `"摩尔线程IPO首次发行新股数量"`
  - [变体] `"长飞光纤近一年的管理层变动与股权激励事件"`
- `get_esg_data`
  - [示例] `"诚意药业的中诚信ESG评级"`
- `stock_highfreq_quotes`（结构化参数，非自然语言）
  - [示例] `{"symbols":"300033.SZ,300059,贵州茅台","indicators":"开盘价,最高价,最低价,收盘价,涨跌幅,成交量","data_mode":"real_time","interval":1}`
  - [变体] 同结构，`interval` 改 5（5分钟K线）

### news-mcp（生产在用）

- `search_notice`
  - [实测] `query="长飞光纤 2026年一季度报告 公司经营情况"`，`time_start="2026-01-01"`，
    `time_end="2026-07-04"` → 返回合并利润表实际数字段（营收等，同比对比）
  - [生产实例] `backend/data/news.py:fetch_news_ifind` 实际拼法：`query=f"{name} {symbol}"`，
    `time_start`/`time_end` 为近 N 天窗口，`size=max_results`
- `search_news`
  - [示例] `"盈趣科技 脑机接口相关业务进展"`（同 `search_notice` 的 `time_start`/`time_end`/`size` 结构）

### index-mcp（明仓完全未用）

- `index_data`
  - [示例] `"沪深300、中证2000过去10个交易日的涨跌幅和收盘点数"`
  - [变体] `"创业板指最近一年的最高点和最低点"`
- `sector_data`
  - [实测·反例] `"光通信概念板块 成分股"` → **返回空**`{"text":""}`（概念名称随意措辞会命中失败）
  - [实测] `"光通信(申万三级行业)板块的成分股个数"` → 命中`申银万国行业类->通信`，成分股个数=127，按日连续多天返回
  - **教训**：板块/概念命名必须用官方分类体系措辞（申万/中证/证监会行业分类），不能只写口语化概念名
- `index_highfreq_quotes`（结构化参数）
  - [示例] `{"symbols":"000001.SH,000941,创业板指","indicators":"最高价,最新价,涨跌幅,动态市盈率,上涨家数","data_mode":"realtime"}`

### global-stock-mcp（明仓完全未用）

- `global_stock_profile`
  - [示例] `"智谱、minimax的所属行业、上市日期与发行价"`
- `global_stock_quotes`
  - [实测] `"Marvell(MRVL)最近5个交易日的涨跌幅、收盘价、换手率"` → 返回`MRVL.O 迈威尔科技`近5日数据，币种`USD`
  - [变体] `"苹果和特斯拉近10个交易日的涨跌幅、换手率"`
- `global_stock_financial`
  - [实测·反例] `"Marvell在最新报告期的ROE、营收增速与市场一致预期净利润"` → **超时**（`Read timed out timeout=12.0`），指标类型塞太多导致
  - [实测] `"Marvell最新报告期的ROE和营收增速"`（简化后）→ 3.5s内返回，ROE(摊薄)=0.1894%，营收近1年增长率=27.5682%，报告期=`最新一期(MRQ)`
  - **教训**：query 拆小、涉及"一致预期"类字段单独查、必要时把超时从默认 12s 调宽 + 加重试
- `global_stock_events`
  - [示例] `"minimax的IPO日期、数量、价格及保荐人"`

**模板总数**：19 个工具，共 41 条问法模板（含 [实测]/[示例]/[变体]/反例）。

## 5. PIT（Point-in-Time）判定

| 工具 | 判定 | 理由 |
|---|---|---|
| `get_stock_financials`（历史报告期字段） | **较干净** | 可按 `yyyymmdd` 报告期精确取值（实测验证），但服务端未返回 `disclosure_date`，报告期≠披露日；**未验证**"财报发布前1天 vs 发布后1天"取值是否一致，正式接入回测前需专门补测 |
| `get_stock_financials`（一致预期/盈利预测字段） | **前视风险高** | 滚动更新，只返回"当前最新一致预期"，不能反推"历史某日的彼时预期"，只适合当前决策辅助（③研究裁量道），禁止喂回测 |
| `search_notice`/`search_news` | **PIT干净** | `time_start`/`time_end` 必填过滤，内容与实际披露日期对齐，明仓在用两个工具里最安全 |
| `get_stock_performance` | **PIT干净** | 历史行情+技术指标按交易日归档，可按历史日期回放；技术指标多为滞后指标不构成未来函数 |
| `get_stock_events` | **PIT干净** | 事件自带精确发生/披露日期 |
| `get_risk_indicators` | **形式PIT，实为滚动快照** | 本手册 2026-07-04 实测确认参数为`起始交易日期=截止日1年前,截止交易日期=最新`——即"今天查到的beta"永远是"以今天为终点倒推1年"，不是"历史某天可知的beta"，除非能显式指定历史 as-of 截止日重新计算（未验证是否支持），当前只能进②面板道 |
| `stock_highfreq_quotes`/`index_highfreq_quotes` | **不适用** | description 明确"仅支持交易日日内数据，不支持历史查询"，只能用于盘中监控 |
| `sector_data`/`index_data` | **较干净，需核实成分口径** | 按交易日归档（实测多日连续返回），但成分股名单随调仓变化，**未验证**服务端历史查询是用"历史当日实际成分"还是"当前成分倒推" |
| `get_stock_summary`/`get_stock_info`/`get_stock_shareholders`/`get_esg_data` | **快照类，前视风险** | description 注明不支持具体时间筛选（summary）或未强调时间过滤，只适合当前研究上下文，不适合历史信号 |
| `global_stock_quotes`/`global_stock_financial`/`global_stock_profile`/`global_stock_events` | **与A股同名工具同构，未逐项复验** | 探针验证行情/财务按日期返回；PIT特性应比照A股对应工具，正式启用前需比照做一次同类专项验证 |

## 6. 明仓接线现状

**生产在用（news-mcp，2/19）**：
- `search_news`/`search_notice` — `backend/data/news.py:fetch_news_ifind`（L522）、
  `fetch_titles_ifind`（L577），经 `backend/data/news_adapters/ifind.py:IFindAdapter`（L13）接入
  M54 新闻层。

**零调用（stock-mcp 9/10，index-mcp 3/3，global-stock-mcp 4/4）**：
- `get_stock_financials` 在 `backend/data/market_capabilities.py` 被登记为 CN
  `fundamentals`/`filings` 层的 `evidence_probe`，但只是元数据占位，代码里从未真正调用。
- `backend/data/external_sources.py` 把 `ifind_mcp` 登记为候选源，`high_value_datasets` 列了
  `stock_financials`/`stock_events`/`stock_shareholders`/`index_data`/`sector_data` 等字段名，
  同样只是文档登记，未落地成调用代码。
- 其余 15 个工具（`search_stocks`/`get_stock_performance`/`get_stock_info`/
  `get_stock_shareholders`/`get_risk_indicators`/`get_stock_events`/`get_esg_data`/
  `stock_highfreq_quotes`/`index_data`/`sector_data`/`index_highfreq_quotes`/
  `global_stock_profile`/`global_stock_quotes`/`global_stock_financial`/`global_stock_events`）
  无任何登记，纯空白。

按 M61 §9 高价值排序（供 P1 体检优先级参考）：`get_stock_events`（避雷用，②道）>
`get_stock_performance` 技术形态字段（①道候选）> `sector_data`/`index_data`（板块联动，②/③道）>
`global_stock_quotes`/`global_stock_financial`（海外领先指标，③道）。

## 7. 坑与注意

1. **QPS=1 是硬限流**，批量任务（多股票×多工具）必须显式串行等待，不要开多线程/多进程绕过，
   会被拒绝或封禁。
2. **17/19 工具只吃自然语言 `query`**，不是 REST 参数——不要尝试传结构化字段（除
   `stock_highfreq_quotes`/`index_highfreq_quotes`），措辞不对会静默返回空文本而不是报错，容易
   被误判为"工具不可用"。
3. **`search_news`/`search_notice` 单次上限 20 条**（默认 5），覆盖长历史窗口（如回填一年新闻）
   必须按月/按旬分批切窗口调用，不能指望一次查询吃下整年数据。
4. **板块/概念命名要用官方分类体系措辞**（申万一二三级行业、中证行业、证监会行业分类），随口的
   概念名称（如"光通信概念板块"）大概率返回空，`description` 里已提示"板块命名具有相似性"。
5. **一致预期/盈利预测类字段禁止喂回测**——`get_stock_financials`/`global_stock_financial` 里的
   "预测归母净利润中值"等前瞻字段只能进③研究裁量道。
6. **`get_risk_indicators`（beta/夏普/VAR）是滚动窗口，不是历史 as-of 值**——查询时点=计算时点，
   不能把"今天查到的beta"当作"历史某天可知的beta"直接喂历史回测。
7. **港美股财务类 query 不要一次塞多类指标**，尤其"一致预期"类字段容易触发 12s 默认超时，正式
   接入需要拆分 query + 放宽超时 + 重试策略。
8. **高频快照工具（`stock_highfreq_quotes`/`index_highfreq_quotes`）不支持历史回放**，只能用于
   盘中监控/M60 触发确认场景，不要试图拿它做历史信号。
9. **接入任何一个新工具前，先在本手册补一条 [实测] 问法模板**，不要凭 description 直接上生产
   （参考 §4 `sector_data` 的空返回教训——不试就以为能用，容易踩空）。

## 额度政策与预算纪律（2026-07-05 实证补充）

- 超限报错原文：`{"code":1,"msg":"success","data":{"answer":"用户使用工具已超限 "}}`——**HTTP 200 + code=1 伪成功**,靠 answer 文本识别;调用方必须把该文本当额度错误处理,不得当空数据。
- 实证刷新模式：07-04 深夜耗尽→07-05 凌晨恢复（21 季度窗大抓成功）→07-05 白天再耗尽。推断**日额度每日刷新**;官方免费档另有**月度总量上限**（mcp.51ifind.com）,月池余量仅账户后台可见。
- 预算纪律：①回填/重抓类大抓集中凌晨排程,单日一批;②测试与验收一律走缓存/fixture,禁打真实 iFinD;③盘后滴灌是唯一日常消耗(几十次/日量级);④连续两日凌晨仍超限→按月池耗尽处理,上报 owner 决定等月初或升级档位。
- **2026-07-06 起已订阅个人版付费套餐（一个月）**：07-06 02:08 免费档仍超限,owner 订阅后 02:31 探针即恢复。额度明显宽于免费档,但上述纪律照旧执行;**到期日约 2026-08-06,到期前需 owner 决定续订或回落免费档纪律**。
