# iFinD MCP — 当前接线、权限与验证边界

> 更新：2026-09-24。代码路径核对不等于账号可用、源覆盖完整或生产数据通过质量门。
> 套餐档位及刷新日未知；2026-09-24 的实际 MCP 回执明确显示当前账户请求用量已耗尽。

## 接线现状

| 能力 | 当前代码入口 | 边界 |
|---|---|---|
| A 股日线行情 | `backend/data/market.py` 注册 `ifind_cn`，`backend/data/market_sources.py::fetch_cn_daily_ifind`，priority 60；仅 `IFIND_MCP_ENABLED` 和 token 同时启用后才进入 CN fallback | 兜底源，排在其他已配置源之后；项目 client 的 QPS 限制为 1，单次延迟曾约 10 秒。请求显式要前复权，校验返回复权参数，按表头解析并滤除不完整 OHLCV；任何口径不符都应失败并交给 fallback，不能混价。函数现有 `@_retry(max_attempts=2)` 是既有行情调用行为，不授权审计/冻结实验重试 |
| 新闻/标题 | `backend/data/news.py::fetch_news_ifind`, `fetch_titles_ifind`；`backend/data/news_adapters/ifind.py::IFindAdapter`，接入现有新闻聚合 | 新闻/公告解析与源错误仍须按实际日志、日期和失败分母记录；通道存在不代表某日覆盖完整 |
| 公告分类 | `backend/data/category_fetchers.py::fetch_announcements_ifind_notice`；`backend/data/global_disclosures.py` 有明确调用 | M61 category provider，可能经 `backend.data.category_registry` 被读取或由 backfill 调用 |
| 公司事件 | `fetch_corporate_events_ifind`，provider `ifind_events` | 按返回日期/字段核实；空返回不等于无事件 |
| 股东数据 | `fetch_holders_ifind_shareholders`，provider `ifind_shareholders` | 有报告期与单位解析；无日期/字段不完整的记录会降级，不能补零 |
| 港美股/其他分类 | `fetch_overseas_ifind_global`，provider `ifind_global`；工具能力还含指数/板块端点 | 按单独市场、币种、日期与组成口径评估；不代表 HK/US 晋升正式路径 |
| 财务、板块及其他接口 | `backend/data/market_capabilities.py` / `backend/data/external_sources.py` 有候选能力元数据；`backend/tools/m61_source_health.py` 有若干探针 | 元数据登记不是对应生产消费者或已核验历史覆盖。逐项探针会请求真实服务 |

四个 endpoint id 为 `hexin-ifind-ds-stock-mcp`、`hexin-ifind-ds-news-mcp`、
`hexin-ifind-ds-index-mcp`、`hexin-ifind-ds-global-stock-mcp`。服务端工具集可能变化；
当前工具名和参数应以实际授权下的 `tools/list` 返回为准，不沿用 2026-07 文档里
“19 个工具”的固定清单。客户端在 `backend/data/ifind_mcp.py`，默认关闭，配置项为
`IFIND_MCP_ENABLED`、`IFIND_MCP_TOKEN`、`IFIND_MCP_BASE_URL`、
`IFIND_MCP_TIMEOUT_SECONDS`、`IFIND_MCP_QPS_LIMIT`；当前代码默认 QPS=1、超时 30 秒。
这是项目 client 的进程级请求起始间隔限制，不应写成官方服务端限流合同；仍禁止并发绕过项目限制。

## 额度与调用项

