"""M61 category provider fetchers and persistence helpers."""
from __future__ import annotations

import json
import logging
import math
import random
import time
from datetime import date, datetime
from typing import Any

import requests

from backend.config import settings
from backend.data.category_registry import CategoryProvider, FetchRequest, register_category_provider
from backend.data.ifind_mcp import (
    GLOBAL_STOCK_MCP_ID,
    NEWS_MCP_ID,
    STOCK_MCP_ID,
    IfindMcpClient,
    parse_ifind_mcp_text,
)
from backend.data.orm import _utcnow

logger = logging.getLogger(__name__)

REPORT_API_URL = "https://reportapi.eastmoney.com/report/list"
EASTMONEY_FFLOW_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
EASTMONEY_FFLOW_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
EASTMONEY_FFLOW_HISTORY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.eastmoney.com/",
}
EASTMONEY_QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com",
    "Origin": "https://quote.eastmoney.com",
}
_STOCK_IFIND_CLIENT: IfindMcpClient | None = None
OVERSEAS_SYMBOLS = (
    ("MRVL", "Marvell"),
    ("MU", "美光"),
    ("NVDA", "英伟达"),
    ("AVGO", "博通"),
)


class SharedThrottle:
    """Process-local serial throttle for Eastmoney endpoints."""

    def __init__(self, min_interval: float = 1.2, jitter: tuple[float, float] = (0.05, 0.25)) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        delay = self.min_interval + random.uniform(*self.jitter) - elapsed
        if delay > 0:
            time.sleep(delay)
        self._last_call = time.monotonic()


_EASTMONEY_THROTTLE = SharedThrottle()


def _stock_ifind_client() -> IfindMcpClient:
    global _STOCK_IFIND_CLIENT
    if _STOCK_IFIND_CLIENT is None or not isinstance(_STOCK_IFIND_CLIENT, IfindMcpClient):
        _STOCK_IFIND_CLIENT = IfindMcpClient()
    return _STOCK_IFIND_CLIENT


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


