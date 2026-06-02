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
from sqlalchemy.orm import Session

from backend.data.database import Position, ReviewRun, Signal, Stock, get_db

router = APIRouter()

_POSTMARKET_REPORT_VERSION = "m31_postmarket_review_v1"
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


def _postmarket_review_html(db: Session, day: str) -> str:
    signals = (
        db.query(Signal)
        .filter(Signal.date == day)
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
    rule_version_text = ", ".join(rule_versions)
    profile_text = str(weights.profile or "unknown")

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>StockSage 盘后复盘 - {html.escape(day)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #111827; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{ margin: 20px 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 7px 9px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .notice {{ font-weight: 700; color: #7c2d12; }}
    .meta {{ color: #374151; }}
  </style>
</head>
<body>
  <h1>StockSage 盘后复盘 - {html.escape(day)}</h1>
  <p class="notice">{_POSTMARKET_DISCLAIMER}</p>
  <section>
    <h2>版本</h2>
    <ul class="meta">
      <li><strong>report_version:</strong> {html.escape(_POSTMARKET_REPORT_VERSION)}</li>
      <li><strong>rule/profile version:</strong> {html.escape(rule_version_text)} / {html.escape(profile_text)}</li>
      <li><strong>rule_version:</strong> {html.escape(rule_version_text)}</li>
      <li><strong>profile_version:</strong> {html.escape(profile_text)}</li>
    </ul>
  </section>
  <section>
    <h2>摘要</h2>
    <p>{html.escape(summary)}</p>
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
            headers={"Content-Disposition": f'attachment; filename="postmarket-review-{day}.doc"'},
        )
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="postmarket-review-{day}.html"'},
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
    snapshot_at = snapshot.get("generated_at") or datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    rows = [
        {"metric": "snapshot_at", "value": snapshot_at},
        {"metric": "active_stocks", "value": summary.get("active_stocks", "")},
        {"metric": "price_covered", "value": summary.get("price_covered", "")},
        {"metric": "two_year_price_covered", "value": summary.get("two_year_price_covered", "")},
        {"metric": "financial_covered", "value": summary.get("financial_covered", "")},
        {"metric": "news_24h_covered", "value": summary.get("news_24h_covered", "")},
        {"metric": "latest_price_date", "value": summary.get("latest_price_date", "")},
        {"metric": "signals_count", "value": summary.get("signals_count", "")},
        {"metric": "signals_first_date", "value": summary.get("signals_first_date", "")},
        {"metric": "signals_latest_date", "value": summary.get("signals_latest_date", "")},
    ]
    columns = [
        ("metric", "指标"),
        ("value", "数值"),
    ]
    return _csv_response(rows, columns, "coverage.csv")
