# 数据消费端内部审计（2026-07-04）

只读审计。范围：数据库实际存储 vs 打分/信号/标签/回测/面板代码实际消费。
不改代码、不提交。数据库快照来自 `<repo>/mingcang.db`，审计时刻 2026-07-04。

---

## 一、数据库盘点

40 张表。行数快照：

| 表 | 行数 | 备注 |
|---|---:|---|
| prices | 924,191 | 732 symbol，2018-11-30~2026-07-03 |
| news | 11,358 | 117 symbol，2025-12-30~2026-07-03（仅约6个月窗口，非全历史） |
| financial_metrics | 2,398 | 120 symbol，2019-12-31~2026-03-31 |
| m54_oos_score_cache | 19,357 | 113 symbol，2026-04-01~2026-07-03 |
| market_snapshots | 49,915 | 88 symbol，2024-01-02~2026-05-18 |
| signals | 1,387 | 117 symbol，2026-05-12起 |
| long_term_labels | 239 | 118 symbol，2026-05-15起 |
| decision_runs | 1,949 | |
| llm_usage_log | 20,545 | |
| stock_memory_items | 1,220 | |
| sentiment_cache | 7,278 | |
| audit_log_fts* | 7,501 | FTS 索引表 |
| decision_memory_layered | 117 | |
| research_states | 117 | |
| index_prices | 380 | 仅2条曲线：sh000300(280)/sh000905(100)，且只有 close，无OHLC |
| stocks | 732 | active=147 / inactive=585 |
| positions | 5 | closed=4 / open=1 |
| review_cases/review_runs | 2 / 3 | |
| chat_sessions/chat_messages | 2 / 2 | |
| ai_memory | 8 | |
| memory_atoms | 3 | |
| memory_promotion_candidates | 1 | |
| forward_theses | 2 | |

**基本空表（0行，结构性未启用）**：`gate_b_observations`、`memory_profiles`、`memory_scenarios`、
`pending_ai_actions`、`theme_hypotheses`、`theme_records`、`thesis_confidence_entries`、
`thesis_records`、`universe_snapshots`。共9张表完全没有数据——对应的功能模块（主题假设、
论文记录、宇宙快照、待办AI动作等）在当前跑法下从未产生过一行数据。

### financial_metrics 覆盖细节（关键）

- 覆盖 120/732 全部股票（16%），但覆盖当前 active 池 115/147（78%），
  覆盖当前 long_term_labels 使用的 118 支中的 113 支（96%）——**比 LEADER.md
  "financial 10/70" 的印象好得多**，这条旧记录看起来是更早期/更小宇宙时的快照，
  已经过时（见五、测试影响评估）。
- 但**字段级覆盖薄**（2,398行内的NULL率）：
  - `shares_outstanding`：**100% NULL**（2398/2398，全表无一行有值）
  - `long_term_debt`：51.2% NULL
  - `current_ratio`：39.3% NULL
  - `operating_cf`：38.5% NULL
  - `total_assets`/`total_equity`/`roe`/`asset_turnover`：35.4-35.6% NULL
  - `revenue`/`net_profit`/`gross_margin`：<1% NULL（这几个字段质量好）
- 根因见 `backend/data/fundamentals.py:239`：`"shares_outstanding": None,  # 该接口不含，留空`——
  akshare `stock_financial_analysis_indicator` 接口本身不提供股本数据，代码从未尝试从别的接口补，
  这是**采集侧从未接入**，不是"入库了但没用"。

### market_snapshots 覆盖细节（关键）

- `north_net_buy`：**100% NULL**（0/49,915）
- `large_order_net_inflow`：**100% NULL**（0/49,915）
- `margin_balance`/`market_cap`/`float_market_cap`/`shares_outstanding`：99.8% 有值（49,827/49,915）
- 根因在代码注释里写得很明白（`backend/data/market_snapshots.py:11-13`）：
  - north_net_buy："个股口径在 2024-08 后政策变更不再公开，写 NULL"（数据源被监管下架，非我方bug）
  - large_order_net_inflow："fflow daykline 端点在 Clash TUN 环境下返回空体"（本机网络环境问题，
    技术上可能是能修的）
- 这两列是**主动决定不抓**，代码里留着字段和管道只是为了 schema 兼容，不是"漏抓"。

### news 表字段级覆盖

