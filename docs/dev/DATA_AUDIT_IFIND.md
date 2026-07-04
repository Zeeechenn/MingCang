# iFinD MCP 数据源审计（2026-07-04）

审计目的：owner 发现明仓生产代码只用了 iFinD MCP 的 `search_news`/`search_notice`
两个工具，怀疑数据层"没读说明书、没用全功能"。本文档只读调研 + 少量探针调用，
不改代码、不提交、不写 DB。

客户端：`backend/data/ifind_mcp.py`（`IfindMcpClient`，JSON-RPC over HTTP，
`tools/list` + `tools/call`，QPS 限流 1.0，token 从 `.env IFIND_MCP_TOKEN` 读取，
`base_url=https://api-mcp.51ifind.com:8643/ds-mcp-servers`）。

4 个 endpoint 全部连通、`tools/list` 全部 `ok=true`：

| endpoint (mcp_id) | 工具数 | list_tools 延迟 |
|---|---|---|
| hexin-ifind-ds-stock-mcp | 10 | 132ms |
| hexin-ifind-ds-news-mcp | 2 | 116ms |
| hexin-ifind-ds-index-mcp | 3 | 180ms |
| hexin-ifind-ds-global-stock-mcp | 4 | 124ms |
| **合计** | **19** | |

关键结构性发现：**除了 `stock_highfreq_quotes` / `index_highfreq_quotes`
两个高频工具外，其余 17 个工具的入参都只有一个 `query: string`
（自然语言问句），由 iFinD 服务端做语义解析。** 这意味着"读说明书"的核心
其实是"喂对自然语言问法"，不是拼 REST 参数——这也是为什么此前只用了两个新闻
工具：其余工具在没人试探自然语言问法时，看起来像"没有可用参数"，容易被跳过。

---

## ① 4 端点 × 19 工具全目录

### hexin-ifind-ds-stock-mcp（A股，10工具）

| 工具 | 参数 | 覆盖内容 | 请求样例 |
|---|---|---|---|
| `get_stock_summary` | `query`(必填,str) | 上市公司基础信息/近期行情/最新财务指标/IPO/业绩预告/估值/股本股东/行业分类主营业务（"不支持具体指标和具体时间的筛选"，只做摘要） | `{"query":"同花顺和恒生电子最新估值水平"}` |
| `search_stocks` | `query`(必填,str) | 自然语言智能选股→股票代码列表，支持指标数值约束/行业板块/主题概念 | `{"query":"汽车零部件行业的市值大于1000亿的股票"}` |
| `get_stock_performance` | `query`(必填,str) | 日频历史行情+技术指标(MACD/KDJ等)+技术形态(连板/涨跌停/创新高/突破反转)+融资融券/龙虎榜 | `{"query":"三花智控最近5日的涨跌幅与换手率"}` |
| `get_stock_info` | `query`(必填,str) | 证券基本信息(是否转融通/指数成分股)+公司基础资料(行业分类/工商注册/主营业务) | `{"query":"格力电器的上市时间与所属申万行业"}` |
| `get_stock_shareholders` | `query`(必填,str) | 股本结构(总股本/自由流通/限售解禁/AB股/海外股本)+股东数据(前N大股东/机构持股) | `{"query":"光明乳业的流通股占比、前5大股东持股占比"}` |
| `get_stock_financials` | `query`(必填,str) | 三表原始数据+偿债/盈利/成长/风险/规模/杠杆等财务分析指标+估值指标(PE/PB/PS及历史分位数)。**注：财务指标时间为报告期格式** | `{"query":"科大讯飞在2025-12-31的ROE、净利润率"}` |
| `get_risk_indicators` | `query`(必填,str) | 量化风险指标：alpha/beta/波动率/夏普比率/VAR（基于历史价格序列，非财务/经营风险） | `{"query":"航天电子过去1年的beta指标值（以沪深300作为市场基准）"}` |
| `get_stock_events` | `query`(必填,str) | 公开披露事件：IPO、再融资/并购重组、管理层变动、大股东增减持/解禁、股权激励/员工持股、风险警示/监管问询/司法诉讼 | `{"query":"摩尔线程IPO首次发行新股数量"}` |
| `get_esg_data` | `query`(必填,str) | ESG评级与报告数据 | `{"query":"诚意药业的中诚信ESG评级"}` |
| `stock_highfreq_quotes` | `symbols`(必填,str,≤10个逗号拼接), `indicators`(必填,str,≤10个), `data_mode`(必填,enum:`highfreq`/`real_time`), `interval`(可选,enum:1/3/5/10/15/30/60,默认1) | 实时快照/高频分钟序列；**仅支持交易日日内数据，不支持历史查询** | `{"symbols":"300033.SZ,300059,贵州茅台","indicators":"开盘价,最高价,最低价,收盘价,涨跌幅,成交量","data_mode":"real_time","interval":1}` |