[官方 iFinD MCP 价格页](https://mcp.51ifind.com/#/pricing)于 2026-09-23 查看时显示：

| 页面套餐 | 页面价格 | 页面调用额度 | 页面 CSV 项数 |
|---|---:|---:|---:|
| Basic | ¥40 | 3,000 calls | 5 × 2,000 items |
| Pro | ¥99 | 8,000 calls | 100 × 6,000 items |
| Flagship | ¥199 | 20,000 calls | 300 × 12,000 items |

该快照没有确认当前项目账号订阅何档，也没有弄清 `items`、期限、共享/重置规则及
各工具如何计费；不得据此估算可用请求数或账单，不可推断已续费/可用。套餐信息会变动，
实际以调用前账户页面/回执为准。代码的 QPS=1 是运行限制；新套餐说明不构成提高限速的依据。

## 最小只读缺口审计

2026-09-24 已按核定范围发出一次只读 `603986 search_news` 请求，参数为
`time_start=2026-09-21`、`time_end=2026-09-23`、`size=5`；没有调用 `search_notice`，没有重试。
响应中 `data` 只有 `answer`，明确说明当前账户 MCP 请求用量已耗尽，没有新闻记录可解析。
原始回执保存在仓库外，SHA-256 为
`4de2d3b1b10808467d65e60d8134137d637b8fb8d5f3f2a596f1bcaa54f8fa93`。额度耗尽目前确证；套餐档位与刷新日仍未知。

09-23 日测日志报告新闻/公告解析错误，但当时原始响应未保存；不能据 09-24 answer-only 配额回执
反推两次错误同因。旧解析器假定 `data.data` 存在，遇到 answer-only JSON 会在解析空串时失败。
本候选工作树已增加显式 quota 分类并在同一单项新闻调用停止；公告分类会将 answer-only 配额错误
作为 provider failure 交给既有 category registry 记录降级并尝试原顺序的后续来源。相关 31 项
m63/iFind 聚焦检查通过，整体 `make verify` 由主任务另行确认。解析修复只改善错误分类和停止行为，
不会恢复额度、补造新闻或提高来源覆盖。

后续新增查询前先用本地一致快照核对缺口：官方池/当前持仓、symbol、类别/字段、行情日期或财报报告期、
披露/采集时间、source、价格口径/单位、缺失和降级原因；快照 SHA-256，以 `mode=ro&immutable=1`
读取，不访问或修改活动 DB。若本地证据已能说明缺口，停止于此。当前账户已返回用量耗尽；不要再发
iFinD 请求、升级套餐、推断额度刷新日期或安排重试。

若确需比较源，最小入口为：

```text
python3 -m backend.tools.m61_source_health --list
python3 -m backend.tools.m61_source_health --source ifind --category <one-category> --symbols <one-symbol> --out /private/tmp/ifind-one-probe.json
```

第一条只列登记矩阵；第二条是真实 API 探针，会按固定历史问题逐 symbol 调用。
本例单一 category/symbol 至多一个探针调用，仍可能产生费用并受账号额度限制；当前额度已耗尽，
不得运行第二条。未来如额度状态由账户页面/回执确认恢复，仍须有明确缺口、字段/样本、预算和授权。
输出需留原始回执/hash、真实失败和未知完成状态；不重试，
不提高 QPS，不把 `coverage` 数量等同可信度、PIT 或生产适用性。

不要用 `python3 -m backend.tools.m61_backfill` 做只读验证：它会通过 provider 获取数据并写 M61
类别表。`backend.tools.coverage_snapshot` 走应用默认 SessionLocal，不是对活动 DB 的不可变审计替代。
禁止在此步骤调用回填、改配置开启源、刷新历史价格/财务、修改官方面板或账本。维护写入仍需 P0-B2
独立的备份、影响审核、窗口、回滚与明确授权。

## PIT 与字段解释边界

| 数据类型 | 当前可用结论 |
|---|---|
| 历史财务报告期 | 报告期可按历史日期查询的旧测试，不等于披露日或可重建历史修订链。缺 disclosure/as-of 证据不得作为严格 PIT 回测输入 |
| 一致预期/盈利预测 | 滚动最新值不可反推过去时点；只可在有标注的当前研究语境，禁止回测 |
| 风险指标 | 旧测试见滚动的一年窗口到最新，不是历史固定 as-of 指标 |
| 日线 | 必须核对复权方式、交易日、OHLCV 完整性、单位与公司行动；源标签/代码通过不等于历史现金 NAV 可靠 |
| 公司事件/公告/股东 | 每条保留报告期、发布/发生/采集日期和解析质量；未知、空响应、解析失败、权限拒绝分开记 |
| 行业/指数成分 | 需确认查询返回历史当期成分还是当前成分，未核实时不得用于历史成分回测 |
| 港美股 | 另核交易日历、市场代码、币种、调整口径与字段；不得从 A 股同名工具推定 |

## 历史实测记录（有日期，不视为当前回执）

- **2026-07-04**：归档审计及本手册记录过有限探针；部分 `get_stock_financials` 报告期、
  `get_stock_performance` 日频、事件日期及新闻时间过滤返回过数据。`get_risk_indicators` 当时
  表现为“截止日前一年至最新”的滚动窗口。样例及结论只代表当日返回，不认证现在覆盖或权限。
- **2026-07-05**：曾观察到 HTTP 200 中包含“用户使用工具已超限”；不得把这类响应当空数据或成功。
  旧订阅记录约 2026-08-06 到期；不推断当前账号套餐，也不复用旧个人账号结论。
- **2026-09-23**：官方价格页快照如上；账号套餐/调用余额未确认。正式日测日志记有 iFinD 新闻/公告解析错误，原响应未保存，不能据此确定错误类别。
- **2026-09-24**：获准的一次 `603986 search_news`（09-21 至 09-23，size 5）返回 answer-only 的当前账户额度耗尽提示；未请求 `search_notice`、未重试。当前额度耗尽确证，套餐和刷新日未知；原始响应 hash 见上。

对任何运行保持固定分母：请求、响应、解析、权限、超时、限流和未知完成分别登记。
在冻结实验中，失败保持失败且不重试；普通 provider 的现有有限 fallback 也不能抹掉失败来源或证明数据可信。