- `content`：26%（2958/11358）为空，74% 有正文
- `summary`：**100% NULL**（11358/11358，字段从未被写入）
- `sentiment_score`：**100% NULL**（11358/11358，字段从未被写入）

---

## 二、消费端映射（数据 → 决策 真实依赖图）

### 2.1 技术/动量打分（`backend/analysis/technical.py`）

- 输入字段：`close`（trend/rsi/macd）、`volume`（score_volume，`backend/analysis/technical.py:85-94`，
  近5日均量/近20日均量比较）、`atr14`（止损止盈计算，非技术分本身）。
- **volume 确实被用了**（不是"入库未用"）：`score_volume()` 直接读 `df["volume"]`，
  放量确认 trend 方向。
- `adx14` 用于震荡市过滤（`adx_filter_factor`，`technical.py:43-59`）。
- prices 表没有"amount"（成交额）字段，故该维度天然不存在，非遗漏。
- `backend/analysis/alpha_factors.py:40-56` 另有一路用 volume 算
  `price_volume_divergence`（量价背离因子），供 qlib 模型使用。

### 2.2 M54 新闻打分

- 生产信号路径（`backend/jobs/postmarket.py:124-152` → `_postmarket_news_sentiment` →
  `backend/analysis/sentiment.py:analyze_news`）**只消费 `news.title`**（近24小时窗口，
  `get_recent_news_items(..., hours=24)`），不读 `content`/`summary`/`sentiment_score`/`source`。
  prompt 只拼标题列表（`sentiment.py:181-182`）。
- M54 v2观察层路径（`backend/data/news_layer_v2.py`、`backend/data/news_extraction.py`）
  **会用 content**：`news_extraction.py:370-372` 优先用 `member.content`（若
  `content_status=="full"`），否则退化为 `score_cluster_title_only`
  （`news_extraction.py:226-264`）。这条路径是 observe-only，不进生产 `signals` 表。
- **flow_score 数据源为何 FLOW_MISSING（本次审计最严重发现）**：
  - `backend/data/news_fusion.py:239-261` `_default_flow_provider()` 尝试
    `import_module("backend.tools.m52_flow_floor")`
  - **该模块在代码库中根本不存在**（`find` 全库搜索无匹配，`CHANGELOG.md` 无记录）。
    只有 `.git/refs/heads/archive/local/codex/m52-news-sentiment-on-m51` 这个已归档分支名提示
    M52 milestone 存在过，但对应的 `m52_flow_floor.py` 实现从未合入 main 或已被删除。
  - 结果：`import_module` 每次都抛异常，被 `except Exception: return None` 吞掉
    （`news_fusion.py:242-243`），`flow_score` **永远是 None**。
  - 数据库验证：`m54_oos_score_cache.flow_score` **19,357/19,357 行全部 NULL（100%）**，
    `FLOW_MISSING` 标志出现在 51.8%（10,035/19,357）的行里（其余行是
    `PYRAMID_NOT_TRIGGERED`，根本没跑到 fuse_signal，不打这个特定flag，但 flow_score
    同样是 None）。
  - 这不是"数据没采到"，是**整条独立信号通路的代码入口从一开始就没接上**——
    `NEWS_CHANNEL_WEIGHT=1.0` 和 `FLOW_CHANNEL_WEIGHT=1.0` 在设计上是平权的两条腿
    （`news_fusion.py:22-24`），现实中 news 一条腿在跑，flow 一条腿从未跑过一次。
  - 注意：这个 "flow" 和长期标签团的 "flow"（qfii_flow_analyst，见下）是**两个完全不同的东西**——
    M54 的 flow 指的是 M52 规划中的"资金流"独立通道（本应类似 north_net_buy/大单净流入一类实时资金流），
    qfii_flow_analyst 指的是季度QFII十大股东持仓变化。两者都缺数据，但缺的是不同的数据、不同的代码路径。

### 2.3 长期标签四子代理（`backend/agents/long_term/`）

聚合逻辑在 `team.py`，四路：`track`（赛道，LLM）、`quality`（Piotroski，算法）、
`boom`（jingqi景气，算法）、`flow`（QFII外资流向，算法）。

- **track_analyst.py**：消费 `Stock.industry` + `prices`（近30/90/180日涨幅，`_compute_price_moves`,
  `track_analyst.py:126-150`）+ Tavily 检索（供应链/海外关键词，需 `tavily_api_key`）。LLM 主导。
  `runtime_readiness` 不可用时兜底 `score=0, confidence=0, label_vote="观望"`
  （`track_analyst.py:231-238`）。
