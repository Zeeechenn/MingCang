> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

# a-stock-data 使用手册

## ① 一句话定位

a-stock-data（github.com/simonlin1212/a-stock-data，一个面向 AI coding assistant 的 Skill
文件，内嵌 Python 直连 mootdx/腾讯/东财/百度/新浪/巨潮/同花顺/iwencai 等上游 HTTP 接口，零第三方
wrapper 依赖）是明仓六源里**理论能力覆盖面最广**的候选（README 称新闻/盘口/公告/F10/财务/研报
六类全覆盖，外加资金流/龙虎榜/行业），但明仓侧**零接入，仅在 `external_sources.py` 登记为
catalog 条目**——本手册的 13 个端点候选，**验证状态一律"候选未验,待 P1 体检"**，接入与否留待
P1 体检结果判定，不预设结论。

## ② 能力目录：13 个端点候选（清单来自 `docs/dev/DATA_AUDIT_EXTERNAL.md` §5 + 2026-07-04 对
   `github.com/simonlin1212/a-stock-data` SKILL.md（V3.3.0）原文核对，URL 均为原文抄录，未经明仓实测）

| # | 端点/接口 | URL / 协议 | 功能 | 覆盖类别 | 验证状态 |
|---|---|---|---|---|---|
| 1 | mootdx 客户端（通达信 TCP 协议，非 HTTP） | `mootdx.quotes.Quotes`（TCP，非 URL） | K线(1/5/15/30/60分钟+日/周/月线) + 五档盘口 + 逐笔成交(买/卖/中性) | quotes（含盘口深度） | 候选未验,待 P1 体检 |
| 2 | 腾讯财经行情 | `https://qt.gtimg.cn/q` | PE(TTM)/PB/市值/流通市值/换手率/涨跌停价/指数/ETF 快照 | quotes | 候选未验,待 P1 体检 |
| 3 | 东财 push2 个股基本面 | `https://push2.eastmoney.com/api/qt/stock/get` | 个股基本面快照（简况类字段） | f10 | 候选未验,待 P1 体检 |
| 4 | 东财 push2 板块/概念归属 | `https://push2.eastmoney.com/api/qt/slist/get` | 个股所属行业/概念/地域板块列表 | sector | 候选未验,待 P1 体检 |
| 5 | 新浪财报三表 | `https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022` | 资产负债表/利润表/现金流量表 | financials | 候选未验,待 P1 体检 |
| 6 | 东财研报（个股+行业） | `https://reportapi.eastmoney.com/report/list`（`qType=0` 个股 / `qType=1` 行业，同一端点） | 研报列表（标题/机构/评级/EPS预测/行业分类），**支持 `beginTime`/`endTime` 日期范围**，PDF 模板 `https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf` | research_reports | 候选未验,待 P1 体检 |
| 7 | 同花顺一致预期 EPS | `https://basic.10jqka.com.cn/`（对应接口） | 机构一致预期 EPS 预测（含"预测机构数"字段） | research_reports | 候选未验,待 P1 体检 |
| 8 | 东财 push2 分钟级资金流 | `https://push2.eastmoney.com/api/qt/stock/fflow/kline/get` | 个股主力/超大单/大单/中单/小单净流入（分钟级，`klt=1`；日级用 `klt=101`），金额单位**元**（非万元） | fund_flow | 候选未验,待 P1 体检 |
| 9 | 东财 120 日资金流 | `https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` | 个股日级资金流历史（120日窗口） | fund_flow | 候选未验,待 P1 体检 |
| 10 | 东财 datacenter 龙虎榜 | `https://datacenter-web.eastmoney.com/api/data/v1/get`（`RPT_DAILYBILLBOARD_DETAILSNEW` 上榜记录 / `RPT_BILLBOARD_DAILYDETAILSBUY`、`RPT_BILLBOARD_DAILYDETAILSSELL` 买卖席位） | 个股上榜记录 + 买卖席位 TOP5 + 机构专用席位(`OPERATEDEPT_CODE="0"`)动向，支持 `TRADE_DATE` 范围过滤 | lhb | 候选未验,待 P1 体检 |
| 11 | 东财 datacenter 融资融券/大宗交易/限售解禁 | 同上端点，报表分别为 `RPTA_WEB_RZRQ_GGMX`（融资融券）/ `RPT_DATA_BLOCKTRADE`（大宗交易）/ `RPT_LIFT_STAGE`（限售解禁） | 融资融券余额明细、大宗交易成交(含溢价率)、历史+未来90天解禁日历 | corporate_events | 候选未验,待 P1 体检 |
| 12 | 巨潮公告全文检索 | `https://www.cninfo.com.cn/new/hisAnnouncement/query`（POST，需先经 `http://www.cninfo.com.cn/new/data/szse_stock.json` 拿 orgId 映射） | 全市场公告全文检索（标题/类型/日期/详情URL） | announcements | 候选未验,待 P1 体检 |
| 13 | 东财新闻（个股 + 全球7x24） | `https://search-api-web.eastmoney.com/search/jsonp`（个股新闻，**与明仓 `eastmoney.md` 已直连的接口相同**）+ `https://np-weblist.eastmoney.com/comm/web/getFastNewsList`（全球财经快讯） | 个股新闻流 + 全球财经快讯 | news | 候选未验,待 P1 体检（个股新闻端点本身明仓已直连，见 `eastmoney.md`，但 a-stock-data 的封装/字段处理方式未核对） |

