"""M54 阶段7b — 确定性作用域分类 + 域共享 digest 键控（零 LLM）。

只挂 v2 管线，不接触 legacy 情感打分链或生产权重。将 ``EventCluster``
（见 ``backend.data.news_clustering``）归入四个作用域之一
（``market``/``policy``/``sector``/``stock``），并为非个股专属簇生成
一个跨股可复用的共享 digest 缓存键，使同一政策/行业事件簇每天只需
打一次分。

设计约束（见任务侦察）：
- 分类规则纯确定性（关键词/实体计数），不调用任何 LLM。
- 共享键必须兼容 ``news_extraction.py`` 现有的缓存 seam
  （目前该文件没有任何缓存——本模块只负责“给出键”，不新建第二套缓存
  存储系统；调用方可直接把 ``shared_digest_key`` 当作
  memoization/cache 字典的 key，或未来持久化表的主键片段）。
- 复用 ``news_clustering._EVENT_KEYWORDS`` 的 ``regulatory`` 词表思路
  （此处独立维护一份等价的政策关键词表，避免 import 私有 `_` 前缀符号）
  以及 ``news_extraction._BROAD_ENTITIES`` 风格的行业词表来做 sector 判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from backend.data.news_clustering import EventCluster

Scope = Literal["market", "policy", "sector", "stock"]

SCOPES: tuple[Scope, ...] = ("market", "policy", "sector", "stock")

# 政策/监管关键词（与 news_clustering._EVENT_KEYWORDS["regulatory"] 同源词汇，
# 额外补充宏观政策常见词）。命中任一即视为政策域。
_POLICY_KEYWORDS = (
    "公告",
    "监管",
    "问询",
    "处罚",
    "立案",
    "减持",
    "增持",
    "回购",
    "停牌",
    "复牌",
    "风险提示",
    "政策",
    "央行",
    "国务院",
    "发改委",
    "证监会",
    "财政部",
    "降准",
    "降息",
    "利率",
    "监管层",
    "新规",
    "指导意见",
    "法规",
)

# 大盘/市场整体关键词——命中且无明确个股实体时归入 market。
_MARKET_KEYWORDS = (
    "大盘",
    "沪指",
    "深指",
    "上证",
    "深证",
    "创业板指",
    "北向资金",
    "两市",
    "市场情绪",
    "全市场",
    "指数",
    "A股",
    "股市",
)

# 行业/板块关键词（复用 news_extraction._BROAD_ENTITIES 风格词表）——
# 命中且没有单一明确个股指向时归入 sector。
_SECTOR_KEYWORDS = (
    "半导体",
    "新能源",
    "机器人",
    "算力",
    "芯片",
    "电池",
    "白酒",
    "存储芯片",
    "光刻胶",
    "DRAM",
    "HBM",
    "GPU",
    "CPO",
    "AI",
    "光伏",
    "储能",
    "医药",
    "军工",
    "地产",
    "银行",
    "证券",
)


def classify_scope(cluster: EventCluster) -> Scope:
    """确定性规则分类 ``EventCluster`` 的作用域，零 LLM 调用。

    判定顺序（先命中先得，互斥优先级由业务语义决定）：
    1. ``policy``：标题命中政策/监管关键词。
    2. ``market``：无可识别个股实体、且命中大盘/市场关键词
       （或代表标题里完全没有股票代码/公司实体）。
    3. ``sector``：命中行业关键词，且簇涉及的公司实体数 >= 2
       （多股同行业 = 行业共性事件，非单一个股专属）。
    4. ``stock``：默认——具备明确单一个股指向的簇。
    """
    title = cluster.representative_title or ""
    company_entities = _company_entities(cluster)

    if any(keyword in title for keyword in _POLICY_KEYWORDS):
        return "policy"

    if not company_entities and any(keyword in title for keyword in _MARKET_KEYWORDS):
        return "market"

    if not company_entities and not _has_symbol_signal(cluster):
        # 没有任何个股线索（代码/公司实体），也没命中显式大盘词——
        # 仍归为 market 作为兜底，因为它显然不是个股专属簇。
        return "market"

    if any(keyword in title for keyword in _SECTOR_KEYWORDS) and len(company_entities) >= 2:
        return "sector"

    return "stock"


def _has_symbol_signal(cluster: EventCluster) -> bool:
    if cluster.symbol:
        return True
    return bool(_company_entities(cluster))


def _company_entities(cluster: EventCluster) -> set[str]:
    """从簇实体列表中提取“看起来像公司/个股”的实体（排除纯行业关键词）。"""
    entities = {entity.strip() for entity in cluster.entities if entity.strip()}
    return {
        entity
        for entity in entities
        if entity not in _SECTOR_KEYWORDS
        and entity not in _MARKET_KEYWORDS
        and not entity.isdigit()
    }


def shared_digest_key(scope: Scope, cluster: EventCluster, as_of: datetime | date) -> str:
    """生成域共享缓存键（scope + 簇标识 + 日期）。

    - ``stock`` 域没有共享意义（每簇本就是单股专属），仍返回一个稳定键，
      调用方应据此判断是否走共享路径（``scope != "stock"``），而不是靠
      key 格式本身区分。
    - 非 stock 域用“域标识”而非簇的完整 ``cluster_id``（后者按 URL/标题
      hash 生成，同一事件不同来源/措辞会产出不同 cluster_id，破坏跨股
      复用）；这里改用 ``event_type`` + 归一化后的代表标题/行业关键词
      做域内事件标识，使同一政策/行业事件当天稳定映射到同一个键。
    - 键格式设计为可直接作为 dict key 或未来 DB 表主键片段使用，兼容
      ``news_extraction.py`` 目前缺失的缓存 seam（该文件尚无任何缓存，
      本函数不建立新的存储系统，只提供确定性键）。
    """
    date_key = _as_date_key(as_of)
    if scope == "stock":
        return f"stock:{cluster.symbol}:{cluster.cluster_id}:{date_key}"

    domain_id = _domain_identifier(scope, cluster)
    return f"{scope}:{domain_id}:{date_key}"


def _as_date_key(as_of: datetime | date) -> str:
    if isinstance(as_of, datetime):
        return as_of.date().isoformat()
    return as_of.isoformat()


def _domain_identifier(scope: Scope, cluster: EventCluster) -> str:
    if scope == "policy":
        # 政策簇按事件类型归并——同一天的监管/政策事件共享一份打分。
        return f"event_{cluster.event_type or 'unknown'}"
    if scope == "market":
        return "broad"
    if scope == "sector":
        sector_terms = sorted(
            keyword for keyword in _SECTOR_KEYWORDS if keyword in (cluster.representative_title or "")
        )
        if sector_terms:
            return "sector_" + "_".join(sector_terms)
        return f"event_{cluster.event_type or 'unknown'}"
    return cluster.cluster_id


@dataclass
class ScopeSharingPlan:
    """簇作用域共享计划——供编排器决定谁走共享打分、谁按股打分。"""

    shared_clusters: dict[str, list[str]] = field(default_factory=dict)
    """shared_digest_key -> 该键下的 cluster_id 列表（同键簇当天只需打一次分）。"""

    stock_only_clusters: list[str] = field(default_factory=list)
    """按股独立打分的 cluster_id 列表（scope == "stock"）。"""

    scope_by_cluster: dict[str, Scope] = field(default_factory=dict)
    """cluster_id -> 分类到的 scope，供调用方审计/落盘。"""

    naive_llm_calls: int = 0
    """未做域共享时的估算 LLM 调用数（每簇一次）。"""

    shared_llm_calls: int = 0
    """域共享后的估算 LLM 调用数（去重后的 shared key 数 + stock-only 簇数）。"""

    @property
    def estimated_savings(self) -> int:
        return self.naive_llm_calls - self.shared_llm_calls


def plan_scope_sharing(
    clusters: list[EventCluster],
    symbols: list[str] | None = None,
) -> ScopeSharingPlan:
    """对一批簇分类作用域，规划共享 vs 按股打分，并估算 LLM 调用数节省。

    ``symbols`` 目前仅用于文档化/未来扩展（例如校验传入簇集合覆盖了
    哪些关注列表股票），当前实现不依赖它做出决策——分类完全基于簇
    自身内容（确定性，符合"作用域分类零 LLM"的铁律）。
    """
    plan = ScopeSharingPlan()
    plan.naive_llm_calls = len(clusters)

    as_of_by_cluster: dict[str, datetime] = {
        cluster.cluster_id: cluster.first_seen for cluster in clusters
    }

    for cluster in clusters:
        scope = classify_scope(cluster)
        plan.scope_by_cluster[cluster.cluster_id] = scope

        if scope == "stock":
            plan.stock_only_clusters.append(cluster.cluster_id)
            continue

        key = shared_digest_key(scope, cluster, as_of_by_cluster[cluster.cluster_id])
        plan.shared_clusters.setdefault(key, []).append(cluster.cluster_id)

    plan.shared_llm_calls = len(plan.stock_only_clusters) + len(plan.shared_clusters)
    _ = symbols  # reserved for future coverage checks; not used in the deterministic decision
    return plan
