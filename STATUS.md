# MingCang — Current Status

> Updated 2026-09-24. Latest formal daily evidence is the 09-23 run, completed at
> 00:25 on 09-24 as `PIPELINE_PARTIAL` (exit 4): Track B completed; One Loop remains
> blocked by adjustment-basis drift. [ROADMAP](docs/ROADMAP.md) is the sole queue;
> [PROJECT](PROJECT.md) is the architecture map.

## Runtime truth

| Surface | Verified state |
|---|---|
| Release | Package/API/frontend version `v0.8.4`; publication requires the matching GitHub tag/release receipt. |
| Configuration (last inspected 09-17) | technical/sentiment 0.6/0.4, quant 0.0, entry 25.0; memory decision context and Atlas disabled; scheduler `manual` (not worker-liveness evidence). |
| Frozen One Loop v1 | 20/20 complete closes (08-19–09-15), 20 unique batches/envelopes, committed eight-card panels; 4/20 degraded. Immutable continuity baseline only. |
| Later dates | 21 complete / 26 compared dates; comparison counts do not make every date complete or clear quality/economic gates. |
| 09-17 | 25/25 official-pool prices refreshed later; original signal/job/panel evidence is absent and was not backfilled. |
| 09-18 | Track B complete; Track A `PIPELINE_PARTIAL` on basis drift for 300394 and 603993. Panel exists but fails integrity. |
| 09-22 | Offline check: 25/25 official and 56/56 watchlist OHLCV/technical checks. Historical rows are not certified PIT/adjusted prices or a same-day run. Formal run remains missing; available run used 09-21 data. |
| 09-23 formal run | 25/25 official signals, 8 committed panel cards, 56/56 broad scan, 6 new + 1 reused labels, 3/3 deep reviews. Track B complete; Track A remains `uncleared_adjustment_basis_drift`; final `PIPELINE_PARTIAL` (exit 4). |
| 09-23 recovery | First attempt stopped on expired OAuth with 11 partial signals in an error run. Recovery ended 00:25:27 with 85 logged calls (official 16, broad 54, labels 6, deep 9, panel 0); this is not token/billing evidence. Auth circuit breaker stops repeated calls after an auth failure but proves neither future login nor quality. |
| 09-24 iFinD | One approved `603986 search_news` request for 09-21–23, size 5, returned answer-only “当前账户MCP请求用量已耗尽”. No notice request or retry. Account quota exhaustion is confirmed; plan and refresh date unknown. Parser/provider now classifies quota failure and stops or falls back; coverage is not restored. |
| 09-24 财务诊断 | 快照 147 只启用 A 股，125 只有财务，最新全为 Q1；现金流缺 50、ROE/资产/权益各缺 44、披露日缺 37。AkShare 实取 000858 得到 H1 与直接财务字段。映射及跳过旧行有缺陷，不能归因于 iFinD；新抓取不证明历史 PIT。 |
| Price/NAV | `blocked_price_basis`; prior audit flagged 20 saved-collection symbols. Two-symbol maintenance below does not certify the full collection or authoritative corporate-action history; no return promotion. |
| Scope | CN daily path. HK/US, news direction, and model experiments are shadow/experimental and do not imply production or trading activation. |

The 09-23 report and outputs are in the user-provided `明仓日测_2026-09-22_23/测试结果.md`
and its evidence directory. Recovery IDs: official `3bbeeeca7af249ed9d77951a9ebe70fa`,
panel `3785c5dac0ff4410ab09c4cfd0368c5d`, broad scan
`56ee6750357f4a089c1a27ac360f31ba`, deep review
`d3fb33bfe40e4885a8824a0836bd44ff`; first-attempt error
`f622a0d9236747c68e3df096fa44afdd`. The read-only final snapshot is
`/private/tmp/mingcang-daily-20260923/final.db`; do not write to it during review.
The canonical start date is non-rolling: preserve frozen artifacts. Clearance records
an operator fact; it does not repair prices or recreate a missing run.

## Implemented capabilities and gates

