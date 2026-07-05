# D4 评估报告

## 结论一行

接，但只按低风险顺序接：**打板层 → 融资融券 → 大宗交易 → 股东户数 → 互动易 → 一致预期 EPS**；全部先不进①回测因子道，打板/两融/大宗/股东户数进②面板避雷或市场温度，互动易/一致预期进③研究裁量；只有完成披露时间/PIT 专项验证后，才允许升入①道。

## 品类评估表

| 品类 | a-stock-data 源与接口 | 更新频率/历史回填 | PIT 语义 | 三车道发牌与接入建议 | 对“判断质量”的价值 |
|---|---|---|---|---|---|
| 股东户数/筹码集中度 | 东财 datacenter，`RPT_HOLDERNUMLATEST`，函数 `holder_num_change()`，字段含 `END_DATE/HOLDER_NUM/HOLDER_NUM_RATIO/AVG_FREE_SHARES` | 季度/定期报告口径；可按 `END_DATE` 倒序翻页，历史回填**结构上可行**，但当前 helper 只取第一页 | **不适合回测直用**。`END_DATE` 是报告期末，不是披露日；季度股东户数通常随定期报告或互动回复延迟披露，延迟天数不固定。未见该函数返回 disclosure_date，PIT=UNVERIFIED/高前视风险 | **②面板避雷 + ③研究裁量；暂不进①**。接，但只展示“最新已披露筹码变化”，不做历史因子 | 减少“价格横盘但筹码悄悄集中/发散”误判；可辅助左侧信号解释吸筹或派发 |
| 融资融券 | 东财 datacenter，`RPTA_WEB_RZRQ_GGMX`，函数 `margin_trading()`，字段含 `DATE/RZYE/RZMRE/RQYE/RZRQYE` | 日级；按 `DATE` 倒序。历史回填结构上可行，但需补分页；精确全历史深度 UNVERIFIED | 相对干净但仍需专项验证。交易所两融日度数据通常盘后/次日可得；a-stock-data 未写明盘后几点可得。回测只能用 `DATE` 后一交易日可见，不能当天盘中用 | **②面板避雷，少量可做①候选但需 PIT harness**。建议先接为面板趋势，不喂信号 | 减少“价格上涨但杠杆资金过热/融资余额背离”的误判 |
| 一致预期 EPS | 同花顺 `basic.10jqka.com.cn/new/{code}/worth.html`，函数 `ths_eps_forecast()`；另东财研报列表有单篇 EPS 预测 | 同花顺页面是当前机构覆盖快照；无 as-of 历史。东财研报有 `publishDate` 和单篇 EPS，可历史过滤但不是 consensus | **PIT 不干净**。当前一致预期不能反推历史某日的当时预期；明仓 iFinD 手册也已把一致预期判为“只返回当前最新滚动值，禁止喂回测” | **③研究裁量；不进①/②核心信号**。接，但只作为当前估值参考，并展示机构数 | 减少“只看 PE 不看盈利预期”的估值误判；可辅助 PE 消化/PEG，但不能当历史 alpha |
| 互动易 | 巨潮互动易 `irm.cninfo.com.cn`，函数 `cninfo_irm()`；两步：`queryKeyboardInfo` 拿 `secid`，再 `company/question` | 问答分页；代码参数含 `startDay/endDay` 但示例留空，日期过滤能力 UNVERIFIED。回答率因公司而异 | **③ only**。返回 `pubDate`/`ask_time`，但未明确区分提问时间和回答时间；若今天抓历史问答，可能看到当时尚未回答的后续回复，PIT=UNVERIFIED | **③研究裁量；不进①，②只做引用卡片**。接，作为“公司如何回应传闻/订单/业务”的证据 | 减少基于新闻标题猜公司口径的误判，特别适合 copilot/深研里的“公司回应”槽位 |
| 打板层/市场温度 | 东财 push2ex 四池：`em_zt_pool/em_zb_pool/em_dt_pool/em_yzt_pool`；同花顺 `ths_limit_up_pool()`；情绪函数 `limit_up_sentiment()` | 交易日按 `date=YYYYMMDD` 查询；涨停/炸板/跌停/昨涨停池可历史日期查询。全历史深度和盘中刷新频率 UNVERIFIED | **盘后可用，盘中会变**。涨停池、炸板池、封板资金、炸板率、连板梯队在交易中动态变化；若做回测必须保存盘后快照或使用下一交易日可见。a-stock-data 未写明盘后几点稳定 | **②市场温度优先接；①暂缓**。这是本轮最契合“市场温度=打板层”的品类，先做盘后市场温度，不做历史因子 | 减少“个股信号好但市场接力情绪崩”的漏判；可补 M59/M60 对赚钱效应、连板高度、炸板率的盲区 |
| 大宗交易 | 东财 datacenter，`RPT_DATA_BLOCKTRADE`，函数 `block_trade()`，字段含 `TRADE_DATE/DEAL_PRICE/CLOSE_PRICE/BUYER/SELLER/premium_pct` | 日级/逐笔记录；按 `TRADE_DATE` 倒序，历史回填结构上可行，需补分页 | **clean-ish，但披露时点未验**。`TRADE_DATE` 是成交日，不等于可见时间；通常交易所盘后披露，精确可得时间 UNVERIFIED。回测需 T+1 或披露时间保护 | **②面板避雷 + ③研究裁量；不先做①**。接，识别折价大宗/机构通道异常 | 减少“技术面强但大宗折价减持压力未显性化”的误判 |

