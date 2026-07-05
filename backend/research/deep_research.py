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


def _latest_price_context(db, symbol: str) -> dict:
    """Collect latest close and short-term price context for one symbol."""
    latest = (
        db.query(Price)
        .filter(Price.symbol == symbol)
        .order_by(Price.date.desc())
        .first()
    )
    if latest is None:
        return {"symbol": symbol, "available": False}
    older = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date < latest.date)
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
        "latest_date": latest.date,
        "latest_close": latest.close,
        "change_20d": change_20d,
    }


def _latest_financial_context(db, symbol: str) -> dict:
    """Collect latest available financial metric row for one symbol."""
    row = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.symbol == symbol)
        .order_by(FinancialMetric.report_date.desc())
        .first()
    )
    if row is None:
        return {"symbol": symbol, "available": False}
    return {
        "symbol": symbol,
        "available": True,
        "report_date": row.report_date,
        "revenue_yoy": row.revenue_yoy,
        "net_profit_yoy": row.net_profit_yoy,
        "roe": row.roe,
        "gross_margin": row.gross_margin,
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
        )
        for row in rows
    ]
    if memory_items:
        items.extend(
            item for item in memory_items
            if cutoff <= item.published_at <= upper
        )
    return items, audit_news_items(items, now=as_of_dt)


