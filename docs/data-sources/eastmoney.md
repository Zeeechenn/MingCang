> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

# 东方财富（直连）使用手册

## ① 一句话定位

明仓目前**只直连了东财一个未文档化的新闻搜索 jsonp 接口**（新闻正文一级路径），其余所有
"eastmoney"/`_em` 字样命中都是经 akshare 包了一层，不是直连；东财公开生态里资金流(push2)、
公告全文、研报、龙虎榜等接口生态明仓完全没碰，是双重空白（既没直连也没经 akshare 调用）。

## ② 能力目录

### 已直连：新闻搜索 jsonp 端点

| 项 | 内容 |
|---|---|
| URL | `https://search-api-web.eastmoney.com/search/jsonp` |
| 方法 | GET，`requests.Session(trust_env=False)`，`timeout=10` |
| 关键参数 | `cb`（jsonp callback，固定 `"jQuery_mingcang"`）、`param`（JSON 字符串，内含 `keyword`=股票代码、`type=["cmsArticleWebOld"]`、`client/clientType/clientVersion`、`param.cmsArticleWebOld.{searchScope,sort,pageIndex,pageSize=50,preTag,postTag}`）、`_`（时间戳占位） |
| 必需 headers | `Referer: https://so.eastmoney.com/`、`User-Agent: Mozilla/5.0` |
| 日期范围 | **不支持**，返回按相关度/时间排序的近期结果，`pageSize` 固定 50，无 start/end 参数 |
| 返回字段（响应体 `result.cmsArticleWebOld` 数组，代码内重命名） | `新闻标题`(title)、`新闻链接`(自行拼 `http://finance.eastmoney.com/a/{code}.html`)、`发布时间`(date)、`文章来源`(mediaName)、`新闻内容`(content，**含正文全文**，HTML `<em>` 高亮标签会被代码用正则剥离) |
| 限制 | 未文档化/逆向接口，无 SLA；异常直接触发 fallback（见下） |

### 值得知道的东财公开接口方向（仅审计里有据，未在明仓验证）

以下方向来自 `docs/dev/DATA_AUDIT_EXTERNAL.md` §2.2 的公开知识调研，**明仓代码零接入**，
标注"未验证"，不是照抄文档的猜测扩充：

| 方向 | URL 模式（公开知识） | 覆盖类目 | 状态 |
|---|---|---|---|
| 个股资金流历史K线 | `push2.eastmoney.com/api/qt/stock/fflow/kline/get` | 资金流 | 未验证；审计文档判断 akshare `stock_individual_fund_flow` 底层大概率即此接口（本手册 akshare.md §2.5 实测该 akshare 函数因沙箱代理拦截 `push2his.eastmoney.com` 未跑通，方向一致） |
| 公告频道 | `data.eastmoney.com/notices` | 公告（全文+PDF链接） | 未验证；明仓只接了"预约披露日历"（经 akshare `stock_report_disclosure`），未接公告正文 |
| 研报频道 | `data.eastmoney.com/report/` | 研报（个股/行业全文摘要+评级） | 未验证；owner 点名的研报类目前完全空白 |
| 龙虎榜 | `data.eastmoney.com/stock/lhb` | 龙虎榜 | 未验证；只能经 akshare `stock_lhb_*_em` 系列拿到（16个函数，见 akshare.md），且这些函数也未被明仓调用 |

## ③ 调用示例

### 直连新闻搜索（可直接复制，Python）

```python
import json
import requests

symbol = "000001"
cb = "jQuery_mingcang"
inner = {
    "uid": "", "keyword": symbol,
    "type": ["cmsArticleWebOld"],
    "client": "web", "clientType": "web", "clientVersion": "curr",
    "param": {
        "cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 50,
            "preTag": "", "postTag": "",
        }
    },
}
session = requests.Session()
session.trust_env = False
resp = session.get(
    "https://search-api-web.eastmoney.com/search/jsonp",
    params={"cb": cb, "param": json.dumps(inner, ensure_ascii=False), "_": "1"},
    headers={"Referer": "https://so.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
    timeout=10,
)
raw = resp.text.strip()
if raw.startswith(cb):
    raw = raw[len(cb):].strip("();")
data = json.loads(raw)
articles = data.get("result", {}).get("cmsArticleWebOld", [])
```

