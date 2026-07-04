# 数据层架构审计（2026-07-04）

只读审计。范围：`backend/data/` 全部架构组件（provider fallback、能力目录、PIT、质量门、
schema 运行时补丁、外部源探针、缓存策略）+ `backend/agent/context.py`（LLM 上下文组装）。
不改代码、不提交。背景材料：`docs/dev/DATA_AUDIT_IFIND.md`、`DATA_AUDIT_EXTERNAL.md`、
`DATA_AUDIT_INTERNAL_USAGE.md`（消费端"逻辑饥饿"清单，本文档在架构层面解释那些发现的根因）。

---

## 一、现状架构画像

### 1.1 Provider fallback chain（`backend/data/providers.py`）

- 两个**并行的、写死类型的**全局注册表：`_DAILY_PROVIDERS: list[DailyProvider]`
  （`providers.py:36`）和 `_INDEX_PROVIDERS: list[IndexProvider]`（`providers.py:37`）。
  `DailyProvider`/`IndexProvider`（`providers.py:15-33`）都是 `frozen dataclass`，
  `fetch` 字段的类型别名固定为 `(symbol, days) -> DataFrame`（行情专用签名）。
- 注册：`register_daily_provider(name, markets, fetch, priority, cooldown_seconds, ...)`
  （`providers.py:49-72`），按 `priority` 升序插入排序（数字越小越先尝试，
  `providers.py:71`），`data_type` 字段默认值就是 `"daily_price"`（`providers.py:21`）——
  即"品类"这个概念在类型系统里只作为一个**装饰性字符串字段**存在，从未被 fallback
  遍历逻辑读取或分支。
- 降级/健康检查：`_PROVIDER_HEALTH: dict[str, dict]`（`providers.py:38`）记录
  successes/failures/skipped/last_error/cooldown_until；`fetch_daily_with_fallback`
  （`providers.py:203-227`）线性遍历排序后的 provider 列表，`observe_only` 的直接跳过、
  冷却中的跳过、异常/空结果记为 failure 并进入 cooldown，成功即返回。这是一套完整、
  可测试的（`tests/test_m31_cache_and_freshness.py`）行情 fallback 骨架，但**只服务两种
  fetch 签名**（daily bars / index bars），没有第三种。
- `provider_fallback_chains(market)`（`providers.py:194-200`）把两条链的元数据（含健康
  状态）暴露给 `market_capabilities.py`（`market_capabilities.py:11,385`）和
  `quality.py`（`quality.py:12,100-106`）做可观测面。

**结论**：fallback chain 机制本身（注册-排序-遍历-冷却-健康计数）是一个通用的算法骨架，
但**数据结构和调用点是按"行情"（daily_price/index_price）硬编码的两条平行赛道**，不是
按品类参数化的单一注册表。要接入公告/研报/资金流等新品类，要么复制一整套
`_XXX_PROVIDERS`/`XxxProvider`/`register_xxx_provider`/`fetch_xxx_with_fallback`
（当前一条链约 90 行），要么重构成 `dict[str, list[Provider]]` 按 `data_type` 单例化。

### 1.2 Capability registry（`backend/data/market_capabilities.py`）

- `CAPABILITY_LAYERS`（`market_capabilities.py:15-58`）声明 7 层：quote / kline /
  fundamentals / capital_flow / derivatives / filings / tools_fallback，每层带
  `required_fields`。这个 7 层框架**已经是品类无关的**——形式上支持任意数量的新层。
- `_CAPABILITIES[market][layer_id]`（`market_capabilities.py:165-319`）是**手写的三维
  字典**（market × layer × 状态元数据），CN 的 `capital_flow`/`derivatives` 明确标记
  `status: "observe_only"/"planned"`、`providers: []` 或 `[..., "_candidate"]` 后缀
  （`market_capabilities.py:188-201`）——即约 7×3=21 个 market×layer 格子里，
  **CN 只有 quote/kline/fundamentals/filings/tools_fallback 5 格是 `"production"`**，
  capital_flow 是 observe_only，derivatives 是 planned/not_connected；HK/US 全部
  `seeded`/`planned`（除 quote/kline 是 daily_price_bridge 之外）。
