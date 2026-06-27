"""M54 news content feasibility probe.

This probe is intentionally read-only: it calls the existing news fetchers,
captures their source responses before ``content`` is dropped, and prints a
human-readable coverage summary.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests

from backend.config import settings
from backend.data import news as news_data

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test3_universe_50.json"
DEFAULT_TARGET_COUNT = 3
PREVIEW_CHARS = 120


@dataclass(frozen=True)
class StockTarget:
    symbol: str
    name: str


@dataclass(frozen=True)
class ProbeItem:
    symbol: str
    title: str
    content: str
    published_at: datetime | None
    source: str
    url: str


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    label: str
    target: StockTarget
    items: list[ProbeItem]
    skipped_reason: str | None = None
    warning: str | None = None


@contextmanager
def _capture_session_get() -> Iterator[list[requests.Response]]:
    captured: list[requests.Response] = []
    original_get = requests.Session.get

    def traced_get(
        session: requests.Session,
        url: str | bytes,
        **kwargs: Any,
    ) -> requests.Response:
        response = original_get(session, url, **kwargs)
        captured.append(response)
        return response

    with patch.object(requests.Session, "get", traced_get):
        yield captured


@contextmanager
def _capture_requests_get() -> Iterator[list[requests.Response]]:
    captured: list[requests.Response] = []
    original_get = requests.get

    def traced_get(url: str | bytes, **kwargs: Any) -> requests.Response:
        response = original_get(url, **kwargs)
        captured.append(response)
        return response

    with patch.object(requests, "get", traced_get):
        yield captured


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"</?em>", "", text).strip()


def _preview(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return compact[:PREVIEW_CHARS] if compact else "（无正文）"


def _parse_jsonp_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    callback = "jQuery_mingcang"
    if raw.startswith(callback):
        raw = raw[len(callback) :].strip("();")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _parse_eastmoney_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return news_data._cst_to_utc(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def _parse_anspire_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip().replace("T", " ")[:19]
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _response_for_url(responses: Sequence[requests.Response], needle: str) -> requests.Response | None:
    for response in responses:
        if needle in str(response.url):
            return response
    return None


def _eastmoney_items_from_response(symbol: str, response: requests.Response) -> list[ProbeItem]:
    payload = _parse_jsonp_payload(response.text)
    articles = payload.get("result", {}).get("cmsArticleWebOld", [])
    if not isinstance(articles, list):
        return []

    items: list[ProbeItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _clean_text(article.get("title"))
        code = str(article.get("code") or "").strip()
        url = f"http://finance.eastmoney.com/a/{code}.html" if code else ""
        if not title:
            continue
        items.append(
            ProbeItem(
                symbol=symbol,
                title=title,
                content=_clean_text(article.get("content")),
                published_at=_parse_eastmoney_datetime(article.get("date")),
                source=_clean_text(article.get("mediaName")) or "东财",
                url=url,
            )
        )
    return items


def fetch_eastmoney_probe(target: StockTarget) -> ProbeResult:
    call_error: Exception | None = None
    with _capture_session_get() as responses:
        try:
            news_data._fetch_news_df(target.symbol)
        except Exception as exc:  # pragma: no cover - defensive for operator probes.
            call_error = exc

    response = _response_for_url(responses, "search-api-web.eastmoney.com/search/jsonp")
    if response is None:
        reason = "未捕获东财直连 JSONP 响应；可能已 fallback 到 AkShare 或请求未发出"
        if call_error is not None:
            reason = f"{reason}（调用异常：{call_error}）"
        return ProbeResult("eastmoney", "东财直连 API", target, [], skipped_reason=reason)

    try:
        items = _eastmoney_items_from_response(target.symbol, response)
    except Exception as exc:
        return ProbeResult(
            "eastmoney",
            "东财直连 API",
            target,
            [],
            skipped_reason=f"东财原始响应解析失败：{exc}",
        )

    warning = f"现有 fetcher 调用异常，但已捕获原始响应：{call_error}" if call_error else None
    return ProbeResult("eastmoney", "东财直连 API", target, items, warning=warning)


def _anspire_results_payload(response: requests.Response) -> list[dict[str, Any]]:
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    results = payload.get("results") or []
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except json.JSONDecodeError:
            return []
    if not isinstance(results, list):
        return []
    return [row for row in results if isinstance(row, dict)]


def _anspire_items_from_response(symbol: str, response: requests.Response) -> list[ProbeItem]:
    items: list[ProbeItem] = []
    for result in _anspire_results_payload(response):
        title = _clean_text(result.get("title"))
        url = str(result.get("url") or "").strip()
        if not title and not url:
            continue
        source = news_data._domain_from_url(url) or "anspire"
        items.append(
            ProbeItem(
                symbol=symbol,
                title=title or "（无标题）",
                content=_clean_text(result.get("content")),
                published_at=_parse_anspire_datetime(result.get("date")),
                source=source,
                url=url,
            )
        )
    return items


def fetch_anspire_probe(
    target: StockTarget,
    *,
    days: int | None,
    max_results: int | None,
) -> ProbeResult:
    if not settings.anspire_api_key:
        return ProbeResult(
            "anspire",
            "Anspire",
            target,
            [],
            skipped_reason="未配置 ANSPIRE_API_KEY / settings.anspire_api_key",
        )

    call_error: Exception | None = None
    effective_max_results = max_results or settings.anspire_news_max_results
    with _capture_requests_get() as responses:
        try:
            news_data.fetch_stock_news_anspire(
                target.symbol,
                target.name,
                days=days,
                max_results=effective_max_results,
                limit=effective_max_results,
            )
        except Exception as exc:  # pragma: no cover - defensive for operator probes.
            call_error = exc

    response = _response_for_url(responses, news_data.ANSPIRE_SEARCH_URL)
    if response is None:
        reason = "未捕获 Anspire 搜索响应；请求可能未发出或网络层抛错"
        if call_error is not None:
            reason = f"{reason}（调用异常：{call_error}）"
        return ProbeResult("anspire", "Anspire", target, [], skipped_reason=reason)

    try:
        items = _anspire_items_from_response(target.symbol, response)
    except Exception as exc:
        return ProbeResult(
            "anspire",
            "Anspire",
            target,
            [],
            skipped_reason=f"Anspire 原始响应解析失败：{exc}",
        )

    warning = f"现有 fetcher 调用异常，但已捕获原始响应：{call_error}" if call_error else None
    return ProbeResult("anspire", "Anspire", target, items, warning=warning)


def _load_universe(path: Path) -> list[StockTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"universe JSON must contain a list or stocks list: {path}")

    targets: list[StockTarget] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip()
        name = str(row.get("name") or symbol).strip()
        if symbol:
            targets.append(StockTarget(symbol=symbol, name=name or symbol))
    return targets


def _targets_from_args(symbols: Sequence[str]) -> list[StockTarget]:
    universe = _load_universe(DEFAULT_UNIVERSE)
    by_symbol = {target.symbol: target for target in universe}
    if not symbols:
        return universe[:DEFAULT_TARGET_COUNT]
    targets: list[StockTarget] = []
    for raw_symbol in symbols:
        symbol = raw_symbol.strip()
        if not symbol:
            continue
        targets.append(by_symbol.get(symbol, StockTarget(symbol=symbol, name=symbol)))
    return targets


def _content_lengths(items: Sequence[ProbeItem]) -> list[int]:
    return [len(item.content.strip()) for item in items]


def _nonempty_content_count(items: Sequence[ProbeItem]) -> int:
    return sum(1 for item in items if item.content.strip())


def _oldest_datetime(items: Sequence[ProbeItem]) -> datetime | None:
    dates = [item.published_at for item in items if item.published_at is not None]
    return min(dates) if dates else None


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "不可判定"


def _format_length_stats(lengths: Sequence[int]) -> str:
    if not lengths:
        return "无返回新闻"
    median = statistics.median(lengths)
    median_text = f"{median:.1f}" if isinstance(median, float) and not median.is_integer() else f"{median:.0f}"
    return f"min/median/max={min(lengths)}/{median_text}/{max(lengths)}"


def _print_result(result: ProbeResult) -> None:
    print(f"\n[{result.label}]")
    if result.skipped_reason:
        print(f"状态：未完成统计；原因：{result.skipped_reason}")
        return
    if result.warning:
        print(f"提示：{result.warning}")

    total = len(result.items)
    lengths = _content_lengths(result.items)
    oldest = _oldest_datetime(result.items)
    print(f"正文覆盖：{_nonempty_content_count(result.items)} / {total}")
    print(f"正文长度：{_format_length_stats(lengths)}")
    print(f"最旧发布日期：{_format_datetime(oldest)}")
    print("样例：")
    if not result.items:
        print("  （无返回新闻）")
        return
    for index, item in enumerate(result.items[:2], start=1):
        print(f"  {index}. {item.title}")
        print(f"     正文前{PREVIEW_CHARS}字：{_preview(item.content)}")


def _history_text(items: Sequence[ProbeItem]) -> str:
    oldest = _oldest_datetime(items)
    if oldest is None:
        return "否（无可解析发布日期）"
    now_date = datetime.now(UTC).date()
    age_days = max((now_date - oldest.date()).days, 0)
    return f"是（最旧 {oldest:%Y-%m-%d}，约 {age_days} 天前）"


def _source_conclusion(provider: str, label: str, results: Sequence[ProbeResult]) -> str:
    provider_results = [result for result in results if result.provider == provider]
    items = [item for result in provider_results for item in result.items]
    if items:
        provides_content = "是" if _nonempty_content_count(items) else "否"
        return f"{label} 提供正文={provides_content}；可回溯历史={_history_text(items)}"

    reasons = [result.skipped_reason for result in provider_results if result.skipped_reason]
    if reasons:
        return f"{label} 提供正文=未验证；可回溯历史=未验证（{reasons[0]}）"
    return f"{label} 提供正文=否；可回溯历史=否（无返回新闻）"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M54 新闻正文可行性探针：统计东财/Anspire 原始 content 覆盖和历史回溯。",
    )
    parser.add_argument(
        "symbols",
        nargs="*",
        help="股票代码；默认取 paper_trading/test3_universe_50.json 前 3 支",
    )
    parser.add_argument(
        "--anspire-days",
        type=int,
        default=None,
        help="覆盖 Anspire FromTime 窗口天数；默认沿用 settings.anspire_news_days",
    )
    parser.add_argument(
        "--anspire-max-results",
        type=int,
        default=None,
        help="覆盖 Anspire top_k；默认沿用 settings.anspire_news_max_results",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    targets = _targets_from_args(args.symbols)
    if not targets:
        raise SystemExit("没有可探测股票代码")

    print("M54 新闻正文可行性探针")
    print("只读探测：不写数据库、不改新闻入库逻辑。")
    print("正文判定：按原始响应里的非空 content 字段统计。")
    print("目标股票：" + "、".join(f"{target.symbol}({target.name})" for target in targets))
    if args.anspire_days is not None:
        print(f"Anspire 窗口：最近 {args.anspire_days} 天")
    else:
        print(f"Anspire 窗口：settings.anspire_news_days={settings.anspire_news_days} 天")

    all_results: list[ProbeResult] = []
    for target in targets:
        print(f"\n=== {target.symbol} {target.name} ===")
        eastmoney_result = fetch_eastmoney_probe(target)
        anspire_result = fetch_anspire_probe(
            target,
            days=args.anspire_days,
            max_results=args.anspire_max_results,
        )
        all_results.extend([eastmoney_result, anspire_result])
        _print_result(eastmoney_result)
        _print_result(anspire_result)

    eastmoney_line = _source_conclusion("eastmoney", "东财", all_results)
    anspire_line = _source_conclusion("anspire", "Anspire", all_results)
    print(f"\n结论：{eastmoney_line}；{anspire_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