## ③ 调用示例

```python
# #6 东财研报（支持日期范围，是 13 个候选里 PIT 语义最好的一个）
import requests

REPORT_API = "https://reportapi.eastmoney.com/report/list"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

def eastmoney_reports(code: str, begin: str = "2024-01-01", end: str = "2026-07-04"):
    params = {
        "industryCode": "*", "pageSize": "100", "industry": "*",
        "rating": "*", "ratingChange": "*",
        "beginTime": begin, "endTime": end,
        "pageNo": "1", "fields": "", "qType": "0",
        "orgCode": "", "code": code, "rcode": "",
    }
    r = requests.get(REPORT_API, params=params,
                      headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
                      timeout=30)
    return r.json().get("data") or []

# reports = eastmoney_reports("688017")  # 未实测,候选状态
```

```python
# #10 东财龙虎榜（datacenter 通用 filter 查询模式）
import requests

def eastmoney_datacenter(report_name, filter_str, page_size=50,
                          sort_columns="TRADE_DATE", sort_types="-1"):
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": report_name, "filter": filter_str,
        "pageSize": page_size, "sortColumns": sort_columns, "sortTypes": sort_types,
    }
    r = requests.get(url, params=params, timeout=15)
    return r.json().get("result", {}).get("data") or []

# data = eastmoney_datacenter(
#     "RPT_DAILYBILLBOARD_DETAILSNEW",
#     filter_str='(TRADE_DATE>=\'2024-05-01\')(TRADE_DATE<=\'2024-05-31\')(SECURITY_CODE="002475")',
# )  # 未实测,候选状态
```

```bash
# #12 巨潮公告全文检索（HTTP POST，需先拿 orgId 映射，示例仅示意，未实测）
curl -s "https://www.cninfo.com.cn/new/hisAnnouncement/query" \
  -X POST --data "stock=688017,9900041602&tabName=fulltext&pageSize=30&pageNum=1" \
  -H "Referer: https://www.cninfo.com.cn/new/disclosure"
```

## ④ PIT 判定

**全部标注 unknown**——13 个端点均未被明仓实测，以下仅是基于 SKILL.md 原文的**结构性观察**，
不是验证结论：