- `PROBE_LINKS`（`market_capabilities.py:60-162`）登记的 probe（`ifind_mcp`/`ftshare`/
  `sec_data_api`/`hkexnews`/`yfinance_global`）全部走 `_probe_links_for`
  （`market_capabilities.py:322-339`）附加 `write_policy="no_database_writes"` +
  `signal_impact="none"`——**这是元数据登记，不是可调用的 provider**，与 §一.1 的
  fallback chain 是两套互不相通的系统（`DATA_AUDIT_IFIND.md` §④ 已验证 `ifind_mcp`
  17/19 工具"只登记未调用"正是这个断层的产物）。
- **多少是空牌子**：`_CAPABILITIES` 里带 `_candidate` 后缀或 `providers: []` 的格子
  （HK 全部 4 层 fundamentals/capital_flow/derivatives/filings + US 同 4 层 + CN 的
  capital_flow/derivatives）共 10/21 格是纯声明、零实现；CN 的 5 个"production"格里，
  filings 也只是"预约披露日历"（弱覆盖，`DATA_AUDIT_EXTERNAL.md` §2.2 已指出）。

### 1.3 PIT 机制（`backend/data/point_in_time.py`）

- `_PIT_DATE_FIELDS: dict[str, tuple[str, str]]`（`point_in_time.py:35-42`）是一个
  **按 ORM 类名注册的白名单**：目前只覆盖 6 个模型——`Price`/`Signal`/`LongTermLabel`
  （kind="string"）、`FinancialMetric`（kind="financial_disclosure"，带 45 天 fallback
  特判）、`IndexPrice`（string）、`NewsItem`（kind="datetime"，字段 `published_at`）。
  未在此表中的 model **透传不拦截**（`point_in_time.py` 文档字符串明确写此局限）。
- `PITSession.query()`（`point_in_time.py:62-92`）只拦截"按 ORM 类整体查询"路径，
  列级查询 `db.query(Model.field)` 不会被拦截——这是文档自陈的已知局限
  （`point_in_time.py:66-69`），不是本次新发现，但对新品类同样适用，扩品类时容易踩同一个坑。
- **可扩展性判断**：注册新品类只需一行 `"NewModel": ("date_field", "string")`——**前提是**
  该品类只有一个干净的"截止时点"字段。财务这种"报告期 vs 披露日期"双时间轴已经需要
  第三种 kind（`financial_disclosure`，`point_in_time.py:80-89`）做特判 fallback；公告/
  研报（发布时点单一，较像 news）应可直接复用 datetime kind；资金流/龙虎榜按
  `trade_date` 复用 string kind；但事件类（定增/回购/解禁）常有"事件发生日 vs
  披露公告日"两个时间轴，board/概念板块成分变化本身是"名单随时间漂移"（
  `DATA_AUDIT_IFIND.md` §③ 已指出这类 PIT 风险），**这些都需要新的 kind 分支或
  完全不同的拦截逻辑**，不是简单加一行字典就能解决——PIT 层对"单时间轴"品类友好，
  对"多时间轴/名单漂移"品类需要真实设计工作。

### 1.4 质量门（`backend/data/quality.py`）

- `build_data_coverage_report`（`quality.py:19-112`）和
  `build_data_coverage_snapshot`（`quality.py:116-181`）是生产唯一的"数据健康"聚合面
  （`backend/tools/coverage_snapshot.py:8` 直接调用后者）。
- **实际计算的覆盖率只有 4 项**：`price_covered`/`two_year_price_covered`/
  `financial_covered`/`news_24h_covered`（`quality.py:66-69,78-81`），对应的
  `checks` 也只有这 4 个布尔阈值（`quality.py:130-137`）。
