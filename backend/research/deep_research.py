"""[M63 现役] [active] 消费者: backend/api/routes/research.py, backend/research/research_report_gate.py, backend/tools/m63_research.py.
Manual weekend/sector deep research workflow.

This module is deliberately separate from scheduler.py and the daily signal
path. It only runs when called explicitly from CLI or API.
"""
from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import BASE_DIR
from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.database import FinancialMetric, NewsItem, Price, Stock
from backend.data.degradation import emit_degradation
from backend.data.news import RawNews
from backend.data.news_audit import NewsAudit, audit_news_items
from backend.research.agents import ResearchSection, build_research_sections

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeepResearchReport:
    """Result of a manual deep research run."""

    topic: str
    symbols: list[str]
    as_of: str
    summary: str
    path: Path | None
    source_count: int
    risk_flags: list[str]
    retrieval_iterations: tuple[dict, ...] = ()  # evaluator/planner 闭环轨迹
    sections: tuple[dict, ...] = ()
    long_term_framework: dict | None = None
    quality_status: str = "partial"
    source_relevance: dict | None = None
    retrieval_stop_reason: str = ""
    historical_context_sources: tuple[dict, ...] = ()
    # M50 ResearchReportGate verdict (default pass for backward compat).
    # When gate_status == "blocked": file is NOT written; `path` holds the
    # intended-but-unwritten path — callers must check gate_status, not path.
    gate_status: str = "pass"            # pass / warning / blocked / gate_disabled
    gate_reasons: tuple[str, ...] = ()   # blocked reasons or warning messages


def default_output_dir() -> Path:
    """Return the default directory for research reports."""
    return BASE_DIR / "docs" / "research"