- **piotroski_analyst.py（quality）**：消费 `financial_metrics` 全部数值字段算9因子F-Score
  （`backend/data/fundamentals.py:342-418`）。
  - `compute_piotroski_factors` 要求同symbol至少2期记录，否则 `available=False`
    （`fundamentals.py:359-362`），返回 `score=0, confidence=0, label_vote="观望"`
    （`piotroski_analyst.py:83-89`），key_findings写"财务数据不足"。
  - 数据库中显式带这句话的label只有18/239（7.5%）——因为多数symbol确实有≥2期数据，
    这一支路径触发不算频繁。
  - **但更隐蔽的降级在因子级**：`shares_outstanding` 100% NULL ⇒ `no_new_shares`
    因子（`fundamentals.py:394-396`）**对所有股票、所有周期永远算 False**——不是"防摊薄未通过"，
    是这项检测从未真正跑起来过。9个因子里白白扣1个，systematically 拉低每支股票的F-Score
    （F-Score中位数由4.5变成事实上略低的基准，`piotroski_analyst.py:56`
    `_score_to_signal_score` 假设中位数4.5对称，但一个因子结构性锁死在False打破了这个假设）。
    `long_term_debt`/`current_ratio`/`operating_cf` 也有35-51%的期次是 None，
    对应因子在这些周期同样静默判 False（而非"数据缺失、不计入"）。
  - 这与项目既有记忆 `feedback_piotroski_bias.md`（"Piotroski对电力/扩张期成长股系统性偏严"）
    可能是**同一现象的另一半解释**：不只是方法论对成长股天然严格，还有一个数据层面的、
    对所有股票一视同仁的隐藏扣分项。
- **jingqi_analyst.py（boom）**：消费 `financial_metrics` 的 `net_profit_yoy`/`revenue_yoy`/`roe`
  算Δ类指标 + 同行业分位（`fundamentals.py:423-520`）。`compute_jingqi_deltas` 同样要求
  ≥2期数据，否则 `available=False` → `score=0, confidence=0, label_vote="观望"`
  （`jingqi_analyst.py:135-141`，key_findings写"财报数据不足"）。
  `list_peers`（`fundamentals.py:609-618`）只在**自选股池内**找同行业股票——
  由于当前 active 池仅147支，很多行业可能凑不齐peers，会静默走`_score_no_peers`
  阈值兜底分支（代码注释自己承认"首批只有10只股，多数行业可能没有peers"，
  `jingqi_analyst.py:20`——现在池子扩到147支，这条注释可能已过时但兜底逻辑还在）。
- **qfii_flow_analyst.py（flow）**：消费 `backend.data.qfii_holdings.get_qfii_history`
  （十大流通股东季度数据），**与市场资金流数据（market_snapshots/M52）完全无关**。
  只做"反向规避"单向判断：无QFII持仓记录 → `confidence=0, label_vote="观望"`
  （`qfii_flow_analyst.py:133-142`）；有持仓但未触发减仓阈值 → 同样 `confidence=0`
  （`qfii_flow_analyst.py:161-168`）。`confidence=0` 的报告在 `team.py:46`
  的 `_aggregate_score` 里被直接跳过（不参与加权），设计上就是"多数时候不投票，
  只在触发时一票否决式扣分"，这是有意为之的设计（模块docstring写明），不算降级bug。
- **聚合与质量门（team.py）**：`_assess_label_quality`（`team.py:96-122`）——
  若 `track` 的 `confidence<0.01` → 整体标签质量直接判 `degraded`（无论quality/boom
  是否给出了有效分数），因为 `track` 被视为强制项（`settings.long_term_track_enabled`）。
  数据库里 `quality` 投票分布：观望86 / 规避142 / 值得持有11（共239条），
  "规避"占59.4%——需要注意这里的"规避"来自四路投票**任一路投规避即一票否决**
  （`team.py:59-60`），不能简单归因于quality单路。

### 2.4 M59 面板（`backend/tools/m59_panel.py`）

面板自身在 `_build_header` 里显式声明了降级 flag（代码写死，不是我推断）：