- **与 §一.2 的 7 层能力目录完全脱节**：`build_market_capability_catalog()` 被原样塞进
  返回值（`quality.py:85,107`）作为**旁路展示字段**，但 `checks`/`warnings` 从不读取
  它——也就是说，capability 目录声明了 capital_flow/derivatives/filings 三层，
  coverage snapshot 却从未对这三层做过任何"覆盖率是否达标"的计算或告警。这是
  `DATA_AUDIT_INTERNAL_USAGE.md` 里"north_net_buy/large_order_net_inflow 100% NULL
  但零告警"这一发现的**架构根因**：质量门的检查项是硬编码的 4 个計數器，不是"遍历
  已声明的能力层逐一验证"的通用循环。新增品类不会自动获得健康检查，除非有人手写
  第 5、第 6 个 `_covered()` 计数器。

### 1.5 Schema 运行时（`backend/data/schema_runtime.py`）

- `_ensure_runtime_schema()`（`schema_runtime.py:9-368`）是一个**线性增长的、按里程碑
  手写的幂等 DDL 补丁脚本**：每次启动对 `prices`/`news`/`financial_metrics`/
  `positions`/... 逐表 `PRAGMA table_info` 探测缺列再 `ALTER TABLE`，外加十几个
  `CREATE TABLE IF NOT EXISTS`（`ai_memory`/`stock_memory_items`/`memory_atoms`/
  `market_snapshots`/`decision_runs`/`research_states`/... ）。没有 Alembic 或版本化
  migration 框架，每加一张表/一列就在这个文件末尾追加一个新代码块（当前 368 行，
  M6.1 到近期里程碑的补丁都堆在一起）。这本身与"品类是否通用"无关，是**独立的技术债**：
  新增 7-8 个品类大概率意味着这个文件再增长 200-400 行手写 DDL 块，可维护性会明显下降，
  但机制上"能用"，不阻塞增量接入。

### 1.6 外部源探针（`backend/data/external_sources.py`）

- `ExternalSource`/`ExternalEvidenceTrial`（`external_sources.py:18-43`）是**登记目录**
  （a_stock_data/ftshare/tickflow/tushare_qfq/ifind_mcp/sec_data_api/hkexnews/
  yfinance_global 共 8 个候选源），`build_external_source_catalog()`
  （`external_sources.py:280-311`）只输出静态 dict，不触发任何网络调用。
- 真正有价值的可复用件是 `_probe_payload()`（`external_sources.py:376-400`）——一个
  **品类无关**的探针返回值 shape：`ok/provider/market/layer/symbol/latency_ms/
  sample_size/fields_present/write_policy/signal_impact/error`，配合
  `summarize_probe_results()`（`external_sources.py:421-478`）对照
  `CAPABILITY_LAYERS.required_fields` 算 `missing_fields`/`field_status`。这是全库
  **唯一一处已经按"源 × 品类"参数化设计的健康探针骨架**，但目前只有 6 个具体 probe
  函数实现（SEC filings/companyfacts、yfinance basic/options、hkex filings、
  ftshare/tickflow/tushare_qfq/ifind_mcp 各一个），且**从不写库、不进 coverage_snapshot**
  ——是与 §一.4 质量门完全独立的第二套"健康"系统，两者互不感知。

### 1.7 缓存策略（`backend/data/cache_policy.py`）

- `FreshnessContract`（`cache_policy.py:22-28`）按 `data_type: str` 声明刷新频率/
  过期策略，**已经覆盖到 capital_flow / sector_or_industry 两个尚未实现的品类**
  （`cache_policy.py:88-108`）——这是全库里少数几处"提前为未来品类占位"设计合理的
  地方，扩品类时只需追加一个 `FreshnessContract` 元组项，成本极低。但契约是声明性的，
  真正的"零网络 intraday"强制只挂钩到 `intraday_zero_network_policy()` 里手写的
  几个 entrypoint 白名单（`cache_policy.py:149-160`），新品类的 fetcher 不会自动
  被这个策略管辖，需要手动加入白名单。

### 1.8 隐藏的"品类无关契约"蓝图（`backend/data/global_data.py`，易被忽略）

