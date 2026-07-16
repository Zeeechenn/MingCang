"""CSV exports for signals / positions / reviews / coverage snapshot.

M25.4 导出能力（建议 / P2）：
  - GET /api/export/signals.csv?symbol=&limit=
  - GET /api/export/positions.csv?status=
  - GET /api/export/reviews.csv?kind=&limit=
  - GET /api/export/coverage.csv

CSV 用 UTF-8 with BOM 输出方便 Excel 直接打开；列名优先用中文以便阅读。
Excel (.xlsx) 作为后续增强，本期不实现。
"""
from __future__ import annotations

import csv
import html
import io
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.data.database import Position, Price, ReviewRun, Signal, Stock, get_db
from backend.observability import correlation_headers, get_correlation_id

router = APIRouter()

_POSTMARKET_REPORT_VERSION = "m31_postmarket_review_v2"
_EVIDENCE_CARD_CAP = 10
_POSTMARKET_DISCLAIMER = "研究复盘，非投资建议、非价格预测"


def _csv_response(rows: list[dict], columns: list[tuple[str, str]], filename: str) -> Response:
    """Encode rows as UTF-8 BOM CSV and wrap in a Response with download headers."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in columns])
    data = "﻿" + buf.getvalue()
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            **correlation_headers(),
        },
    )


def _format_number(value: float | None, digits: int = 1) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _active_profile_for_day(day: str):
    from backend.config import active_signal_weights

    try:
        parsed_day = date.fromisoformat(day)
    except ValueError:
        parsed_day = None
    return active_signal_weights(parsed_day)


def _percent(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:+.{digits}f}%"


def _evidence_cards_html(signals: list, names: dict, cap: int = _EVIDENCE_CARD_CAP) -> str:
    """Render per-signal evidence cards (score decomposition, levels, rationale)."""
    cards = []
    for signal in signals[:cap]:
        label = f"{signal.symbol} {names.get(signal.symbol, '')}".strip()
        rationale = (signal.llm_rationale or "").strip() or "（无 LLM 综合理由记录）"
        cards.append(
            '<div class="card">'
            f"<h3>{html.escape(label)} · {html.escape(signal.recommendation or '')} "
            f"（综合 {html.escape(_format_number(signal.composite_score))} / 置信 {html.escape(signal.confidence or '')}）</h3>"
            '<ul class="meta">'
            f"<li>量化 / 技术 / 情感分: {html.escape(_format_number(signal.quant_score))} / "
            f"{html.escape(_format_number(signal.technical_score))} / {html.escape(_format_number(signal.sentiment_score))}</li>"
            f"<li>止损 / 止盈: {html.escape(_format_number(signal.stop_loss, 2))} / {html.escape(_format_number(signal.take_profit, 2))}</li>"
            f"<li>涨跌停 / 规则版本: {html.escape(signal.limit_status or 'normal')} / {html.escape(signal.rule_version or 'unknown')}</li>"
            "</ul>"
            f"<p>{html.escape(rationale)}</p>"
            "</div>"
        )
    if not cards:
        return "<p>当日没有可展示的信号证据卡。</p>"
    capped_note = ""
    if len(signals) > cap:
        capped_note = f'<p class="meta">仅展示综合分最高的 {cap} 条信号证据卡，完整 {len(signals)} 条见上方信号表。</p>'
    return "\n".join(cards) + capped_note


def _position_review_html(db: Session, day: str) -> str:
    """Render open-position review plus any positions closed on the report day."""
    open_positions = (
        db.query(Position)
        .filter(Position.status == "open")
        .order_by(Position.symbol)
        .all()
    )
    closed_today = (
        db.query(Position)
        .filter(Position.status == "closed", Position.closed_at == day)
        .order_by(Position.symbol)
        .all()
    )
    if not open_positions and not closed_today:
        return "<p>当前没有持仓，且当日没有平仓记录。</p>"

    open_rows = []
    for pos in open_positions:
        latest = (
            db.query(Price.close)
            .filter(Price.asset_key == pos.asset_key)
            .order_by(Price.date.desc())
            .first()
        )
        current = float(latest[0]) if latest else None
        unrealized = None
        if current is not None and pos.avg_cost:
            unrealized = (current - pos.avg_cost) / pos.avg_cost * 100
        label = f"{pos.symbol} {pos.name or ''}".strip()
        open_rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(_format_number(pos.quantity, 0))}</td>"
            f"<td>{html.escape(_format_number(pos.avg_cost, 2))}</td>"
            f"<td>{html.escape(_format_number(current, 2))}</td>"
            f"<td>{html.escape(_percent(unrealized))}</td>"
            f"<td>{html.escape(_format_number(pos.stop_loss, 2))}</td>"
            f"<td>{html.escape(_format_number(pos.take_profit, 2))}</td>"
            f"<td>{html.escape(pos.opened_at or '')}</td>"
            "</tr>"
        )

    parts = ["<h3>当前持仓</h3>"]
    open_table = "\n".join(open_rows) if open_rows else '<tr><td colspan="8">当前无持仓。</td></tr>'
    parts.append(
        "<table><thead><tr>"
        "<th>股票</th><th>数量</th><th>成本</th><th>现价</th><th>浮动盈亏</th>"
        "<th>止损</th><th>止盈</th><th>建仓日</th>"
        f"</tr></thead><tbody>{open_table}</tbody></table>"
    )

    if closed_today:
        closed_rows = []
        for pos in closed_today:
            label = f"{pos.symbol} {pos.name or ''}".strip()
            closed_rows.append(
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f"<td>{html.escape(_format_number(pos.quantity, 0))}</td>"
                f"<td>{html.escape(_format_number(pos.avg_cost, 2))}</td>"
                f"<td>{html.escape(_format_number(pos.close_price, 2))}</td>"
                f"<td>{html.escape(_percent(pos.realized_pnl_pct))}</td>"
                f"<td>{html.escape(_format_number(pos.realized_pnl, 2))}</td>"
                "</tr>"
            )
        parts.append("<h3>当日平仓</h3>")
        parts.append(
            "<table><thead><tr>"
            "<th>股票</th><th>数量</th><th>成本</th><th>平仓价</th><th>已实现盈亏%</th><th>已实现盈亏</th>"
            f"</tr></thead><tbody>{''.join(closed_rows)}</tbody></table>"
        )
    return "\n".join(parts)


def _coverage_status(snapshot: dict) -> str:
    warnings = snapshot.get("warnings") or []
    checks = snapshot.get("checks") or {}
    if warnings or any(value is False for value in checks.values()):
        return "warning"
    return "pass"


def _daily_provider_chain(snapshot: dict, market: str = "CN") -> str:
    chain = (
        snapshot.get("provider_fallback_chains", {})
        .get("chains_by_market", {})
        .get(market, {})
        .get("daily", [])
    )
    names = []
    for item in chain:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                names.append(str(name))
    return " > ".join(names)


def _data_trust_html(db: Session) -> str:
    from backend.data.quality import build_data_coverage_snapshot

    snapshot = build_data_coverage_snapshot(db)
    summary = snapshot.get("summary", {})
    warnings = snapshot.get("warnings") or []
    warning_text = ", ".join(str(item.get("code", "")) for item in warnings if item.get("code")) or "none"
    return (
        "<ul class=\"meta\">"
        f"<li><strong>coverage_status:</strong> {html.escape(_coverage_status(snapshot))}</li>"
        f"<li><strong>latest_price_date:</strong> {html.escape(str(summary.get('latest_price_date') or ''))}</li>"
        f"<li><strong>warning_count:</strong> {len(warnings)}</li>"
        f"<li><strong>warnings:</strong> {html.escape(warning_text)}</li>"
        f"<li><strong>CN daily provider chain:</strong> {html.escape(_daily_provider_chain(snapshot) or 'unavailable')}</li>"
        "</ul>"
    )


def _postmarket_review_html(db: Session, day: str) -> str:
    # Signal.date 可能是纯日期，也可能是批次时间戳(YYYY-MM-DDTHH:MM+08:00)，
    # 取日前缀比较才能同时命中两种格式。
    signals = (
        db.query(Signal)
        .filter(func.substr(Signal.date, 1, 10) == day)
        .order_by(Signal.composite_score.desc())
        .all()
    )
    review = (
        db.query(ReviewRun)
        .filter(ReviewRun.kind == "daily", ReviewRun.as_of == day)
        .order_by(ReviewRun.created_at.desc())
        .first()
    )
    symbols = [signal.symbol for signal in signals]
    names = {}
    if symbols:
        names = {
            row.symbol: row.name
            for row in db.query(Stock).filter(Stock.symbol.in_(symbols)).all()
        }
    weights = _active_profile_for_day(day)
    rule_versions = sorted({signal.rule_version or "unknown" for signal in signals}) or ["no_signal_rule_version"]
    summary = (review.summary if review else None) or f"{day} 盘后复盘：读取 {len(signals)} 条当日信号。"

    rows = []
    for signal in signals:
        label = f"{signal.symbol} {names.get(signal.symbol, '')}".strip()
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(_format_number(signal.composite_score))}</td>"
            f"<td>{html.escape(signal.recommendation or '')}</td>"
            f"<td>{html.escape(signal.confidence or '')}</td>"
            f"<td>{html.escape(_format_number(signal.technical_score))}</td>"
            f"<td>{html.escape(_format_number(signal.sentiment_score))}</td>"
            f"<td>{html.escape(signal.limit_status or '')}</td>"
            f"<td>{html.escape(signal.rule_version or 'unknown')}</td>"
            "</tr>"
        )
    signal_table = "\n".join(rows) if rows else '<tr><td colspan="8">当日没有信号。</td></tr>'
    evidence_cards = _evidence_cards_html(signals, names)
    position_review = _position_review_html(db, day)
    data_trust = _data_trust_html(db)
    rule_version_text = ", ".join(rule_versions)
    profile_text = str(weights.profile or "unknown")
    correlation_id = get_correlation_id() or "none"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>MingCang 盘后复盘 - {html.escape(day)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #111827; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{ margin: 20px 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 7px 9px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .notice {{ font-weight: 700; color: #7c2d12; }}
    .meta {{ color: #374151; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 14px; margin: 10px 0; }}
    .card h3 {{ margin: 0 0 6px; font-size: 15px; }}
    .card p {{ margin: 6px 0 0; white-space: pre-wrap; }}
    h3 {{ margin: 16px 0 8px; }}
  </style>
</head>
<body>
  <h1>MingCang 盘后复盘 - {html.escape(day)}</h1>
  <p class="notice">{_POSTMARKET_DISCLAIMER}</p>
  <section>
    <h2>版本</h2>
    <ul class="meta">
      <li><strong>report_version:</strong> {html.escape(_POSTMARKET_REPORT_VERSION)}</li>
      <li><strong>rule/profile version:</strong> {html.escape(rule_version_text)} / {html.escape(profile_text)}</li>
      <li><strong>rule_version:</strong> {html.escape(rule_version_text)}</li>
      <li><strong>profile_version:</strong> {html.escape(profile_text)}</li>
      <li><strong>correlation_id:</strong> {html.escape(correlation_id)}</li>
    </ul>
  </section>
  <section>
    <h2>摘要</h2>
    <p>{html.escape(summary)}</p>
  </section>
  <section>
    <h2>数据可信度</h2>
    {data_trust}
  </section>
  <section>
    <h2>当日信号</h2>
    <table>
      <thead>
        <tr>
          <th>股票</th>
          <th>综合分</th>
          <th>建议</th>
          <th>置信度</th>
          <th>技术分</th>
          <th>情感分</th>
          <th>涨跌停状态</th>
          <th>规则版本</th>
        </tr>
      </thead>
      <tbody>
        {signal_table}
      </tbody>
    </table>
  </section>
  <section>
    <h2>信号证据卡</h2>
    {evidence_cards}
  </section>
  <section>
    <h2>持仓复盘</h2>
    {position_review}
  </section>
</body>
</html>
"""