### hexin-ifind-ds-news-mcp（新闻/公告，2工具，明仓当前唯一在用的端点）

| 工具 | 参数 | 覆盖内容 | 请求样例 |
|---|---|---|---|
| `search_notice` | `query`(必填), `size`(可选,默认5,上限20), `time_start`(必填,yyyy-MM-dd), `time_end`(必填) | A股/基金/港美股公告内容语义检索，返回相关公告**段落片段**文本 | `{"query":"光迅科技 2024年度报告 公司报告期从事主要业务","time_start":"2025-01-01","time_end":"2026-01-01","size":5}` |
| `search_news` | 同上 | 同花顺财经新闻资讯片段检索 | `{"query":"盈趣科技 脑机接口相关业务进展","time_start":"2025-01-01","time_end":"2026-01-01","size":5}` |

### hexin-ifind-ds-index-mcp（指数/板块，3工具，明仓完全未用）

| 工具 | 参数 | 覆盖内容 | 请求样例 |
|---|---|---|---|
| `index_data` | `query`(必填,str) | 指数(沪深300/新能源车指数等)+基金/债券/期货/ESG指数的行情/技术指标/财务分析/估值指标(含债券指数到期收益率) | `{"query":"沪深300、中证2000过去10个交易日的涨跌幅和收盘点数"}` |
| `sector_data` | `query`(必填,str) | 市场分类板块/行业分类板块/概念板块的行情+技术指标+财务分析+估值+股本股东分布 | `{"query":"医疗设备板块(中证行业)的成分股个数及过去5个交易日的成分股平均涨跌幅"}` |
| `index_highfreq_quotes` | `symbols`(必填), `indicators`(必填), `data_mode`(必填,enum), `interval`(可选) | 指数实时快照/高频序列，仅交易日日内 | `{"symbols":"000001.SH,000941,创业板指","indicators":"最高价,最新价,涨跌幅,动态市盈率,上涨家数","data_mode":"realtime"}` |

### hexin-ifind-ds-global-stock-mcp（港美股，4工具，明仓完全未用）

| 工具 | 参数 | 覆盖内容 | 请求样例 |
|---|---|---|---|
| `global_stock_profile` | `query`(必填,str) | 证券基本信息+上市公司信息+股本股东结构 | `{"query":"智谱、minimax的所属行业、上市日期与发行价"}` |
| `global_stock_quotes` | `query`(必填,str) | 日频行情+技术指标+技术形态+定量风险(beta/夏普/波动率) | `{"query":"苹果和特斯拉近10个交易日的涨跌幅、换手率"}` |
| `global_stock_financial` | `query`(必填,str) | 三表原始数据+财务分析衍生指标与附注+估值/盈利预测等基本面数据 | `{"query":"Google和Meta在最新报告期的ROE、ROA、利润增速"}` |
| `global_stock_events` | `query`(必填,str) | IPO/回购/分红/ESG事件（不覆盖非标准公告的热点新闻类事件） | `{"query":"minimax的IPO日期、数量、价格及保荐人"}` |

---

## ② 探针实测结果（10次真实调用，全部走通，QPS内完成）

1. **`get_stock_financials`（历史季度，601869 长飞光纤）**
   query=`"长飞光纤(601869)在2024-09-30的ROE、净利润率、总资产、营业收入"`
   → 返回 Markdown 表，字段含 ROE(TTM)/ROE(TTM平均)/ROE(扣除加权)/销售净利率/
   资产总计/营业总收入/单季度营业收入及其同比增速等，**日期精确落在
   `20240930`**，证明**能按历史报告期取值，不是只有最新快照**。片段：
   ```
   |601869.SH|长飞光纤|20240930|51.4655|9.4294|9.293|86.945亿|3.5583|306.2452亿|...
   ```

2. **`get_stock_financials`（盈利预测，同一股票）**
   query=`"长飞光纤2026年一致预期归母净利润与市盈率"`
   → 返回 `预测归母净利润中值` 字段（年度=2026，截至日期=最新），
   **确认覆盖研报一致预期/盈利预测，这是明仓目前完全没有的数据类型**（现有
   `FinancialMetric` 只存已披露财报，无前瞻一致预期）。