- `CANONICAL_SCHEMAS`（`global_data.py:55-80+`）为 quote/kline/fundamentals/
  capital_flow/... 每层声明了 `required_fields` + `pit_date_field` +
  `decision_visibility_rule`（例如 fundamentals 层写明
  `"disclosure_date must be known and <= decision date"`）。**这本质上就是本报告
  第二节要问的"统一 DataCategory 抽象"的雏形**——但全仓 grep 确认 `CANONICAL_SCHEMAS`
  只在 `global_data.py` 内被定义和展示，从未被 §一.1 的 provider 注册、§一.3 的 PIT
  拦截、或 §一.4 的质量门实际读取/强制执行。也就是说：**架构师此前已经想清楚了
  "品类应该长什么样"，但这份设计蓝图停在 M41 的只读展示层，没有被接回任何写路径。**
  这是本次审计里最值得注意的一点：不是"没想过通用化"，是"想过、写了契约、没接线"。

### 1.9 接线图（文字版）：数据类别 × 源 × 消费者

```
[行情 daily/index]
  源: akshare_sina/efinance/eastmoney/akshare_em/tushare_qfq/tickflow (CN)
      yfinance (HK/US)
  → providers.py fallback chain（唯一实产 provider 系统）
  → prices/index_prices 表 → PITSession(Price/IndexPrice)
  → technical.py / factors.py / qlib_data.py → signals 表（生产）

[基本面 financial_metrics]
  源: akshare_financial_abstract/indicator（唯二实调）；ifind_mcp.get_stock_financials
      只有 evidence_probe 元数据登记，从未调用（DATA_AUDIT_IFIND.md §④）
  → fundamentals.py 手写解析 → financial_metrics 表 → PITSession(FinancialMetric)
  → piotroski_analyst.py / jingqi_analyst.py（long_term 四子代理之二）

[新闻]
  源: Anspire(主) / Tavily(标题兜底) / eastmoney(直连) / ifind_mcp.search_news+search_notice
  → news_adapters/registry.py（唯一"品类内"已实现的多源适配器注册模式，
    NewsSourceAdapter Protocol + 工厂字典，按 settings.news_adapters_enabled 顺序实例化）
  → news 表 → PITSession(NewsItem，published_at)
  → sentiment.py（只读 title，24h 窗口，生产路径）
  → news_fusion.py/news_layer_v2.py（读 content，observe-only，M54 v2）

[资金流 M52/M54 fusion 通道]
  设计上应有: import backend.tools.m52_flow_floor（模块不存在，news_fusion.py:239-261
  静默吞异常返回 None）→ flow_score 恒为 None → FLOW_MISSING 100% 触发
  （已在 DATA_AUDIT_INTERNAL_USAGE.md §二.2、DATA_AUDIT_EXTERNAL.md §4.3 定位，
  是集成缺口不是架构缺口，但暴露的"静默吞异常无告警"模式是架构级风险，见二.④）

[QFII 十大流通股东]
  源: akshare.stock_gdfx_free_top_10_em
  → qfii_holdings.py → 独立表/逻辑 → qfii_flow_analyst.py（long_term 四子之一，
    与"资金流"字面同名但完全不同数据源/代码路径）

[市值/股本/融资余额快照 market_snapshots]
  源: eastmoney直连(RPTA_WEB_RZRQ_GGMX) → market_snapshots.py
  → market_features.py（MARKET_FEATURE_COLS 含 north_net_buy/large_order_net_inflow
    两列 100% NULL，fillna(0.0) 常数特征混入 qlib 训练矩阵，零告警）

[公告/研报/资金流(实时)/龙虎榜/股东户数/板块/海外股 —— 本次待接入的 7-8 类]
  能力目录(market_capabilities.py)已声明 capital_flow/derivatives/filings 三层，
  状态 observe_only/planned/not_connected，providers 字段大多是 "_candidate" 占位符
  外部源目录(external_sources.py)已登记 a_stock_data/ifind_mcp/tushare/hkexnews/
  sec_data_api 共 8 个候选源的 high_value_datasets 清单
  → 但 providers.py 没有对应的 fallback chain 数据结构，PIT 没有对应表，
    quality.py 没有对应覆盖率检查，agent/context.py 没有对应字段拼装
  → 目前 100% 停留在"文档/登记"阶段，DATA_AUDIT_IFIND/EXTERNAL 两份审计已逐源
    验证这些接口大多真实可用，只是零代码调用

[LLM 上下文组装]
  backend/agent/context.py::mingcang_stock_context（agent/context.py:203-285）
    手写拼接 Stock + latest_signal + open_position + LongTermLabel +
    decision_memory_layered + research_copilot + memory_context，六路查询手工 return dict
  backend/tools/m59_panel.py 另起一套手写字段拼接（面板自己的 header/buy_candidates/
    review_attribution，与 context.py 不共享代码）
  backend/analysis/sentiment.py 自己单独查 news 表拼 prompt（只用 title）
  backend/agents/long_term/*.py 四个子代理各自独立查询 financial_metrics/
    qfii_holdings/prices，无共享的"证据打包"函数
  → 结论：不存在统一 context builder，每个消费者各自手写查询+拼接逻辑
```

