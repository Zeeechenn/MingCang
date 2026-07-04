# Anspire + Tavily 手册

> M61 手册库 | 生成 2026-07-04 | 接入新能力必须同步更新本手册

素材来源：`docs/dev/DATA_AUDIT_EXTERNAL.md` §6（一句话带过，本次未深挖）+ 代码内省。

## 1. 一句话定位

Anspire 是明仓**新闻主源**，Tavily 是**标题级兜底搜索**。两者本质都是**网页搜索型接口**（不是
结构化数据库、不带官方披露时间戳的强保证），历史回溯存在选择偏差（搜索引擎索引什么、什么时候
索引不可控），**禁止作为 PIT 历史信号源**用于回测，只适合"当前/近期决策辅助"场景。

## 2. 能力目录

| 工具 | 入参 | 返回字段 | 限制 |
|---|---|---|---|
| `fetch_stock_news_anspire(symbol, name, days=None, max_results=None, limit=None, now=None)` | `days`(默认`settings.anspire_news_days`=2)，`max_results`(默认`settings.anspire_news_max_results`=5) | 事件型新闻，含正文（经来源审计过滤，只保留命中公司身份、像事件新闻、通过审计分的条目） | 需 `ANSPIRE_API_KEY`；query 拼法固定为 `f"{name} {symbol} A股 最新消息 公告 业绩 订单 减持 立案 回购"`；`FromTime`/`ToTime` 参数存在但是"搜索窗口"非"披露时间过滤"（搜索引擎语义，见 §4） |
| `search_titles_tavily(query, days=1, max_results=5)` | 任意自由文本 query | 仅标题列表（无正文、无规范URL、无真实发布时间戳） | 需 `TAVILY_API_KEY`；`days` 是 Tavily 自己的"最近N天"搜索窗口参数，非结构化披露日期过滤 |
| `fetch_titles_tavily(symbol, name, days=1, max_results=5)` | 包装 `search_titles_tavily`，query固定为 `f"{name} {symbol} 股票 最新消息"` | 同上 | 同上 |

代码位置：`backend/data/news.py`：
- `fetch_stock_news_anspire`（L383）
- `search_titles_tavily`（L480）
- `fetch_titles_tavily`（L514）

## 3. 问法/调用模板

Anspire（固定拼法，不建议随意改写 query 结构，审计过滤逻辑是针对这个模板调的）：

```python
fetch_stock_news_anspire("300308", "中际旭创", days=2, max_results=5)
# 内部实际 query = "中际旭创 300308 A股 最新消息 公告 业绩 订单 减持 立案 回购"
```

Tavily 标题兜底：

```python
fetch_titles_tavily("300308", "中际旭创", days=1, max_results=5)
# 内部实际 query = "中际旭创 300308 股票 最新消息"
```

Tavily 也可用于任意自由文本搜索（非个股场景，如板块/赛道调研）：

```python
search_titles_tavily("光通信 CPO 800G 出货 进展", days=7, max_results=10)
```

## 4. PIT 判定

**禁作 PIT 历史源**——两者都是网页搜索型接口：
- 搜索引擎索引一篇网页的时间与该网页实际发布/披露的时间不对齐，无法保证"历史某日查询=当时能看到
  的信息"。
- `days`/`FromTime`/`ToTime` 是"搜索范围窗口"参数，不是结构化的披露时间戳过滤（对比 iFinD
  `search_news`/`search_notice` 的 `time_start`/`time_end` 是必填且与实际发布时间对齐，见
  `docs/data-sources/ifind.md` §5）。
- Tavily 标题级结果**没有可用的发布时间戳**（`fetch_titles_tavily` 用 `window.as_of` 或抓取时刻
  兜底，见 `backend/data/news_adapters/tavily.py` 的 `published_at` 处理），本质是"抓取时刻"不是
  "新闻发生时刻"。
- 结论：只能用于**当前决策辅助/研究提示（③研究裁量道）**，历史回测/信号构建一律不采信这两个源
  给出的"历史窗口"结果。

## 5. 明仓接线现状

- **Anspire（生产在用，主源之一）**：`backend/data/news_adapters/anspire.py:AnspireAdapter`
  （L13）包一层 `fetch_stock_news_anspire`，注册于
  `backend/data/news_adapters/registry.py`（`"anspire": AnspireAdapter`，L16）。
- **Tavily（生产在用，标题级兜底）**：`backend/data/news_adapters/tavily.py:TavilyAdapter`
  （`provides_content = False`，明确标注不含正文），注册于 registry.py（`"tavily": TavilyAdapter`，
  L17）。
- **默认启用列表**：`settings.news_adapters_enabled` 默认值只有 `["eastmoney"]`
  （`backend/config.py` L260），Anspire/Tavily/iFinD 是否实际参与需看运行时 `.env`/配置覆盖，
  不要假设默认就全部启用。
- 两者定位历史上未变，M61 审计本节"未深挖"，如需更细行为（如审计分阈值 `anspire_news_min_score`
  默认75 如何影响过滤率）需另起专项验证再补充本手册。

## 6. 坑与注意

1. **不要把 `days`/`FromTime`/`ToTime` 当成 PIT 保证**——这是搜索范围窗口，不是发布时间过滤，
   两者有本质区别（对照 iFinD news-mcp 反而是干净的，见 `ifind.md`）。
2. **Tavily 标题级结果不含正文**，`TavilyAdapter.provides_content = False` 已在代码里显式标注，
   不要误以为可以直接拿它做内容分析，只能做标题级信号/补量。
3. **Anspire 的 query 拼法是精心调过的固定模板**（含"公告 业绩 订单 减持 立案 回购"等关键词组），
   改动这个模板会影响审计过滤逻辑的召回率，如需调整应连同 `evidence_from_*` 审计逻辑一起评估。
4. **两者都需要对应 API key 才生效**（`ANSPIRE_API_KEY`/`TAVILY_API_KEY`），未配置时函数直接返回
   空列表，不会报错，调试时先查 `.env`。
5. **禁止用这两个源做历史回填/回测新闻特征**——M61 D8 已确认"新闻层重框定"里干净历史数据要用
   iFinD 而非 Anspire（Anspire 无历史正文可回填，阶段0探针已证实）。
