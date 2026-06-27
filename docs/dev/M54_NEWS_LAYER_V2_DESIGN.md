# M54 新闻层 v2 — 多源可插拔 · 正文级 · 多信号综合评分（设计 spec）

> 状态文档（docs/dev，maintainer-only）。承接 M52 收口裁决（标题级新闻情感干净 OOS 证伪）
> 与 M53 外部数据源接入。**全程 observe-only / default-off / 生产 diff=0 / 不污染 legacy+capable
> 预注册候选 / 独立 OOS 命名空间。** 经 2026-06-28 brainstorming 定稿，路线 A（纵向薄切片）。

## 0. 背景与动机

- **M52 收口裁决（2026-06-28）**：sonnet 干净三腿 OOS（50 支 / 42 IC天 / 全覆盖 / 0 失败）证实
  legacy/slim/m52 **无显著差异、全负 IC、无一过门**。结论：标题级新闻情感（任何过滤变体、
  任何模型）**无短周期预测力**，瓶颈在信号本身。详见 `paper_trading/m52_oos_preregister.md` §阶段6。
- **决定性新发现**：M52 全程建立在「26 字纯标题、零正文」之上。两个主力源**都返回正文却在入库口丢弃**：
  - 东财 `backend/data/news.py:141` 取到 `content`→ `:146` return 只留标题/链接/时间/来源，**正文丢**。
  - Anspire（占库 96%）`:399` 读 `content` 仅用于判重 → `:411` 建 `RawNews` 不含 content，**正文丢**。
  - DB `news.summary` 列 100% 为空（0/2551）。
- **源结构纠偏**：库内 96% 是 Anspire 财经媒体（证券时报网等），**Tavily 仅占 4%**（兜底），
  iFinD MCP 已是第一兜底（`config.py:305`）。所以问题不是「只用 Tavily」，而是「全链路只留标题」。
- **兆易创新教训**：一天内新闻猛变 = 一个事件的几十篇转载/二手评论灌爆情感分。**机械堆源会更糟**
  （更多评论=更多噪声）。真正的修法是事件聚类 + materiality 加权 + 用「源多样性」而非「数量」做置信。

## 1. 目标与非目标

**目标（两者并重）**：
1. **基建（产品/工程价值，与 alpha 无关照样上线）**：多源可插拔、统一 evidence schema、拉正文、
   用户自选/自接源；"处理方式源无关" = 换/加源不改任何评分逻辑（OpenBB「connect once, consume everywhere」）。
2. **alpha（须 OOS 挣到启用资格）**：正文级 + 多信号综合评分，目标跑赢 legacy。架构上线不以 alpha 为门槛，
   但 v2 评分模型 default-off，靠独立预注册 OOS 决定是否启用。

**关键澄清——"源无关"的真正含义**：不是「输出与源无关」（更好的源理应更好结果），而是
**「处理与源无关」**——任何源归一成同一 evidence 对象、走同一管线，适配器绝不碰评分。

**非目标 / Stop conditions**：
- 不动生产 legacy（`sentiment_news_pack_enabled=False` 不变）；不污染 legacy+capable 预注册候选。
- 未过独立 OOS 门即启用 v2 / 接入 live test2 / 改情感权重 / 外溢到 official signal·仓位·scheduler。
- 不机械堆源充数（无 dedup/materiality 的多源会放大 whipsaw）。
- 把探索性 IC 当统计裁决。

## 2. 架构分层（每层单一职责、接口清晰、可独立测试）

```
┌─ Source Adapters (可插拔) ─────────────────────────────┐
│ AnspireAdapter  EastmoneyAdapter  iFinDAdapter  TavilyAdapter  <用户自接>
│ 单职责: 从某源取数 → 吐 list[NewsEvidence]（含正文）；绝不评分
└──────────────┬─────────────────────────────────────────┘
               │  统一 NewsEvidence（客观事实）
┌──────────────▼─ Normalize + Dedup/Cluster ────────────┐
│ 跨源按 url规范化/标题相似/共享 entities/时间邻近 聚成 EventCluster
│ source_diversity = 簇内不同 provider 数（非文章数）← 反 whipsaw
│ 只剔明显垃圾（榜单/广告/纯行情），保留广度（06-18 教训）
└──────────────┬─────────────────────────────────────────┘
┌──────────────▼─ 分级抽取(LLM, 结构化) ─────────────────┐
│ 第1层 廉价预筛(便宜档/规则): relevance/materiality/event_type(标题+entities)
│ 第2层 强模型啃全文: 仅 materiality高/直接相关/簇内分歧 → 读全文 → ClusterScore
│ 其余: 标题级轻打分(content_depth=title_only)
└──────────────┬─────────────────────────────────────────┘
┌──────────────▼─ 确定性融合 + 降级(可审计) ─────────────┐
│ news_score(簇加权) ⊕ flow_score(真实资金流,独立通道) → composite + confidence
│ 缺失永远显式 降confidence + 打flag，绝不塞冒充信号的中性0
└──────────────┬─────────────────────────────────────────┘
               ▼ NewsSignalV2 候选(default-off) — 独立 OOS,赢 legacy/legacy+capable 才启用
```