def _slug(text: str) -> str:
    """Build a filesystem-safe slug while preserving Chinese characters."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:48] or "deep-research"


def _symbol_names(db, symbols: list[str]) -> dict[str, str]:
    """Return symbol to display-name mapping."""
    rows = db.query(Stock).filter(Stock.symbol.in_(symbols)).all() if symbols else []
    return {row.symbol: row.name for row in rows}


def _latest_price_context(db, symbol: str, *, as_of: str) -> dict:
    """Collect latest close and short-term price context for one symbol."""
    latest = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date <= as_of)
        .order_by(Price.date.desc())
        .first()
    )
    if latest is None:
        return {"symbol": symbol, "available": False, "as_of": as_of, "reason": "cutoff 前没有价格行"}
    older = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date < latest.date, Price.date <= as_of)
        .order_by(Price.date.desc())
        .limit(20)
        .all()
    )
    closes = [row.close for row in reversed(older)] + [latest.close]
    change_20d = None
    if len(closes) >= 2 and closes[0]:
        change_20d = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
    return {
        "symbol": symbol,
        "available": True,
        "as_of": as_of,
        "latest_date": latest.date,
        "latest_close": latest.close,
        "change_20d": change_20d,
    }


def _latest_financial_context(db, symbol: str, *, as_of: str) -> dict:
    """Collect latest point-in-time-visible financial metric row for one symbol."""
    cutoff_at = datetime.strptime(as_of, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    row = (
        db.query(FinancialMetric)
        .filter(
            FinancialMetric.symbol == symbol,
            FinancialMetric.report_date <= as_of,
            FinancialMetric.disclosure_date.isnot(None),
            FinancialMetric.disclosure_date <= as_of,
            FinancialMetric.fetched_at <= cutoff_at,
        )
        .order_by(FinancialMetric.disclosure_date.desc(), FinancialMetric.report_date.desc())
        .first()
    )
    if row is None:
        return {
            "symbol": symbol,
            "available": False,
            "quality": "missing",
            "as_of": as_of,
            "missing_fields": ["report_date/disclosure_date/fetched_at PIT-visible financial row"],
            "reason": "没有同时满足报告期、披露日与抓取时间截止的财务行",
        }
    fields = ("revenue_yoy", "net_profit_yoy", "roe", "gross_margin")
    missing_fields = [field for field in fields if getattr(row, field) is None]
    observed_count = len(fields) - len(missing_fields)
    return {
        "symbol": symbol,
        "available": observed_count > 0,
        "quality": "complete" if not missing_fields else "partial" if observed_count else "missing",
        "as_of": as_of,
        "report_date": row.report_date,
        "disclosure_date": row.disclosure_date,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "revenue_yoy": row.revenue_yoy,
        "net_profit_yoy": row.net_profit_yoy,
        "roe": row.roe,
        "gross_margin": row.gross_margin,
        "missing_fields": missing_fields,
    }


def _collect_news(
    db,
    symbols: list[str],
    as_of_dt: datetime,
    *,
    window_days: int = 14,
    limit: int = 80,
    memory_items: list[RawNews] | None = None,
) -> tuple[list[RawNews], list[NewsAudit]]:
    """Collect recent stored news and audit the source trail."""
    cutoff = as_of_dt - timedelta(days=window_days)
    # F4: add upper bound so replayed/backfilled runs with a past as_of don't
    # pick up newer news, which would trigger gate lookahead blocks.
    # as_of_dt is naive (matches Anspire published_at semantics); ceiling is
    # end-of-day 23:59:59 on the as_of date.
    upper = as_of_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    rows = (
        db.query(NewsItem)
        .filter(
            NewsItem.symbol.in_(symbols),
            NewsItem.published_at >= cutoff,
            NewsItem.published_at <= upper,
            NewsItem.fetched_at.is_not(None),
            NewsItem.fetched_at <= upper,
        )
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
        .all()
    ) if symbols else []
    items = [
        RawNews(
            title=row.title,
            url=row.url,
            published_at=row.published_at,
            source=row.source,
            symbol=row.symbol,
            content=row.content,
            fetched_at=row.fetched_at,
        )
        for row in rows
    ]
    if memory_items:
        items.extend(
            item for item in memory_items
            if item.published_at is not None
            and cutoff <= item.published_at <= upper
            and (fetched_at := item.fetched_at) is not None
            and fetched_at <= upper
        )
    return items, audit_news_items(items, now=as_of_dt)


def _collect_long_term_historical_context(
    db,
    *,
    symbols: list[str],
    names: dict[str, str],
    topic: str,
    as_of_dt: datetime,
    window_days: int = 365,
    limit: int = 12,
) -> list[dict]:
    """Expose older local articles as background candidates, never fresh triggers."""
    if not symbols:
        return []
    lower = as_of_dt - timedelta(days=window_days)
    upper = as_of_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    rows = (
        db.query(NewsItem)
        .filter(
            NewsItem.symbol.in_(symbols),
            NewsItem.published_at >= lower,
            NewsItem.published_at <= upper,
            NewsItem.fetched_at <= upper,
        )
        .order_by(NewsItem.published_at.desc())
        .limit(500)
        .all()
    )
    candidates: list[dict] = []
    for row in rows:
        text = f"{row.title or ''} {row.content or ''}".casefold()
        company_matches = [
            symbol for symbol in symbols
            if re.search(rf"(?<!\d){re.escape(symbol)}(?!\d)", text)
            or (names.get(symbol) and names[symbol].casefold() in text)
        ]
        theme_match = bool(topic and len(topic.strip()) >= 2 and topic.strip().casefold() in text)
        if not company_matches and not theme_match:
            continue
        candidates.append({
            "title": row.title,
            "source": row.source,
            "symbol_association": row.symbol,
            "published_at": row.published_at.isoformat(),
            "age_days": max(0, (as_of_dt - row.published_at).days),
            "company_text_matches": company_matches,
            "theme_text_match": theme_match,
            "semantic_support_reviewed": False,
        })
        if len(candidates) >= limit:
            break
    return candidates


@dataclass(frozen=True)
class EvidenceEvaluation:
    """Evaluator 输出：判断当前证据是否够，并给出下一步检索建议。"""

    quality: str            # ok / weak / insufficient
    usable_count: int
    weak_count: int
    relevant_count: int
    missing_financial_symbols: list[str]
    next_plan: dict | None  # 若 quality != ok，提示下一轮检索的 action / 参数


def _evaluate_evidence(
    *,
    topic: str,
    symbols: list[str],
    names: dict[str, str],
    audits: list[NewsAudit],
    financials: list[dict],
    window_days: int,
    min_usable: int = 3,
    max_window: int = 60,
    exhausted_providers: set[str] | None = None,
    attempted_financials: set[str] | None = None,
    theme_research: bool = False,
    allow_external_retrieval: bool = True,
) -> EvidenceEvaluation:
    """Agentic RAG 闭环的 evaluator + planner。

    优先级：
      1. 新闻不足且窗口未到上限 → expand_news_window
      2. 新闻不足且本地穷尽 → fetch_external_news (anspire 优先，否则 tavily)
      3. 财务缺失 → backfill_financials
      4. 否则 → quality=ok / weak（无可执行计划）
    """
    exhausted_providers = exhausted_providers or set()
    attempted_financials = attempted_financials or set()

    relevance = _source_relevance(audits, topic=topic, symbols=symbols, names=names)
    usable_count = sum(1 for a in audits if a.usable)
    relevant_count = relevance["direct_company_count"] + (
        relevance["direct_theme_count"] if theme_research else 0
    )
    below_evidence_bar = relevant_count < min_usable
    weak_count = len(audits) - usable_count
    missing_financials = [
        item["symbol"]
        for item in financials
        if not item.get("available") and item["symbol"] not in attempted_financials
    ]

    # 1) 扩窗
    if below_evidence_bar and window_days < max_window:
        next_window = min(max_window, window_days * 2)
        return EvidenceEvaluation(
            quality="insufficient",
            usable_count=usable_count,
            weak_count=weak_count,
            relevant_count=relevant_count,
            missing_financial_symbols=missing_financials,
            next_plan={
                "action": "expand_news_window",
                "from_days": window_days,
                "to_days": next_window,
                "reason": f"文本直接相关来源 {relevant_count} 条 < 阈值 {min_usable}（来源总数 {usable_count}），扩大时间窗回补",
            },
        )

    # 2) 外部检索
    if below_evidence_bar and allow_external_retrieval:
        from backend.config import settings as _settings
        provider: str | None = None
        if (
            "anspire" not in exhausted_providers
            and _settings.anspire_enabled
            and _settings.anspire_api_key
        ):
            provider = "anspire"
        elif "tavily_web" not in exhausted_providers and _settings.tavily_api_key:
            return EvidenceEvaluation(
                quality="insufficient",
                usable_count=usable_count,
                weak_count=weak_count,
                relevant_count=relevant_count,
                missing_financial_symbols=missing_financials,
                next_plan={
                    "action": "web_search",
                    "provider": "tavily_web",
                    "search_queries": _build_search_queries(topic, symbols, names),
                    "reason": (
                        f"本地窗口已扩到 {window_days} 天仍只有 {relevant_count}/{min_usable} 条文本直接相关来源"
                        "，调用 Tavily web_search 纯内存补证"
                    ),
                },
            )
        if provider is not None:
            return EvidenceEvaluation(
                quality="insufficient",
                usable_count=usable_count,
                weak_count=weak_count,
                relevant_count=relevant_count,
                missing_financial_symbols=missing_financials,
                next_plan={
                    "action": "fetch_external_news",
                    "provider": provider,
                    "days": window_days,
                    "reason": (
                        f"本地窗口已扩到 {window_days} 天仍只有 {relevant_count}/{min_usable} 条文本直接相关来源，"
                        f"调用 {provider} 外部检索补证"
                    ),
                },
            )

    # 3) 财务回补
    if missing_financials and allow_external_retrieval:
        return EvidenceEvaluation(
            quality="insufficient",
            usable_count=usable_count,
            weak_count=weak_count,
            relevant_count=relevant_count,
            missing_financial_symbols=missing_financials,
            next_plan={
                "action": "backfill_financials",
                "symbols": list(missing_financials),
                "reason": f"{len(missing_financials)} 个标的缺财务指标，触发回补",
            },
        )

    # 4) 终态
    if not below_evidence_bar:
        return EvidenceEvaluation(
            quality="ok",
            usable_count=usable_count,
            weak_count=weak_count,
            relevant_count=relevant_count,
            missing_financial_symbols=missing_financials,
            next_plan=None,
        )
    return EvidenceEvaluation(
        quality="insufficient" if below_evidence_bar else "weak",
        usable_count=usable_count,
        weak_count=weak_count,
        relevant_count=relevant_count,
        missing_financial_symbols=missing_financials,
        next_plan=None,
    )


def _execute_plan(
    plan: dict,
    db,
    symbols: list[str],
    *,
    topic: str = "",
) -> dict:
    """执行 evaluator/planner 给出的下一步动作；返回执行摘要供 trace。"""
    action = plan.get("action")
    if action == "expand_news_window":
        return {"action": action, "window_days_next": int(plan["to_days"])}
    if action == "fetch_external_news":
        return _fetch_external_news(db, symbols, plan["provider"], days=int(plan["days"]))
    if action == "web_search":
        queries = plan.get("search_queries") or ([topic] if topic else symbols)
        results = _tavily_web_search([str(q) for q in queries if str(q).strip()][:3])
        return {
            "action": "web_search",
            "provider": "tavily_web",
            "fetched": len(results),
            "results": results,
            "errors": [],
        }
    if action == "backfill_financials":
        return _backfill_financials(db, plan["symbols"])
    return {"action": action, "skipped": True}


def _build_search_queries(topic: str, symbols: list[str], names: dict[str, str]) -> list[str]:
    """Build bounded Tavily search queries from topic + covered symbols."""
    queries = [topic.strip()] if topic.strip() else []
    for symbol in symbols[:2]:
        label = f"{names.get(symbol, '')} {symbol}".strip()
        if label:
            queries.append(f"{topic} {label} 最新公告 订单 风险")
    return queries[:3] or ["A股 最新公告 风险"]


def _tavily_web_search(
    queries: list[str],
    *,
    max_results_per_query: int = 5,
    days: int = 30,
) -> list[dict]:
    """Call Tavily search as a pure in-memory evidence source."""
    clean_queries = [q.strip() for q in queries if q and q.strip()]
    if not clean_queries:
        return []

    from backend.config import settings
    if not settings.tavily_api_key:
        return []

    import requests

    session = requests.Session()
    session.trust_env = False
    output: list[dict] = []
    seen: set[str] = set()
    for query in clean_queries:
        try:
            resp = session.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results_per_query,
                    "days": days,
                    "include_answer": False,
                },
                timeout=12,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception as exc:  # pragma: no cover - 网络层异常兜底
            logger.warning("Tavily web_search failed query=%s: %s", query, exc)
            continue
        for item in results:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            key = url or title
            if not title or key in seen:
                continue
            seen.add(key)
            output.append({
                "title": title,
                "url": url,
                "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
                "published_date": item.get("published_date") or "",
                "source": "tavily_web",
                "query": query,
            })
    return output


def _parse_web_date(value: str | None, fallback: datetime | None = None) -> datetime | None:
    """Parse Tavily date strings into naive datetimes."""
    if not value:
        return None
    raw = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _web_results_to_news(results: list[dict], *, fallback_dt: datetime) -> list[RawNews]:
    """Convert Tavily result dicts to RawNews for the existing audit path."""
    items: list[RawNews] = []
    for result in results:
        title = str(result.get("title") or "").strip()
        if not title:
            continue
        published_at = _parse_web_date(result.get("published_date"))
        # Unknown source dates are not assigned the current as-of date.
        if published_at is None:
            continue
        items.append(RawNews(
            title=title,
            url=str(result.get("url") or ""),
            published_at=published_at,
            source="tavily_web",
            symbol=None,
            content=str(result.get("snippet") or "").strip() or None,
            fetched_at=datetime.now(),
        ))
    return items


def _fetch_external_news(
    db,
    symbols: list[str],
    provider: str,
    *,
    days: int,
) -> dict:
    """按 provider 调用外部新闻检索并落库，返回执行摘要。"""
    from backend.data.database import Stock
    from backend.data.news import fetch_stock_news_anspire, save_news_to_db

    inserted = 0
    errors: list[str] = []
    for sym in symbols:
        stock = db.query(Stock).filter(Stock.symbol == sym).first()
        name = stock.name if stock else sym
        try:
            if provider == "anspire":
                items = fetch_stock_news_anspire(sym, name, days=days)
            elif provider == "tavily":
                if stock is None:
                    items = []
                else:
                    from backend.data.tavily_news import fetch_tavily_news

                    items = fetch_tavily_news(stock, limit=5)
            else:
                items = []
            inserted += save_news_to_db(items, db)
        except Exception as exc:  # pragma: no cover - 网络层异常兜底
            errors.append(f"{sym}:{exc}")
    return {
        "action": "fetch_external_news",
        "provider": provider,
        "fetched": inserted,
        "errors": errors,
    }


def _backfill_financials(db, symbols: list[str]) -> dict:
    """触发缺失财务的 per-symbol 回补，返回执行摘要。"""
    from backend.data.fundamentals import sync_financial_metrics

    synced = 0
    errors: list[str] = []
    for sym in symbols:
        try:
            synced += sync_financial_metrics(sym, db)
        except Exception as exc:  # pragma: no cover - 数据源异常兜底
            errors.append(f"{sym}:{exc}")
    return {
        "action": "backfill_financials",
        "symbols": list(symbols),
        "synced": synced,
        "errors": errors,
    }


def _source_relevance(
    audits: list[NewsAudit],
    *,
    topic: str,
    symbols: list[str],
    names: dict[str, str],
) -> dict:
    """Count headline/body matches separately from database symbol association."""
    usable = [audit for audit in audits if audit.usable]
    company_rows: list[NewsAudit] = []
    topic_rows: list[NewsAudit] = []
    associated_only: list[NewsAudit] = []
    for audit in usable:
        text = f"{audit.news.title or ''} {audit.news.content or ''}".casefold()
        symbol_hit = any(re.search(rf"(?<!\d){re.escape(symbol)}(?!\d)", text) for symbol in symbols)
        name_hit = any(names.get(symbol) and names[symbol].casefold() in text for symbol in symbols)
        if symbol_hit or name_hit:
            company_rows.append(audit)
            continue
        topic_hit = bool(topic and len(topic.strip()) >= 2 and topic.strip().casefold() in text)
        if topic_hit:
            topic_rows.append(audit)
        elif audit.news.symbol in symbols:
            # The data pipeline attached the item to a stock, but title/body did
            # not independently confirm the company or theme relevance.
            associated_only.append(audit)
    return {
        "usable_source_count": len(usable),
        "direct_company_count": len(company_rows),
        "direct_theme_count": len(topic_rows),
        "associated_without_text_match_count": len(associated_only),
        "company_titles": [row.news.title for row in company_rows],
        "theme_titles": [row.news.title for row in topic_rows],
        "semantic_support_reviewed_count": 0,
        "text_match_is_not_semantic_support": True,
        "classification_rule": "usable sources are matched against headline/body company name or exact code, then topic phrase; symbol metadata alone is association, not direct evidence",
    }


def _build_summary(
    topic: str,
    symbols: list[str],
    source_count: int,
    weak_count: int,
    *,
    min_required: int = 3,
    direct_relevance_count: int = 0,
) -> str:
    """Build a concise deterministic research summary."""
    symbol_text = "、".join(symbols) if symbols else "未指定标的"
    evidence_status = (
        f"与公司/主题可核对匹配的来源 {direct_relevance_count} 条，低于要求 {min_required} 条，当前只能列出待核验问题"
        if direct_relevance_count < min_required
        else f"公司/主题直接匹配来源达到基础门槛 {min_required} 条，仍需核对样本覆盖和证据内容"
    )
    return (
        f"{topic} 本次覆盖 {symbol_text}；审计后可用来源 {source_count} 条、偏弱或过期 {weak_count} 条。"
        f"{evidence_status}；来源数量不等于公司或板块相关性。结论用于专题研究，不直接生成交易信号。"
    )


def _evidence_quality_status(
    evaluation: EvidenceEvaluation,
    relevance: dict,
    *,
    min_required: int,
    theme_research: bool,
    financials: list[dict],
    gate_status: str,
    long_term_framework: dict | None,
) -> str:
    direct_count = int(relevance.get("direct_company_count", 0))
    if theme_research:
        direct_count += int(relevance.get("direct_theme_count", 0))
    if theme_research:
        dimensions = (long_term_framework or {}).get("framework", [])
        if not dimensions or any(item.get("status") != "complete" for item in dimensions):
            return "partial"
    if evaluation.quality != "ok" or direct_count < min_required:
        return "partial"
    if not financials or any(item.get("quality") != "complete" for item in financials):
        return "partial"
    if gate_status != "pass":
        return "partial"
    return "sufficient"


_DEEP_CONTEXT_SECTIONS = [
    "announcements",
    "research_reports",
    "corporate_events",
    "holders",
    "lhb",
    "data_health",
]


def _compact_m61_context_pack(pack: dict, *, item_limit: int = 2, field_chars: int = 140) -> dict:
    compact = dict(pack)
    for section, value in list(compact.items()):
        if not isinstance(value, dict):
            continue
        section_value = dict(value)
        items = section_value.get("items")
        if isinstance(items, list):
            clipped: list[dict] = []
            for item in items[:item_limit]:
                if not isinstance(item, dict):
                    clipped.append(item)
                    continue
                clipped.append({
                    key: (val[:field_chars] if isinstance(val, str) and len(val) > field_chars else val)
                    for key, val in item.items()
                })
            section_value["items"] = clipped
        compact[section] = section_value
    return compact


def _topic_looks_sector_level(topic: str, symbols: list[str]) -> bool:
    if len(symbols) != 1:
        return True
    return any(token in topic for token in ("行业", "产业链", "板块", "主题", "赛道", "sector"))


def _build_m61_research_context_text(
    *,
    symbols: list[str],
    db,
    as_of_dt: datetime,
    topic: str,
    max_chars: int = 2000,
) -> str:
    """Render extra M61 research context without replacing legacy evidence."""
    if not symbols:
        return ""
    sections = list(_DEEP_CONTEXT_SECTIONS)
    if _topic_looks_sector_level(topic, symbols):
        sections.insert(-1, "overseas")
    per_symbol_budget = max(400, max_chars // max(1, len(symbols)))
    chunks: list[str] = []
    for symbol in symbols:
        try:
            pack = build_stock_context_pack(symbol, as_of=as_of_dt, sections=sections, db=db)
            pack = _compact_m61_context_pack(pack)
            text = render_context_text(pack, per_symbol_budget)
        except Exception as exc:
            emit_degradation(
                component="research_layer",
                category="deep_research_context_pack",
                provider="context_builder",
                error=str(exc),
                context={"symbol": symbol, "topic": topic, "as_of": as_of_dt.isoformat()},
                db=db,
            )
            continue
        if text.strip():
            chunks.append(text)
    output = "\n\n".join(chunks)
    return output[:max_chars]


def _section_to_dict(section: ResearchSection) -> dict:
    """Serialize a ResearchSection for persistence and debate context."""
    return {
        "role": section.role,
        "title": section.title,
        "content": section.content,
        "catalysts": list(section.catalysts),
        "risks": list(section.risks),
        "valuation_anchor": section.valuation_anchor,
        "evidence_snippets": list(section.evidence_snippets),
        "stance": section.stance,
        "confidence": section.confidence,
    }


def _render_section_structured(section: ResearchSection) -> list[str]:
    """Render non-empty IC memo fields for one section."""
    rows: list[str] = []
    if section.stance:
        rows.append(f"- 立场：{section.stance}（confidence={section.confidence:.2f}）")
    if section.catalysts:
        rows.append("- 催化剂：" + "；".join(section.catalysts))
    else:
        rows.append("- 催化剂：本次没有基于直接相关证据确认催化剂")
    if section.risks:
        rows.append("- 风险：" + "；".join(section.risks))
    else:
        rows.append("- 风险：没有额外来源风险标记；不代表其他风险已排除")
    if section.valuation_anchor:
        rows.append(f"- 估值锚：{section.valuation_anchor}")
    if section.evidence_snippets:
        rows.append("- 证据片段：" + "；".join(section.evidence_snippets[:4]))
    return rows


def _render_report(
    *,
    topic: str,
    symbols: list[str],
    names: dict[str, str],
    as_of: str,
    summary: str,
    prices: list[dict],
    financials: list[dict],
    audits: list[NewsAudit],
    risk_flags: list[str],
    sections: list[ResearchSection],
    context_text: str = "",
    iterations: list[dict] | None = None,
    long_term_framework: dict | None = None,
    source_relevance: dict | None = None,
    quality_status: str = "partial",
    retrieval_stop_reason: str = "",
    historical_context_sources: list[dict] | None = None,
    offline: bool = False,
) -> str:
    """Render the deep research report as Markdown."""
    usable = [audit for audit in audits if audit.usable]
    weak = [audit for audit in audits if not audit.usable]
    symbol_label = ", ".join(
        f"{symbol} {names.get(symbol, '')}".strip() for symbol in symbols
    ) or "未指定"
    lines = [
        f"# {topic} — 深度研究",
        "",
        f"- 日期：{as_of}",
        f"- 标的：{symbol_label}",
        "- 类型：手动专题研究，不进入日常盘后信号流水线",
        "- 上下文版本：ctx=m61_p3",
        "",
        "## 核心结论",
        summary,
        "",
        "## 证据覆盖与角色边界",
        f"- 成分股范围：{symbol_label}（{len(symbols)} 只；这是本次解析到的名单，不代表全行业完整名册）",
        f"- 研究质量状态：{quality_status}；新鲜且来源分数达标 {len(usable)} 条，弱/过期 {len(weak)} 条。",
        f"- 文本直接命中公司名/代码来源：{(source_relevance or {}).get('direct_company_count', 0)} 条；直接命中主题词来源：{(source_relevance or {}).get('direct_theme_count', 0)} 条。",
        f"- 仅被数据记录绑定到个股、但标题/正文未命中公司或主题：{(source_relevance or {}).get('associated_without_text_match_count', 0)} 条，不计入相关证据。",
        "- 相关性按标题/正文中的公司全名或代码精确包含、主题词包含分类；单靠 NewsItem.symbol 关联字段不算直接证据。",
        "- 当前没有语义审核器；文本命中属于检索候选，不代表来源实质支持催化或论点。",
        f"- 执行模式：{'离线只读；网络/模型/财务回补关闭' if offline else '手动研究；规则模板本身不调用模型'}。",
        "- 下列五个角色是确定性规则模板，不表示本次分别调用了五个独立模型或 LongTermTeam 分析师。",
        "- Deep Research 入口不调用多轮辩论、Director/Researcher/RiskManager 裁量卡或 Serenity；它们的输出不能从此报告推定。",
        f"- 检索循环停止原因：{retrieval_stop_reason or '未记录'}。",
        "",
        "## 研究员分工结论",
    ]
    for section in sections:
        lines.extend([f"### {section.title}", section.content, ""])
        structured = _render_section_structured(section)
        if structured:
            lines.extend(["结构化 IC Memo：", *structured, ""])

    lines.extend([
        "## 行业/主题观察",
        f"- 主题关键词：{topic}",
        f"- 可追溯来源数量：{len(usable)}",
        f"- 来源偏弱或过期数量：{len(weak)}",
        "",
    ])
    if long_term_framework is not None:
        lines.extend(["## 板块长期研究框架（证据状态）", "- 这是本地数据支持的检查框架，不是已完成的行业长期结论。"])
        coverage = long_term_framework.get("coverage", {})
        lines.append(
            f"- 成分股覆盖：{coverage.get('symbol_count', 0)} 只；财务行 {coverage.get('financial_rows', 0)} 只；"
            f"财务指标覆盖 {coverage.get('financial_metric_coverage', '0/0')}；"
            f"报告期={','.join(coverage.get('financial_report_periods', [])) or '无'}；"
            f"期间可比={coverage.get('financial_periods_comparable', False)}。"
        )
        for item in long_term_framework.get("framework", []):
            lines.append(f"### {item['dimension']}（{item['status']}）")
            lines.append("- 当前证据：" + ("；".join(item.get("evidence", [])) or "暂无可用的直接证据"))
            lines.append("- 缺少：" + ("；".join(item.get("missing", [])) or "未记录额外缺项"))
            lines.append("- 可检验条件：" + str(item.get("check") or "待定义"))
        lines.extend(["- 边界：" + "；".join(long_term_framework.get("limitations", [])), ""])

    if historical_context_sources is not None:
        lines.extend([
            "## 长期历史背景来源（本地最多一年）",
            "- 以下是标题/正文文本匹配候选，标注为历史背景；不进入当前短线来源门，也未经人工语义确认。",
        ])
        if historical_context_sources:
            for item in historical_context_sources:
                lines.append(
                    f"- {item['published_at'][:10]}（约 {item['age_days']} 天前，{item.get('source') or '来源未知'}）："
                    f"{item['title']}；公司文本命中={','.join(item['company_text_matches']) or '无'}；"
                    f"主题文本命中={'是' if item['theme_text_match'] else '否'}。"
                )
        else:
            lines.append("- 过去一年本地存档中没有标题/正文命中成分股或主题词的候选来源。")
        lines.append("")

    lines.append("## 个股快照")
    for price in prices:
        sym = price["symbol"]
        if price.get("available"):
            lines.append(
                f"- {sym} {names.get(sym, '')}：最新收盘 {price['latest_close']}，"
                f"日期 {price['latest_date']}，近 20 日变化 {price.get('change_20d')}%"
            )
        else:
            lines.append(f"- {sym} {names.get(sym, '')}：暂无价格数据")

    lines.extend(["", "## 基本面快照"])
    for item in financials:
        sym = item["symbol"]
        if item.get("available"):
            lines.append(
                f"- {sym}：状态 {item.get('quality')}；报告期 {item['report_date']}，披露日 {item.get('disclosure_date')}，"
                f"营收同比 {item.get('revenue_yoy')}，净利同比 {item.get('net_profit_yoy')}，"
                f"ROE {item.get('roe')}，缺少字段 {','.join(item.get('missing_fields') or []) or '无'}"
            )
        else:
            lines.append(f"- {sym}：暂无 PIT 可见财务指标；缺少/不可见 {','.join(item.get('missing_fields') or [])}；原因 {item.get('reason', '')}")

    if context_text:
        lines.extend(["", "## M61 统一上下文", context_text])

    lines.extend(["", "## 风险复核"])
    if risk_flags:
        lines.extend(f"- {flag}" for flag in risk_flags)
    else:
        lines.append("- 暂未发现来源审计层面的硬风险；仍需结合估值、仓位和大盘环境。")

    lines.extend(["", "## 来源审计"])
    if audits:
        for audit in audits[:20]:
            status = "可用" if audit.usable else "降权"
            flags = ",".join(audit.risk_flags) or "none"
            lines.append(
                f"- [{status} score={audit.score} flags={flags}] "
                f"{audit.news.source}｜{audit.news.published_at:%Y-%m-%d}｜"
                f"{_format_source_title(audit.news.title, audit.news.url, audit.news.source)}"
            )
    else:
        lines.append("- 本地数据库暂无近 14 日新闻；本报告只保留结构化研究框架。")

    if iterations:
        lines.extend(["", "## 检索闭环（evaluator + planner）"])
        for idx, it in enumerate(iterations, 1):
            plan = it.get("next_plan") or {}
            result = it.get("plan_result") or {}
            if it.get("stop_reason") == "iteration_limit":
                plan_text = "达到检索轮数上限，当前缺口未解决；不表示证据门通过"
            elif plan:
                action = plan.get("action")
                if action == "expand_news_window":
                    plan_text = (
                        f"扩大新闻窗口 → {plan.get('to_days')} 天（{plan.get('reason')}）"
                    )
                elif action == "fetch_external_news":
                    fetched = result.get("fetched", "?")
                    plan_text = (
                        f"外部检索 {plan.get('provider')} (days={plan.get('days')}) "
                        f"→ 新增 {fetched} 条；{plan.get('reason')}"
                    )
                elif action == "backfill_financials":
                    synced = result.get("synced", "?")
                    plan_text = (
                        f"回补财务 {plan.get('symbols')} → 同步 {synced} 行；"
                        f"{plan.get('reason')}"
                    )
                elif action == "web_search":
                    fetched = result.get("fetched", "?")
                    plan_text = (
                        f"Tavily web_search → 纯内存新增 {fetched} 条；"
                        f"{plan.get('reason')}"
                    )
                else:
                    plan_text = f"{action}：{plan.get('reason', '')}"
            else:
                plan_text = f"停止原因：{it.get('stop_reason', '当前轮没有后续检索计划')}"
            lines.append(
                f"- 第 {idx} 轮 (window={it['window_days']}d)："
                f"usable={it['usable_count']} weak={it['weak_count']} "
                f"质量={it['quality']}；{plan_text}"
            )

    lines.extend([
        "",
        "## 待验证问题",
        "- 后续公告或财报是否验证当前主题逻辑？",
        "- 价格走势是否已经提前反映主题预期？",
        "- 是否存在政策、订单、客户集中度或估值拥挤风险？",
        "",
        "## 免责声明",
        "本报告由 MingCang 手动深度研究流程生成，不构成投资建议，不自动触发买卖信号。",
        "",
    ])
    return "\n".join(lines)


def _format_source_title(title: str, url: str, source: str) -> str:
    """Format source audit rows, linking pure web-search evidence."""
    if source == "tavily_web" and url:
        return f"[{title}]({url})｜{url}"
    return f"{title}｜{url}"


def _build_llm_text(summary: str, sections: list[ResearchSection]) -> str:
    """Build a text blob containing only LLM-generated structured fields.

    Used by the ResearchReportGate forbidden-wording scanner (F1): the scan must
    target only what the LLM wrote (summary, section content, catalysts, risks,
    valuation_anchor), never the raw news titles embedded in the source-audit
    section which are user/data-source content and may legitimately contain words
    such as 加仓/减仓/抄底/满仓.
    """
    parts: list[str] = [summary]
    for section in sections:
        if section.content:
            parts.append(section.content)
        parts.extend(section.catalysts)
        parts.extend(section.risks)
        if section.valuation_anchor:
            parts.append(section.valuation_anchor)
    return "\n".join(parts)


def run_deep_research(
    *,
    topic: str,
    symbols: list[str],
    db,
    output_dir: Path | str | None = None,
    as_of: str | None = None,
    persist: bool = True,
    min_usable_sources: int = 3,
    max_iterations: int = 5,
    seed_queries: list[str] | None = None,
    long_term_theme: bool | None = None,
    allow_external_retrieval: bool = True,
) -> DeepResearchReport:
    """Run a deep research workflow with an evaluator/planner re-query loop.

    Each iteration:
      1. collect news at current window
      2. (re)load financial snapshots
      3. evaluate evidence quality + emit one of:
           expand_news_window / fetch_external_news / backfill_financials
      4. execute the plan and re-evaluate
    """
    clean_symbols = [s.strip() for s in symbols if s.strip()]
    is_theme_research = long_term_theme if long_term_theme is not None else _topic_looks_sector_level(topic, clean_symbols)
    # F3: default as_of uses Beijing local date so it matches Anspire published_at
    # (which is naive Beijing time), preventing false lookahead blocks at 00-08 UTC.
    _CST = timezone(timedelta(hours=8))
    day = as_of or datetime.now(_CST).strftime("%Y-%m-%d")
    as_of_dt = datetime.strptime(day, "%Y-%m-%d")
    names = _symbol_names(db, clean_symbols)
    prices = [_latest_price_context(db, symbol, as_of=day) for symbol in clean_symbols]
    financials = [_latest_financial_context(db, symbol, as_of=day) for symbol in clean_symbols]

    window_days = 14
    audits: list[NewsAudit] = []
    iterations: list[dict] = []
    evaluation: EvidenceEvaluation | None = None
    loop_stop_reason = "iteration_limit"
    exhausted_providers: set[str] = set()
    attempted_financials: set[str] = set()
    memory_news: list[RawNews] = []
    clean_seed_queries = [q.strip() for q in (seed_queries or []) if q and q.strip()]
    if clean_seed_queries:
        if not allow_external_retrieval:
            raise ValueError("离线研究禁止 seed_queries 外部检索；请清空种子查询")
        seed_result = _execute_plan(
            {"action": "web_search", "search_queries": clean_seed_queries[:3]},
            db,
            clean_symbols,
            topic=topic,
        )
        memory_news.extend(_web_results_to_news(
            seed_result.get("results", []),
            fallback_dt=as_of_dt,
        ))
        if seed_result.get("fetched", 0) > 0:
            exhausted_providers.add("tavily_web")
    for iteration_index in range(max_iterations):
        _, audits = _collect_news(
            db, clean_symbols, as_of_dt, window_days=window_days,
            memory_items=memory_news,
        )
        # 财务可能在上一轮 backfill 被刷新；每轮重读以反映最新状态
        financials = [_latest_financial_context(db, symbol, as_of=day) for symbol in clean_symbols]
        evaluation = _evaluate_evidence(
            topic=topic,
            symbols=clean_symbols,
            names=names,
            audits=audits,
            financials=financials,
            window_days=window_days,
            min_usable=min_usable_sources,
            exhausted_providers=exhausted_providers,
            attempted_financials=attempted_financials,
            theme_research=is_theme_research,
            allow_external_retrieval=allow_external_retrieval,
        )
        plan_result: dict | None = None
        if evaluation.next_plan is not None:
            plan_result = _execute_plan(evaluation.next_plan, db, clean_symbols, topic=topic)
            action = evaluation.next_plan.get("action")
            if action == "expand_news_window":
                window_days = int(plan_result.get("window_days_next", window_days))
            elif action == "fetch_external_news":
                # 标记 provider 已尝试，避免下一轮重复打同一个外部源
                exhausted_providers.add(evaluation.next_plan["provider"])
            elif action == "web_search":
                memory_news.extend(_web_results_to_news(
                    plan_result.get("results", []),
                    fallback_dt=as_of_dt,
                ))
                exhausted_providers.add("tavily_web")
            elif action == "backfill_financials":
                attempted_financials.update(evaluation.next_plan["symbols"])
        iterations.append({
            "window_days": window_days,
            "usable_count": evaluation.usable_count,
            "weak_count": evaluation.weak_count,
            "relevant_count": evaluation.relevant_count,
            "quality": evaluation.quality,
            "next_plan": evaluation.next_plan,
            "plan_result": plan_result,
        })
        relevant_enough = evaluation.relevant_count >= min_usable_sources
        if (evaluation.quality == "ok" and relevant_enough) or evaluation.next_plan is None:
            loop_stop_reason = (
                "text_match_threshold_met_no_semantic_review" if evaluation.quality == "ok" else
                "relevant_source_shortfall_no_provider_available"
                if evaluation.relevant_count < min_usable_sources else
                "no_actionable_plan"
            )
            break
        if iteration_index == max_iterations - 1:
            iterations[-1]["stop_reason"] = "iteration_limit"

    assert evaluation is not None  # max_iterations >= 1 保证至少一轮
    _, audits = _collect_news(
        db, clean_symbols, as_of_dt, window_days=window_days,
        memory_items=memory_news,
    )
    financials = [_latest_financial_context(db, symbol, as_of=day) for symbol in clean_symbols]
    evaluation = _evaluate_evidence(
        topic=topic,
        symbols=clean_symbols,
        names=names,
        audits=audits,
        financials=financials,
        window_days=window_days,
        min_usable=min_usable_sources,
        exhausted_providers=exhausted_providers,
        attempted_financials=attempted_financials,
        theme_research=is_theme_research,
        allow_external_retrieval=allow_external_retrieval,
    )
    usable_count = evaluation.usable_count
    weak_count = evaluation.weak_count
    risk_flags = sorted({flag for audit in audits for flag in audit.risk_flags})
    source_relevance = _source_relevance(
        audits, topic=topic, symbols=clean_symbols, names=names,
    )
    direct_relevance_count = source_relevance["direct_company_count"]
    if is_theme_research:
        direct_relevance_count += source_relevance["direct_theme_count"]
    long_term_framework = None
    quality_status = _evidence_quality_status(
        evaluation,
        source_relevance,
        min_required=min_usable_sources,
        theme_research=is_theme_research,
        financials=financials,
        gate_status="pending",
        long_term_framework=long_term_framework,
    )
    summary = _build_summary(
        topic,
        clean_symbols,
        usable_count,
        weak_count,
        min_required=min_usable_sources,
        direct_relevance_count=direct_relevance_count,
    )
    sections = build_research_sections(
        topic=topic,
        symbols=clean_symbols,
        names=names,
        prices=prices,
        financials=financials,
        source_count=usable_count,
        weak_source_count=weak_count,
        risk_flags=risk_flags,
    )
    from backend.research.agents import build_long_term_theme_framework
    long_term_framework = build_long_term_theme_framework(
        topic=topic,
        symbols=clean_symbols,
        names=names,
        financials=financials,
        source_count=usable_count,
        weak_source_count=weak_count,
        risk_flags=risk_flags,
    ) if (long_term_theme if long_term_theme is not None else _topic_looks_sector_level(topic, clean_symbols)) else None
    context_text = _build_m61_research_context_text(
        symbols=clean_symbols,
        db=db,
        as_of_dt=as_of_dt,
        topic=topic,
        max_chars=2000,
    )
    historical_context = _collect_long_term_historical_context(
        db,
        symbols=clean_symbols,
        names=names,
        topic=topic,
        as_of_dt=as_of_dt,
    ) if is_theme_research else []

    out_dir = Path(output_dir) if output_dir is not None else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}-{_slug(topic)}.md"
    text = _render_report(
        topic=topic,
        symbols=clean_symbols,
        names=names,
        as_of=day,
        summary=summary,
        prices=prices,
        financials=financials,
        audits=audits,
        risk_flags=risk_flags,
        iterations=iterations,
        sections=sections,
        context_text=context_text,
        long_term_framework=long_term_framework,
        source_relevance=source_relevance,
        quality_status=quality_status,
        retrieval_stop_reason=loop_stop_reason,
        historical_context_sources=historical_context,
        offline=not allow_external_retrieval,
    )

    # M50 Phase 1: build report object BEFORE write so gate can inspect it.
    report = DeepResearchReport(
        topic=topic,
        symbols=clean_symbols,
        as_of=day,
        summary=summary,
        path=path,
        source_count=usable_count,
        risk_flags=risk_flags,
        retrieval_iterations=tuple(iterations),
        sections=tuple(_section_to_dict(section) for section in sections),
        long_term_framework=long_term_framework,
        quality_status=quality_status,
        source_relevance=source_relevance,
        retrieval_stop_reason=loop_stop_reason,
        historical_context_sources=tuple(historical_context),
    )

    # ResearchReportGate — write-before hook.
    from backend.config import settings as _settings
    if _settings.research_report_gate_enabled:
        from backend.research.research_report_gate import (
            _annotate_warnings,
            run_research_report_gate,
        )
        # F1: build llm_text from LLM-generated structured fields only.
        # This must NOT include raw news titles from the source-audit section —
        # those are user-submitted content and commonly contain words like
        # 加仓/减仓/抄底/满仓 that would cause false forbidden-wording blocks.
        llm_text = _build_llm_text(summary, sections)
        verdict = run_research_report_gate(
            report, audits, text,
            llm_text=llm_text,
            weak_source_count=weak_count,
            prices=prices,
            financials=financials,
        )
        if verdict.status == "blocked":
            logger.warning(
                "ResearchReportGate BLOCKED report %r — reasons: %s",
                topic,
                verdict.reasons,
            )
            # Do NOT write file, do NOT persist.  Mark report blocked so callers
            # can distinguish it; `path` still holds the intended (unwritten) path.
            return replace(
                report, gate_status="blocked", gate_reasons=tuple(verdict.reasons)
            )
        if verdict.status == "warning":
            text = _annotate_warnings(text, verdict)
        report = replace(
            report, gate_status=verdict.status, gate_reasons=tuple(verdict.warnings)
        )
    else:
        verdict = None
        report = replace(report, gate_status="gate_disabled")

    final_quality_status = _evidence_quality_status(
        evaluation,
        source_relevance,
        min_required=min_usable_sources,
        theme_research=is_theme_research,
        financials=financials,
        gate_status=report.gate_status,
        long_term_framework=long_term_framework,
    )
    text = text.replace(
        f"研究质量状态：{report.quality_status}",
        f"研究质量状态：{final_quality_status}",
    )
    report = replace(report, quality_status=final_quality_status)

    path.write_text(text, encoding="utf-8")
    if persist:
        _persist_report(db, report, audits, gate=verdict)
    return report


def _persist_report(db, report: DeepResearchReport, audits: list[NewsAudit], *, gate=None) -> None:
    """Persist the report as decision evidence and research memory."""
    from backend.decision.harness import record_decision_run
    from backend.memory.research_memory import remember_deep_research

    result = {
        "rule_version": "deep_research_v1",
        "recommendation": "专题研究",
        "confidence": "中",
        "composite_score": 0.0,
        "breakdown": {},
        "risk_notes": report.risk_flags,
        "stop_loss": None,
        "take_profit": None,
        "position_pct": None,
    }
    input_snapshot = {
        "topic": report.topic,
        "symbols": report.symbols,
        "report_path": str(report.path) if report.path else None,
        "source_count": report.source_count,
        "quality_status": report.quality_status,
        "source_relevance": report.source_relevance,
        "retrieval_stop_reason": report.retrieval_stop_reason,
        "retrieval_iterations": list(report.retrieval_iterations),
        "source_audit": [
            {
                "title": audit.title,
                "score": audit.score,
                "usable": audit.usable,
                "risk_flags": audit.risk_flags,
                "url": audit.news.url,
                "source": audit.news.source,
            }
            for audit in audits[:20]
        ],
        "sections": list(report.sections),
        "long_term_framework": report.long_term_framework,
        "context_version": "ctx=m61_p3",
        "gate_status": gate.status if gate is not None else "gate_disabled",
        "gate_warnings": gate.warnings if gate is not None else [],
    }
    for symbol in report.symbols or [""]:
        record_decision_run(
            db,
            run_type="deep_research",
            symbol=symbol,
            as_of=report.as_of,
            result=result,
            input_snapshot=input_snapshot,
            notes=f"{report.summary} ctx=m61_p3",
        )
    remember_deep_research(
        db,
        topic=report.topic,
        summary=report.summary,
        symbols=report.symbols,
        report_path=str(report.path) if report.path else "",
        sections=list(report.sections),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for manual deep research."""
    parser = argparse.ArgumentParser(description="Run a manual MingCang deep research report")
    parser.add_argument("--topic", required=True, help="研究主题，例如：AI算力产业链")
    parser.add_argument("--symbols", default="", help="逗号分隔股票代码，例如：300308,300394")
    parser.add_argument("--as-of", default=None, help="研究日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--output-dir", default=None, help="报告输出目录，默认 docs/research")
    parser.add_argument("--seed-queries", default="", help="逗号分隔 Tavily seed queries，用于首轮纯内存补证")
    args = parser.parse_args(argv)

    print("提示：日常研究入口是 `python3 -m backend.tools.m63_research --target <目标>`；直调本模块绕过 m63 路由与研究队列登记。")

    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        report = run_deep_research(
            topic=args.topic,
            symbols=[s for s in args.symbols.split(",") if s],
            db=db,
            output_dir=args.output_dir,
            as_of=args.as_of,
            seed_queries=[q for q in args.seed_queries.split(",") if q.strip()],
            persist=True,
        )
        print(report.path)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