```
degradation_flags = [
    "llm_layer:not_implemented",       # 买入候选/复盘归因的LLM裁量层从未接入
    "quant_model:placeholder_v0",       # 量化模型仍是占位版
    "market_regime:missing_index_ohlc", # index_prices只有close，无open/high/low
]
```

- `market_regime`：`value=None`，因为 `backend.analysis.timing.regime` 需要指数OHLC，
  而 `index_prices` 表只有 `close`/`change_pct`（数据库验证：380行，仅
  sh000300/sh000905两条曲线，无open/high/low/volume列）。面板转而用一个
  "池等权MA regime"兜底（`_market_regime`，`m59_panel.py:420-444`），
  并在动量末档旁边加注："2026-07-03网格证伪：动量末档在下行市反向，不能当避雷器用"。
- `buy_candidates`：每条都带 `llm_discretion: None, llm_layer: "not_implemented"`——
  LLM裁量层是空位，只展示规则信号本身。
- `review_attribution`：同样 `llm_layer: "not_implemented"`。
- `watchtower_followups`/`watchtower_confirm`（M60 Phase 1/2）：读取
  `/private/tmp/m60_watchtower_*.json`/`m60_confirm_*.json`，**审计时刻这两个文件确实存在**
  （2026-07-03当天生成），说明这条线目前有在跑，不是纯占位；但面板本身承认这是
  "只读最近一次扫描结果，从不自己触发扫描"（docstring原话）。
- `research_reference`（买入候选/持仓体检里的"研究参考"）：只读 `long_term_labels` +
  `stock_memory_items(memory_type='research_pointer')`，明确注释
  "never scored (owner 2026-07-03 软联动裁决)"——即长期标签和研究记忆**只做展示，
  不参与打分/排序**，这是产品侧的既定裁决，不是bug。

### 2.5 M58 网格回测（`backend/tools/m58_grid_backtest.py`）

- 输入**只有 `prices` 表**：调用 `backend.analysis.factors.add_all_factors` +
  `backend.analysis.technical` 的 `score_trend`/`score_rsi`/`score_macd`/`score_volume`
  （`m58_grid_backtest.py:24-31`）。
- 模块docstring自陈："Exit and LGBM walk-forward channels are left for later phases"——
  当前默认网格只测T（趋势类）/M（动量类）价格因子组合，**financial_metrics、news、
  long_term_labels 完全不参与这条回测**。
- `m59_panel.py` 复用了 `m58_grid_backtest.regime_from_pool_equal_weight`
  做池等权regime判断（前面提到）。

---

## 三、"入库未用"清单

| # | 字段/表 | 入库情况 | 消费情况 | 备注 |
|---|---|---|---|---|
| 1 | `market_snapshots.north_net_buy` | 100% NULL（结构性未抓，非"入库未用"，是"从未入库"） | `market_features.py` 声明为特征列，`fillna(0.0)` | 见下方专项分析 |
| 2 | `market_snapshots.large_order_net_inflow` | 同上，100% NULL | 同上 | 见下方专项分析 |
| 3 | `news.summary` | 100% NULL，从未写入 | 无（字段存在但生产/M54代码都不写它） | 纯 schema 遗留 |
| 4 | `news.sentiment_score` | 100% NULL，从未写入 | 无 | 实际情感分存在 `sentiment_cache` 表，这个列是重复设计但空转 |
| 5 | `news.content`（26%为空的部分） | 74%有内容 | 生产信号路径（postmarket.py）**完全不读这个字段**，只有 M54 v2 observe-only 路径读 | 生产信号只用标题，正文26%缺失+74%可用但未被用 |
| 6 | `financial_metrics.shares_outstanding` | 100% NULL | Piotroski `no_new_shares` 因子引用它，但因为永远None，因子永远False | 见"逻辑饥饿"#2 |
| 7 | 9张0行表（theme_records/thesis_records/universe_snapshots等） | 完全空 | 无对应生产代码路径写入/读出 | 功能休眠，非本次审计重点 |

### 专项：north_net_buy / large_order_net_inflow 的"特征矩阵零方差"问题

这两列虽然被文档明确标注"主动不抓"，但它们**没有从消费端摘除**：