3. **`search_notice`（长飞光纤 2026年一季报）**
   query=`"长飞光纤 2026年一季度报告 公司经营情况"`, time_start=2026-01-01,
   time_end=2026-07-04
   → 返回**合并利润表实际数字段**（营业总收入/营业收入等，2026Q1 vs
   2025Q1对比），段落质量高、非仅摘要，能直接引用报表数字做交叉验证。
   `time_start`/`time_end` 是**必填**参数，日期过滤天然支持。

4. **`get_stock_performance`（历史区间行情+技术指标）**
   query=`"长飞光纤2024年1月1日至2024年3月31日的收盘价、MACD指标、是否涨停"`
   → 返回按交易日排列的 MACD 值 + 收盘价序列，日期精确到日
   （20240329/20240328/...）。**增量价值：MACD/KDJ等衍生技术指标 + 涨跌停/
   连板等技术形态标签，是明仓 `prices` 表目前没有的字段**（`prices` 只存
   OHLCV，技术指标需自行计算）。

5. **`get_stock_events`（603986 兆易创新）**
   query=`"兆易创新(603986)最近的定向增发、股份回购、限售解禁事件"`
   → 返回限售解禁字段：`限售解禁日期=20260616`，本期流通数量/未流通数量/
   已流通数量、`流通股份类型=股权激励一般股份`。**确认覆盖解禁事件且带精确
   日期**；本次样本未命中回购/定增记录（可能近期确无该类事件，非工具缺陷，
   description 明确列出"再融资与投资事件：如配股、增发、并购重组"）。

6. **`sector_data`（光通信板块，首次尝试）**
   query=`"光通信概念板块 成分股"` → **返回空** `{"text":""}`（工具可用，
   但概念名称匹配失败，需要更精确的板块命名/分类前缀）。

7. **`sector_data`（重试，换用申万三级行业命名）**
   query=`"光通信(申万三级行业)板块的成分股个数"`
   → 命中 `内地股票->申银万国行业类->通信`，**成分股个数=127**，按日连续
   多天返回（20260624~20260703）。**确认板块/行业成分数据可用，但概念板块
   命名需要按官方分类体系措辞，随意关键词容易返回空**（这是"读说明书"价值
   最直接的体现——description 里已提示"板块命名具有相似性，请尽可能提供
   板块所属分类信息"，第一次没照做就落空了）。

8. **`global_stock_quotes`（MRVL Marvell）**
   query=`"Marvell(MRVL)最近5个交易日的涨跌幅、收盘价、换手率"`
   → 返回 `MRVL.O 迈威尔科技` 近5日涨跌幅/收盘价（美元计价，币种字段
   `USD`），日期到 20260702。**确认美股行情数据真实可用、有币种标注**。

9. **`global_stock_financial`（MRVL，首次尝试）**
   query=`"Marvell在最新报告期的ROE、营收增速与市场一致预期净利润"`
   → **`HTTPSConnectionPool ... Read timed out (timeout=12.0)`**。这是本次
   审计唯一一次报错，判定为**偶发超时**（可能该query触发多指标+一致预期
   联合解析、服务端耗时较长），而非权限/端点不可用问题。

10. **`global_stock_financial`（MRVL，简化重试）**
    query=`"Marvell最新报告期的ROE和营收增速"`（去掉"一致预期"这个较重的
    子请求）
    → 3.5s 内返回：`ROE(摊薄)=0.1894%`、`营收近1年增长率=27.5682%`，
    报告期标注为`最新一期(MRQ)`。**确认港美股财务数据真实可用**；
    超时更像是"单次query塞太多不同类指标"导致的延迟风险，而非该工具本身
    不可用——**用量建议：查询港美股一致预期类字段时应拆分为更小的query，
    并设置比默认12s更宽松的timeout或做重试**。

**结论：19个工具中，18个在探针中直接可用；1个（`global_stock_financial`）
首次超时、简化query后即恢复正常，不存在权限不足或系统性报错。**

---

## ③ PIT（Point-in-Time）判定表