@router.get("/export/postmarket-review.html")
def export_postmarket_review_html(
    as_of: str | None = Query(None),
    export_format: str = Query("html", alias="format", pattern="^(html|word)$"),
    db: Session = Depends(get_db),
) -> Response:
    day = as_of or datetime.now(UTC).replace(tzinfo=None).date().isoformat()
    body = _postmarket_review_html(db, day)
    if export_format == "word":
        return Response(
            content=body,
            media_type="application/msword",
            headers={
                "Content-Disposition": f'attachment; filename="postmarket-review-{day}.doc"',
                **correlation_headers(),
            },
        )
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="postmarket-review-{day}.html"',
            **correlation_headers(),
        },
    )


@router.get("/export/signals.csv")
def export_signals_csv(
    symbol: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> Response:
    q = db.query(Signal).order_by(Signal.date.desc())
    if symbol:
        q = q.filter(Signal.symbol == symbol)
    sigs = q.limit(limit).all()
    rows = [
        {
            "date": s.date,
            "symbol": s.symbol,
            "market": getattr(s, "market", "CN") or "CN",
            "signal_scope": getattr(s, "signal_scope", "production") or "production",
            "composite_score": round(s.composite_score, 2) if s.composite_score is not None else "",
            "recommendation": s.recommendation,
            "confidence": s.confidence or "",
            "quant_score": round(s.quant_score, 2) if s.quant_score is not None else "",
            "technical_score": round(s.technical_score, 2) if s.technical_score is not None else "",
            "sentiment_score": round(s.sentiment_score, 2) if s.sentiment_score is not None else "",
            "stop_loss": s.stop_loss if s.stop_loss is not None else "",
            "take_profit": s.take_profit if s.take_profit is not None else "",
            "limit_status": s.limit_status or "",
            "rule_version": s.rule_version or "",
        }
        for s in sigs
    ]
    columns = [
        ("date", "日期"),
        ("symbol", "代码"),
        ("market", "市场"),
        ("signal_scope", "信号范围"),
        ("composite_score", "综合分"),
        ("recommendation", "建议"),
        ("confidence", "置信度"),
        ("quant_score", "量化分"),
        ("technical_score", "技术分"),
        ("sentiment_score", "情感分"),
        ("stop_loss", "止损"),
        ("take_profit", "止盈"),
        ("limit_status", "涨跌停状态"),
        ("rule_version", "规则版本"),
    ]
    return _csv_response(rows, columns, "signals.csv")


@router.get("/export/positions.csv")
def export_positions_csv(
    status: str | None = Query(None, pattern="^(open|closed)$"),
    db: Session = Depends(get_db),
) -> Response:
    q = db.query(Position).order_by(Position.opened_at.desc())
    if status:
        q = q.filter(Position.status == status)
    pos = q.all()
    rows = [
        {
            "symbol": p.symbol,
            "market": p.market,
            "currency": p.currency or "",
            "name": p.name or "",
            "status": p.status,
            "opened_at": p.opened_at,
            "closed_at": p.closed_at or "",
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "close_price": p.close_price if p.close_price is not None else "",
            "cost": round(p.quantity * p.avg_cost, 2),
            "stop_loss": p.stop_loss if p.stop_loss is not None else "",
            "take_profit": p.take_profit if p.take_profit is not None else "",
            "realized_pnl": p.realized_pnl if p.realized_pnl is not None else "",
            "realized_pnl_pct": p.realized_pnl_pct if p.realized_pnl_pct is not None else "",
        }
        for p in pos
    ]
    columns = [
        ("symbol", "代码"),
        ("market", "市场"),
        ("currency", "币种"),
        ("name", "名称"),
        ("status", "状态"),
        ("opened_at", "建仓日"),
        ("closed_at", "平仓日"),
        ("quantity", "股数"),
        ("avg_cost", "买入价"),
        ("close_price", "平仓价"),
        ("cost", "成本"),
        ("stop_loss", "止损"),
        ("take_profit", "止盈"),
        ("realized_pnl", "已实现盈亏"),
        ("realized_pnl_pct", "盈亏率"),
    ]
    return _csv_response(rows, columns, "positions.csv")


@router.get("/export/reviews.csv")
def export_reviews_csv(
    kind: str | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Response:
    q = db.query(ReviewRun).order_by(ReviewRun.as_of.desc())
    if kind:
        q = q.filter(ReviewRun.kind == kind)
    reviews = q.limit(limit).all()
    rows = [
        {
            "as_of": r.as_of,
            "kind": r.kind,
            "status": r.status,
            "summary": (r.summary or "").replace("\n", " "),
            "path": r.path or "",
            "created_at": str(r.created_at) if r.created_at else "",
        }
        for r in reviews
    ]
    columns = [
        ("as_of", "日期"),
        ("kind", "类别"),
        ("status", "状态"),
        ("summary", "摘要"),
        ("path", "报告路径"),
        ("created_at", "生成时间"),
    ]
    return _csv_response(rows, columns, "reviews.csv")


@router.get("/export/coverage.csv")
def export_coverage_csv(db: Session = Depends(get_db)) -> Response:
    from backend.data.quality import build_data_coverage_snapshot

    snapshot = build_data_coverage_snapshot(db)
    summary = snapshot.get("summary", {})
    warnings = snapshot.get("warnings") or []
    warning_codes = ",".join(str(item.get("code")) for item in warnings if item.get("code"))
    freshness_contract = snapshot.get("freshness_contract", {})
    daily_freshness = freshness_contract.get("daily_price", {})
    intraday_policy = snapshot.get("intraday_zero_network_policy", {})
    snapshot_at = snapshot.get("generated_at") or datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    rows = [
        {"metric": "snapshot_at", "value": snapshot_at},
        {"metric": "coverage_status", "value": _coverage_status(snapshot)},
        {"metric": "warning_count", "value": len(warnings)},
        {"metric": "warning_codes", "value": warning_codes},
        {"metric": "active_stocks", "value": summary.get("active_stocks", "")},
        {"metric": "price_covered", "value": summary.get("price_covered", "")},
        {"metric": "two_year_price_covered", "value": summary.get("two_year_price_covered", "")},
        {"metric": "financial_covered", "value": summary.get("financial_covered", "")},
        {"metric": "news_24h_covered", "value": summary.get("news_24h_covered", "")},
        {"metric": "latest_price_date", "value": summary.get("latest_price_date", "")},
        {"metric": "daily_provider_chain_CN", "value": _daily_provider_chain(snapshot)},
        {"metric": "freshness_contract_daily_price", "value": daily_freshness.get("intraday_policy", "")},
        {"metric": "intraday_remote_fetch_allowed", "value": intraday_policy.get("remote_fetch_allowed", "")},
        {"metric": "signals_count", "value": summary.get("signals_count", "")},
        {"metric": "signals_first_date", "value": summary.get("signals_first_date", "")},
        {"metric": "signals_latest_date", "value": summary.get("signals_latest_date", "")},
    ]
    columns = [
        ("metric", "指标"),
        ("value", "数值"),
    ]
    return _csv_response(rows, columns, "coverage.csv")