- `backend/data/market_features.py:8-14` 的 `MARKET_FEATURE_COLS` 仍然包含这两列；
- `attach_market_features()` 被 `backend/data/qlib_data.py:195,248` 调用，
  而 `qlib_data` 被 `backend/analysis/qlib_engine.py` 用于训练/打分（`qlib_score`），
  这条路径被 `backend/jobs/postmarket.py:183` 在生产链路里调用（`quant_score` 的来源之一）；
- `attach_market_features` 对缺失列做 `fillna(0.0)`（`market_features.py:58行区域`）——
  也就是说，**quant 模型的特征矩阵里，这两列每一行永远是常数0**。
- 影响：对LGBM/qlib这类树模型，零方差特征通常会被自动跳过分裂，***大概率无害***，
  但仍然是"看起来在用真实资金流特征、实际上在喂两列常数"的静默失真，
  且没有任何日志/flag 提示"这两个特征其实是死的"——不像 news_fusion 那样至少留了
  `FLOW_MISSING` 标志。这是本次审计里**唯一一处"完全没有降级信号、纯粹静默"的数据缺口**。

---

## 四、"逻辑饥饿"清单（决策逻辑因数据缺失静默/半静默降级）

| # | 位置 | 触发条件 | 降级行为 | 严重度 |
|---|---|---|---|---|
| 1 | `backend/data/news_fusion.py:239-261`（`_default_flow_provider`） | `backend.tools.m52_flow_floor` 模块不存在，import恒定失败 | `flow_score=None` 永久；触发时打 `FLOW_MISSING` 标志，confidence 乘 `FLOW_MISSING_CONFIDENCE_MULTIPLIER=0.75`（`news_fusion.py:129-131`） | **最高**——整条设计中平权的信号通道100%从未运行过，M54 news综合分事实上只用了news一条腿 |
| 2 | `backend/data/fundamentals.py:394-396`（Piotroski `no_new_shares`因子） | `shares_outstanding` 100% NULL | 因子永远判 False，隐蔽拉低所有股票F-Score，且不产生任何"数据不足"标志（不像 available=False 那种显式降级） | **高**——无声、无flag、影响全量股票和全部历史 |
| 3 | `backend/agents/long_term/piotroski_analyst.py:83-89`、`jingqi_analyst.py:135-141` | 同symbol financial_metrics记录<2期 | `score=0, confidence=0, label_vote="观望"`，该路在team.py聚合时被跳过不参与加权 | 中——数据库验证目前仅18/239（7.5%）触发，但对新纳入自选股或次新股会持续触发 |
| 4 | `backend/agents/long_term/track_analyst.py:231-238` | `runtime_readiness(settings)["usable"]==False`（LLM不可用/超预算） | `score=0, confidence=0, label_vote="观望"`；因 `track` 被设为强制项，`team.py:104-112` 会把整体标签质量打成 `failed` 或 `degraded` | 中——依赖LLM可用性和预算，非数据问题但同样是"静默拉回中性" |
| 5 | `backend/tools/m59_panel.py:241-256`（header） | `index_prices` 无OHLC | `market_regime.value=None`，改用池等权MA兜底（面板自己承认是fallback） | 中——面板层面已显式暴露这个flag，不算"静默" |
| 6 | `backend/tools/m58_grid_backtest.py`（docstring自陈） | Exit/LGBM walk-forward "left for later phases" | 当前网格回测只覆盖价格因子T/M家族，financial/news/long_term_labels完全不参与验证 | 中——不是bug，是范围声明，但意味着"综合信号"从未被这条回测真正验证过 |
| 7 | `backend/agents/long_term/jingqi_analyst.py:20,34-53`（`_score_no_peers`） | 同行业在147支active池内凑不到peers | 退化为Δ绝对值阈值兜底评分，不做行业分位 | 低-中——注释写于池子更小的时期，实际触发率未在本次审计中量化 |
| 8 | `backend/analysis/sentiment.py` + `backend/jobs/postmarket.py:134`（`hours=24`窗口） | 无论news表实际覆盖多长，生产情感分只看近24小时标题 | 更早、可能更重要的新闻（哪怕still-relevant）不进当天情感分 | 低-中——设计选择而非数据缺陷，但和"新闻层信息不够全"的owner担忧直接相关 |

---

## 五、测试影响评估（不下结论，逐项列影响面）

