# 数据需求侧审计：消费端模块的"数据饥饿"深查（2026-07-04）

只读审计。与三份供给侧审计（`DATA_AUDIT_IFIND.md` / `DATA_AUDIT_EXTERNAL.md` /
`DATA_AUDIT_INTERNAL_USAGE.md`）互补：供给侧回答"我们有什么数据、漏了什么数据"，
本文回答"每个决策/研究模块**设计上想用什么信息 vs 实际收到什么信息**"，粒度打到
prompt 槽位/评分因子级。不改代码、不提交、不写库。

数据库快照 `mingcang.db`（2026-07-04，只读连接）；QFII 缓存 `~/.mingcang/qfii_cache/`
（文件系统直查）；所有断言带 file:line 或 SQL/文件系统查询结果。

**图例**（用于各节与末尾矩阵）：
- **●有**：真实数据流入且被该模块实际消费
- **◐空转**：模块/schema 设计了槽位或字段，但值恒为 None/常量/占位，或库里有数据但该模块不读
- **○无槽位**：该模块的输入设计里根本没有这类信息（不是没填值，是从未规划）

---

## 1. 单股研究 / copilot（backend/agent/ + backend/research/copilot.py）

**决策职责**：owner 做一支股票研究时的第一入口（`stock-context` CLI +
copilot 影子结论），AGENTS.md 规定单股研究必须报告 copilot 双轨结论。

**设计输入**：copilot prompt（`_build_prompt`，`backend/research/copilot.py:231-256`）
的 payload 原文只设计了 **3 类槽位**：

```python
payload = {
    "official_signal": official,
    "recent_news": news,
    "long_term_label": long_term,
    "shadow_rules": {...},
}
```

加提示语"请基于以下本地证据生成精简副驾驶卡"。System prompt（`copilot.py:23-26`）：
"你是 MingCang 的 A 股研究副驾驶。你只输出影子研究意见……"

**实际输入**（逐槽位核查）：

| 槽位 | 实际填值 | 判定 |
|---|---|---|
| `official_signal` | Signal 表当日行 + DecisionRun 反解析（`copilot.py:87-120,162-202`），quant/technical/sentiment 分、止损止盈、risk_notes 全真实 | ●有 |
| `recent_news` | **只取 `title/source/published_at` 三字段**（`copilot.py:132-138`）。`NewsItem.summary/content/sentiment_score` 三个字段在 copilot/deep_research/dossier/context 整条链路一次都没被读过（grep 全文确认） | ◐空转（库里 74% 新闻有正文，模块只读标题） |
| `long_term_label` | LongTermLabel 表真实行（`copilot.py:142-159`），但其可信度受第 2 节的四子代理饥饿传导（trusted 仅 37.2%） | ●有（上游打折） |
| 公告 / 研报 / 股东变化 / 龙虎榜 / 日度资金流 / 同行业对比 / 事件时间线 | payload 里**没有这些 key**，模板设计阶段就未纳入 | ○无槽位 ×7 类 |

**另一处槽位空转（schema 级）**：`ResearchState.thesis/risks/open_questions` 三字段
自建行起就是常量 `""`/`"[]"`（`copilot.py:266-267`、`backend/decision/harness.py:246-247,401`），
全仓库无任何函数二次写入；真实被更新的只有 `last_signal_summary/last_review_json`
（`harness.py:251,403`）。`dossier.py:171` 把这些恒空字段原样吐给下游。

**饥饿差距**：owner 拿到的"单股研究结论"实际建立在：官方信号（技术+情感加权分）
+ 近期新闻**裸标题** + 一条可信度 37.2% 的长期标签。财务数据（`FinancialMetric`）
在整条单股 copilot 路径全文零引用。

**补齐各类数据会解锁什么**：
- **公告全文**：copilot 能核对"标题传闻 vs 公司口径"，影子结论的 risks 槽位可以基于
  真实风险披露而非新闻标题推断；`ResearchState.risks` 才有可能被真实填值。
