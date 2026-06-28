# M54 新闻层 v2 — 干净 OOS 预注册判据（先于跑数落盘）

> 2026-06-28 落盘。承接 M52 收口（标题级情感无 IC）与 M54 设计 spec。**先写阈值与窗口，结果出来只对照、不事后挑解释**（守干净 OOS 纪律，防 p-hacking）。
> 全程 observe-only / 生产 diff=0 / 独立 OOS cache 命名空间 `oos_news_v2` / 不动 live test2 / 不污染 M52 的 legacy+capable 候选判据。

## 0. 前置数据依赖（必须先满足才有意义）
v2 的价值在"读正文"。但 DB 现有历史 news 行 **content 全为 NULL**（content 列在阶段0 才加）。东财正文回填**仅 ~59 天**（探针实测到 2026-04-29）。
**因此跑前必须先做内容回填**：对 universe 在窗口内回填东财正文（覆盖 ~Apr29–今），否则 v2 会因 content_status=title_only 大量走降级（DEGRADED/NEWS_THIN）→ 不是对"正文级"的真实检验。
- 若回填覆盖足 → 用历史窗口 OOS。
- 若覆盖不足 → 改"从现在起向前采集正文"，数周后样本够再 OOS。
**回填覆盖率（有正文窗口/总新闻窗口）是跑前的 go/no-go 门：< 50% 不开跑，改向前采集。**

## 1. 固定设置（跑前锁定）
- **Universe**：`paper_trading/test3_universe_50.json`（50 支）。
- **窗口**：跑前据回填覆盖确定；优先 2026-04-29..（今-7d）以匹配东财回填可达范围。
- **Lookback**：3 天。**Horizons**：h3d / h5d。
- **缓存隔离**：ns `oos_news_v2`，禁止写生产 sentiment_cache。
- **DEGRADED 排除**：degradation_flags 含 DEGRADED 的窗不进 IC 主样本（harness 已实现 skip + 计数）。

## 2. 对照腿（同窗口/同 universe/同缓存隔离，各自独立 ns）
| 腿 | 含义 |
|---|---|
| legacy-fast | M52 收口基线（全标题、便宜档） |
| legacy-capable | legacy 广度 + capable 模型（M52 已证伪此杠杆为负，作下界对照） |
| **news_layer_v2** | 本里程碑候选：正文级 + 分级抽取 + source_diversity 加权 + 资金流融合 |

## 3. 主目标：相对排序
同一样本下 news_layer_v2 vs legacy 的 IC/ICIR 排序。**主裁决看相对排序**（M52 教训：绝对值易虚高，稳健的是排序）。

## 4. 绝对晋级门（次要，过不了也不影响主裁决，但上 live 必须全过）
- IC mean ≥ 0.04 / ICIR ≥ 0.40 / 分桶单调 / 非重叠 stride IC 天数 ≥ 20 / 足量新鲜样本 / fallback<10% / DEGRADED 已排除。

## 5. 预注册决策规则（跑前写定）
1. **news_layer_v2 显著 > legacy（Δ IC ≥ +0.02 两 horizon）且过绝对门** → v2 列为候选（仍需用户显式 epoch-reset 授权 + test2 边界才上 live）。
2. **v2 ≈ legacy（Δ<0.02）或仍为负** → v2 正文级也无 alpha；**复证 M52 根本结论"新闻短周期无预测力"**；保留 v2 代码与 harness 作资产，生产维持 legacy，转二期（公告/龙虎榜事件路线）或将新闻降级为上下文。
3. **v2 优于 legacy 但不过绝对门** → 有方向但样本/质量不足，扩样本/扩源（iFinD/公告）后再预注册一轮。
4. 任一上 live 前置：绝对门全过 **且** 用户显式授权。本轮只出研究裁决。

## 6. 诚实 caveat（跑前写定）
- 东财正文 ~140 字（是正文 lead/摘要，非超长全文）；回填仅 ~59d；50 支样本 + 短窗，h5d 非重叠 IC 天可能 < 20（样本硬限）——这会卡绝对门 h5d，但不否定主目标（相对排序）。
- v2 OOS 用 LLM 打分（capable 档），跨多个额度窗口、需数天；缓存接力、失败分不落（沿用 M52 纪律）。
- 绝对值不可信，验的是相对排序在干净 OOS 上能否站住。

## 7. 结果（跑后填）
_(待回填，严格对照 §5)_