---

## 二、结构适配性判断

**总体判断：局部结构问题，非全面推倒重来——但"局部"恰好卡在最贵的四个位置
（provider 类型化、PIT 白名单粒度、质量门硬编码、上下文组装无复用），这四处不动，
"照葫芦画瓢"会把技术债线性放大 7-8 倍。**

### ① Schema：要几张新表？现有模式够不够通用

不够通用，且**不应该**强行套用 NewsItem/FinancialMetric 的"一品类一张宽表"模式到全部
新品类——这两个模型本身就是按各自语义手工设计的窄表（news 的 title/url/published_at，
financial_metrics 的 revenue/roe/... 逐字段列），对公告（发布主体+文号+全文+关联公司）、
龙虎榜（营业部买卖明细+净额）、股东（前十大股东名称+持股比例+变动方向）、板块成分
（成分股名单+加入/剔除日期）这些结构迥异的品类没有复用空间。现实预期：**7-8 个新品类
大概率需要 7-8 张新表**（或按"事实型 vs 名单型"合并为 2-3 个模式族），工作量在
"设计字段+写 ORM model+加 schema_runtime.py 补丁块"这条路径上是线性的，每张表约
半天到一天。真正的通用化机会不在"表"这一层，而在 §一.8 提到的 `CANONICAL_SCHEMAS`
契约——如果每张新表都被要求声明 `required_fields`/`pit_date_field`，后续三个门
（PIT/质量/探针）才有可能自动接线，否则又是 8 次手工重复。

### ② Provider 接口：fallback chain 是按"行情"设计的还是品类无关的

**按行情设计**（`providers.py:15-33` 的 `fetch: DailyFetcher`/`IndexFetcher` 类型别名
固定为 `(symbol, days) -> DataFrame`）。品类无关只体现在算法层面（排序/冷却/健康计数
可以照搬），数据结构和调用点是行情专用的。"照葫芦画瓢"是可行的——可以为每个新品类
复制一条 `_ANNOUNCEMENT_PROVIDERS`/`AnnouncementProvider`/`fetch_announcement_
with_fallback`，每条约 80-100 行，8 个品类 × 2-3 源 = 又一份约 700-800 行的重复代码,
且每条链要单独接入 `market_capabilities.py`/`quality.py`/probe 系统（因为那两处也是
手写的品类特判，见①③④）。中度重构方案（见三.B）就是把这条链改成
`_PROVIDERS: dict[str, list[Provider]]` keyed by `data_type`，一次性做完，后续每个新
品类只需 `register_provider(category="announcement", name=..., fetch=...)` 一行，
边际成本从"百行复制"降到"一行注册"。

### ③ PIT：新类别怎么保证 as-of 语义，现 point_in_time.py 能不能复用