| Area | State and open gate |
|---|---|
| P0-A panel | Eight-card panel, same-run watchtower/prior-panel delta, explicit no-LLM state and append-only human observations. 09-23 Track B completed. Fresh content quality, real user completion, notification delivery and independently checked outcomes remain separate. Opinion or completed scan is not task completion, delivery, or trade. |
| P0-B price safety | 09-24 20:39 用户批准后已更新 002409/688525 共 2,294 行 OHLCV/ATR 及来源字段。完整备份、逐行 ATR 独立重算、quick_check 通过；其他行情及 63 张非价格表不变。备份位于 `~/.mingcang/backups/`，回执 `mingcang-five-fixes-install-20260924/approved-price-acceptance.json`。原信号/面板不重算；全历史公司行为与 NAV 仍未认证，盘前严格来源/240行预热已接显式开关，默认关闭；24/25历史混源仍阻塞，新增provider前拒绝与complete/partial/blocked回执。 |
| P0-R NAV | Manual-only cash NAV with explicit next-open, costs, halts, partial fills and actions. Clean price basis and authoritative actions required; proxy diagnostics cannot promote returns. |
| P0-C research inputs | 单股上下文和 Piotroski 接严格缺失/时点语义；财务直接金额映射与显式定向补齐。旧标签质量是生成时记录。全池覆盖、修订历史和缺失披露日仍未解决；安装代码不等于生产补数完成。 |
| Research report quality | 深研分开统计新鲜度与文本相关性，显示质量/停止原因及板块长期维度缺口；规则模板不冒充分析师/辩论实际运行。partial 不算完成研究。 |
| P1/P2 experiments | Four-gate audit, saved-window reader, recorder, frozen budgets, optional manifest v2/folds/holdout and bounded local process. Provider identity/billed usage, source/calendar truth, isolated account/credentials and economic approval remain open. See [model contract](docs/dev/MODEL_COMPARISON_CONTRACT.md) for that task only. |
| News/event risk | Explicit experimental offline audit CLI reads a caller-supplied immutable SQLite snapshot and writes an external report only. Snapshot has 50 shadow rows on two dates (07-16, 08-19; latest 36 days old) and zero feedback rows. Stored token values are zero but do not prove zero use/cost. PIT, independent human gold, reconciled cost and forward samples are unverified; direction remains shadow. See [news contract](docs/dev/NEWS_EVENT_RISK_CONTRACT.md) for that task only. |
| Stock-page evidence | Experimental：API/CLI/MCP统一准备，来源追查、人工判断/观察、任务幂等台账。整体UI保持；本地停止不等于远端取消，服务商实际调用/费用未知。真实来源、模型和用户价值仍待验收。 |
| `m63_research --preflight` | Opt-in experimental watchlist/universe validation and capacity/unknown-bound report. Not full-market scan, capacity reservation, source authorization or value acceptance; defaults unchanged. |
| Joint historical research | Real-data replay first: two isolated windows, 772,482 daily rows and 5,474/5,564 observed codes. `make research-test` runs technical replay + news inputs; `research-check` runs code checks. Model arms/NAV incomplete; subscription only, no new API fees. See news contract. Production unchanged. |

实现或测试通过不代表稳定/默认启用；记忆路由、风险政策、历史价格、调度和真实交易均未获晋升。

## Model and source boundary

The five-session GPT-6 heartbeat is expired/`PAUSED`; 09-22 is missing; 09-16 raw
failed initialization and desk never started. No paired result/provider/billing
receipt or economic treatment exists. Do not retry or replace those slots. The
separately approved fixed-25 channel check remains 1/60 reserved; v2 is frozen and
v3 is default-off, `prepared_not_activated`, fake-only. No evidence clears
source/provider truth, billing, isolation or economic approval. See the [model
contract](docs/dev/MODEL_COMPARISON_CONTRACT.md).

## Verification boundary

09-24 v0.8.4：新锁隔离 `make verify` 通过，后端 2,594 passed/14 skipped；前端58项、构建、ESLint、桌面/手机冒烟、Ruff、mypy382文件、文档/卫生/版本检查与依赖审计通过。财务UTC日末边界已修，DB哈希未变；UI/调度未改，启用阻塞保留。

此前研究修复已完成隔离与浏览器验收。
同快照五粮液前后对照、白酒 5 股离线报告完成；外部/模型调用为零、DB 哈希不变。
原联合历史入口仍 partial；独立 GPT-5.5 新闻试跑保留 211 成功、4 失败、1 中断远端结果未知，按用户要求暂停。其结果不是旧 GPT-6 对照或收益验证；此前发布验证见 CHANGELOG。

09-24 首轮回执 `mingcang-stage1-20260924/`：覆盖/新闻盘点及经批准的GPT-5.5五案对照完成；评分差异存在歧义，未证明增益，Luna通道失败保留。第二轮已获授权，四项在现有个股研究区扩展，整体UI不变。

这些检查不认证来源/模型身份、账单、人类完成或收益；日常运行证据单独验收。 Recoverable
documentation originals and archive metadata are indexed in the
[archive digest](docs/evidence/document_archive_digest.md).