- **研报/一致预期**：payload 可加"预期兑现度/估值分位"槽位（iFinD `get_stock_financials`
  探针已验证一致预期可取，见 DATA_AUDIT_IFIND.md ②-2），让"贵不贵"从 LLM 内生知识变成数据判断。
- **股东变化**：`long_term_label.key_findings` 里 QFII 结论目前是自然语言间接带出，可升级为结构化槽位。
- **事件（解禁/定增/回购/问询）**：影子结论可提示"未来 30 天解禁冲击"这类当前完全盲区的信息。
- **资金流/龙虎榜**：`recent_news` 旁边可并列"资金面"槽位，验证消息与钱是否同向。

---

## 2. 长期标签四子代理（backend/agents/long_term/）

**决策职责**：产出"值得持有/观望/估值偏高/规避"长期标签，约束交易措辞
（标签缺失时不允许强于 buy/watch 级建议，AGENTS.md）。聚合权重
track 0.3 / quality 0.3 / boom 0.4 / flow 0.1（`team.py:36-41`，config 实测），
任一路投"规避"即一票否决（`team.py:59-60`）。

**数据库总貌**（239 条标签，118 symbol，2026-05-15 起）：
`quality` 整体分布 degraded 136 / failed 14 / **trusted 89（37.2%）**；
最终 label：规避 153（64.0%）/ 观望 56 / 估值偏高 21 / 值得持有 9。

### 2.1 track（赛道，唯一 LLM 主导）— 双层饥饿最严重

**设计输入（rubric）**：实际加载的 system prompt 是
`.pi/skills/track-analyst/SKILL.md`（14713 字节，`track_analyst.py:108-123`
按优先级加载，本机第一优先级命中）。它要求五层框架逐层给证据：
第一层供应链（**锁单/排产周期、原材料涨价幅度、交期变化——要求具体数字**）、
第二层海外领先指标（**海外龙头 backlog、扩产锁单**）、第三层周期 vs 结构性、
第四层炒作过滤、第五层高位过滤（6 个月涨幅>50%、PE 消化、一致预期拥挤度）。

**实际输入**：`_build_prompt`（`track_analyst.py:178-212`）原文只有三类插槽：

```python
f"代码：{symbol}\n名称：{name}\n{industry_txt}{move_txt}{evidence_txt}\n\n"
f"输出 JSON 必须含 layer1-5 + score(-100~+100) + label_vote + key_findings(≤3条)。"
```

| 插槽 | 实际内容 | 判定 |
|---|---|---|
| `industry_txt` | `Stock.industry` 静态快照，缺失时让 LLM"基于公司名推断" | ●有（无边际信息） |
| `move_txt` | prices 表近 30/90/180 日涨幅（`track_analyst.py:126-150`） | ●有（唯一量化输入，纯价格） |
| `evidence_txt` | 最多 **8 条 Tavily 裸标题**（`track_analyst.py:199-201`），无正文/来源/时间戳 | ◐空转（见下） |
| 锁单/交期/涨价数字、海外 backlog、一致预期、财务趋势 | **无对应数据字段**——SKILL.md 要求的核心证据全靠 LLM 内生知识自由发挥 | ○无槽位 |

**evidence 通道还有一个参数语义错位**：`track_analyst.py:170` 把自己构造的检索
query 当作 `symbol` 参数传给 `fetch_titles_tavily(symbol, name, ...)`
（`backend/data/news.py:514`），实发 query 被二次包装为
`f"{name} {q} 股票 最新消息"`（`news.py:519`），第二条 query 的 `name` 被拼两次，
检索意图被稀释（未完全失效，但"供应链证据检索"实际发出去的是泛化的个股新闻检索）。

**LLM 可用性叠加**：`long_term_labels` 里 key_findings 精确等于
"LLM 调用失败，默认观望"的行 **123/239（51.5%）**，且非历史遗留——2026-07-02
当天 3/28、07-03 当天 **9/23（39.1%）** 仍在发生（quality_notes_json 均为
`["赛道研究员 LLM 调用失败"]`）。track 是强制项（`team.py:104-112`），单点失败即把
整条标签打成 failed/degraded，无论 quality/boom（合计权重 0.7）算得多扎实。