def _extract_ifind_rows(text: str) -> list[dict[str, Any]]:
    parsed = parse_ifind_mcp_text(text)
    candidates: list[Any] = [parsed.get("json")]
    candidates.extend(table.get("rows", []) for table in parsed.get("tables", []))

    def walk(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            text_value = value.strip()
            if not text_value:
                return []
            try:
                decoded = json.loads(text_value)
            except json.JSONDecodeError:
                decoded = None
            if decoded is not None:
                rows = walk(decoded)
                if rows:
                    return rows
            nested = parse_ifind_mcp_text(text_value)
            table_rows: list[dict[str, Any]] = []
            for table in nested.get("tables", []):
                table_rows.extend(table.get("rows", []))
            return table_rows
        if isinstance(value, list):
            rows: list[dict[str, Any]] = []
            for item in value:
                rows.extend(walk(item))
            return rows
        if isinstance(value, dict):
            for key in ("answer", "text", "data", "result", "rows", "list", "items"):
                child = value.get(key)
                rows = walk(child)
                if rows:
                    return rows
            row_keys = [key for key, child in value.items() if not isinstance(child, (dict, list))]
            if row_keys:
                return [value]
        return []

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        rows.extend(walk(candidate))
    return rows


def _extract_first_string_field(value: Any, field: str) -> str | None:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _extract_first_string_field(decoded, field)
    if isinstance(value, list):
        for item in value:
            found = _extract_first_string_field(item, field)
            if found is not None:
                return found
    if isinstance(value, dict):
        child = value.get(field)
        if isinstance(child, str) and child.strip():
            return child
        for item in value.values():
            found = _extract_first_string_field(item, field)
            if found is not None:
                return found
    return None


def _classify_event_type(text: str) -> str:
    if "解禁" in text or "本期流通数量" in text or "未流通数量" in text or "已流通数量" in text:
        return "解禁"
    if "定增" in text or "增发" in text:
        return "定增"
    if "回购" in text or "购回" in text:
        return "回购"
    if "监管" in text or "处罚" in text or "警示" in text:
        return "监管"
    if "分红" in text or "派息" in text:
        return "分红"
    if "并购" in text or "重组" in text:
        return "并购"
    return "其他"


def _event_row(item: dict[str, Any], request: FetchRequest) -> dict | None:
    event_date_value = (
        item.get("事件日期")
        or item.get("日期")
        or item.get("发生日期")
        or item.get("解禁日期")
        or item.get("公告日期")
        or item.get("date")
        or item.get("event_date")
    )
    if not event_date_value:
        return None
    title = _compact(
        item.get("事件名称")
        or item.get("事件")
        or item.get("标题")
        or item.get("公告标题")
        or item.get("title")
    )
    detail = _compact(
        item.get("详情")
        or item.get("事件内容")
        or item.get("内容")
        or item.get("公告内容")
        or item.get("detail")
    )
    event_text = " ".join(part for part in (title, detail, json.dumps(item, ensure_ascii=False)) if part)
    event_type = _classify_event_type(event_text)
    if not title:
        company = _compact(item.get("证券简称")) or request.symbol or ""
        title = f"{company} {event_type} {_compact(event_date_value)}".strip()
    if not title:
        return None
    return {
        "symbol": request.symbol,
        "event_type": event_type,
        "title": title,
        "event_date": _parse_datetime(event_date_value),
        "detail": detail or json.dumps(item, ensure_ascii=False, default=str),
        "provider": "ifind_events",
        "fetched_at": _utcnow(),
    }


def _parse_share_count(value: Any) -> float | None:
    """Normalize iFinD 股本 values to raw shares (股); 万股/亿股 are converted."""
    text = _compact(value).replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    multiplier = 1.0
    if "亿股" in text:
        multiplier = 100_000_000.0
        text = text.replace("亿股", "")
    elif "万股" in text:
        multiplier = 10_000.0
        text = text.replace("万股", "")
    elif text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    text = text.replace("股", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number * multiplier


def _parse_int(value: Any) -> int | None:
    text = _compact(value).replace(",", "").replace("户", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return int(number)


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and _compact(item.get(key)):
            return item.get(key)
    for wanted in keys:
        for key, value in item.items():
            if str(key).startswith(wanted) and _compact(value):
                return value
    for wanted in keys:
        for key, value in item.items():
            if wanted in str(key) and _compact(value):
                return value
    return None


def _row_report_date_value(item: dict[str, Any]) -> Any:
    return _first_present(item, ("报告期", "报告日期", "截止日期", "日期", "report_date"))


def _ranked_holder_json(row: dict[str, Any]) -> str | None:
    holders: list[dict[str, Any]] = []
    for rank in range(1, 11):
        marker = f"第{rank}名"
        holder: dict[str, Any] = {"rank": rank}
        for key, value in row.items():
            key_text = str(key)
            if marker not in key_text or not _compact(value):
                continue
            if key_text.startswith("股东名称"):
                holder["holder"] = _compact(value)
            elif key_text.startswith("股东持股数量"):
                holder["shares"] = _parse_share_count(value)
            elif key_text.startswith("股东持股比例"):
                holder["ratio_pct"] = _to_float(value)
            elif key_text.startswith("股东持股股份性质"):
                holder["share_type"] = _compact(value)
            elif key_text.startswith("股东性质"):
                holder["holder_type"] = _compact(value)
        if holder.get("holder"):
            holders.append(holder)
    return json.dumps(holders, ensure_ascii=False, default=str) if holders else None


def _ifind_shareholder_cell(value: str) -> str | None:
    text = value.strip()
    return text or None


def _parse_ifind_shareholder_table(text: str, request: FetchRequest, fetched_at: datetime) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []

    headers = [_ifind_shareholder_cell(cell) or "" for cell in lines[0].strip().strip("|").split("|")]
    total_shares_idx = next(
        (
            idx
            for idx, header in enumerate(headers)
            if "总股本" in header and "上市前" not in header
        ),
        None,
    )
    top10_shares_idx = next(
        (idx for idx, header in enumerate(headers) if "前十大股东持股数量合计" in header),
        None,
    )
    top10_pct_idx = next(
        (idx for idx, header in enumerate(headers) if "前十大股东持股比例合计" in header),
        None,
    )
    holder_start_idx = next(
        (
            idx
            for idx, header in enumerate(headers)
            if "股东名称" in header and "第1名" in header
        ),
        6,
    )

    rows: list[dict] = []
    today = fetched_at.date()
    for line in lines[2:]:
        cells = [_ifind_shareholder_cell(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        report_date_raw = cells[2]
        if report_date_raw is None:
            continue
        try:
            report_date = _parse_datetime(report_date_raw)
        except (TypeError, ValueError):
            continue
        if report_date.date() > today:
            logger.debug(
                "skip future ifind_shareholders row symbol=%s report_date=%s today=%s",
                request.symbol,
                report_date.date().isoformat(),
                today.isoformat(),
            )
            continue

        holders: list[dict[str, Any]] = []
        for rank in range(10):
            offset = holder_start_idx + rank * 5
            if len(cells) <= offset:
                break
            holder_name = cells[offset]
            if holder_name is None:
                continue
            holders.append(
                {
                    "name": holder_name,
                    "shares": _parse_share_count(cells[offset + 1] if len(cells) > offset + 1 else None),
                    "pct": _to_float(cells[offset + 2] if len(cells) > offset + 2 else None),
                    "nature": cells[offset + 3] if len(cells) > offset + 3 else None,
                }
            )

        if 0 < len(holders) < 10:
            logger.debug(
                "skip incomplete ifind_shareholders row symbol=%s report_date=%s holders=%s",
                request.symbol,
                report_date.date().isoformat(),
                len(holders),
            )
            continue

        total_shares = (
            _parse_share_count(cells[total_shares_idx])
            if total_shares_idx is not None and len(cells) > total_shares_idx
            else None
        )
        if total_shares is None and top10_shares_idx is not None and top10_pct_idx is not None:
            top10_shares = _parse_share_count(cells[top10_shares_idx] if len(cells) > top10_shares_idx else None)
            top10_pct = _to_float(cells[top10_pct_idx] if len(cells) > top10_pct_idx else None)
            if top10_shares is not None and top10_pct and top10_pct > 0:
                total_shares = top10_shares / (top10_pct / 100.0)
        top10_json = json.dumps(holders, ensure_ascii=False, default=str) if holders else None
        if total_shares is None and top10_json is None:
            continue
        rows.append(
            {
                "symbol": request.symbol,
                "report_date": report_date,
                "total_shares": total_shares,
                "float_shares": None,
                "top10_json": top10_json,
                "holder_count": None,
                "provider": "ifind_shareholders",
                "fetched_at": fetched_at,
            }
        )
    return rows


def _holder_snapshot_row(rows: list[dict[str, Any]], request: FetchRequest, fetched_at: datetime) -> dict | None:
    dated_rows = []
    for item in rows:
        date_value = _row_report_date_value(item)
        if date_value:
            dated_rows.append((_parse_datetime(date_value), item))
    if dated_rows:
        latest_date = max(parsed for parsed, _ in dated_rows)
        rows = [item for parsed, item in dated_rows if parsed == latest_date]

    merged: dict[str, Any] = {}
    top10_rows: list[dict[str, Any]] = []
    for item in rows:
        merged.update({key: value for key, value in item.items() if _compact(value)})
        holder_name = _compact(
            item.get("股东名称")
            or item.get("股东")
            or item.get("holder")
            or item.get("holder_name")
        )
        if holder_name:
            top10_rows.append(item)

    report_date_value = _first_present(
        merged,
        ("报告期", "报告日期", "截止日期", "日期", "report_date"),
    )
    provider = "ifind_shareholders"
    if report_date_value:
        report_date = _parse_datetime(report_date_value)
    else:
        report_date = datetime.combine(fetched_at.date(), datetime.min.time())
        provider = "ifind_shareholders_undated"

    total_shares = _parse_share_count(
        _first_present(merged, ("总股本", "总股份", "股本总数", "total_shares"))
    )
    float_shares = _parse_share_count(
        _first_present(merged, ("流通股本", "自由流通股本", "流通A股", "float_shares"))
    )
    holder_count = _parse_int(
        _first_present(merged, ("股东户数", "股东总户数", "holder_count"))
    )
    top10_value = _first_present(merged, ("前十大股东", "前10大股东", "前十大股东列表", "top10"))
    if top10_rows:
        top10_json = json.dumps(top10_rows, ensure_ascii=False, default=str)
    elif _ranked_holder_json(merged) is not None:
        top10_json = _ranked_holder_json(merged)
    elif top10_value is not None:
        top10_json = json.dumps(top10_value, ensure_ascii=False, default=str)
    else:
        top10_json = None

    if total_shares is None and float_shares is None and top10_json is None and holder_count is None:
        return None
    return {
        "symbol": request.symbol,
        "report_date": report_date,
        "total_shares": total_shares,
        "float_shares": float_shares,
        "top10_json": top10_json,
        "holder_count": holder_count,
        "provider": provider,
        "fetched_at": fetched_at,
    }


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


def fetch_corporate_events_ifind(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for ifind_events")
    start = _date_str(request.start)
    end = _date_str(request.end)
    name = _compact(request.extra.get("name")) or request.symbol
    query = f"{name}({request.symbol}) {start}至{end} 解禁 定增 回购 监管处罚 分红 并购重组 事件"
    result = _stock_ifind_client().call_tool(
        STOCK_MCP_ID,
        "get_stock_events",
        {"query": query},
    )
    rows = []
    for item in _extract_ifind_rows(result.text):
        row = _event_row(item, request)
        if row is not None:
            if request.start and row["event_date"].date() < request.start:
                continue
            if request.end and row["event_date"].date() > request.end:
                continue
            rows.append(row)
    return rows


def fetch_holders_ifind_shareholders(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for ifind_shareholders")
    name = _compact(request.extra.get("name")) or request.symbol
    query = f"{name}({request.symbol}) 最新股本结构与前十大股东"
    result = _stock_ifind_client().call_tool(
        STOCK_MCP_ID,
        "get_stock_shareholders",
        {"query": query},
    )
    fetched_at = _utcnow()
    answer = _extract_first_string_field(result.text, "answer")
    if answer:
        rows = _parse_ifind_shareholder_table(answer, request, fetched_at)
        if rows:
            return rows
    row = _holder_snapshot_row(_extract_ifind_rows(result.text), request, fetched_at)
    return [] if row is None else [row]


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


def _eastmoney_secid(symbol: str) -> str:
    prefix = "1" if symbol.startswith("6") else "0"
    return f"{prefix}.{symbol}"


def _parse_fflow_kline(kline: str, symbol: str, fetched_at: datetime) -> dict | None:
    # Requested fields2 order: f51 date, f52 main, f53 small, f54 medium,
    # f55 large, f56 super-large. Remaining f57-f61 fields are not persisted.
    parts = [part.strip() for part in kline.split(",")]
    if len(parts) < 6:
        return None
    trade_date = _parse_datetime(parts[0])
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "main_net": _to_float(parts[1]),
        "small_net": _to_float(parts[2]),
        "medium_net": _to_float(parts[3]),
        "large_net": _to_float(parts[4]),
        "super_large_net": _to_float(parts[5]),
        "metric": "main_net",
        "value": _to_float(parts[1]),
        "currency": "CNY",
        "source": "eastmoney_fflow",
        "provider": "eastmoney_fflow",
        "fetched_at": fetched_at,
    }


def _parse_fflow_history_kline(kline: str, symbol: str, fetched_at: datetime) -> dict | None:
    # push2his fields2 order: f51=date, f52=main_net, f53=small_net,
    # f54=medium_net, f55=large_net, f56=super_large_net. f57-f65 are
    # Eastmoney ratio/derived public fields and are not persisted here.
    parts = [part.strip() for part in kline.split(",")]
    if len(parts) < 6:
        return None
    trade_date = _parse_datetime(parts[0])
    main_net = _to_float(parts[1])
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "main_net": main_net,
        "small_net": _to_float(parts[2]),
        "medium_net": _to_float(parts[3]),
        "large_net": _to_float(parts[4]),
        "super_large_net": _to_float(parts[5]),
        "metric": "main_net",
        "value": main_net,
        "currency": "CNY",
        "source": "eastmoney_fflow_history",
        "provider": "eastmoney_fflow_history",
        "fetched_at": fetched_at,
    }


def fetch_fund_flow_eastmoney_fflow(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for eastmoney_fflow")
    response = requests.get(
        EASTMONEY_FFLOW_URL,
        params={
            "secid": _eastmoney_secid(request.symbol),
            "klt": 101,
            "lmt": 250,
            "fields1": "f1,f2,f3",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        },
        headers=EASTMONEY_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    klines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list):
        raise ValueError("eastmoney_fflow missing data.klines")

    fetched_at = _utcnow()
    rows = []
    for item in klines:
        if not isinstance(item, str):
            continue
        row = _parse_fflow_kline(item, request.symbol, fetched_at)
        if row is None:
            continue
        if request.start and row["trade_date"].date() < request.start:
            continue
        if request.end and row["trade_date"].date() > request.end:
            continue
        rows.append(row)
    return rows


def fetch_fund_flow_eastmoney_fflow_history(request: FetchRequest) -> list[dict]:
    if not request.symbol:
        raise ValueError("symbol is required for eastmoney_fflow_history")
    _EASTMONEY_THROTTLE.wait()
    response = requests.get(
        EASTMONEY_FFLOW_HISTORY_URL,
        params={
            "secid": _eastmoney_secid(request.symbol),
            "fields1": "f1,f2,f3,f7",
            "fields2": EASTMONEY_FFLOW_HISTORY_FIELDS2,
            "lmt": str(request.limit or 120),
        },
        headers=EASTMONEY_QUOTE_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    klines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list):
        raise ValueError("eastmoney_fflow_history missing data.klines")

    fetched_at = _utcnow()
    rows = []
    for item in klines:
        if not isinstance(item, str):
            continue
        row = _parse_fflow_history_kline(item, request.symbol, fetched_at)
        if row is None:
            continue
        if request.start and row["trade_date"].date() < request.start:
            continue
        if request.end and row["trade_date"].date() > request.end:
            continue
        rows.append(row)
    return rows


def _overseas_row(item: dict[str, Any], symbol: str, name: str, fetched_at: datetime) -> dict | None:
    date_value = _first_present(item, ("日期", "交易日期", "date", "snap_date"))
    close = _to_float(_first_present(item, ("收盘价", "收盘", "最新价", "close")))
    if date_value is None or close is None:
        return None
    chg_pct_1d = _to_float(_first_present(item, ("涨跌幅", "日涨跌幅", "1日涨跌幅", "chg_pct_1d")))
    chg_pct_20d = _to_float(_first_present(item, ("20日涨跌幅", "近20日涨跌幅", "20日收益率", "chg_pct_20d")))
    note = json.dumps(item, ensure_ascii=False, default=str)
    return {
        "symbol": symbol,
        "name": name,
        "snap_date": _parse_datetime(date_value),
        "close": close,
        "chg_pct_1d": chg_pct_1d,
        "chg_pct_20d": chg_pct_20d,
        "note": note[:400] if note else None,
        "provider": "ifind_global",
        "fetched_at": fetched_at,
    }


def fetch_overseas_ifind_global(request: FetchRequest) -> list[dict]:
    """Fetch fixed overseas reference snapshots; request.universe is intentionally ignored."""
    rows: list[dict] = []
    client = _stock_ifind_client()
    fetched_at = _utcnow()
    for symbol, name in OVERSEAS_SYMBOLS:
        query = f"{name}({symbol})最近20个交易日的收盘价、涨跌幅、20日涨跌幅、换手率"
        result = client.call_tool(
            GLOBAL_STOCK_MCP_ID,
            "global_stock_quotes",
            {"query": query},
        )
        candidates = []
        for item in _extract_ifind_rows(result.text):
            row = _overseas_row(item, symbol, name, fetched_at)
            if row is not None:
                candidates.append(row)
        if not candidates:
            continue
        candidates.sort(key=lambda row: row["snap_date"], reverse=True)
        latest = candidates[0]
        oldest = candidates[-1]
        if latest.get("chg_pct_20d") is None and len(candidates) >= 2:
            old_close = oldest.get("close")
            new_close = latest.get("close")
            if old_close not in (None, 0) and new_close is not None:
                latest["chg_pct_20d"] = (float(new_close) / float(old_close) - 1.0) * 100.0
        rows.append(latest)
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


def save_corporate_events(rows: list[dict], db) -> int:
    from backend.data.database import CorporateEvent

    inserted = 0
    for row in rows:
        existing = (
            db.query(CorporateEvent)
            .filter(
                CorporateEvent.symbol == row["symbol"],
                CorporateEvent.event_type == row["event_type"],
                CorporateEvent.event_date == row["event_date"],
                CorporateEvent.title == row["title"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            CorporateEvent(
                symbol=row["symbol"],
                event_type=row["event_type"],
                title=row["title"],
                event_date=row["event_date"],
                detail=row.get("detail"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def save_holder_snapshots(rows: list[dict], db) -> int:
    from backend.data.database import HolderSnapshot

    inserted = 0
    for row in rows:
        existing = (
            db.query(HolderSnapshot)
            .filter(
                HolderSnapshot.symbol == row["symbol"],
                HolderSnapshot.report_date == row["report_date"],
                HolderSnapshot.provider == row["provider"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            HolderSnapshot(
                symbol=row["symbol"],
                report_date=row["report_date"],
                total_shares=row.get("total_shares"),
                float_shares=row.get("float_shares"),
                top10_json=row.get("top10_json"),
                holder_count=row.get("holder_count"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def save_fund_flows(rows: list[dict], db) -> int:
    from backend.data.database import FundFlow

    inserted = 0
    for row in rows:
        existing = (
            db.query(FundFlow)
            .filter(
                FundFlow.symbol == row["symbol"],
                FundFlow.trade_date == row["trade_date"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            FundFlow(
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                main_net=row.get("main_net"),
                super_large_net=row.get("super_large_net"),
                large_net=row.get("large_net"),
                medium_net=row.get("medium_net"),
                small_net=row.get("small_net"),
                provider=row.get("provider") or "unknown",
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def save_overseas_snapshots(rows: list[dict], db) -> int:
    from backend.data.database import OverseasSnapshot

    inserted = 0
    for row in rows:
        existing = (
            db.query(OverseasSnapshot)
            .filter(
                OverseasSnapshot.symbol == row["symbol"],
                OverseasSnapshot.snap_date == row["snap_date"],
                OverseasSnapshot.provider == row["provider"],
            )
            .first()
        )
        if existing:
            changed = False
            for field in ("close", "chg_pct_1d", "chg_pct_20d", "note", "name"):
                if getattr(existing, field) is None and row.get(field) is not None:
                    setattr(existing, field, row.get(field))
                    changed = True
            if changed:
                existing.fetched_at = row.get("fetched_at") or _utcnow()
            continue
        db.add(
            OverseasSnapshot(
                symbol=row["symbol"],
                name=row["name"],
                snap_date=row["snap_date"],
                close=row.get("close"),
                chg_pct_1d=row.get("chg_pct_1d"),
                chg_pct_20d=row.get("chg_pct_20d"),
                note=row.get("note"),
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


def _probe_ifind_events() -> bool:
    if not settings.ifind_mcp_enabled or not settings.ifind_mcp_token:
        return False
    return any(tool.get("name") == "get_stock_events" for tool in IfindMcpClient().list_tools(STOCK_MCP_ID))


def _probe_ifind_shareholders() -> bool:
    if not settings.ifind_mcp_enabled or not settings.ifind_mcp_token:
        return False
    return any(tool.get("name") == "get_stock_shareholders" for tool in IfindMcpClient().list_tools(STOCK_MCP_ID))


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


def _probe_eastmoney_fflow() -> bool:
    try:
        response = requests.get(
            EASTMONEY_FFLOW_URL,
            params={
                "secid": "1.601869",
                "klt": 101,
                "lmt": 1,
                "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
            headers=EASTMONEY_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return bool(isinstance(data, dict) and data.get("klines"))
    except Exception as exc:
        logger.debug("eastmoney_fflow probe failed: %s", exc)
        return False


def _probe_eastmoney_fflow_history() -> bool:
    try:
        _EASTMONEY_THROTTLE.wait()
        response = requests.get(
            EASTMONEY_FFLOW_HISTORY_URL,
            params={
                "secid": "1.601869",
                "fields1": "f1,f2,f3,f7",
                "fields2": EASTMONEY_FFLOW_HISTORY_FIELDS2,
                "lmt": "1",
            },
            headers=EASTMONEY_QUOTE_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return bool(isinstance(data, dict) and data.get("klines"))
    except Exception as exc:
        logger.debug("eastmoney_fflow_history probe failed: %s", exc)
        return False


def _probe_ifind_global() -> bool:
    if not settings.ifind_mcp_enabled or not settings.ifind_mcp_token:
        return False
    return any(
        tool.get("name") == "global_stock_quotes"
        for tool in _stock_ifind_client().list_tools(GLOBAL_STOCK_MCP_ID)
    )


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
        name="ifind_global",
        category="overseas",
        fetch=fetch_overseas_ifind_global,
        probe=_probe_ifind_global,
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
register_category_provider(
    CategoryProvider(
        name="eastmoney_fflow_history",
        category="fund_flow",
        fetch=fetch_fund_flow_eastmoney_fflow_history,
        probe=_probe_eastmoney_fflow_history,
        priority=9,
    )
)
register_category_provider(
    CategoryProvider(
        name="eastmoney_fflow",
        category="fund_flow",
        fetch=fetch_fund_flow_eastmoney_fflow,
        probe=_probe_eastmoney_fflow,
        priority=10,
    )
)
register_category_provider(
    CategoryProvider(
        name="ifind_events",
        category="corporate_events",
        fetch=fetch_corporate_events_ifind,
        probe=_probe_ifind_events,
        priority=10,
    )
)
register_category_provider(
    CategoryProvider(
        name="ifind_shareholders",
        category="holders",
        fetch=fetch_holders_ifind_shareholders,
        probe=_probe_ifind_shareholders,
        priority=10,
    )
)
