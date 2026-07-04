# M61 Phase 1 — 源体检发牌表(质量门·第一道)

> 2026-07-04 | 依据:m61_source_health 全量体检(39格,paper_trading/m61_out/source_health_full_20260704.json)+ 手册补充实测 + leader 定向探针。
> 发牌规则:主源=该类数据生产接入首选;备源=fallback;拒绝=不接+原因。PIT 车道:①回测 ②面板/避雷 ③研究 reference。

## 网络环境事实(影响多格判定,先读)

- **东财 push2 / push2his 主机族:本机间歇封禁**(单次低频可通,连发触发反爬冷却)。akshare 资金流/部分行情函数底层即此族。生产日频单次调用可行,批量回填需退避设计。
- 东财 datacenter-web / reportapi / search-api / np-weblist 主机:稳定可达。
- iFinD MCP:稳定,QPS=1,每查询 ~11 条上限(按旬切窗绕过)。

## 发牌表

| 类别 | 主源 | 备源 | 拒绝 | 车道 | 关键证据 |
|---|---|---|---|---|---|
| 新闻 news | **iFinD search_news**(PIT clean,回溯≥8个月,正文~91%) | Anspire(前向)/东财jsonp(前向) | akshare(risky,最近N条) | ①②③ | 已实战:标的1 1~7月 7016 行 |
| 公告 announcements | **iFinD search_notice**(clean,可回溯) | akshare stock_notice_report(3216行,range✅但单调用~73s,只宜低频批量);巨潮cninfo(候选待验,全文最权威) | tushare(无权限) | ①② | 补 NEWS_THIN 的主力 |
| **研报 research_reports** | **东财 reportapi 直连**(**日期范围实证✅**,publishDate+机构+评级+EPS预测) | akshare stock_research_report_em(同API封装,318行) | tushare report_rc(无权限) | ①③ | **解锁研报修正因子**(P5) |
| 龙虎榜 lhb | **akshare stock_lhb_detail_em**(clean,2080行全历史,datacenter稳定) | 东财datacenter直连(同源) | — | ①② | 白捡的回测级行为数据 |
| **资金流 fund_flow** | **东财 push2 fflow/kline 直连(唯一路,不稳定)**——B7 设计约束:日频低频采集+指数退避;历史~120-250天/股,放行窗口一次抓 | 龙虎榜作避雷道部分替代 | akshare封装(同主机被封)/tushare(无权限)/iFinD(**无此专项**) | ①(前向攒)② | flow 腿地基,全案最脆弱格 |
| 公司事件 corporate_events | **iFinD get_stock_events**(事件自带日期;解禁/定增/回购/监管) | 东财datacenter(解禁RPT_LIFT_STAGE/大宗/融资融券,候选待验) | — | ①② | M59 避雷区主料 |
| 股东 holders | **iFinD get_stock_shareholders**(快照) | — | akshare(列名drift 'sdltgd'报错) | ② + 修Piotroski股本 | shares_outstanding 补源 |
| 财务 financials | **iFinD get_stock_financials**(**报告期精确到日=①道可用**;一致预期字段仅当前值→③道) | akshare(现役)+tushare daily_basic(clean备) | 新浪三表(候选,暂不需要) | ①③ | 手册 §5 PIT 拆道结论 |
| 行情 quotes | 现有 fallback 链不动 | +tushare daily(clean,date-range✅) | — | ① | 无需改 |
| 板块 sector | **iFinD sector_data** | akshare(push2冷却,待复验) | — | ②③ | 板块联动预警 |
| 简况 f10 | **iFinD get_stock_info/summary** | tushare stock_basic(5534行) | — | ③ | copilot 槽位 |
| 海外 overseas | **iFinD global_stock_***(MRVL/MU 实测可取) | — | — | ③ | 海外领先指标自动化 |
| 风险指标 | iFinD get_risk_indicators(**滚动快照,禁入①道**) | — | — | ②仅 | 手册实测:窗口=截止日前1年 |

## a-stock-data 定位裁决

它不是一个"服务",是 **13 个上游端点的坐标目录**(手册 a-stock-data.md)。"接入 a-stock-data"实为"直连这些上游端点"。已单独验证:东财 reportapi ✅(研报主源);待验:巨潮 cninfo(公告备源)、datacenter 解禁/大宗;放弃跟进:腾讯/新浪行情快照(现有链已覆盖)。**不引入其仓库代码,只取端点坐标**。

## 对 P2 施工的直接输入

1. B6 新品类表优先序:announcements、research_reports、lhb、corporate_events(数据已验)→ fund_flows(前向攒+退避)→ holders;
2. B7 flow 腿:数据源=push2 fflow 直连,**必须内建退避与显式降级**(网络事实决定);Piotroski 股本=iFinD get_stock_shareholders;
3. 研报修正因子(P5)预注册假设可以起草——数据地基已实证。