### 2.2 quality（Piotroski，算法）— 静默的"8+1"因子

**设计输入**：9 因子需要 `financial_metrics` 8 个字段的两期值
（`fundamentals.py:342-418`）。

**实际可得率**（2398 行独立复核）：`shares_outstanding` **100% NULL**
（采集侧从未接入，`fundamentals.py:239` 注释自陈"该接口不含，留空"）；
`long_term_debt` 51.2% / `current_ratio` 39.3% / `operating_cf` 38.5% NULL。

**后果**：`available=False` 的显式降级只占 7.5%（18/239 写"财务数据不足"）；
**其余 92.5% 表面正常跑完，但每一条的 `no_new_shares` 因子
（`fundamentals.py:394-396`，两个 `is not None` 条件必然 False）永远判 False**——
9 因子实为"8 因子+1 恒失败"，对全量股票静默单向扣分，无任何 flag。
另有隐性口径问题：找不到去年同期时退化用上一期（`fundamentals.py:365-369`），
同比变环比且不打标。quality 路投票：规避 142 / 观望 86 / 值得持有 11。

### 2.3 boom（jingqi 景气，算法）— 行业分位核心机制大面积失效

**设计输入**：Δ 类指标（`net_profit_yoy/revenue_yoy/roe` 的边际变化）+
**同行业分位**——分位数是 7×34 景气框架的核心相对排序机制。

**实际输入**：Δ 计算真实可用（依赖字段缺失率 20-35%，是 financial_metrics 里
质量较好的部分）；但 `list_peers`（`fundamentals.py:609-618`）**只在 active 自选池内**
找同行业。独立 SQL 验证：active 147 支分布在 89 个行业，**55/89（61.8%）的行业
只有 1 支 active 股**——这些 symbol 的 `list_peers` 必然为空，
必走 `_score_no_peers` 绝对值阈值兜底（`jingqi_analyst.py:34-53,144`），
完全跳过行业分位。这不是池子小的历史遗留，是当前行业分布下的**常态**。

### 2.4 flow（QFII 外资流向，算法）— 历史上从未开过口的分析师

**设计输入**：QFII 在十大流通股东的季度持仓（≥4 季窗口），触发"≥2 家连续减仓
≥2 季且减仓≥峰值 20%"才投规避（`qfii_flow_analyst.py:112-118`）。

**实际输入与可得率**（重要：**这份数据不在 SQLite**，在
`~/.mingcang/qfii_cache/*.json` 文件缓存，`qfii_holdings.py:33`；数据源是
akshare 十大流通股东 + 外资机构名白名单过滤 `qfii_holdings.py:40-54`）：
- 缓存文件仅 **59 个 symbol**（占 labels 用的 118 支的 50%，占全池 732 支的 8%）
- 59 个文件、200 个 (symbol,quarter) 条目中非空仅 **16/200（8%）**；
  至少一季有 QFII 持仓的 symbol 仅 **13/59**（≈118 支中的 11%）
- `long_term_labels.votes_json` 里 flow 出现 229 次，**229 次全部"观望"**，
  规避阈值生产历史**零触发**

即 flow 路对综合分的实际影响是 **100% 时间为零**（confidence=0 被
`team.py:46` 跳过）——"多数时候不投票"的设计意图，实测是"所有时候"。
注意：这个 flow（季度 QFII 股东）与 M54 的 flow（日度资金流通道，
`m52_flow_floor` 模块不存在、19357/19357 NULL）是**两个不同的缺口**。

**本模块补齐各类数据会解锁什么**：
- **财务补全（股本/现金流/负债）**：quality 从"8+1"恢复成真 9 因子，消除全池静默扣分——
  这可能直接改变"规避 64%"的标签分布（与既有记忆"Piotroski 对成长股偏严"是同一现象的数据侧解释）。
- **全市场行业数据**（akshare `stock_board_industry_cons_em` 或 iFinD `sector_data`）：
  jingqi 的 peers 从"池内 61.8% 行业孤股"扩到全市场，行业分位机制才真正启用。
