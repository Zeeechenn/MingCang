"""M61 category provider fetchers and persistence helpers."""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from typing import Any

import requests

from backend.config import settings
from backend.data.category_registry import CategoryProvider, FetchRequest, register_category_provider
from backend.data.ifind_mcp import NEWS_MCP_ID, IfindMcpClient, parse_ifind_mcp_text
from backend.data.orm import _utcnow

logger = logging.getLogger(__name__)

REPORT_API_URL = "https://reportapi.eastmoney.com/report/list"
EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.eastmoney.com/",
}


def _date_str(value: date | datetime | None) -> str:
    if value is None:
        return _utcnow().strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%d")


def _compact(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _parse_datetime(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = _compact(value)
    if not text:
        return fallback or _utcnow()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None)


def _to_float(value: Any) -> float | None:
    text = _compact(value).replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def _extract_ifind_items(text: str) -> list[dict[str, Any]]:
    parsed = parse_ifind_mcp_text(text)
    candidates: list[Any] = [parsed.get("json")]
    candidates.extend(table.get("rows", []) for table in parsed.get("tables", []))

    def walk(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            rows: list[dict[str, Any]] = []
            for item in value:
                rows.extend(walk(item))
            return rows
        if isinstance(value, dict):
            if any(key in value for key in ("公告标题", "资讯标题", "title", "标题")):
                return [value]
            for key in ("data", "result", "rows", "list"):
                child = value.get(key)
                if isinstance(child, str):
                    try:
                        child = json.loads(child)
                    except json.JSONDecodeError:
                        continue
                rows = walk(child)
                if rows:
                    return rows
        return []

    out: list[dict[str, Any]] = []
    for candidate in candidates:
        out.extend(walk(candidate))
    return out


def _announcement_row(item: dict[str, Any], request: FetchRequest) -> dict | None:
    title = _compact(
        item.get("公告标题")
        or item.get("title")
        or item.get("标题")
        or item.get("资讯标题")
    )
    if not title:
        return None
    source_url = _compact(item.get("URL") or item.get("url") or item.get("公告链接"))
    source_url = source_url or None
    published_at = _parse_datetime(
        item.get("日期")
        or item.get("公告日期")
        or item.get("publishDate")
        or item.get("published_at"),
        datetime.combine(request.start or date.today(), datetime.min.time()),
    )
    content = _compact(item.get("公告内容") or item.get("content") or item.get("内容") or item.get("资讯内容"))
    ann_type = _compact(item.get("公告类型") or item.get("类型") or item.get("category"))
    return {
        "symbol": request.symbol,
        "title": title,
        "content": content or None,
        "ann_type": ann_type or None,
        "published_at": published_at,
        "source_url": source_url,
        "url": source_url or f"ifind-notice://{request.symbol}/{published_at:%Y%m%d}/{abs(hash(title))}",
        "provider": "ifind_notice",
        "source": "ifind_notice",
        "fetched_at": _utcnow(),
    }


def fetch_announcements_ifind_notice(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for ifind_notice")
    start = _date_str(request.start)
    end = _date_str(request.end)
    name = _compact(request.extra.get("name")) or request.symbol
    size = min(int(request.limit or 20), 20)
    query = f"{name}({request.symbol}) 公告 {start}至{end}"
    result = IfindMcpClient().call_tool(
        NEWS_MCP_ID,
        "search_notice",
        {
            "query": query,
            "time_start": start,
            "time_end": end,
            "size": size,
        },
    )
    rows = []
    for item in _extract_ifind_items(result.text):
        row = _announcement_row(item, request)
        if row is not None:
            rows.append(row)
    return rows


def fetch_research_reports_eastmoney(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for eastmoney_reportapi")
    limit = min(int(request.limit or 50), 100)
    response = requests.get(
        REPORT_API_URL,
        params={
            "code": request.symbol,
            "beginTime": _date_str(request.start),
            "endTime": _date_str(request.end),
            "pageSize": limit,
            "pageNo": 1,
            "qType": 0,
        },
        headers=EASTMONEY_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else []
    rows = []
    for item in data or []:
        title = _compact(item.get("title") or item.get("reportName") or item.get("报告名称"))
        org_name = _compact(item.get("orgSName") or item.get("orgName") or item.get("机构"))
        publish_date = item.get("publishDate") or item.get("publish_date") or item.get("日期")
        if not title or not org_name or not publish_date:
            continue
        rows.append(
            {
                "symbol": request.symbol,
                "title": title,
                "org_name": org_name,
                "rating": _compact(item.get("emRatingName") or item.get("rating")) or None,
                "eps_forecast_y1": _to_float(item.get("predictThisYearEps")),
                "eps_forecast_y2": _to_float(item.get("predictNextYearEps")),
                "publish_date": _parse_datetime(publish_date),
                "info_code": _compact(item.get("infoCode")) or None,
                "provider": "eastmoney_reportapi",
            }
        )
    return rows


def fetch_lhb_akshare(request: FetchRequest) -> list[dict]:
    import akshare as ak

    start = _date_str(request.start).replace("-", "")
    end = _date_str(request.end).replace("-", "")
    df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
    if df is None or len(df) == 0:
        return []
    records = df.to_dict(orient="records")
    rows = []
    for item in records:
        symbol = _compact(item.get("代码") or item.get("SECURITY_CODE") or item.get("股票代码"))
        if request.symbol and symbol != request.symbol:
            continue
        trade_date = item.get("上榜日") or item.get("TRADE_DATE") or item.get("日期")
        if not symbol or not trade_date:
            continue
        buy_snapshot = {
            key: _compact(item.get(key))
            for key in ("龙虎榜买入额", "BILLBOARD_BUY_AMT", "买入额")
            if _compact(item.get(key))
        }
        sell_snapshot = {
            key: _compact(item.get(key))
            for key in ("龙虎榜卖出额", "BILLBOARD_SELL_AMT", "卖出额")
            if _compact(item.get(key))
        }
        rows.append(
            {
                "symbol": symbol,
                "trade_date": _parse_datetime(trade_date),
                "reason": _compact(item.get("上榜原因") or item.get("EXPLANATION") or item.get("解读")) or None,
                "net_buy_amount": _to_float(item.get("龙虎榜净买额") or item.get("NET_BUY_AMT")),
                "buy_seats_json": json.dumps(buy_snapshot, ensure_ascii=False) if buy_snapshot else None,
                "sell_seats_json": json.dumps(sell_snapshot, ensure_ascii=False) if sell_snapshot else None,
                "provider": "akshare_lhb",
            }
        )
    return rows


def save_announcements(rows: list[dict], db) -> int:
    from backend.data.database import Announcement

    inserted = 0
    for row in rows:
        existing = (
            db.query(Announcement)
            .filter(
                Announcement.symbol == row["symbol"],
                Announcement.title == row["title"],
                Announcement.published_at == row["published_at"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            Announcement(
                symbol=row["symbol"],
                title=row["title"],
                content=row.get("content"),
                ann_type=row.get("ann_type"),
                published_at=row["published_at"],
                source_url=row.get("source_url") or row.get("url"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def save_research_reports(rows: list[dict], db) -> int:
    from backend.data.database import ResearchReport

    inserted = 0
    for row in rows:
        existing = (
            db.query(ResearchReport)
            .filter(
                ResearchReport.symbol == row["symbol"],
                ResearchReport.org_name == row["org_name"],
                ResearchReport.publish_date == row["publish_date"],
                ResearchReport.title == row["title"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            ResearchReport(
                symbol=row["symbol"],
                title=row["title"],
                org_name=row["org_name"],
                rating=row.get("rating"),
                eps_forecast_y1=row.get("eps_forecast_y1"),
                eps_forecast_y2=row.get("eps_forecast_y2"),
                publish_date=row["publish_date"],
                info_code=row.get("info_code"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def save_lhb(rows: list[dict], db) -> int:
    from backend.data.database import LhbRecord

    inserted = 0
    for row in rows:
        existing = (
            db.query(LhbRecord)
            .filter(
                LhbRecord.symbol == row["symbol"],
                LhbRecord.trade_date == row["trade_date"],
                LhbRecord.reason == row.get("reason"),
            )
            .first()
        )
        if existing:
            continue
        db.add(
            LhbRecord(
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                reason=row.get("reason"),
                net_buy_amount=row.get("net_buy_amount"),
                buy_seats_json=row.get("buy_seats_json"),
                sell_seats_json=row.get("sell_seats_json"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def _probe_ifind_notice() -> bool:
    if not settings.ifind_mcp_enabled or not settings.ifind_mcp_token:
        return False
    return any(tool.get("name") == "search_notice" for tool in IfindMcpClient().list_tools(NEWS_MCP_ID))


def _probe_eastmoney_reportapi() -> bool:
    try:
        response = requests.get(
            REPORT_API_URL,
            params={
                "code": "000001",
                "beginTime": "2026-01-01",
                "endTime": "2026-01-02",
                "pageSize": 1,
                "pageNo": 1,
                "qType": 0,
            },
            headers=EASTMONEY_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.debug("eastmoney_reportapi probe failed: %s", exc)
        return False


def _probe_akshare_lhb() -> bool:
    try:
        import akshare as ak

        df = ak.stock_lhb_detail_em(start_date="20260401", end_date="20260401")
        return df is not None
    except Exception as exc:
        logger.debug("akshare_lhb probe failed: %s", exc)
        return False


register_category_provider(
    CategoryProvider(
        name="ifind_notice",
        category="announcements",
        fetch=fetch_announcements_ifind_notice,
        probe=_probe_ifind_notice,
        priority=10,
    )
)
register_category_provider(
    CategoryProvider(
        name="eastmoney_reportapi",
        category="research_reports",
        fetch=fetch_research_reports_eastmoney,
        probe=_probe_eastmoney_reportapi,
        priority=10,
    )
)
register_category_provider(
    CategoryProvider(
        name="akshare_lhb",
        category="lhb",
        fetch=fetch_lhb_akshare,
        probe=_probe_akshare_lhb,
        priority=10,
    )
)
