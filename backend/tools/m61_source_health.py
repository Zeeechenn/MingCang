"""M61 source health check harness.

Read-only probes for the M61 data-foundation source matrix. The harness makes
small bounded calls, catches every per-probe failure, and emits one JSON
scorecard per registered source/category pair.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from backend.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYMBOLS = ["601869", "300308"]
HIST_START = "2026-02-01"
HIST_END = "2026-02-28"
DEFAULT_OUT_DIR = REPO_ROOT / "paper_trading" / "m61_out"
SCHEMA_VERSION = "m61_source_health.v1"

CATEGORIES = (
    "quotes",
    "financials",
    "announcements",
    "research_reports",
    "fund_flow",
    "lhb",
    "corporate_events",
    "holders",
    "sector",
    "news",
    "f10",
    "overseas",
)

ProbeFn = Callable[[list[str]], "ProbeResult"]


@dataclass(frozen=True)
class CallSample:
    rows: int = 0
    content_non_empty: int = 0
    latency_ms: float = 0.0
    supports_date_range: bool = False
    dates: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    calls: list[CallSample] = field(default_factory=list)
    pit_verdict: str | None = None


@dataclass(frozen=True)
class ProbeSpec:
    source: str
    category: str
    probe_fn: ProbeFn


def _truncate_error(error: Any) -> str:
    return str(error).replace("\n", " ")[:120]


def _date_in_range(value: str) -> bool:
    normalized = value.replace("/", "-")
    return HIST_START <= normalized <= HIST_END


def _extract_dates(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    found: list[str] = []
    for match in re.findall(r"20\d{2}[-/]?\d{2}[-/]?\d{2}", text):
        if "-" in match or "/" in match:
            normalized = match.replace("/", "-")
        else:
            normalized = f"{match[:4]}-{match[4:6]}-{match[6:8]}"
        found.append(normalized)
    return sorted(set(found))


def _count_rows(payload: Any) -> int:
    if payload is None:
        return 0
    if isinstance(payload, pd.DataFrame):
        return int(len(payload))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("data", "result", "items", "list", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                nested = _count_rows(value)
                if nested:
                    return nested
        return 1 if payload else 0
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return 0
        return max(1, len([line for line in stripped.splitlines() if line.strip()]))
    return 1


def _count_content(payload: Any, content_fields: Iterable[str] = ("body", "value", "content", "text", "raw_text", "title")) -> int:
    fields = tuple(content_fields)
    if payload is None:
        return 0
    if isinstance(payload, pd.DataFrame):
        if payload.empty:
            return 0
        for field_name in fields:
            matching = [col for col in payload.columns if field_name.lower() in str(col).lower()]
            if matching:
                return int(payload[matching[0]].astype(str).str.strip().ne("").sum())
        return int(len(payload))
    if isinstance(payload, list):
        if not payload:
            return 0
        if all(isinstance(item, dict) for item in payload):
            total = 0
            for item in payload:
                total += int(any(str(item.get(field) or "").strip() for field in fields))
            return total
        return sum(1 for item in payload if str(item or "").strip())
    if isinstance(payload, dict):
        for key in ("data", "result", "items", "list", "rows"):
            value = payload.get(key)
            if isinstance(value, (list, dict)):
                count = _count_content(value, fields)
                if count:
                    return count
        return int(any(str(payload.get(field) or "").strip() for field in fields))
    if isinstance(payload, str):
        return int(bool(payload.strip()))
    return 0


def _call_sample(
    started: float,
    payload: Any,
    *,
    supports_date_range: bool = False,
    content_fields: Iterable[str] = ("body", "value", "content", "text", "raw_text", "title"),
    error: str | None = None,
) -> CallSample:
    rows = _count_rows(payload)
    dates = _extract_dates(payload)
    return CallSample(
        rows=rows,
        content_non_empty=min(rows, _count_content(payload, content_fields)) if rows else 0,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        supports_date_range=supports_date_range,
        dates=dates,
        error=error,
    )


def _error_sample(started: float, exc: Any) -> CallSample:
    return CallSample(latency_ms=round((time.perf_counter() - started) * 1000, 2), error=_truncate_error(exc))


def _score_probe(source: str, category: str, result: ProbeResult) -> dict[str, Any]:
    calls = result.calls
    errors = [_truncate_error(call.error) for call in calls if call.error]
    distinct_errors = list(dict.fromkeys(errors))
    successes = [call for call in calls if not call.error and call.rows > 0]
    rows = sum(call.rows for call in successes)
    content = sum(call.content_non_empty for call in successes)
    latencies = [call.latency_ms for call in calls if call.latency_ms is not None]
    dates = sorted({date for call in calls for date in call.dates})
    supports_date_range = any(call.supports_date_range for call in calls)
    historical_dates = [date for date in dates if _date_in_range(date)]
    historical_rows = sum(call.rows for call in successes if any(_date_in_range(date) for date in call.dates))

    pit_verdict = result.pit_verdict or _classify_pit(
        supports_date_range=supports_date_range,
        historical_dates=historical_dates,
        calls=calls,
    )
    return {
        "source": source,
        "category": category,
        "available": bool(successes),
        "coverage": int(rows),
        "backfill": {
            "supports_date_range": bool(supports_date_range),
            "historical_rows": int(historical_rows),
            "earliest_seen": dates[0] if dates else None,
        },
        "completeness": round(content / rows, 4) if rows else 0.0,
        "latency_ms": round(statistics.median(latencies), 2) if latencies else None,
        "stability": {
            "calls": len(calls),
            "failures": len(errors),
            "error_samples": distinct_errors,
        },
        "pit_verdict": pit_verdict,
    }


def _classify_pit(*, supports_date_range: bool, historical_dates: list[str], calls: list[CallSample]) -> str:
    if supports_date_range and historical_dates:
        return "clean"
    if calls and not supports_date_range:
        return "risky"
    return "unknown"


def _no_url_probe(_: list[str]) -> ProbeResult:
    return ProbeResult(calls=[CallSample(error="endpoint URL not documented")], pit_verdict="unknown")


def _ifind_tool_probe(mcp_id: str, tool_name: str, arguments_by_symbol: Callable[[str], dict[str, Any]]) -> ProbeFn:
    def probe(symbols: list[str]) -> ProbeResult:
        from backend.data.ifind_mcp import call_ifind_mcp_tool

        calls: list[CallSample] = []
        for symbol in symbols[:2]:
            started = time.perf_counter()
            try:
                payload = call_ifind_mcp_tool(tool_name, arguments_by_symbol(symbol), mcp_id=mcp_id)
                if not payload.get("ok"):
                    calls.append(_error_sample(started, payload.get("error") or "iFinD call failed"))
                else:
                    calls.append(
                        _call_sample(
                            started,
                            payload.get("parsed") or payload.get("result") or payload,
                            supports_date_range=tool_name in {"search_news", "search_notice"},
                        )
                    )
            except Exception as exc:
                calls.append(_error_sample(started, exc))
        return ProbeResult(calls=calls)

    return probe


def _akshare_probe(function_name: str, call_builder: Callable[[Any, str], Any], *, supports_date_range: bool = False) -> ProbeFn:
    def probe(symbols: list[str]) -> ProbeResult:
        import akshare as ak

        fn = getattr(ak, function_name)
        calls: list[CallSample] = []
        for symbol in symbols[:2]:
            started = time.perf_counter()
            try:
                payload = call_builder(fn, symbol)
                calls.append(_call_sample(started, payload, supports_date_range=supports_date_range))
            except Exception as exc:
                calls.append(_error_sample(started, exc))
            time.sleep(1)
        return ProbeResult(calls=calls)

    return probe


def _eastmoney_news_probe(symbols: list[str]) -> ProbeResult:
    from backend.data.news import fetch_stock_news_cn

    calls: list[CallSample] = []
    for symbol in symbols[:2]:
        started = time.perf_counter()
        try:
            payload = [item.__dict__ for item in fetch_stock_news_cn(symbol, limit=3)]
            calls.append(_call_sample(started, payload, content_fields=("body", "title")))
        except Exception as exc:
            calls.append(_error_sample(started, exc))
        time.sleep(1)
    return ProbeResult(calls=calls, pit_verdict="risky")


def _eastmoney_http_probe(url: str, params: dict[str, Any]) -> ProbeFn:
    def probe(_: list[str]) -> ProbeResult:
        started = time.perf_counter()
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return ProbeResult(calls=[_call_sample(started, resp.text)], pit_verdict="risky")
        except Exception as exc:
            return ProbeResult(calls=[_error_sample(started, exc)], pit_verdict="unknown")

    return probe


def _tushare_call(api_name: str, params: dict[str, Any]) -> ProbeFn:
    def probe(_: list[str]) -> ProbeResult:
        calls: list[CallSample] = []
        started = time.perf_counter()
        if not settings.tushare_token:
            return ProbeResult(calls=[_error_sample(started, "TUSHARE_TOKEN is not configured")])
        try:
            import tushare as ts

            pro = ts.pro_api(settings.tushare_token)
            payload = getattr(pro, api_name)(**params)
            calls.append(_call_sample(started, payload, supports_date_range=bool(params.get("start_date"))))
        except Exception as exc:
            calls.append(_error_sample(started, exc))
        time.sleep(1)
        return ProbeResult(calls=calls)

    return probe


def _tushare_multi(calls_to_make: list[tuple[str, dict[str, Any]]]) -> ProbeFn:
    def probe(_: list[str]) -> ProbeResult:
        calls: list[CallSample] = []
        if not settings.tushare_token:
            started = time.perf_counter()
            return ProbeResult(calls=[_error_sample(started, "TUSHARE_TOKEN is not configured")])
        try:
            import tushare as ts

            pro = ts.pro_api(settings.tushare_token)
        except Exception as exc:
            started = time.perf_counter()
            return ProbeResult(calls=[_error_sample(started, exc)])

        for api_name, params in calls_to_make[:3]:
            started = time.perf_counter()
            try:
                payload = getattr(pro, api_name)(**params)
                calls.append(_call_sample(started, payload, supports_date_range=bool(params.get("start_date"))))
            except Exception as exc:
                calls.append(_error_sample(started, exc))
            time.sleep(1)
        return ProbeResult(calls=calls)

    return probe


def _tickflow_quotes_probe(symbols: list[str]) -> ProbeResult:
    from backend.data.tickflow import fetch_tickflow_daily

    calls: list[CallSample] = []
    for symbol in symbols[:2]:
        started = time.perf_counter()
        try:
            payload = fetch_tickflow_daily(symbol, "CN", days=30)
            calls.append(_call_sample(started, payload, supports_date_range=False))
        except Exception as exc:
            calls.append(_error_sample(started, exc))
        time.sleep(1)
    return ProbeResult(calls=calls, pit_verdict="risky")


def _market(symbol: str) -> str:
    return "sh" if symbol.startswith(("6", "9")) else "sz"


def _ts_code(symbol: str) -> str:
    return f"{symbol}.SH" if symbol.startswith(("6", "9")) else f"{symbol}.SZ"


def _register_specs() -> list[ProbeSpec]:
    from backend.data.ifind_mcp import GLOBAL_STOCK_MCP_ID, INDEX_MCP_ID, NEWS_MCP_ID, STOCK_MCP_ID

    specs: list[ProbeSpec] = [
        ProbeSpec("ifind", "quotes", _ifind_tool_probe(STOCK_MCP_ID, "get_stock_performance", lambda s: {"query": f"{s}在2026年2月1日至2026年2月28日的收盘价、成交量"})),
        ProbeSpec("ifind", "financials", _ifind_tool_probe(STOCK_MCP_ID, "get_stock_financials", lambda s: {"query": f"{s}在2025-12-31的ROE、营业收入、净利润"})),
        ProbeSpec("ifind", "announcements", _ifind_tool_probe(NEWS_MCP_ID, "search_notice", lambda s: {"query": f"{s} 2026年2月 公告", "time_start": HIST_START, "time_end": HIST_END, "size": 3})),
        ProbeSpec("ifind", "corporate_events", _ifind_tool_probe(STOCK_MCP_ID, "get_stock_events", lambda s: {"query": f"{s}最近的定向增发、股份回购、限售解禁事件"})),
        ProbeSpec("ifind", "holders", _ifind_tool_probe(STOCK_MCP_ID, "get_stock_shareholders", lambda s: {"query": f"{s}前十大股东和流通股占比"})),
        ProbeSpec("ifind", "sector", _ifind_tool_probe(INDEX_MCP_ID, "sector_data", lambda _: {"query": "通信(申万行业)板块2026年2月的成分股个数和涨跌幅"})),
        ProbeSpec("ifind", "news", _ifind_tool_probe(NEWS_MCP_ID, "search_news", lambda s: {"query": f"{s} 2026年2月 新闻", "time_start": HIST_START, "time_end": HIST_END, "size": 3})),
        ProbeSpec("ifind", "f10", _ifind_tool_probe(STOCK_MCP_ID, "get_stock_info", lambda s: {"query": f"{s}上市时间、所属行业、主营业务"})),
        ProbeSpec("ifind", "overseas", _ifind_tool_probe(GLOBAL_STOCK_MCP_ID, "global_stock_quotes", lambda _: {"query": "Marvell(MRVL)在2026年2月1日至2026年2月28日的收盘价和涨跌幅"})),
        ProbeSpec("akshare", "quotes", _akshare_probe("stock_zh_a_hist", lambda fn, s: fn(symbol=s, period="daily", start_date="20260201", end_date="20260228", adjust="qfq"), supports_date_range=True)),
        ProbeSpec("akshare", "financials", _akshare_probe("stock_financial_analysis_indicator", lambda fn, s: fn(symbol=s))),
        ProbeSpec("akshare", "announcements", _akshare_probe("stock_notice_report", lambda fn, _: fn(symbol="全部", date="20260210"), supports_date_range=True)),
        ProbeSpec("akshare", "research_reports", _akshare_probe("stock_research_report_em", lambda fn, s: fn(symbol=s))),
        ProbeSpec("akshare", "fund_flow", _akshare_probe("stock_individual_fund_flow", lambda fn, s: fn(stock=s, market=_market(s)))),
        ProbeSpec("akshare", "lhb", _akshare_probe("stock_lhb_detail_em", lambda fn, _: fn(start_date="20260201", end_date="20260228"), supports_date_range=True)),
        ProbeSpec("akshare", "holders", _akshare_probe("stock_gdfx_free_top_10_em", lambda fn, s: fn(symbol=s, date="20251231"))),
        ProbeSpec("akshare", "sector", _akshare_probe("stock_board_industry_name_em", lambda fn, _: fn())),
        ProbeSpec("akshare", "news", _akshare_probe("stock_news_em", lambda fn, s: fn(symbol=s))),
        ProbeSpec("akshare", "f10", _akshare_probe("stock_individual_info_em", lambda fn, s: fn(symbol=s))),
        ProbeSpec("eastmoney", "news", _eastmoney_news_probe),
        ProbeSpec("eastmoney", "fund_flow", _eastmoney_http_probe("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get", {"lmt": 5, "klt": 101, "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55"})),
        ProbeSpec("tushare", "quotes", _tushare_multi([
            ("daily", {"ts_code": _ts_code(DEFAULT_SYMBOLS[0]), "start_date": "20260201", "end_date": "20260228"}),
            ("adj_factor", {"ts_code": _ts_code(DEFAULT_SYMBOLS[0]), "start_date": "20260201", "end_date": "20260228"}),
        ])),
        ProbeSpec("tushare", "financials", _tushare_call("daily_basic", {"ts_code": _ts_code(DEFAULT_SYMBOLS[0]), "trade_date": "20260210"})),
        ProbeSpec("tushare", "f10", _tushare_call("stock_basic", {"exchange": "", "list_status": "L", "fields": "ts_code,symbol,name,area,industry,list_date"})),
        ProbeSpec("tushare", "fund_flow", _tushare_call("moneyflow", {"ts_code": _ts_code(DEFAULT_SYMBOLS[0]), "start_date": "20260201", "end_date": "20260228"})),
        ProbeSpec("tushare", "announcements", _tushare_call("anns_d", {"ts_code": _ts_code(DEFAULT_SYMBOLS[0]), "start_date": "20260201", "end_date": "20260228"})),
        ProbeSpec("tickflow", "quotes", _tickflow_quotes_probe),
    ]
    specs.extend(ProbeSpec("a_stock_data", category, _no_url_probe) for category in CATEGORIES)
    return specs


PROBE_REGISTRY = _register_specs()


def registered_probe_matrix(registry: list[ProbeSpec] | None = None) -> list[dict[str, str]]:
    active = registry if registry is not None else PROBE_REGISTRY
    return [{"source": spec.source, "category": spec.category} for spec in active]


def _select_specs(
    *,
    source: str | None,
    category: str | None,
    all_sources: bool,
    registry: list[ProbeSpec],
) -> tuple[list[ProbeSpec], int]:
    if all_sources:
        selected = registry
    else:
        selected = [
            spec
            for spec in registry
            if (source is None or spec.source == source) and (category is None or spec.category == category)
        ]
    has_source = bool(source and any(spec.source == source for spec in registry))
    no_probe = 0
    if source and category and not selected and has_source:
        no_probe = 1
    return selected, no_probe


def run_sweep(
    *,
    source: str | None = None,
    category: str | None = None,
    symbols: list[str] | None = None,
    all_sources: bool = False,
    registry: list[ProbeSpec] | None = None,
) -> dict[str, Any]:
    active_registry = registry if registry is not None else PROBE_REGISTRY
    selected, n_no_probe = _select_specs(source=source, category=category, all_sources=all_sources, registry=active_registry)
    active_symbols = symbols or DEFAULT_SYMBOLS
    results: list[dict[str, Any]] = []
    for spec in selected:
        try:
            probe_result = spec.probe_fn(active_symbols)
        except Exception as exc:
            probe_result = ProbeResult(calls=[CallSample(error=_truncate_error(exc))])
        results.append(_score_probe(spec.source, spec.category, probe_result))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "summary": {
            "n_probed": len(results),
            "n_available": sum(1 for item in results if item["available"]),
            "n_no_probe": n_no_probe,
        },
    }


def _default_out_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUT_DIR / f"source_health_{stamp}.json"


def _parse_symbols(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_SYMBOLS
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M61 read-only source health check harness.")
    parser.add_argument("--source", choices=sorted({spec.source for spec in PROBE_REGISTRY}), default=None)
    parser.add_argument("--category", choices=CATEGORIES, default=None)
    parser.add_argument("--symbols", default=None, help="Comma-separated test symbols; default 601869,300308")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path")
    parser.add_argument("--all", action="store_true", help="Run the full registered source/category matrix")
    parser.add_argument("--list", action="store_true", help="Print registered source/category probe matrix and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "probes": registered_probe_matrix()}, ensure_ascii=False, indent=2))
        return 0

    if not args.all and not args.source:
        raise SystemExit("--source is required unless --all or --list is used")

    payload = run_sweep(
        source=args.source,
        category=args.category,
        symbols=_parse_symbols(args.symbols),
        all_sources=args.all,
    )
    out_path = args.out or _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