- **公告/事件/研报作为 track 的 evidence 槽位**：SKILL.md 五层框架的第一、二层
  才有真实数字可引用，track 从"LLM 凭训练知识打分"变成"LLM 核对证据打分"。
- **股东数据入库+扩覆盖**：flow 路从 11% 覆盖扩到全池，反向规避才可能真正触发过一次。
- **海外数据**（iFinD global-stock 4 工具已验证可用、零调用）：SKILL.md 第二层
  "海外领先指标"从纯方法论文字变成可填充的数据槽位。

---

## 3. 深度调研模块（backend/research/deep_research.py）

**决策职责**：手动触发的主题/个股深研，产出 Markdown 报告 + 记忆条目。

**设计输入 vs 实际输入**：这是全项目**数据闭环最完整**的模块——
evaluator/planner 循环（`deep_research.py:676-878`）真实查三张表
（news 14 天窗口起步 / prices / financial_metrics）+ 两个外部 API
（Anspire 补新闻、Tavily web search），证据不足会自动扩窗/回补财务
（`deep_research.py:168-312`）。但仍有四个槽位级问题：

1. **"研究员分工结论"零 LLM**：报告里 5 个"研究员角色"段落
   （sector_researcher/company_researcher/risk_reviewer/source_auditor/research_writer）
   全部是确定性阈值模板（`backend/research/agents.py:71-83,145-163`：涨幅>5%、
   ROE>10 之类写死规则拼字符串），`agents.py` 全文无一次 LLM provider 调用；
   而变量名/注释/gate 检查（`deep_research.py:656-660` `_build_llm_text`、
   `research_report_gate.py:292-309` 的"LLM 越界措辞扫描"）都按"LLM 生成"处理。
   **命名暗示 LLM 综合判断、实为规则模板**——全项目最典型的一处。
2. **"待验证问题"是纯常量**：三条写死问句（`deep_research.py:637-640`），
   与当次证据内容无关，每份报告完全一样。
3. **基本面快照只有 3 字段**（revenue_yoy/net_profit_yoy/roe），
   缺失时输出"暂无财务指标数据"（`deep_research.py:574`）。
4. **证据分级门槛供给不上**：`research_evidence_defs.py:18-26` 定义 6 级
   SourceTier（primary > official > filing > ir > industry > social_lead），
   但系统不采集公告全文/招股书/问询函/IR 纪要，实际证据永远只能命中最低两档
   （industry=新闻标题、social_lead=弱来源）；`research_report_gate.py:345`
   的定性/数字分轨检查要求数字断言必须有 primary/official/filing 三档背书——
   实践中几乎总是被迫"降级为定性表述"。**门槛设计精细、供给侧永远够不到门槛。**

另：`theme_hypothesis_engine.py` / `forward_thesis.py` 是纯存储层
（文件头自陈"No LLM calls"），写入口挂 ATLAS dormant guard
（`backend/api/routes/research.py:501-514`），deep_research 不会自动写入——
深研报告与结构化论点库是两条不打通的管线，全靠 owner 手动搬运。

**补齐会解锁什么**：公告全文/研报直接把 SourceTier 的 filing/primary 档从
形同虚设变成可命中，深研报告的数字断言才能过 gate 不被降级；财务字段补全让
"基本面快照"从 3 字段扩到偿债/现金流/毛利趋势；事件数据让"待验证问题"
可以按真实催化剂生成而非三条常量。

---

## 4. M59 面板（backend/tools/m59_panel.py）

**决策职责**：盘后操作面板——owner 实盘操作的最终交互面（明仓方向 2026-07 定调的终点形态）。

页头自陈降级（`m59_panel.py:241-245`）：`llm_layer:not_implemented` /
`quant_model:placeholder_v0` / `market_regime:missing_index_ohlc`。逐区块：