@dataclass(frozen=True)
class EvidenceEvaluation:
    """Evaluator 输出：判断当前证据是否够，并给出下一步检索建议。"""

    quality: str            # ok / weak / insufficient
    usable_count: int
    weak_count: int
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

    usable_count = sum(1 for a in audits if a.usable)
    weak_count = len(audits) - usable_count
    missing_financials = [
        item["symbol"]
        for item in financials
        if not item.get("available") and item["symbol"] not in attempted_financials
    ]

    # 1) 扩窗
    if usable_count < min_usable and window_days < max_window:
        next_window = min(max_window, window_days * 2)
        return EvidenceEvaluation(
            quality="insufficient",
            usable_count=usable_count,
            weak_count=weak_count,
            missing_financial_symbols=missing_financials,
            next_plan={
                "action": "expand_news_window",
                "from_days": window_days,
                "to_days": next_window,
                "reason": f"可用来源 {usable_count} 条 < 阈值 {min_usable}，扩大时间窗回补",
            },
        )

    # 2) 外部检索
    if usable_count < min_usable:
        from backend.config import settings as _settings
        provider: str | None = None
        if "anspire" not in exhausted_providers and _settings.anspire_api_key:
            provider = "anspire"
        elif "tavily_web" not in exhausted_providers and _settings.tavily_api_key:
            return EvidenceEvaluation(
                quality="insufficient",
                usable_count=usable_count,
                weak_count=weak_count,
                missing_financial_symbols=missing_financials,
                next_plan={
                    "action": "web_search",
                    "provider": "tavily_web",
                    "search_queries": _build_search_queries(topic, symbols, names),
                    "reason": (
                        f"本地窗口已扩到 {window_days} 天仍 {usable_count}/{min_usable}，"
                        "调用 Tavily web_search 纯内存补证"
                    ),
                },
            )
        if provider is not None:
            return EvidenceEvaluation(
                quality="insufficient",
                usable_count=usable_count,
                weak_count=weak_count,
                missing_financial_symbols=missing_financials,
                next_plan={
                    "action": "fetch_external_news",
                    "provider": provider,
                    "days": window_days,
                    "reason": (
                        f"本地窗口已扩到 {window_days} 天仍 {usable_count}/{min_usable}，"
                        f"调用 {provider} 外部检索补证"
                    ),
                },
            )

    # 3) 财务回补
    if missing_financials:
        return EvidenceEvaluation(
            quality="insufficient",
            usable_count=usable_count,
            weak_count=weak_count,
            missing_financial_symbols=missing_financials,
            next_plan={
                "action": "backfill_financials",
                "symbols": list(missing_financials),
                "reason": f"{len(missing_financials)} 个标的缺财务指标，触发回补",
            },
        )

    # 4) 终态
    if usable_count >= min_usable:
        return EvidenceEvaluation(
            quality="ok",
            usable_count=usable_count,
            weak_count=weak_count,
            missing_financial_symbols=missing_financials,
            next_plan=None,
        )
    return EvidenceEvaluation(
        quality="weak",
        usable_count=usable_count,
        weak_count=weak_count,
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


def _parse_web_date(value: str | None, fallback: datetime) -> datetime:
    """Parse Tavily date strings into naive datetimes."""
    if not value:
        return fallback
    raw = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return fallback


def _web_results_to_news(results: list[dict], *, fallback_dt: datetime) -> list[RawNews]:
    """Convert Tavily result dicts to RawNews for the existing audit path."""
    items: list[RawNews] = []
    for result in results:
        title = str(result.get("title") or "").strip()
        if not title:
            continue
        items.append(RawNews(
            title=title,
            url=str(result.get("url") or ""),
            published_at=_parse_web_date(result.get("published_date"), fallback_dt),
            source="tavily_web",
            symbol=None,
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
                    from backend.tools.backfill_coverage import _fetch_tavily_news
                    items = _fetch_tavily_news(stock, limit=5)
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


def _build_summary(topic: str, symbols: list[str], source_count: int, weak_count: int) -> str:
    """Build a concise deterministic research summary."""
    symbol_text = "、".join(symbols) if symbols else "未指定标的"
    return (
        f"{topic} 覆盖 {symbol_text}；本次使用 {source_count} 条可追溯新闻/公告证据，"
        f"{weak_count} 条来源或时效性偏弱。结论用于专题研究，不直接生成交易信号。"
    )


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
    if section.risks:
        rows.append("- 风险：" + "；".join(section.risks))
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
        "## 个股快照",
    ])
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
                f"- {sym}：报告期 {item['report_date']}，营收同比 {item.get('revenue_yoy')}，"
                f"净利同比 {item.get('net_profit_yoy')}，ROE {item.get('roe')}"
            )
        else:
            lines.append(f"- {sym}：暂无财务指标数据")

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
            if plan:
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
                plan_text = "结论：当前证据满足阈值，停止补证"
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
    # F3: default as_of uses Beijing local date so it matches Anspire published_at
    # (which is naive Beijing time), preventing false lookahead blocks at 00-08 UTC.
    _CST = timezone(timedelta(hours=8))
    day = as_of or datetime.now(_CST).strftime("%Y-%m-%d")
    as_of_dt = datetime.strptime(day, "%Y-%m-%d")
    names = _symbol_names(db, clean_symbols)
    prices = [_latest_price_context(db, symbol) for symbol in clean_symbols]
    financials = [_latest_financial_context(db, symbol) for symbol in clean_symbols]

    window_days = 14
    audits: list[NewsAudit] = []
    iterations: list[dict] = []
    evaluation: EvidenceEvaluation | None = None
    exhausted_providers: set[str] = set()
    attempted_financials: set[str] = set()
    memory_news: list[RawNews] = []
    clean_seed_queries = [q.strip() for q in (seed_queries or []) if q and q.strip()]
    if clean_seed_queries:
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
    for _ in range(max_iterations):
        _, audits = _collect_news(
            db, clean_symbols, as_of_dt, window_days=window_days,
            memory_items=memory_news,
        )
        # 财务可能在上一轮 backfill 被刷新；每轮重读以反映最新状态
        financials = [_latest_financial_context(db, symbol) for symbol in clean_symbols]
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
            "quality": evaluation.quality,
            "next_plan": evaluation.next_plan,
            "plan_result": plan_result,
        })
        if evaluation.quality == "ok" or evaluation.next_plan is None:
            break

    assert evaluation is not None  # max_iterations >= 1 保证至少一轮
    _, audits = _collect_news(
        db, clean_symbols, as_of_dt, window_days=window_days,
        memory_items=memory_news,
    )
    financials = [_latest_financial_context(db, symbol) for symbol in clean_symbols]
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
    )
    usable_count = evaluation.usable_count
    weak_count = evaluation.weak_count
    risk_flags = sorted({flag for audit in audits for flag in audit.risk_flags})
    summary = _build_summary(topic, clean_symbols, usable_count, weak_count)
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
    context_text = _build_m61_research_context_text(
        symbols=clean_symbols,
        db=db,
        as_of_dt=as_of_dt,
        topic=topic,
        max_chars=2000,
    )

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