部分复用。`_PIT_DATE_FIELDS` 字典结构（`point_in_time.py:35-42`）对"单一发布时点"
的品类（公告、研报、龙虎榜——都是"某天发生/披露"的事实记录）可以直接加一行复用
`datetime`/`string` kind；对"名单随时间漂移"的品类（板块成分、股东名单）PIT 语义
不是"记录时间 <= as_of"这么简单，而是"用 as_of 当天的名单版本"，需要类似
`universe_snapshot`（`backend/research/universe_guard.py:80-151`，已有先例：
按 cutoff_date 存快照+hash 去重）的独立快照表模式，不能套用 PITSession 的行级过滤。
公告/龙虎榜/资金流：低阻力（一行字典）。板块/股东名单：中阻力（需要仿
universe_guard 模式再实现一次"名单快照"，不是 PIT 拦截层能解决的）。

### ④ 静默降级问题：个别 bug 还是架构性缺陷

**架构性缺陷，不是个别 bug。** 证据：(a) `news_fusion.py:239-261` 的
`_default_flow_provider` 用 `except Exception: return None` 吞掉
`ModuleNotFoundError`（已知发现，架构层面看这是"任何环节 import 失败都会被这个模式
静默降级为 None 而非报警"的普遍写法）；(b) `quality.py` 的质量门检查是硬编码的 4
个计数器，市场能力目录声明的 capital_flow/derivatives/filings 三层完全没有对应检查
——**"声明了能力"和"检查这个能力是否真的在工作"之间没有强制关联**，这才是本次
owner 发现"接了工具只拉K线"能够长期不被察觉的根本原因：架构里不存在"每个已声明的
数据类别必须有一个健康信号，缺失即告警"这条规则，健康观测是 opt-in（需要有人手写
第 N 个 `_covered()`）而非 opt-out。(c) `market_features.py` 的零方差常数特征
（north_net_buy/large_order_net_inflow 恒为 0）混入 qlib 训练矩阵而无任何 flag——
和 (a)(b) 是同一类"缺失被 fillna/exception-swallow 抹平、不产生可观测信号"的模式，
在三个不同代码位置各自独立地重犯了一次。**这是需要在重构里当作一等公民修的架构问题，
不是修完这一个 bug 就完了。**

### ⑤ LLM 上下文组装：有没有统一 context builder

**没有。** `mingcang_stock_context`（`backend/agent/context.py:203-285`）、
`m59_panel.py` 面板拼接、`sentiment.py` 的 prompt 拼接、四个 long_term 子代理各自的
数据查询，是四套独立的手写字段拼装逻辑，互不共享代码也互不同步字段。新增 7-8 个
数据类别，如果每个类别都要出现在"研究上下文"里，意味着这四处每处都要手改一遍
（+ 未来任何新增的第五个消费者）——这是最容易随时间产生"某消费者忘记接入新字段"的
地方，也是当前"看起来充分利用了数据源，实际每个消费者只挑了自己知道的那一小撮字段"
问题（对应 owner"只拉K线"的直觉）的直接架构原因。

---

## 三、三个改造方案对比