### HTTP 直连（等价 curl，便于快速手测）

```bash
curl -sG "https://search-api-web.eastmoney.com/search/jsonp" \
  -H "Referer: https://so.eastmoney.com/" -H "User-Agent: Mozilla/5.0" \
  --data-urlencode 'cb=jQuery_mingcang' \
  --data-urlencode 'param={"uid":"","keyword":"000001","type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr","param":{"cmsArticleWebOld":{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":50,"preTag":"","postTag":""}}}' \
  --data-urlencode '_=1'
```

## ④ PIT 判定

| 端点 | 判定 | 理由 |
|---|---|---|
| 新闻搜索 jsonp（已直连） | risky | 无日期范围参数，无历史存档能力，只能拿到"抓取时刻"的近期快照；东财是否对旧新闻做过编辑/下架未知 |
| push2 资金流K线（未接） | unknown | 未验证；若真是分钟/日级K线且可指定历史区间，理论上可以做到 clean，但本手册未实测 |
| 公告频道 `data.eastmoney.com/notices`（未接） | unknown | 未验证；若支持按公告发布日回溯查询则可 clean，同类能力 akshare 侧的 `stock_notice_report`（见 akshare.md）已确认支持按天查询 |
| 研报频道（未接） | unknown | 未验证 |
| 龙虎榜频道（未接） | unknown | 未验证；同类能力 akshare 侧的 `stock_lhb_detail_em` 已确认支持日期范围，判定 clean，可作东财原生接口的替代 |

## ⑤ 明仓接线现状（file:line）

| 项 | 位置 |
|---|---|
| jsonp 请求 URL | `backend/data/news.py:154` |
| 请求构造/解析/字段重命名 | `backend/data/news.py:132-180` |
| 一级路径入口函数 `fetch_stock_news_cn` | `backend/data/news.py:196` |
| 失败 fallback（重试 3 次后转 akshare `stock_news_em`） | `backend/data/news.py:184-193`（重试逻辑）、`news.py:188`（fallback 调用） |
| M54 news-adapter 层封装 | `backend/data/news_adapters/eastmoney.py:6`（import）、`:10`（`EastmoneyAdapter` 类）、`:25`（调用 `fetch_stock_news_cn`） |

其余所有 "eastmoney"/`_em` 命中（`market_capabilities.py`、`market.py`、`market_sources.py`、
`market_utils.py`、`market_snapshots.py`、`cache_policy.py`、`models/market.py`）均经 akshare
的 `_em` 后缀函数（行情/F10/股东），不是直连，具体清单见 `akshare.md` §⑤。

## ⑥ 坑与注意

- 这是**未文档化/逆向接口**，随时可能改字段名或加反爬限制，无官方 SLA；生产代码已内置
  3 次重试 + 指数退避（`news.py:184-193`），新增调用方也应保留同样的容错策略。
- `cmsArticleWebOld` 返回的 `content` 字段带 `<em>`/`</em>` 高亮标签，代码用正则剥离
  （`news.py:175-177`），直接使用原始响应需要自己处理。
- 本次沙箱网络实测发现：同是 eastmoney 域名，`search-api-web.eastmoney.com` 可正常访问，
  但 `push2his.eastmoney.com`、`17.push2.eastmoney.com` 被沙箱代理拦截（`ProxyError`）——
  接入 push2 系资金流/行情接口前，务必在目标运行环境（而非受限沙箱）单独验证连通性。
- 未接的公告/研报/龙虎榜三个方向，明仓侧连经 akshare 的对应函数（`stock_notice_report`、
  `stock_research_report_em`、`stock_lhb_detail_em`）都未调用——是"双重空白"，优先级上
  应先走 akshare 免 key 路径验证价值，再考虑是否值得直接逆向东财原生接口。