依据来源：a-stock-data README/SKILL 明确是 10 层、40 端点、13 源、自包含 Skill，并列出资金面、打板、互动易等能力；SKILL 源码中对应函数分别使用东财 datacenter、push2ex、同花顺 basic/limit_up、巨潮互动易。参考：  
https://github.com/simonlin1212/a-stock-data  
https://github.com/simonlin1212/a-stock-data/blob/main/SKILL.md  
https://github.com/simonlin1212/a-stock-data/blob/main/CHANGELOG.md  
本地口径参考：[DATA_AUDIT_DEMAND.md](/Users/zeeechenn/mingcang/docs/dev/DATA_AUDIT_DEMAND.md)、[a-stock-data.md](/Users/zeeechenn/mingcang/docs/data-sources/a-stock-data.md)、[ifind.md](/Users/zeeechenn/mingcang/docs/data-sources/ifind.md)、[akshare.md](/Users/zeeechenn/mingcang/docs/data-sources/akshare.md)。

## 接入方案与工作量

**方案 A：按 HTTP 端点改写成明仓 CategoryProvider。**  
推荐不是直接复制 Skill，而是把端点抽成明仓 provider：共享限流 client、分页、字段 schema、PIT 元数据、缓存策略、失败降级。工作量估计：

| 批次 | 内容 | 估计 |
|---|---|---|
| P0 探针 | 6 品类各 2-3 支股票、2-3 个历史日期、非交易日/无数据样本、字段稳定性 | 1-2 天 |
| P1 provider | 东财 datacenter 共用 provider：两融/大宗/股东户数，分页 + 限流 + schema | 2-3 天 |
| P2 市场温度 | push2ex 四池 + 同花顺涨停揭秘 + 情绪聚合，只写盘后快照 | 2-3 天 |
| P3 研究源 | 互动易、一致预期 EPS，接入 copilot/deep research 引用槽位 | 1.5-2.5 天 |
| 验证 | 单元测试、PIT 标记、M59/M60 展示 smoke、无 DB 写或 shadow 表 | 1-2 天 |

合计约 **7-11 个工作日**，若只做“盘后只读面板快照 + 不入库”可压到 **3-5 天**。

**方案 B：不引代码，只借其数据源优先级与防封设计。**  
这是更推荐的第一步：保留明仓 provider 链，不引入“自包含 Skill 文件”形态；借鉴它的原则：通达信/腾讯优先，东财仅用于独有数据；东财串行、会话复用、`>=1s + jitter`、不并发、正常 UA/Referer。工作量约 **0.5-1 天** 可固化到 shared HTTP policy，再逐个品类接 provider。

**推荐：B + 精选 A。**  
先把防封和限流策略纳入明仓 provider 基座，再按价值接“打板层、两融、大宗、股东户数”。一致预期和互动易只作为 research reference，不先改信号公式。

## 风险与不接清单

**主要风险**

| 风险 | 评估 |
|---|---|
| 免费接口稳定性 | 东财、同花顺、巨潮都可能改字段/风控。a-stock-data 自己也记录过接口失效、报表名变更、字段解析 bug、住宅 IP 风控。必须有探针和降级，不可静默写入核心信号 |
| PIT | 最大风险。股东户数缺披露日，一致预期无历史 as-of，互动易缺明确回答时间，打板池盘中动态变化；这些都不能直接喂历史回测 |
| License | Apache-2.0，可借鉴/改写，但若复制代码需保留 LICENSE/NOTICE/出处；更建议只借设计和参数，明仓内自写 provider |
| 与现有源重叠 | 新闻、研报、资金流、龙虎榜、公告、股东户数、事件在 akshare/iFinD 已有部分覆盖。重叠品类不要重复建第二套事实表，应统一成 provider 优先级和 source lineage |
| 工程形态错配 | a-stock-data 是 Markdown Skill 内嵌 Python；明仓是 provider 链/category registry/fetcher。直接粘代码会绕开配置、缓存、审计、PIT 标签和测试，不推荐 |

**不接/暂缓清单**

| 暂缓项 | 原因 |
|---|---|
| 一致预期 EPS 进回测因子 | 当前快照，无历史 as-of，前视风险高 |
| 股东户数进回测因子 | 只有报告期 `END_DATE`，缺披露日，会把未来披露提前到季度末 |
| 互动易进任何量化信号 | 回答时间/PIT 不清，回答率不稳定，文本裁量属性强 |
| 打板池作为历史回测因子 | 盘中动态；除非明仓自己每天盘后落快照，或确认历史接口返回的是当日收盘固定状态 |
| 新闻端点重复接入 | a-stock-data 的东财个股新闻与明仓既有东财路径重叠，不构成新增价值 |
| 大范围复制 Skill 代码 | 形态不匹配，后续维护和审计成本高 |

备注：`dual-search` 要求 Tavily 交叉搜索，但本环境未暴露 Tavily 工具；我使用内置 Web + GitHub 只读文件抓取 + 本地明仓手册完成核对。