| | A. 纯增量 | B. 中度重构 | C. 深度重构 |
|---|---|---|---|
| **做法** | 照现模式为每个新品类复制一套 provider chain + 新表 + 手写 PIT 字典项 + 手写 quality 检查 + 各消费者各自加字段 | 统一 `DataCategory` 抽象：一个 `_PROVIDERS: dict[str, list[Provider]]`（按 `data_type` 参数化）+ 每张新表声明 `CANONICAL_SCHEMAS` 式的 `required_fields`/`pit_date_field`，PIT/质量门/probe 三处改为"遍历已注册品类"的通用循环；消费端（context.py/m59_panel.py/四个子代理）逐步迁移到从这个统一层取数，允许新旧代码共存过渡 | 统一"数据合同"（provider+schema+PIT+质量+健康探针 五件套强制绑定注册）+ 一个真正的 context builder（消费者传入 `symbol, categories: list[str]` 即返回标准化证据包），下游全部改吃新接口，旧的手写查询代码删除 |
| **工作量量级**（codex 任务数） | 每品类 3-5 个任务 × 7-8 品类 ≈ **25-35 个任务**，且任务之间基本独立（可并行派发） | 重构核心四件套 ≈ **8-12 个任务**（一次性），之后每新增品类 1-2 个任务 × 7-8 品类 ≈ **8-16 个任务**，消费端迁移再 4-6 个任务（可分批），合计 **20-30 个任务**但有明显的先后依赖（核心必须先做完） | 五件套 + context builder 重构 ≈ **15-20 个任务**（高耦合，很难并行），下游全部改造（4+ 个消费者 × 逐个迁移 + 删除旧代码 + 重新验证生产信号无回归）≈ **15-25 个任务**，合计 **30-45 个任务**，且末期有"下游全切"这个高风险窗口 |
| **风险** | 低（每条链独立，出问题只影响一个品类，不碰现有生产代码）；但**制度性风险高**——8 遍复制容易 8 次重复同一个"静默降级无告警"反模式（见二④），治标不治本 | 中（核心重构改动 providers.py/point_in_time.py/quality.py 这几个被 5+ 处调用的模块，`providers.py` 的 blast radius 已知含 `market_capabilities.py`/`quality.py`/`m31_cache_benchmark.py` 三处调用方+两个测试文件，需要全部跑一遍回归）；迁移期新旧并存，可控 | 高（下游全部切换意味着 M54/M58/M59/long_term 四子代理/postmarket job 全部要改调用点，任何一处漏改都是生产信号静默用错数据源，正是当前问题的放大版；且"全部改吃新接口"和"保留主源+fallback"的 owner 要求之间需要非常谨慎的迁移期设计） |
| **对盘后操作的影响** | 无影响，可不停机；新品类上线前用 observe_only 挡住即可，符合现有"observe-only 先行"惯例 | 核心重构阶段建议在非交易时段做（涉及 providers.py 等被 postmarket job 直接调用的模块），但因为是内部重构+新增注册项，可以保持旧调用签名兼容（加 shim），事实上**可以不停机**，用 feature flag 灰度 | 下游迁移阶段无法完全避免至少一次"生产信号来源切换"的验证窗口，建议双写双读对比至少 20 个交易日（参照 M54 现有的 20-IC-day gate 惯例）才能下线旧路径，**不停机可行但迁移期显著拉长** |
| **与"主源+fallback保底"模式的兼容性** | 完全兼容（就是在复制这个模式） | 完全兼容且更强——统一注册表让"每个品类至少 1 主 1 备"这条规则可以在一个地方强制校验（例如启动时断言每个 production 状态的品类至少有 2 个 provider），而不是靠人记住 | 完全兼容，且五件套本身把"主源+fallback"作为数据合同的必填字段之一，是三案里对这条 owner 要求落实得最彻底的 |

**不拍板，但给一个工程直觉**：A 案在"品类数量少、赶时间"时合理，但 owner 这次要一次性
接 7-8 个品类，A 案会把当前已经存在的"静默降级/观测缺失"架构缺陷复制 7-8 遍，属于
"先把坑挖大再说"；C 案的"下游全切"窗口和"不停机盘后操作"的硬约束摩擦较大，且过度
设计的风险是五件套还没在真实新品类上跑通就要求全部消费者一起迁移。B 案的核心重构
范围可控（四个模块+ CANONICAL_SCHEMAS 落地），迁移是渐进式的（旧消费者可以继续用老
写法过渡），风险敞口最接近"必须解决的架构问题"和"不必要的推倒重来"之间的分界线。

---

## 四、测试基建：源体检 harness 设计

### 4.1 现有可复用件盘点

- `backend/data/external_sources.py::_probe_payload()`（`external_sources.py:376-400`）
  已经是一个**品类无关**的单次探针结果 shape：ok/provider/market/layer/symbol/
  latency_ms/sample_size/fields_present/error。**可直接复用，无需重新设计返回结构。**
