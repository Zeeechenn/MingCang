"""Manual weekend/sector deep research workflow.

This module is deliberately separate from scheduler.py and the daily signal
path. It only runs when called explicitly from CLI or API.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from backend.config import BASE_DIR
from backend.data.database import FinancialMetric, NewsItem, Price, Stock
from backend.data.news import RawNews
from backend.data.news_audit import NewsAudit, audit_news_items
from backend.research.agents import ResearchSection, build_research_sections


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


def _collect_news(db, symbols: list[str], as_of_dt: datetime) -> tuple[list[RawNews], list[NewsAudit]]:
    """Collect recent stored news and audit the source trail."""
    cutoff = as_of_dt - timedelta(days=14)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol.in_(symbols), NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(80)
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
    return items, audit_news_items(items, now=as_of_dt)


def _build_summary(topic: str, symbols: list[str], source_count: int, weak_count: int) -> str:
    """Build a concise deterministic research summary."""
    symbol_text = "、".join(symbols) if symbols else "未指定标的"
    return (
        f"{topic} 覆盖 {symbol_text}；本次使用 {source_count} 条可追溯新闻/公告证据，"
        f"{weak_count} 条来源或时效性偏弱。结论用于专题研究，不直接生成交易信号。"
    )


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
        "",
        "## 核心结论",
        summary,
        "",
        "## 研究员分工结论",
    ]
    for section in sections:
        lines.extend([f"### {section.title}", section.content, ""])

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
                f"{audit.news.title}｜{audit.news.url}"
            )
    else:
        lines.append("- 本地数据库暂无近 14 日新闻；本报告只保留结构化研究框架。")

    lines.extend([
        "",
        "## 待验证问题",
        "- 后续公告或财报是否验证当前主题逻辑？",
        "- 价格走势是否已经提前反映主题预期？",
        "- 是否存在政策、订单、客户集中度或估值拥挤风险？",
        "",
        "## 免责声明",
        "本报告由 StockSage 手动深度研究流程生成，不构成投资建议，不自动触发买卖信号。",
        "",
    ])
    return "\n".join(lines)


def run_deep_research(
    *,
    topic: str,
    symbols: list[str],
    db,
    output_dir: Path | str | None = None,
    as_of: str | None = None,
    persist: bool = True,
) -> DeepResearchReport:
    """Run a deterministic manual deep research workflow and optionally persist it."""
    clean_symbols = [s.strip() for s in symbols if s.strip()]
    day = as_of or datetime.utcnow().strftime("%Y-%m-%d")
    as_of_dt = datetime.strptime(day, "%Y-%m-%d")
    names = _symbol_names(db, clean_symbols)
    prices = [_latest_price_context(db, symbol) for symbol in clean_symbols]
    financials = [_latest_financial_context(db, symbol) for symbol in clean_symbols]
    _, audits = _collect_news(db, clean_symbols, as_of_dt)
    usable_count = sum(1 for audit in audits if audit.usable)
    weak_count = len(audits) - usable_count
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
        sections=sections,
    )
    path.write_text(text, encoding="utf-8")

    report = DeepResearchReport(
        topic=topic,
        symbols=clean_symbols,
        as_of=day,
        summary=summary,
        path=path,
        source_count=usable_count,
        risk_flags=risk_flags,
    )
    if persist:
        _persist_report(db, report, audits)
    return report


def _persist_report(db, report: DeepResearchReport, audits: list[NewsAudit]) -> None:
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
    }
    for symbol in report.symbols or [None]:
        record_decision_run(
            db,
            run_type="deep_research",
            symbol=symbol or "",
            as_of=report.as_of,
            result=result,
            input_snapshot=input_snapshot,
            notes=report.summary,
        )
    remember_deep_research(
        db,
        topic=report.topic,
        summary=report.summary,
        symbols=report.symbols,
        report_path=str(report.path) if report.path else "",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for manual deep research."""
    parser = argparse.ArgumentParser(description="Run a manual StockSage deep research report")
    parser.add_argument("--topic", required=True, help="研究主题，例如：AI算力产业链")
    parser.add_argument("--symbols", default="", help="逗号分隔股票代码，例如：300308,300394")
    parser.add_argument("--as-of", default=None, help="研究日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--output-dir", default=None, help="报告输出目录，默认 docs/research")
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
            persist=True,
        )
        print(report.path)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