**边界铁律**：适配器只「取数+归一」，评分逻辑全在其下游 → 真正源无关、用户可自接。

## 3. 数据模型（两层严格分离：源能给的事实 / 管线算的判断）

### 3.1 适配器输出 `NewsEvidence`（只有客观事实，扩展现有 `RawNews`）
```python
@dataclass
class NewsEvidence:
    symbol: str
    title: str
    url: str
    published_at: datetime
    source_name: str            # 媒体名,如 "证券时报网"
    provider: str               # 适配器: eastmoney/anspire/ifind/tavily/<用户>
    content: str | None = None  # 正文全文(拉到才有)
    content_status: str = "title_only"   # full | excerpt | title_only ← 缺正文降级原语
    language: str = "zh"
    fetched_at: datetime | None = None
    raw: dict | None = None     # 源特有字段逃生舱;核心不依赖
```
无任何 relevance/sentiment/materiality —— 派生字段是下游的事。

### 3.2 适配器接口契约（用户自接靠它）
```python
class NewsSourceAdapter(Protocol):
    name: str            # "eastmoney"
    requires_key: bool
    provides_content: bool
    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]: ...
```
用户自接 = 实现 Protocol + config 注册，不碰核心。config 决定启用哪些源/优先级/是否拉正文；
默认 `eastmoney`（直连免费、无 key）。

### 3.3 管线派生对象（适配器永不填）
```python
@dataclass
class EventCluster:
    cluster_id: str; symbol: str
    members: list[NewsEvidence]
    event_type: str            # earnings/contract/regulatory/flow/opinion/...
    representative_title: str
    source_diversity: int      # 不同 provider/域名数(非文章数)
    entities: list[str]        # 用于跨公司区分(长鑫 vs 兆易)
    first_seen: datetime

@dataclass
class ClusterScore:
    relevance: float; sentiment: float; materiality: float
    horizon: str; event_type: str
    catalysts: list[str]; risks: list[str]
    evidence_refs: list[str]   # 引用的 url(可审计)
    confidence: float
    content_depth_used: str    # full | title_only

@dataclass
class NewsSignalV2:
    composite: float; news_score: float; flow_score: float | None
    confidence: float
    degradation_flags: list[str]
    contributing_clusters: list[str]
```

### 3.4 持久化（扩展非重建）
`news` 表加 `content TEXT`、`provider TEXT`（`summary` 列闲置，正文进 `content`）。
`RawNews` 保留兼容；`NewsEvidence` 为新归一对象。入库口（东财 `:146`、Anspire `:411`）改为不丢 content。

## 4. 处理管线细则

### 4.1 归一 + 聚类
- 清洗去重（exact URL）→ 跨源聚 EventCluster（URL 规范化 / 标题相似 / 共享 entities / 时间邻近）。
- `source_diversity` = 簇内**不同 provider 数**。只剔明显噪声，保留广度。

### 4.2 分级读正文（成本/信号平衡）
| 层级 | 处理 | 成本 |
|---|---|---|
| 第0层 全部存正文 | 入库口不丢 content | ~0(本就抓了) |
| 第1层 廉价预筛 | 便宜档/规则 → relevance/materiality/event_type | 低 |
| 第2层 强模型啃全文 | 仅 materiality高/直接相关/簇内分歧 → 读全文出 ClusterScore | 高,只花刀刃 |
| routine/低materiality | 标题级轻打分,title_only | 极低 |

### 4.3 确定性融合（可审计,不靠 LLM 拍脑袋）
```
cluster_weight = materiality × relevance × freshness_decay × diversity_weight(source_diversity)
news_score     = Σ(sentiment × cluster_weight) / Σ(cluster_weight)
flow_score     = s_flow_data            # 复用 m52_flow_floor 真实资金流,独立通道
composite      = 置信度加权融合(news_score, flow_score)
                 ├ 同号 → 升 confidence
                 └ 背离 → 降 confidence、缩幅度
```
`diversity_weight` 用不同源数 → "1 源 × 50 转载" 拿不到高权重 = **结构上修兆易 whipsaw**。