- `summarize_probe_results()`（`external_sources.py:421-478`）已经做了"对照
  `CAPABILITY_LAYERS.required_fields` 算 missing_fields"这一步，**字段级覆盖率这一
  维度已经有现成实现**。
- `build_data_coverage_snapshot()`（`quality.py:116-181`）已有"回溯深度"的先例——
  `two_year_price_covered`（`quality.py:67`，>=480 行价格判定两年覆盖）这个模式可以
  直接改写成"回溯深度打分"的通用版本（阈值换成按品类配置）。
- `news_evidence.py::ContentStatus`（`Literal["full","excerpt","title_only"]`，
  `news_evidence.py:11`）已经是"正文完整率"分级的现成词汇表，可以直接搬到 harness
  的评分卡里作为标准分档，不必重新发明。
- **没有现成的**：PIT 判定的自动化探针（目前 PIT 验证是 `DATA_AUDIT_IFIND.md` 里人工
  逐条工具做的，见该文档 §③）、稳定性/时延的多次采样统计（现有 probe 都是单次调用，
  没有"跑 N 次算成功率/P50/P99 延迟"的封装）、覆盖率的"多少支股票 × 多少天"矩阵式
  统计（quality.py 只对已入库品类做简单计数，没有对候选新源做过这个）。

### 4.2 建议的 harness 形状（不写代码，只给设计）

```
输入: (source_id, category, symbol_sample: list[str], lookback_days: int)

跑法（复用 _probe_payload 的单次探针函数作为最内层调用，harness 是外层编排）：
  1. 覆盖率  — 对 symbol_sample 逐个调用源，记录成功/失败比例
  2. 回溯深度 — 请求 lookback_days 窗口，记录实际返回的最早日期距今天数
               （复用 quality.py 的 two_year_price_covered 阈值判定模式）
  3. 正文完整率 — 若品类含文本字段，按 ContentStatus 三档（full/excerpt/title_only）
               统计比例（复用 news_evidence.py 的分档定义）
  4. 时延 — 对 symbol_sample 采样 N=10-20 次调用，记录 P50/P95（_probe_payload 已有
           单次 latency_ms，harness 只需循环采样再聚合，不需要重新设计字段）
  5. 稳定性 — 覆盖率跑法中天然产生的成功/失败序列，计算连续失败次数与总失败率
  6. PIT 判定 — 人工/半自动核对：对同一 symbol 分别用"当前 as_of"和"若干天前 as_of"
              查询，比对返回值是否随 as_of 变化（复用 point_in_time.py 的
              assert_pit_clean 思路，但反过来验证候选源而非验证内部 DB）

输出: 标准化评分卡（每个 source × category 一行）
  {source_id, category, coverage_pct, lookback_days_actual, content_full_pct,
   latency_p50_ms, latency_p95_ms, stability_score(0-1), pit_verdict(clean/risky/
   unverified), sample_size, checked_at}
```

这套 harness 建议直接挂在 `external_sources.py` 现有的 probe 体系之下作为"批量+多次
采样"的外层封装，而不是另起一套——现有 `_probe_payload`/`summarize_probe_results`
已经解决了"单次结果长什么样"和"字段级覆盖率怎么算"两个子问题，harness 真正要新增的
只是"多 symbol 循环"、"多次采样测时延/稳定性"、"PIT 双 as_of 对比"三段逻辑，工作量
预计 2-3 个 codex 任务（不含把结果落到某张评分卡表——如果 owner 要求持久化历史评分，
需要再加一张新表，属于常规 schema 任务）。

---

## 附：本次审计方法说明

代码层证据均标注文件路径+行号，来自直接 Read 源文件与 codegraph 结构化查询交叉验证，
未使用 grep 片段推断结论；`CANONICAL_SCHEMAS` 未被消费的结论经全仓 grep 确认零匹配。
未运行任何写操作、未修改任何代码、未提交任何 commit。