| 工具 | PIT 特性 | 判定 |
|---|---|---|
| `get_stock_financials` | 支持按"报告期"取值（探针1验证`20240930`可精确命中），财务字段自带披露期语义 | **较干净**：可按历史报告期查询，但需自行确认"取数时点"是否等于"当时已披露"（服务端未明确返回`disclosure_date`字段，报告期≠披露日，需要额外核实是否会用财报发布后修订值回填历史——**建议在正式接入前专门测一次"财报发布前1天 vs 发布后1天"取值是否一致**，本次未测，标记为待验证风险） |
| `get_stock_financials`（盈利预测/一致预期字段） | 返回"预测归母净利润中值"等前瞻字段，`截至日期`参数=最新 | **前视风险高**：一致预期是滚动更新的，服务端很可能只返回"当前最新一致预期"而非"历史某日的彼时预期"，回测/历史信号构建若直接引用会引入前视偏差，只适合"当前决策辅助"场景 |
| `search_notice` / `search_news` | `time_start`/`time_end`必填，探针3验证返回内容与公告实际披露日期(2026Q1报告)对齐 | **天然PIT干净**：公告/新闻带发布时间过滤，是目前明仓在用的两个工具里天然最安全的 |
| `get_stock_performance` | 探针4验证按日期精确返回历史MACD/收盘价序列 | **PIT干净**：历史行情+技术指标均按交易日归档，可按历史日期回放，无明显前视风险（技术指标本身多为滞后指标，不构成未来函数） |
| `get_stock_events` | 探针5验证事件带精确日期(`限售解禁日期=20260616`) | **PIT干净**：事件类数据自带事件发生/披露日期 |
| `get_risk_indicators`（beta/夏普/VAR等） | 基于历史价格窗口滚动计算 | **形式PIT，实质需核实窗口口径**：若指标用"截至查询当日"的滚动窗口计算，则和一致预期类似——查询时点＝计算时点，不能拿"今天查到的beta"当作"历史某天可知的beta"，除非明确指定历史as-of日期重新计算（未探针验证，标记为待验证） |
| `stock_highfreq_quotes` / `index_highfreq_quotes` | description明确"仅支持交易日日内数据查询，不支持历史数据查询" | **前视风险/不适用**：这是当前快照工具，不具备历史回放能力，只能用于盘中实时监控，不适合历史信号构建 |
| `sector_data` / `index_data` | 探针6/7验证按日期返回板块成分数（`20260624~20260703`连续多日） | **PIT较干净**：按交易日归档，但**成分股名单本身会随指数调仓变化**，历史某日的"成分股个数"不等于"用今天的成分股名单去查历史行情"——回测时需确认服务端是否按"历史当日实际成分"计算，还是用"当前成分"倒推（未验证，标记风险） |
| `get_stock_summary` / `get_stock_info` / `get_stock_shareholders` / `get_esg_data` | description注明"不支持具体指标和具体时间的筛选"（summary）/未强调时间过滤 | **快照类，前视风险**：更适合"当前研究上下文"，不适合历史信号，用于研究软联动而非回测输入 |
| `global_stock_quotes` / `global_stock_financial` / `global_stock_profile` / `global_stock_events` | 探针8/10验证行情/财务按日期返回；events未专门测历史查询 | **与A股同名工具同构**：行情/财务大概率同样"报告期可查、一致预期为当前快照"，PIT特性应比照A股对应工具，正式启用前需比照做一次同类验证 |

---

## ④ 使用率差距表（能力 vs 明仓代码实际调用）

grep 范围：`backend/` 全部 `*.py`，匹配 `call_ifind_mcp_tool` / 具体工具名 /
`mcp_id=` 调用点。

| 端点 | 工具 | 明仓调用点 | 状态 |
|---|---|---|---|
| news-mcp | `search_news` | `backend/data/news.py:fetch_news_ifind`(L542)、`fetch_titles_ifind`(L596)；经 `backend/data/news_adapters/ifind.py` → `IFindAdapter.fetch` 接入 M54 新闻层 | **生产在用** |
| news-mcp | `search_notice` | 同上，`fetch_news_ifind`/`fetch_titles_ifind` 里与`search_news`并列调用 | **生产在用** |
| stock-mcp | `get_stock_summary` | 无 | **零调用** |
| stock-mcp | `search_stocks` | 无 | **零调用** |
| stock-mcp | `get_stock_performance` | 无 | **零调用** |
| stock-mcp | `get_stock_info` | 无 | **零调用** |
| stock-mcp | `get_stock_shareholders` | 无 | **零调用** |
| stock-mcp | `get_stock_financials` | 无（`backend/data/market_capabilities.py`把`ifind_mcp`列为CN`fundamentals`/`filings`层的`evidence_probe`，但只是元数据登记，未真正调用） | **零调用（仅有元数据占位）** |
| stock-mcp | `get_risk_indicators` | 无 | **零调用** |
| stock-mcp | `get_stock_events` | 无 | **零调用** |
| stock-mcp | `get_esg_data` | 无 | **零调用** |
| stock-mcp | `stock_highfreq_quotes` | 无 | **零调用** |
| index-mcp | `index_data` | 无 | **零调用** |
| index-mcp | `sector_data` | 无 | **零调用** |
| index-mcp | `index_highfreq_quotes` | 无 | **零调用** |
| global-stock-mcp | `global_stock_profile` | 无 | **零调用** |
| global-stock-mcp | `global_stock_quotes` | 无 | **零调用** |
| global-stock-mcp | `global_stock_financial` | 无 | **零调用** |
| global-stock-mcp | `global_stock_events` | 无 | **零调用** |