| 区块 | 数据来源 | LLM | 判定 |
|---|---|---|---|
| 买入候选 `buy_candidates`（`:259-303`） | 只查 signals 表 + 字符串匹配"买"（`:270-282`），附 research_reference | `llm_discretion` 恒 None（`:297-298`）；全库唯一其他引用是测试断言它必须是 None（`tests/test_m59_panel.py:137`） | ◐槽位空转（字段存在、无任何写入路径） |
| 持仓体检 `position_health`（`:306-362`） | positions + prices 纯算术（止损止盈距离） | **连 LLM 占位字段都没有** | ○设计上无槽位 |
| 风险工程 `risk_warnings`（`:545-596`） | 池等权 MA regime 兜底（`:420-444`，因 index_prices 无 OHLC）；动量末档自称 `placeholder_v0`（`:587`）且带硬编码证伪注记（`:26-29`"下行市失效,不能当避雷器用"）；集中度/止损缓冲纯算术 | 无 | 纯价格因子；公告/资金流/龙虎榜/事件字段一个都没有（○无槽位）——**"避雷警示"目前对解禁、监管问询、质押、减持完全盲** |
| 复盘归因 `review_attribution`（`:599-636`） | 只查当日 closed positions 的平仓价/盈亏 | `llm_discipline_candidate` 恒 None（`:631`），全库唯一命中 | ◐空转；**"归因"名不副实——只是平仓记录列表**，没有任何"做对/做错了什么"的分析逻辑（规则或 LLM 都没有） |
| 研究参考 `research_reference`（`:193-198`） | long_term_labels + stock_memory_items(research_pointer)，docstring 自陈 "never scored (owner 2026-07-03 软联动裁决)" | 供未来 LLM 裁量参考 | ●有但只做展示（产品裁决，非 bug） |
| watchtower 跟进（`:647-709`） | 只读 `/private/tmp/m60_watchtower_*.json` 最新快照，"never triggers a scan itself" | 间接（见第 6 节） | ●有（被动展示） |

**补齐会解锁什么**：事件数据（解禁/监管/质押/减持，iFinD `get_stock_events`
探针已验证带精确日期）是"避雷警示"区从纯价格因子升级为真避雷器的唯一路径；
资金流/龙虎榜让买入候选的排序多一条与技术分正交的证据；复盘归因若有
逐笔归因数据支撑（技术贡献 vs 情绪 vs 大盘 beta），LLM 纪律候选槽位才有内容可填。

---

## 5. test2 / 信号 runner（paper_trading/test2_signal_runner.py, biaodi1_runner.py）

**决策职责**：生产/测试信号产出。信号公式（两条聚合路径同构）：

```python
# backend/decision/aggregator.py:221-226（生产默认路径，74.6% 的信号走这条）
composite = (blended_quant * weights.quant
             + tech_score * weights.technical
             + effective_sentiment * 100 * weights.sentiment)
```

权重硬编码默认 **quant 0.0 / technical 0.6 / sentiment 0.4**
（`backend/config.py:101-107`，注释自陈"Qlib IC=0.0228…不合格→weight_quant 归零"；
.env 无覆盖）。**公式里没有资金流项、没有长期标签项**（长期标签只对"观望"做硬截断，
`backend/agents/pipeline.py:327-337`）。抽样逐位核对公式无暗门
（603259: 0.6×47.5+0.4×0=28.5 ✓；300759: 0.6×17.7+0.4×(−65.0)=−15.4 ✓）。

**情感项的真实分布（signals 表 1387 条，2026-05-12~07-04，独立 SQL）**——
以 2026-06-02（Anspire 401 停用、切免费东财+AkShare 源）为 epoch 边界：

| 时段 | n | sentiment=0 占比 | 均值 / 标准差 |
|---|---:|---:|---|
| 06-02 前 | 753 | **61.4%**（多天 100% 全零：05-26、05-27、05-28 各 25/25） | 4.39 / — |
| 06-02 起 | 634 | 8.4% | 19.79 / 51.29 |