| # | 结构性观察 | 判定 |
|---|---|---|
| 6（东财研报） | 显式支持 `beginTime`/`endTime` 参数，结构上具备回溯查询能力 | unknown（结构上像 clean，未验证是否真的按发布日期过滤而非查询时过滤） |
| 10（龙虎榜） | 支持 `TRADE_DATE` 范围 filter，且龙虎榜是交易所公开发布后不变的历史记录 | unknown（结构上像 clean，未验证） |
| 11（融资融券/大宗交易/限售解禁） | 按 `DATE`/`TRADE_DATE` 排序查询,理论上可回溯 | unknown |
| 12（巨潮公告） | 无日期范围参数示例（`seDate` 字段留空），需要额外确认是否支持 | unknown |
| 8/9（资金流分钟级/120日） | 明确是"近期滚动窗口"（120日），非任意历史区间 | unknown，偏 risky（窗口限制） |
| 其余（quotes/f10/sector/financials/news） | 多为当前快照型接口 | unknown，偏 risky（无历史版本存档迹象） |

## ⑤ 明仓接线现状（file:line）

**零接入，仅设计/登记文档层**：

| 项 | 位置 | 说明 |
|---|---|---|
| catalog 条目 | `backend/data/external_sources.py:56`（`ExternalSource(id="a_stock_data", ...)`） | `recommended_stage="evidence_trial"`，`high_value_datasets` 列了 7 项（margin_trading/limit_up_lhb/unlock_calendar/announcements/research_reports/shareholder_count/block_trades），**无任何对应 fetch 函数实现** |
| evidence trial | `backend/data/external_sources.py:318`（`ExternalEvidenceTrial(id="a_stock_data.margin_trading", ...)`） | 唯一具体化的试验，`write_policy="no_database_writes"`、`signal_impact="none"`——纯设计阶段，未落地代码 |
| 能力清单占位符 | `backend/data/market_capabilities.py:191`（`"a_stock_data_candidate"`） | 字符串占位符，非实际 provider 注册 |

全仓 grep 未发现任何 `import` 或 HTTP 调用指向本手册 13 个候选端点的上游域名（`push2.eastmoney.com`
的资金流/basic 路径、`cninfo.com.cn/new/hisAnnouncement`、`reportapi.eastmoney.com` 等）。

## ⑥ 坑与注意

- **定位：零接入，P1 体检后定去留。** 本手册的 13 个端点是候选清单，不是已验证能力，接入前必须
  逐个做连通性+字段稳定性探针（`external_sources.py` 的 integration_notes 已要求"一次只引入一个
  数据集"）。
- 巨潮公告端点（#12）真实 orgId 并非统一 `gssx0{code}` 格式（如 601318→`9900002221`，
  601398→`jjxt0000019`），SKILL.md 原文明确警告硬编码规则会导致大量 601xxx 段股票查不到公告，
  必须先拉 `http://www.cninfo.com.cn/new/data/szse_stock.json` 的官方映射表。
- 东财系接口（push2/datacenter/reportapi/search/np-weblist）据 SKILL.md 社区实测（2026-05）有
  风控阈值：单 IP 每秒 >5 次 / 并发 ≥10 / 1 分钟 ≥200 次会被临时封 IP；SKILL.md 建议所有请求走
  统一限流+连接复用的 helper，明仓若接入需要同等节流设计。
- 端点 #13（个股新闻）与明仓 `eastmoney.md` 已直连的 `search-api-web.eastmoney.com/search/jsonp`
  是**同一个接口**——不构成新增数据源，只是 a-stock-data 的另一种封装方式，接入价值应体现在其余
  12 个未接口子，而非重复接入已有的新闻端点。
- 资金流端点（#8/#9）金额单位是**元**而非万元（SKILL.md 原文特别标注 "push2 资金流金额单位是元
  (非万元)"），接入时若沿用其他资金流函数的万元惯例会出现单位错误。
- 本手册的 URL/参数抄录自 2026-07-04 拉取的 SKILL.md（V3.3.0）原文，比最初的 `DATA_AUDIT_EXTERNAL.md`
  （仅拿到 README 摘要）更细，但**仍未做任何真实网络调用验证**——这是文档层核对，不是 P1 体检。