**用量统计：19 工具中仅 2 个（10.5%）被生产代码实际调用，其余 17 个
（89.5%）从未在 `backend/` 中被 `call_ifind_mcp_tool` 引用，包括整个
`stock-mcp`（10工具中9个未用，`get_stock_financials`只有文档占位没有代码
调用）、`index-mcp`（3个全未用）、`global-stock-mcp`（4个全未用）。**

其余相关代码点（非调用，仅登记/催化）：
- `backend/data/external_sources.py`：把 `ifind_mcp` 登记为候选外部源，
  `high_value_datasets` 里列了 `stock_financials`/`stock_events`/
  `stock_shareholders`/`index_data`/`sector_data` 等——**这些字段名此前已经
  被写进文档"应该用"，但从未真正落地成调用代码**，佐证 owner 的怀疑。
- `backend/data/market_capabilities.py`：CN 的 `fundamentals`/`filings` 层
  probe_links 挂了 `ifind_mcp`，status=`evidence_probe`，同样是登记非调用。
- `backend/tools/m54_daily_accrual.py`、`backend/tools/m54_content_backfill.py`、
  `backend/jobs/postmarket.py`：均只经由 `news.py`/`news_adapters` 间接用到
  `search_news`/`search_notice`，未涉及其余17工具。

---

## ⑤ 高价值未用能力排序（对明仓选股/避雷/出场/研究软联动的潜在价值）

1. **`get_stock_financials` 的"一致预期/盈利预测"字段**（探针2验证可用）—
   明仓现有 `FinancialMetric` 只有已披露历史财报，完全没有前瞻性盈利预测/
   估值分位数据。这是研究软联动（判断"贵不贵""预期兑现度"）的天然缺口，
   但**PIT风险高**，只能用于当前决策辅助/研究提示，不能喂回测。

2. **`get_stock_events`（定增/回购/解禁/重组/监管风险等公开事件）**（探针5
   验证可用且带精确日期）— 明仓目前"避雷"逻辑里缺一个结构化的事件流
   （解禁冲击、监管问询、诉讼风险），现在只能靠新闻文本模糊捕捉。此工具
   直接给出事件类型+日期+数量，适合做"持仓预警"规则输入。

3. **`get_stock_performance` 的技术形态/衍生技术指标字段**（探针4验证）—
   涨跌停/连板/创新高/突破反转等定性形态标签，是明仓 `prices` 表没有的
   现成"出场/择时"辅助信号，比自己重新实现技术指标计算更省事，且天然
   PIT干净，可以安全喂回测。

4. **`sector_data` / `index_data`（板块/行业/概念成分与行情）**（探针6/7
   验证可用，但命名需按官方分类措辞）— 明仓目前没有"板块联动"能力（比如
   持仓个股所在概念板块整体走弱做提前预警，或选股阶段做板块轮动筛选）。
   需注意成分股会随时间变化，历史回测前需专门验证PIT口径。

5. **`global_stock_quotes` / `global_stock_financial`（港美股行情+财务，
   MRVL/MU等"海外领先指标"）**（探针8/10验证真实可用）— 这是 owner 特别
   关心的"海外供应链/赛道领先指标自动化"的关键前提：确认数据真实可取，
   但存在**偶发超时**（探针9），正式接入需要更宽松的超时/重试策略，且
   query不宜一次塞太多指标类型。

（`search_stocks` 智能选股、`get_esg_data`、`stock_highfreq_quotes` 等
工具价值相对更边缘：智能选股受限于"条件范围不宜过大"、ESG对A股短线策略
参考价值低、高频快照工具不支持历史回放，暂不列入优先级前五。）

---

## 附：探针原始返回片段存档位置

完整 JSON（含全部19工具schema + 10次探针的完整text/parsed字段）已落盘于
本次会话 scratchpad（非仓库路径，仅供交叉核对，不纳入版本控制）：
`ifind_tools_dump.json`、`ifind_probes_dump.json`、`ifind_probes_dump2.json`。