### 4.4 降级矩阵（某类缺失——铁律：显式降 confidence + flag，绝不塞冒充信号的中性 0）
| 缺失 | 处理 | flag |
|---|---|---|
| 无新闻/全 title_only | 用现有的算,confidence↓ | `NEWS_THIN` |
| 无资金流 | 退化纯新闻,confidence↓ | `FLOW_MISSING` |
| 某簇仅标题无正文 | 该簇分打 confidence 折扣 | `content_depth=title_only` |
| 两者皆缺 | 中性 + 极低 confidence + flag,**不进 IC 主样本** | `DEGRADED` |
OOS 中低 confidence/降级窗口**单独追踪、不静默平均进主样本**（直接套用 M52 中性-fallback 污染教训）。

## 5. 建设路线（已选 A；B/C 留档备查）

- **A 纵向薄切片【已选】**：先用现有 2 源（东财/Anspire）建最小可插拔层（适配器接口 + evidence schema +
  存正文）+ 只融合「正文情感 + 资金流」，上线基建并跑 OOS；再在验过的骨架上扩源（iFinD/Tavily/用户）
  + 扩信号（公告/龙虎榜）。最省力、最快出验证、满足两者并重。
- **B 基建完整优先**【备查】：先建全套多源注册表 + 完整 schema + 所有信号适配器再评分。架构最全但出
  验证最慢、有在未验证信号上过度投入的风险。
- **C 评分模型优先**【备查】：先拿现有数据调评分科学再建源抽象。但没正文,调评分价值有限。

## 6. 信号类别取舍（4 类都要,分期）

| 类别 | 期 | 理由 |
|---|---|---|
| 新闻正文情感 | **一期** | v2 主体,验「正文 vs 标题」核心 |
| 资金流(s_flow_data) | **一期** | 已有真实数据底座,边际成本低,独立确认通道 |
| 公告/龙虎榜 | **二期(可能最高价值)** | 公告是驱动价格的材料事件;需先接 M53 a-stock-data。若一期正文仍无 IC,这条是新闻层真正出路 |
| 研报/分析师预期 | **延后** | 成本高、信号慢 |

## 7. 验证门控与上线路径（observe-only）

- **独立预注册 OOS**：v2 作为 `news_layer_v2` 候选，与 `legacy-fast`、`legacy-capable` 并排跑**同窗口/同
  universe/同缓存隔离**（复用 `m52_clean_oos.py` harness，新增 variant）。**另开预注册判据**，不复用也不污染
  test2 的 legacy+capable 候选判据。
- **晋级门（沿用 M52 纪律）**：IC mean ≥ 0.04 / ICIR ≥ 0.40 / 分桶单调 / ≥20 非重叠 IC 天 / 足量新鲜样本 /
  fallback<10%；低 confidence/降级窗口单独追踪。
- **上线前置**：绝对门全过 **且** 用户显式 epoch-reset 授权。先只出研究裁决，不上 live。
- **主对照问题**：v2（正文+资金流，分级深读，diversity 加权）能否在干净 OOS 上**显著 > legacy**。
  若否 → 转二期公告/事件路线或将新闻降级为上下文（非 alpha 源）。

## 8. 关键可行性风险（实施第一件事先验）

- **历史正文能否回填**：现有 2551 行无正文；东财/Anspire 多半只返回**近期**正文。
  - 若**可回填** Apr–Jun 窗口 → 一期 OOS 几天内出结果。
  - 若**不可回填** → 一期改为「从现在起向前采集正文」，数周后才够样本 OOS。
  - **实施第 1 个任务 = 拿 1–2 支股票实测东财/Anspire 能否取历史正文**，据此定一期时间线。

## 9. 实施阶段（路线 A）

- **阶段0**：可行性验（历史正文回填）+ `news` 表加 content/provider 列 + 入库口停止丢 content（东财/Anspire）。
- **阶段1**：抽出 `NewsSourceAdapter` Protocol，把现有东财/Anspire 改造成适配器（行为等价，default 走旧路 diff=0）。
- **阶段2**：Normalize+Cluster 层（事件簇 + source_diversity）。
- **阶段3**：分级抽取（预筛 + 选择性全文）+ ClusterScore schema。
- **阶段4**：确定性融合 + 降级矩阵 → NewsSignalV2（default-off）。
- **阶段5**：`m52_clean_oos.py` 加 `news_layer_v2` variant + 独立预注册 + 跑 OOS 出裁决。
- **阶段6（条件）**：若一期赢 → 扩源（iFinD/Tavily/用户自接）+ 扩信号（公告/龙虎榜，接 M53）。

## 10. 开放决策（实施前确认）

- content 存新列（已定：加 `content` 列，不复用 summary）。
- 聚类相似度阈值 / freshness_decay 半衰期 / diversity_weight 函数形：实施时据数据调,先给保守默认。
- 第2层「啃全文」的 materiality 触发阈值:先保守(宁可多读),据 OOS 调。

## 错误记录
| 错误 | 尝试 | 解决 |
|------|------|------|
| （待填） | | |
