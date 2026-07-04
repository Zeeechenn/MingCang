"""Unified stock context pack builder for MingCang data consumers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Callable

from backend.data.database import (
    Announcement,
    CorporateEvent,
    FinancialMetric,
    FundFlow,
    HolderSnapshot,
    LhbRecord,
    LongTermLabel,
    NewsItem,
    OverseasSnapshot,
    Price,
    ResearchReport,
    SessionLocal,
)
from backend.data.degradation import emit_degradation, recent_degradations
from backend.data.fundamentals import compute_piotroski_factors
from backend.data.market_features import FAKE_FEATURE_FLAGS
from backend.tools import m52_flow_floor as flow_floor

SECTION_ORDER = [
    "price",
    "financials",
    "news",
    "announcements",
    "research_reports",
    "corporate_events",
    "holders",
    "lhb",
    "fund_flow",
    "overseas",
    "long_term_label",
    "data_health",
]

SECTION_LABELS = {
    "price": "价格",
    "financials": "财务",
    "news": "新闻",
    "announcements": "公告",
    "research_reports": "研报",
    "corporate_events": "公司事件",
    "holders": "股东",
    "lhb": "龙虎榜",
    "fund_flow": "资金流",
    "overseas": "海外领先指标",
    "long_term_label": "长期标签",
    "data_health": "数据健康",
}

_FINANCIAL_FIELDS = [
    "report_date",
    "disclosure_date",
    "period_type",
    "revenue",
    "revenue_yoy",
    "net_profit",
    "net_profit_yoy",
    "roe",
    "gross_margin",
    "current_ratio",
    "operating_cf",
    "total_assets",
    "total_equity",
    "long_term_debt",
    "asset_turnover",
]


def _as_datetime(value: datetime | None) -> datetime:
    return value or datetime.now()


def _date_string(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _empty_if(condition: bool, payload: dict) -> dict:
    return {"empty": True} if condition else payload


def _pct_change(rows: list[Price], periods: int) -> float | None:
    if len(rows) <= periods:
        return None
    current = rows[-1].close
    base = rows[-periods - 1].close
    if base in (None, 0):
        return None
    return (current / base - 1.0) * 100.0


def _build_price(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date <= _date_string(as_of))
        .order_by(Price.date.desc())
        .limit(61)
        .all()
    )
    if not rows:
        return {"empty": True}
    rows = list(reversed(rows))
    last = rows[-1]
    ma20 = mean([row.close for row in rows[-20:]]) if len(rows) >= 20 else None
    dist_ma20 = None if ma20 in (None, 0) else (last.close / ma20 - 1.0) * 100.0
    return {
        "date": last.date,
        "last_close": last.close,
        "pct_chg_5d": _pct_change(rows, 5),
        "pct_chg_20d": _pct_change(rows, 20),
        "pct_chg_60d": _pct_change(rows, 60),
        "atr14": last.atr14,
        "dist_from_20d_ma": dist_ma20,
    }


def _financial_visible_expr(as_of: datetime) -> str:
    as_of_date = _date_string(as_of)
    return as_of_date


def _build_financials(symbol: str, as_of: datetime, db) -> dict:
    as_of_date = _financial_visible_expr(as_of)
    row = (
        db.query(FinancialMetric)
        .filter(
            FinancialMetric.symbol == symbol,
            (FinancialMetric.disclosure_date <= as_of_date)
            | ((FinancialMetric.disclosure_date.is_(None)) & (FinancialMetric.report_date <= as_of_date)),
        )
        .order_by(FinancialMetric.report_date.desc())
        .first()
    )
    piotroski = compute_piotroski_factors(symbol, db)
    if row is None:
        return {"empty": True, "piotroski": piotroski}
    return {
        "latest": {field: getattr(row, field, None) for field in _FINANCIAL_FIELDS},
        "piotroski": {
            "factors": piotroski.get("factors", {}),
            "score": piotroski.get("score"),
            "score_denominator": piotroski.get("score_denominator"),
            "available": piotroski.get("available"),
            "report_period": piotroski.get("report_period"),
            "comparison_period": piotroski.get("comparison_period"),
        },
    }


def _build_news(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at <= as_of)
        .order_by(NewsItem.published_at.desc())
        .limit(8)
        .all()
    )
    return _empty_if(
        not rows,
        {
            "items": [
                {
                    "title": row.title,
                    "published_at": _iso(row.published_at),
                    "provider": row.provider or row.source,
                    "content_preview": (row.content or "")[:120],
                }
                for row in rows
            ]
        },
    )


def _build_announcements(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(Announcement)
        .filter(Announcement.symbol == symbol, Announcement.published_at <= as_of)
        .order_by(Announcement.published_at.desc())
        .limit(8)
        .all()
    )
    return _empty_if(
        not rows,
        {
            "items": [
                {
                    "title": row.title,
                    "ann_type": row.ann_type,
                    "published_at": _iso(row.published_at),
                }
                for row in rows
            ]
        },
    )


def _eps_forecast_trend(symbol: str, as_of: datetime, db) -> str | None:
    recent_start = as_of - timedelta(days=90)
    prior_start = as_of - timedelta(days=180)
    recent = [
        row.eps_forecast_y1
        for row in db.query(ResearchReport)
        .filter(
            ResearchReport.symbol == symbol,
            ResearchReport.publish_date > recent_start,
            ResearchReport.publish_date <= as_of,
            ResearchReport.eps_forecast_y1.isnot(None),
        )
        .all()
    ]
    prior = [
        row.eps_forecast_y1
        for row in db.query(ResearchReport)
        .filter(
            ResearchReport.symbol == symbol,
            ResearchReport.publish_date > prior_start,
            ResearchReport.publish_date <= recent_start,
            ResearchReport.eps_forecast_y1.isnot(None),
        )
        .all()
    ]
    if not recent or not prior:
        return None
    diff = mean(recent) - mean(prior)
    if abs(diff) < 1e-9:
        return "flat"
    return "up" if diff > 0 else "down"


def _build_research_reports(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(ResearchReport)
        .filter(ResearchReport.symbol == symbol, ResearchReport.publish_date <= as_of)
        .order_by(ResearchReport.publish_date.desc())
        .limit(6)
        .all()
    )
    payload = {
        "items": [
            {
                "title": row.title,
                "org_name": row.org_name,
                "rating": row.rating,
                "eps_forecast_y1": row.eps_forecast_y1,
                "eps_forecast_y2": row.eps_forecast_y2,
                "publish_date": _iso(row.publish_date),
            }
            for row in rows
        ],
        "eps_forecast_trend": _eps_forecast_trend(symbol, as_of, db),
    }
    return _empty_if(not rows, payload)


# PIT 语义按事件类型区分:排期类(解禁/分红)提前公告,event_date 晚于 as_of 也属
# as_of 时点可知,允许前瞻展示;执行记录类(回购成交/监管处置)只有事后才可知,
# 必须 event_date <= as_of,否则历史回放会时间穿越(2026-07-05 盲裁实证)。
_SCHEDULED_EVENT_KEYWORDS = ("解禁", "分红", "除权", "除息", "股东大会")


def _is_scheduled_event(event_type: str | None) -> bool:
    return any(keyword in (event_type or "") for keyword in _SCHEDULED_EVENT_KEYWORDS)


def corporate_event_visible_as_of(event_type: str, event_date: str, as_of: str) -> bool:
    """Return whether a corporate event is PIT-visible at the as_of date."""
    if _is_scheduled_event(event_type):
        return True
    return str(event_date)[:10] <= str(as_of)[:10]


def _build_corporate_events(symbol: str, as_of: datetime, db) -> dict:
    start = as_of - timedelta(days=30)
    end = as_of + timedelta(days=90)
    rows = (
        db.query(CorporateEvent)
        .filter(CorporateEvent.symbol == symbol, CorporateEvent.event_date >= start, CorporateEvent.event_date <= end)
        .order_by(CorporateEvent.event_date.asc())
        .all()
    )
    rows = [
        row
        for row in rows
        if corporate_event_visible_as_of(row.event_type or "", _iso(row.event_date), _iso(as_of))
    ]
    return _empty_if(
        not rows,
        {
            "items": [
                {
                    "event_type": row.event_type,
                    "title": row.title,
                    "event_date": _iso(row.event_date),
                    "detail": row.detail,
                }
                for row in rows
            ]
        },
    )


def _build_holders(symbol: str, as_of: datetime, db) -> dict:
    latest = (
        db.query(HolderSnapshot)
        .filter(HolderSnapshot.symbol == symbol, HolderSnapshot.report_date <= as_of)
        .order_by(HolderSnapshot.report_date.desc())
        .first()
    )
    if latest is None:
        return {"empty": True}
    target = latest.report_date - timedelta(days=365)
    candidates = (
        db.query(HolderSnapshot)
        .filter(
            HolderSnapshot.symbol == symbol,
            HolderSnapshot.report_date >= latest.report_date - timedelta(days=455),
            HolderSnapshot.report_date <= latest.report_date - timedelta(days=275),
            HolderSnapshot.total_shares.isnot(None),
        )
        .all()
    )
    earlier = min(candidates, key=lambda row: abs((row.report_date - target).total_seconds())) if candidates else None
    pct_change = None
    if latest.total_shares is not None and earlier is not None and earlier.total_shares not in (None, 0):
        pct_change = (latest.total_shares / earlier.total_shares - 1.0) * 100.0
    return {
        "latest": {
            "report_date": _iso(latest.report_date),
            "total_shares": latest.total_shares,
            "float_shares": latest.float_shares,
            "holder_count": latest.holder_count,
            "provider": latest.provider,
        },
        "share_trend": {
            "pct_change": pct_change,
            "latest_total_shares": latest.total_shares,
            "baseline_total_shares": earlier.total_shares if earlier else None,
            "baseline_report_date": _iso(earlier.report_date) if earlier else None,
        },
    }


def _build_lhb(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(LhbRecord)
        .filter(LhbRecord.symbol == symbol, LhbRecord.trade_date >= as_of - timedelta(days=90), LhbRecord.trade_date <= as_of)
        .order_by(LhbRecord.trade_date.desc())
        .all()
    )
    return _empty_if(
        not rows,
        {
            "items": [
                {
                    "trade_date": _iso(row.trade_date),
                    "reason": row.reason,
                    "net_buy_amount": row.net_buy_amount,
                }
                for row in rows
            ]
        },
    )


def _fetch_flow_data_for_db(symbol: str, as_of: datetime, db) -> list[dict[str, Any]] | None:
    if db is None:
        return flow_floor.fetch_flow_data_pit(symbol, as_of)
    rows = (
        db.query(FundFlow)
        .filter(FundFlow.symbol == symbol, FundFlow.trade_date <= as_of)
        .order_by(FundFlow.trade_date.desc())
        .limit(65)
        .all()
    )
    if not rows:
        return None
    return [
        {
            "trade_date": row.trade_date,
            "main_net": row.main_net,
            "super_large_net": row.super_large_net,
            "large_net": row.large_net,
            "medium_net": row.medium_net,
            "small_net": row.small_net,
        }
        for row in reversed(rows)
    ]


def _build_fund_flow(symbol: str, as_of: datetime, db) -> dict:
    raw = _fetch_flow_data_for_db(symbol, as_of, db)
    if not raw:
        return {"empty": True}
    values = [float(row.get("main_net")) for row in raw if row.get("main_net") is not None]
    recent5 = sum(values[-5:]) if len(values) >= 5 else None
    return {
        "s_flow": flow_floor.compute_s_flow_data(raw),
        "recent5_main_net": recent5,
    }


def _build_overseas(symbol: str, as_of: datetime, db) -> dict:
    rows = (
        db.query(OverseasSnapshot)
        .filter(OverseasSnapshot.symbol == symbol, OverseasSnapshot.snap_date <= as_of)
        .order_by(OverseasSnapshot.snap_date.desc())
        .limit(6)
        .all()
    )
    return _empty_if(
        not rows,
        {
            "items": [
                {
                    "name": row.name,
                    "snap_date": _iso(row.snap_date),
                    "close": row.close,
                    "chg_pct_1d": row.chg_pct_1d,
                    "chg_pct_20d": row.chg_pct_20d,
                    "note": row.note,
                }
                for row in rows
            ]
        },
    )


def _build_long_term_label(symbol: str, as_of: datetime, db) -> dict:
    row = (
        db.query(LongTermLabel)
        .filter(LongTermLabel.symbol == symbol, LongTermLabel.date <= _date_string(as_of))
        .order_by(LongTermLabel.date.desc(), LongTermLabel.created_at.desc())
        .first()
    )
    if row is None:
        return {"empty": True}
    return {
        "label": row.label,
        "score": row.score,
        "date": row.date,
        "expires_at": row.expires_at,
    }


def _degradation_matches_symbol(event: dict, symbol: str) -> bool:
    raw_context = event.get("context_json")
    if not raw_context:
        return False
    try:
        parsed = json.loads(raw_context)
    except Exception:
        return symbol in raw_context
    return parsed.get("symbol") == symbol


def _build_data_health(symbol: str, as_of: datetime, db) -> dict:
    degradations = [event for event in recent_degradations(hours=72, db=db) if _degradation_matches_symbol(event, symbol)]
    placeholders = {
        name: meta
        for name, meta in FAKE_FEATURE_FLAGS.items()
        if isinstance(meta, dict) and meta.get("placeholder") is True
    }
    if not degradations and not placeholders:
        return {"empty": True}
    return {
        "recent_degradations": degradations,
        "active_fake_feature_flags": placeholders,
    }


_SECTION_BUILDERS: dict[str, Callable[[str, datetime, Any], dict]] = {
    "price": _build_price,
    "financials": _build_financials,
    "news": _build_news,
    "announcements": _build_announcements,
    "research_reports": _build_research_reports,
    "corporate_events": _build_corporate_events,
    "holders": _build_holders,
    "lhb": _build_lhb,
    "fund_flow": _build_fund_flow,
    "overseas": _build_overseas,
    "long_term_label": _build_long_term_label,
    "data_health": _build_data_health,
}


def build_stock_context_pack(
    symbol: str,
    as_of: datetime | None = None,
    sections: list[str] | None = None,
    db=None,
) -> dict:
    """Build a point-in-time stock context pack without calling LLMs or networks."""
    requested = SECTION_ORDER if sections is None else sections
    unknown = [section for section in requested if section not in _SECTION_BUILDERS]
    if unknown:
        raise ValueError(f"unknown section name(s): {', '.join(unknown)}")

    own_session = db is None
    session = db or SessionLocal()
    as_of_dt = _as_datetime(as_of)
    pack: dict[str, Any] = {"symbol": symbol, "as_of": as_of_dt.isoformat()}
    try:
        for section in requested:
            try:
                pack[section] = _SECTION_BUILDERS[section](symbol, as_of_dt, session)
            except Exception as exc:
                pack[section] = {"error": str(exc)}
                emit_degradation(
                    component="context_builder",
                    category=section,
                    provider="context_builder",
                    error=f"failure:{exc}",
                    context={"symbol": symbol, "as_of": as_of_dt.isoformat(), "section": section},
                    db=session,
                )
        return pack
    finally:
        if own_session:
            session.close()


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if value is None:
        return "NA"
    return str(value)


def _section_lines(section: str, value: dict) -> list[str]:
    label = SECTION_LABELS[section]
    if value.get("error") is not None:
        return [f"⚠️ {label}: 数据获取失败"]
    if value.get("empty") is True:
        return [f"({label}: 无数据)"]
    lines = [f"【{label}】"]
    if section == "price":
        lines.append(
            "最新收盘 {last_close} ({date}); 5/20/60日涨跌 {pct_chg_5d}/{pct_chg_20d}/{pct_chg_60d}%; "
            "ATR14 {atr14}; 距20日均线 {dist_from_20d_ma}%".format(**{k: _format_value(value.get(k)) for k in [
                "last_close", "date", "pct_chg_5d", "pct_chg_20d", "pct_chg_60d", "atr14", "dist_from_20d_ma"
            ]})
        )
    elif section == "financials":
        latest = value.get("latest") or {}
        piotroski = value.get("piotroski") or {}
        lines.append(
            "报告期 {report_date}; ROE {roe}; 收入同比 {revenue_yoy}%; 净利同比 {net_profit_yoy}%; "
            "毛利率 {gross_margin}; 经营现金流 {operating_cf}; 流动比率 {current_ratio}".format(
                **{k: _format_value(latest.get(k)) for k in [
                    "report_date", "roe", "revenue_yoy", "net_profit_yoy", "gross_margin", "operating_cf", "current_ratio"
                ]}
            )
        )
        denominator = piotroski.get("score_denominator")
        na_count = 9 - denominator if isinstance(denominator, int) else "NA"
        lines.append(
            f"Piotroski {piotroski.get('score')}/{denominator} (N/A因子 {na_count}): "
            f"{json.dumps(piotroski.get('factors') or {}, ensure_ascii=False, sort_keys=True)}"
        )
    elif section in {"news", "announcements", "corporate_events", "lhb"}:
        for item in value.get("items", []):
            lines.append(" - " + " | ".join(f"{k}={_format_value(v)}" for k, v in item.items() if v not in (None, "")))
    elif section == "research_reports":
        lines.append(f"EPS预测趋势: {_format_value(value.get('eps_forecast_trend'))}")
        for item in value.get("items", []):
            lines.append(" - " + " | ".join(f"{k}={_format_value(v)}" for k, v in item.items() if v not in (None, "")))
    elif section == "holders":
        latest = value.get("latest") or {}
        trend = value.get("share_trend") or {}
        lines.append(
            f"最新 {latest.get('report_date')}; 总股本 {_format_value(latest.get('total_shares'))}; "
            f"流通股 {_format_value(latest.get('float_shares'))}; 户数 {_format_value(latest.get('holder_count'))}; "
            f"约四季股本变化 {_format_value(trend.get('pct_change'))}%"
        )
    elif section == "fund_flow":
        lines.append(f"S-flow {_format_value(value.get('s_flow'))}; 近5日主力净流入 {_format_value(value.get('recent5_main_net'))}")
    elif section == "overseas":
        for item in value.get("items", []):
            lines.append(" - " + " | ".join(f"{k}={_format_value(v)}" for k, v in item.items() if v not in (None, "")))
    elif section == "long_term_label":
        lines.append(
            f"{value.get('date')}: {value.get('label')} score={_format_value(value.get('score'))} expires={value.get('expires_at')}"
        )
    elif section == "data_health":
        lines.append(f"近期降级 {len(value.get('recent_degradations') or [])} 条")
        for event in value.get("recent_degradations") or []:
            lines.append(f" - {event.get('category')}/{event.get('provider')}: {event.get('error')}")
        flags = value.get("active_fake_feature_flags") or {}
        if flags:
            lines.append("假特征占位: " + ", ".join(sorted(flags)))
    return lines


def render_context_text(pack: dict, max_chars: int = 4000) -> str:
    """Render a deterministic Chinese plain-text context prompt."""
    lines = [f"股票: {pack.get('symbol', 'NA')}", f"截至: {pack.get('as_of', 'NA')}"]
    for section in SECTION_ORDER:
        if section in pack:
            lines.extend(_section_lines(section, pack[section]))

    output: list[str] = []
    used = 0
    for line in lines:
        candidate_len = len(line) if not output else len(line) + 1
        if used + candidate_len > max_chars:
            break
        output.append(line)
        used += candidate_len
    return "\n".join(output)