1. **M54 flow_score 从未有值（发现#1）对"新闻层弱"结论的影响**：
   若过去所有关于"M54新闻综合分区分度不够/IC不显著"的判定，都是在
   `flow_score` 恒为None、综合分100%单腿（news-only）的条件下做出的，
   那么"新闻层信息不够全"这个结论本身可能需要重新框定为
   ——"新闻+资金流双通道融合从未被真正验证过，因为资金流通道从未运行"，
   而不是"新闻通道本身弱"。这两者是不同的证伪对象。如果`m52_flow_floor`
   被实现并接入，`m54_oos_score_cache`里当前19,357条历史缓存记录的`composite`
   分数会整体改变（`news_fusion.py:143-153`的融合公式在flow_score有值和无值时
   走完全不同分支），现有的IC/OOS判定（含 `M54_OOS_PREREGISTER.md` 的
   20-IC-day gate 进度）建立在一个从未有真实flow数据的样本上，
   这批历史判定的外部有效性需要重新评估。

2. **Piotroski `shares_outstanding` 结构性缺失（发现#2）对长期标签区分度的影响**：
   如果 `no_new_shares` 因子对**所有**股票、所有周期都恒为False，那么Piotroski
   9因子实际上是"8+1"——这个隐藏的-1分对所有股票一视同仁，理论上不改变股票间的
   **相对排序**（因为大家都被同等扣分），但会系统性压低整体F-Score分布，
   使更多股票落入`piotroski_weak_threshold`以下从而投"规避"票。这可能是
   `long_term_labels`里"规避"占比高（142/239=59.4%，含其他路一票否决）的
   影响因素之一，具体量级需要拿到真实shares_outstanding数据重跑9因子后对比
   才能量化，本次审计只能确认"存在系统性单向偏置"这一事实，不能给出偏置的
   分数量级。

3. **financial_metrics覆盖率"10/70"记忆条目已过时（发现见一）**：
   若之前基于"仅10/70覆盖"的假设做过关于"长期标签因数据太薄不可信"的判定，
   现在实际覆盖是115/147（active池）或113/118（当前labels使用的池），
   数据可得性已大幅改善，但**因子级空洞**（shares_outstanding/long_term_debt/
   current_ratio/operating_cf的35-51%缺失率）意味着"覆盖率高≠字段完整"，
   旧结论里"基本面覆盖薄"这句判断需要拆成两半重新评估：
   symbol覆盖广度（已改善）vs 单symbol内字段完整度（仍然薄）。

4. **市场级regime判定长期使用index_prices的close-only兜底**：
   若过去有基于"regime过滤/衰减"的回测结论（`backend.analysis.timing.regime`、
   `apply_regime_filter`），这些结论建立在指数OHLC实际上从未真正提供的前提下——
   需要确认这些回测当时用的是什么regime数据源（真实OHLC via akshare临时抓取？
   还是同样的close-only降级？）如果历史回测和当前生产环境用的是不同质量的
   regime输入，两者的可比性存疑。

5. **M58网格回测"仅价格因子"范围声明对"综合信号有效性"结论的影响**：
   如果owner或既往复盘曾把M58网格回测的结论泛化为"整个信号系统在震荡市/下行市
   的表现"，需要注意M58本身从未纳入financial/news/long_term_labels，
   该回测证伪的只是纯价格动量/趋势规则族（"2026-07-03网格证伪:动量末档...不能当避雷器用"
   这条注记本身范围就是价格因子层面），不能直接外推到综合信号（quant+technical+sentiment
   加权后的composite_score）在同样市况下的表现。

6. **market_snapshots两列零方差特征混入quant模型（发现见三"专项"）**：
   若quant_score（qlib_engine训练产出）过去被认为"包含了资金流信息"，实际上
   north_net_buy/large_order_net_inflow这两列一直是常数0，模型从未真正见过资金流信号。
   这本身大概率对模型精度无实质影响（零方差特征通常被树模型忽略），
   但如果曾经有过"资金流因子的特征重要性/消融实验"之类的分析并从中得出过结论，
   那些结论需要确认当时是否被这两列常数污染了输入矩阵。

---

## 附：本次审计方法说明

- 数据库统计通过只读 `sqlite3` 连接对 `mingcang.db` 直接查询得出（行数、NULL率、
  min/max日期、distinct symbol计数），所有数字均可复现。
- 代码层证据均标注文件路径+行号，来自直接 Read 源文件，未使用 grep 片段推断结论。
- 未运行任何写操作、未修改任何代码、未提交任何commit。