代码注释自证：`test2_signal_runner.py:105-110` _refresh_news docstring
"有真新闻才不退化成中性 0……2026-06-02 接入 = 情感方法学 epoch 边界：此前情感大量为 0"；
`biaodi1_runner.py:14` 用法注释直接写 `--no-llm # token≈0，纯公式技术+中性情感`。
biaodi1_runner 与 test2 的关键差异：**biaodi1 不刷新新闻**（无 `_refresh_news`，
只回填价格 `biaodi1_runner.py:88-92`），且 `long_term_team_enabled=False`（`:49`）——
标的 1 跑手的信号在无新闻日就是纯技术分。

**flow_score 独立复核**：`m54_oos_score_cache` 19357/19357 行 flow_score NULL（100%）；
`news_fusion.py` 本身也没被 aggregator/trader/pipeline 任何一处调用——
资金流不是"算出来是 0"，是**从未接入产信号主链路**。

**"之前盈利靠什么"的数据结论**：
1. quant 与资金流两个"信息层"对生产综合分的贡献**结构性为零**（权重硬编码 0 +
   通道未接入），确定无疑。
2. 情感层要分期：06-02 前信号事实上 = 0.6×技术分的线性缩放（纯技术）；
   06-02 后情感有真实方差（std≈51），有实质贡献，**不能一概而论说"情感恒中性"**。
3. test2 A/B 回放（test2_ab_state.json，05-18~07-02）：A_quant_on +13.09% vs
   B_quant_off（=生产权重）+16.66%——两组皆正收益。
4. 诚实边界：positions 表是 fixture 级数据（quantity=1.0、avg_cost=50.0 这类），
   **无法做逐笔"技术贡献 vs 情绪贡献 vs 大盘 beta"的定量归因**。能下的结论是
   结构性事实（公式里只有技术+情感两项、其中一项分期退化），"盈利=技术分+牛市 beta"
   在 06-02 前的时段有直接数据支撑，全期定量拆分做不到。

---

## 6. M60 观察哨（docs/dev/M60_WATCHTOWER_SPEC.md vs 现有实现）

spec 规划四层（spec 全文 37 行）：方向层（周频研究→观察清单）→观察哨
（盘后零 LLM：价量异动/板块共振/新闻 L1）→确认层（LLM 裁量）→入场纪律。
逐层供给度：

| 层 | 实现 | 供给判定 |
|---|---|---|
| 方向层→观察清单**自动供给** | **零代码**。grep 全库无任何代码把 track_analyst/serenity/jingqi/长期标签团输出写进 `paper_trading/watchlists/`；watchlist.py:1-42 docstring 自陈评估过复用 forward_thesis/theme_hypotheses 管线后**主动决定不接**（Phase 0 定位为手动 artifact） | ○（当前清单仅 1 个手工主题 innovative_drug.json、3 支股，`thesis` 字段本身是占位文本"owner 前期板块研究,细节待 owner 补充"，`source_ref:"pending"`） |
| 观察哨 Phase 1（backend/tools/m60_watchtower.py，647 行） | **真实现**：价量异动 z-score/分位/量比/新高（`:153-247`）、板块共振（`:254-295`）、新闻 L1 复用 `news_trigger.decide_trigger`（`:327-351`），零 LLM。2026-07-03 真实输出核验：3 支全触发，触发值是当日真实数据（如 603259 daily_return 8.23%、z=2.66） | ●有——但**无调度**（backend/jobs/ 无任何 cron 接入，纯手动 CLI），且只扫 3 支 |
| 确认层 Phase 2（watchtower_confirm.py，492 行） | 真实现，见第 7 节 | ●有但输入薄 |
| Phase 3 前向台账 / 第 4 层入场纪律 | **零代码**——spec 的"实施切片"甚至没给第 4 层排 Phase；预注册假设承诺的自动台账积累不存在，5/10/20 日收益对照只能人工回溯 | ○ |

**现有数据层能供几成**：spec 的触发信号源三件套（价量/共振/新闻 L1）恰好都落在
明仓仅有的两类数据（K 线 + 新闻标题）上，所以 Phase 1 供给率反而高——这是
"按现有数据反向设计的检测器"。但 spec 方向层预设的上游（深研/track-analyst/景气）
本身正是第 2、3 节里数据饥饿最重的模块：**观察清单的质量上限被上游研究的
信息基础锁死**，检测器再灵，清单里只有 1 个占位主题就只有 1 个主题可检。

