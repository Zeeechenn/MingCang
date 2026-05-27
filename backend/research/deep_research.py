"""Manual weekend/sector deep research workflow.

This module is deliberately separate from scheduler.py and the daily signal
path. It only runs when called explicitly from CLI or API.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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
    retrieval_iterations: tuple[dict, ...] = ()  # evaluator/planner 闭环轨迹


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
) -> tuple[list[RawNews], list[NewsAudit]]:
    """Collect recent stored news and audit the source trail."""
    cutoff = as_of_dt - timedelta(days=window_days)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol.in_(symbols), NewsItem.published_at >= cutoff)
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
        elif "tavily" not in exhausted_providers and _settings.tavily_api_key:
            provider = "tavily"
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
) -> dict:
    """执行 evaluator/planner 给出的下一步动作；返回执行摘要供 trace。"""
    action = plan.get("action")
    if action == "expand_news_window":
        return {"action": action, "window_days_next": int(plan["to_days"])}
    if action == "fetch_external_news":
        return _fetch_external_news(db, symbols, plan["provider"], days=int(plan["days"]))
    if action == "backfill_financials":
        return _backfill_financials(db, plan["symbols"])
    return {"action": action, "skipped": True}


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
    min_usable_sources: int = 3,
    max_iterations: int = 5,
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
    day = as_of or datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
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
    for _ in range(max_iterations):
        _, audits = _collect_news(
            db, clean_symbols, as_of_dt, window_days=window_days,
        )
        # 财务可能在上一轮 backfill 被刷新；每轮重读以反映最新状态
        financials = [_latest_financial_context(db, symbol) for symbol in clean_symbols]
        evaluation = _evaluate_evidence(
            audits=audits,
            financials=financials,
            window_days=window_days,
            min_usable=min_usable_sources,
            exhausted_providers=exhausted_providers,
            attempted_financials=attempted_financials,
        )
        plan_result: dict | None = None
        if evaluation.next_plan is not None:
            plan_result = _execute_plan(evaluation.next_plan, db, clean_symbols)
            action = evaluation.next_plan.get("action")
            if action == "expand_news_window":
                window_days = int(plan_result.get("window_days_next", window_days))
            elif action == "fetch_external_news":
                # 标记 provider 已尝试，避免下一轮重复打同一个外部源
                exhausted_providers.add(evaluation.next_plan["provider"])
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
        retrieval_iterations=tuple(iterations),
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
    }
    for symbol in report.symbols or [""]:
        record_decision_run(
            db,
            run_type="deep_research",
            symbol=symbol,
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