**补齐会解锁什么**：公告/事件流可以直接充当观察哨第四类触发源（spec 未规划但
天然契合"事件锚定"定位——解禁/中标/业绩预告是比价量异动更早的信号）；
板块/行业数据（iFinD sector_data，验证可用零调用）能把"板块共振"从
池内 3 支等权升级为真实板块口径。

---

## 7. LLM 裁量层（三条互不打通的线，必须分开说）

| 线 | 状态 | 证据 |
|---|---|---|
| **C1. test2 治疗臂**（Claude 自由裁量选股） | **不是代码**——是对话式人工流程：Claude 在会话里看当日 25 支信号表自由裁量，理由手写进 test2.md 日志（test2.md:90-92,126-131），无 prompt 组装函数、无固定 context schema、自认不可复现（test2.md:135）。paper_trading/*.py grep "裁量/discretion/arm" 零命中 | 不适用"prompt 槽位"审计——裁量上下文=当次会话可见的一切，因会话而异 |
| **C2. M59 面板 llm_discretion / llm_discipline_candidate** | **完全没实现**：两字段全库无任何赋非 None 值的代码，也没有任何"构造 prompt 调 LLM 填充"的代码存在（不是调用失败，是从未编写） | `m59_panel.py:297,631`；测试反向锁定 None（test_m59_panel.py:137） |
| **C3. M60 确认层 watchtower_confirm.py** | **唯一真实现且在跑的结构化 LLM 裁量**（2026-07-03 真实产出 3 张卡，n_llm_calls=3，内容非模板） | 见下 |

**C3 的上下文包**（`_build_symbol_context`，`watchtower_confirm.py:164-194`）实际字段：
`symbol/themes/thesis/validation_conditions/invalidation_conditions/
triggers_today/research_reference/memory_recall`。System prompt
（`watchtower_confirm.py:73-80`）要求"thesis_status 需基于清单里的验证条件与
失效条件裁量，而不是凭直觉"、异动归因四选一。

**薄在哪里**：
- `thesis/validation/invalidation` 全部来自 watchlist，而当前唯一一条的 thesis
  就是占位文本——**可直接观测的后果**：2026-07-03 三张真实裁量卡的 `thesis_status`
  全部是"无法判断"。不是 LLM 偷懒，是输入确实不足以判断。
- `research_reference` 复用 M59 那套（long_term_label + research_pointer），
  不含公告/研报/资金流/事件明细；新闻只在 Phase 1 作为触发摘要，正文不进 Phase 2 上下文。
- 公告/研报/资金流/股东/估值拥挤度：`_build_symbol_context` 函数体没有这些字段——
  ○无槽位（spec 第 3 层文字里写了"估值/拥挤度提示"，实现里没有对应输入）。

**补齐会解锁什么**：这是全项目补数据的**杠杆最高点**——确认层是设计终点
（owner 拍板前的最后一道 LLM 判断），它每个输入槽位的质量直接决定裁量卡价值。
公告全文→"异动归因四选一"里"公司事件"这一路才有据可查；研报/一致预期→
spec 承诺的"估值/拥挤度提示"才能实现；资金流/龙虎榜→区分"游资一日游 vs
机构建仓"这一裁量最需要的判据。

---

## 8. 模块 × 数据类别 饥饿矩阵总表

●=真实消费 ◐=槽位/字段存在但空转（常量/占位/库有值不读） ○=设计上无此槽位 —=不适用

| 模块 \ 数据类别 | K线/技术 | 新闻标题 | 新闻正文 | 情感分 | 财务(已披露) | 公告全文 | 研报/一致预期 | 日度资金流/龙虎榜 | 股东变化 | 事件(解禁/监管等) | 海外数据 | 行业/同业对比 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 单股 copilot | ● | ● | ◐(74%有值不读) | ●(Signal分) | ○(零引用) | ○ | ○ | ○ | ◐(仅经标签间接) | ○ | ○ | ○ |
| 长期-track | ●(涨幅) | ◐(Tavily裸标题+参数错位) | ○ | ○ | ○(未接) | ○ | ○(rubric要求拥挤度) | ○ | ○ | ○ | ○(rubric第二层要求) | ○ |
| 长期-quality | — | — | — | — | ◐(no_new_shares恒False;3字段35-51%缺) | ○ | ○ | ○ | ◐(股本即股东侧数据,100%缺) | ○ | ○ | ○ |
| 长期-boom | — | — | — | — | ●(yoy/roe) | ○ | ○ | ○ | ○ | ○ | ○ | ◐(61.8%行业无peers) |
| 长期-flow | — | — | — | — | — | ○ | ○ | ○ | ◐(覆盖11%,历史0触发) | ○ | ○ | ○ |
| 深度调研 | ● | ● | ◐(audit仅标题级) | — | ●(仅3字段) | ◐(SourceTier设filing/primary档,供给永远够不到) | ○ | ○ | ○ | ○ | ◐(Tavily可搜,非结构化) | ○ |
| M59 面板 | ● | — | — | ●(经signals) | ○ | ○ | ○ | ○ | ○ | ○(避雷区对事件全盲) | ○ | ○ |
| test2/生产信号 | ● | ●(24h窗口) | ◐(生产只读title) | ●(06-02后)/◐(之前61.4%为0) | ○ | ○ | ○ | ◐(flow通道未接入公式) | ○ | ○ | ○ | ○ |
| M60 观察哨 Phase1 | ● | ●(L1触发) | ○ | — | ○ | ○ | ○ | ○ | ○ | ○(spec"事件锚定"但无事件源) | ○ | ◐(池内3支等权共振) |
| M60 确认层 | ●(triggers) | ◐(触发摘要,正文不进) | ○ | — | ○ | ○ | ○(spec要求估值/拥挤度) | ○ | ○ | ○ | ○ | ○ |
| M59 llm裁量/test2治疗臂 | ◐(C2未实现)/—(C1非代码) | | | | | | | | | | | |

**矩阵速读**：12 列数据类别中，全部 10 个消费端模块加起来真正"●"消费的只集中在
3 列（K 线/新闻标题/情感分）；公告全文、研报/一致预期、日度资金流/龙虎榜、
事件、海外数据 5 列是**整列无一个●**——不是某个模块的问题，是整个需求侧
从上游研究到终端面板没有任何一处真实消费过这五类信息。其中"◐空转"最密集的
是财务列和股东列：不是没设计，是设计了之后供给从未跟上。

---

## 9. 结语：三类饥饿的区分（供修复排序参考）

1. **供给缺口型**（数据源有、代码没接）：公告全文/研报/资金流/龙虎榜/事件/海外——
   供给侧审计已确认 akshare/iFinD 对应接口可用且零调用。修复=接采集+给消费端加槽位。
2. **槽位空转型**（schema 有、值恒空）：M54 flow_score（模块不存在）、Piotroski
   shares_outstanding（因子恒 False）、M59 llm_discretion / llm_discipline_candidate、
   ResearchState.thesis/risks/open_questions、news.summary/sentiment_score。
   修复=补写入路径或删槽位止损（避免"看起来在用"的静默失真）。
3. **结构错配型**（数据在、机制够不到）：jingqi peers 只查池内（61.8% 行业孤股）、
   SourceTier 高四档无采集路径、track 的 SKILL.md rubric 与 prompt 插槽脱节、
   watchtower 确认层被占位 thesis 锁死。修复=改机制口径，不一定要新数据。

另有一条与数据无关但影响同级的发现：**track 子代理 LLM 调用失败率**
（历史 51.5%，07-03 当天仍 39%）叠加"track 强制项"聚合规则，是长期标签
trusted 率仅 37.2% 的主要放大器——数据补齐之前，这个单点故障传导先修性价比最高。
