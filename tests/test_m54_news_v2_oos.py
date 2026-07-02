import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from backend.data.database import NewsItem, Price
from backend.data.news_fusion import DEGRADED, NewsSignalV2
from backend.data.news_layer_v2 import PYRAMID_NOT_TRIGGERED


class _MockLLMProvider:
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        sentiment = 0.2
        if "利空" in prompt or "处罚" in prompt:
            sentiment = -0.4
        elif "利好" in prompt or "中标" in prompt:
            sentiment = 0.6
        return {
            "relevance": 0.9,
            "sentiment": sentiment,
            "materiality": 0.9,
            "horizon": "short",
            "event_type": "contract",
            "catalysts": ["mock"],
            "risks": [],
            "confidence": 0.8,
        }


def _add_price_bars(db, symbols: list[str], start: str, days: int = 12) -> None:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    for sym_index, symbol in enumerate(symbols):
        for offset in range(days):
            day = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            close = 10.0 + sym_index + offset * (sym_index + 1)
            db.add(
                Price(
                    symbol=symbol,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1000,
                )
            )
    db.commit()


def _add_news(db, symbol: str, date: str, title: str, content: str) -> None:
    db.add(
        NewsItem(
            symbol=symbol,
            title=title,
            url=f"https://example.test/{symbol}/{date}/{abs(hash(title))}",
            published_at=datetime.strptime(f"{date} 10:00:00", "%Y-%m-%d %H:%M:%S"),
            source="mock",
            provider="mock",
            content=content,
        )
    )


def test_m54_news_v2_oos_mock_smoke_excludes_degraded(test_db, tmp_path, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001", "000002", "000003"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    for date in ("2026-01-05", "2026-01-06"):
        _add_news(test_db, "000001", date, "000001 中标 利好", "full content 利好")
        _add_news(test_db, "000002", date, "000002 处罚 利空", "full content 利空")
    test_db.commit()

    monkeypatch.setattr(
        "backend.data.news_extraction.get_provider",
        lambda: _MockLLMProvider(),
    )
    monkeypatch.delenv("SENTIMENT_CACHE_NS", raising=False)

    out = tmp_path / "m54-oos.json"
    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-06",
        lookback_days=1,
        tier="capable",
        out=out,
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert result["status"] in {"ok", "gate_blocked"}
    assert result["n_symbols"] == 3
    assert result["n_windows"] == 4
    assert result["skipped_degraded"] == 2
    assert result["meta"]["oos_namespace"] == "oos_news_v2"
    assert set(result["metrics"]) == {"h3d", "h5d"}
    assert result["metrics"]["h3d"]["ic_days"] == 0
    assert result["metrics"]["h3d"]["quantile"]["monotonic"] is False
    assert result["gate_blockers"]

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["n_windows"] == 4
    assert written["skipped_degraded"] == 2


def test_m54_news_v2_oos_cache_miss_writes_then_hit_skips_scoring(test_db, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    calls = 0

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        nonlocal calls
        calls += 1
        return NewsSignalV2(
            composite=0.42,
            news_score=0.5,
            flow_score=None,
            confidence=0.7,
            degradation_flags=["FLOW_MISSING"],
            contributing_clusters=["c1"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    first = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )
    second = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == 1
    assert first["meta"]["cache_hits"] == 0
    assert first["meta"]["cache_misses"] == 1
    assert first["meta"]["cache_writes"] == 1
    assert second["meta"]["cache_hits"] == 1
    assert second["meta"]["cache_misses"] == 0
    assert second["meta"]["cache_writes"] == 0
    assert second["n_windows"] == 1


def test_m54_news_v2_oos_degraded_score_is_not_cached(test_db, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    calls = 0

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        nonlocal calls
        calls += 1
        return NewsSignalV2(
            composite=0.0,
            news_score=None,
            flow_score=None,
            confidence=0.05,
            degradation_flags=["NEWS_THIN", "FLOW_MISSING", DEGRADED],
            contributing_clusters=[],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    first = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )
    second = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )

    cached_rows = test_db.execute(text("SELECT COUNT(*) FROM m54_oos_score_cache")).scalar()
    assert calls == 2
    assert first["skipped_degraded"] == 1
    assert first["meta"]["cache_writes"] == 0
    assert second["meta"]["cache_hits"] == 0
    assert cached_rows == 0


def test_m54_news_v2_oos_refresh_ignores_cache_and_ns_isolated(test_db, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    calls = 0

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        nonlocal calls
        calls += 1
        return NewsSignalV2(
            composite=0.1 * calls,
            news_score=0.1 * calls,
            flow_score=None,
            confidence=0.7,
            degradation_flags=[],
            contributing_clusters=[f"c{calls}"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        ns="ns_a",
        db=test_db,
        session_factory=lambda: test_db,
    )
    refreshed = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        ns="ns_a",
        refresh=True,
        db=test_db,
        session_factory=lambda: test_db,
    )
    isolated = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        ns="ns_b",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == 3
    assert refreshed["meta"]["cache_hits"] == 0
    assert refreshed["meta"]["cache_misses"] == 1
    assert refreshed["meta"]["cache_writes"] == 1
    assert refreshed["meta"]["refresh"] is True
    assert refreshed["meta"]["oos_namespace"] == "ns_a"
    assert isolated["meta"]["cache_hits"] == 0
    assert isolated["meta"]["cache_misses"] == 1


def test_m54_news_v2_oos_routes_v2_variant(test_db, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    calls: list[tuple[str, str, int, str]] = []

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        calls.append((symbol, as_of.strftime("%Y-%m-%d"), lookback_days, tier))
        return NewsSignalV2(
            composite=0.25,
            news_score=0.25,
            flow_score=None,
            confidence=0.8,
            degradation_flags=[],
            contributing_clusters=["c1"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        tier="capable",
        variant="v2",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == [("000001", "2026-01-05", 1, "capable")]
    assert result["meta"]["variant"] == "v2"
    assert result["meta"]["oos_namespace"] == "oos_news_v2"


def test_m54_news_v2_oos_legacy_fast_uses_titles_and_isolated_ns(
    test_db, monkeypatch
):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    _add_news(test_db, "000001", "2026-01-04", "旧窗标题 利好", "content")
    _add_news(test_db, "000001", "2026-01-05", "信号日标题 中标", "content")
    _add_news(test_db, "000001", "2026-01-01", "窗外标题 利空", "content")
    test_db.commit()

    calls: list[tuple[list[str], str, str, str]] = []

    def fake_analyze_news(titles, *, symbol=None, tier=""):
        calls.append((list(titles), symbol, tier, tool.os.environ["SENTIMENT_CACHE_NS"]))
        return {"sentiment": -0.35}

    monkeypatch.setattr(tool, "analyze_news", fake_analyze_news)

    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        variant="legacy-fast",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == [
        (
            ["旧窗标题 利好", "信号日标题 中标"],
            "000001",
            "",
            "oos_legacy_fast",
        )
    ]
    assert result["n_windows"] == 1
    assert result["meta"]["variant"] == "legacy-fast"
    assert result["meta"]["oos_namespace"] == "oos_legacy_fast"
    row = test_db.execute(
        text(
            "SELECT namespace, tier, composite FROM m54_oos_score_cache "
            "WHERE symbol = '000001'"
        )
    ).fetchone()
    assert row is not None
    assert row._mapping["namespace"] == "oos_legacy_fast"
    assert row._mapping["tier"] == ""
    assert row._mapping["composite"] == -0.35


def test_m54_news_v2_oos_legacy_capable_uses_capable_tier(test_db, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    _add_news(test_db, "000001", "2026-01-05", "标题 利好", "content")
    test_db.commit()
    calls: list[str] = []

    def fake_analyze_news(titles, *, symbol=None, tier=""):
        calls.append(tier)
        return {"sentiment": 0.55}

    monkeypatch.setattr(tool, "analyze_news", fake_analyze_news)

    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        variant="legacy-capable",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == ["capable"]
    assert result["meta"]["variant"] == "legacy-capable"
    assert result["meta"]["oos_namespace"] == "oos_legacy_capable"


def test_m54_news_v2_oos_align_ns_limits_legacy_to_cached_windows(
    test_db, monkeypatch
):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001", "000002"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    _add_news(test_db, "000001", "2026-01-05", "000001 标题 利好", "content")
    _add_news(test_db, "000002", "2026-01-05", "000002 标题 利空", "content")
    test_db.commit()
    tool._ensure_score_cache_schema(test_db)
    tool._score_cache_set(
        test_db,
        namespace="oos_news_v2",
        symbol="000001",
        sig_date="2026-01-05",
        lookback_days=1,
        tier="capable",
        score={
            "score": 0.4,
            "news_score": 0.4,
            "flow_score": None,
            "confidence": 0.8,
            "degradation_flags": [],
        },
    )

    calls: list[str] = []

    def fake_analyze_news(titles, *, symbol=None, tier=""):
        calls.append(symbol)
        return {"sentiment": 0.2}

    monkeypatch.setattr(tool, "analyze_news", fake_analyze_news)

    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-05",
        lookback_days=1,
        variant="legacy-fast",
        align_ns="oos_news_v2",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert calls == ["000001"]
    assert result["n_windows"] == 1
    assert result["meta"]["align_ns"] == "oos_news_v2"


def test_m54_news_v2_oos_excludes_pyramid_not_triggered_from_ic(test_db, monkeypatch):
    """bug-1b: PYRAMID_NOT_TRIGGERED fallback windows must be excluded from IC,
    same as DEGRADED, and counted separately (skipped_degraded / skipped_not_triggered)."""
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001", "000002", "000003"]
    _add_price_bars(test_db, symbols, "2026-01-05")

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        if symbol == "000001":
            flags = [DEGRADED]
        elif symbol == "000002":
            flags = [PYRAMID_NOT_TRIGGERED]
        else:
            flags = []
        return NewsSignalV2(
            composite=0.3,
            news_score=0.3,
            flow_score=None,
            confidence=0.9,
            degradation_flags=flags,
            contributing_clusters=["c"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-06",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )

    # only 000003 (clean, no flags) contributes windows: 2 signal dates.
    assert result["n_windows"] == 2
    assert result["skipped_degraded"] == 2
    assert result["skipped_not_triggered"] == 2
    assert result["meta"]["skipped_degraded"] == 2
    assert result["meta"]["skipped_not_triggered"] == 2

    # non-pyramid legs (legacy) never emit PYRAMID_NOT_TRIGGERED; only DEGRADED
    # exclusion applies there. This is exercised by the existing DEGRADED-only
    # legacy/v2 tests above and is unaffected by this change.


def test_m54_news_v2_oos_require_price_coverage_raises_on_gap(test_db, monkeypatch):
    """bug-1a: insufficient forward-price coverage in the window's tail must be
    self-evidenced in meta.price_coverage, and must raise when a floor is set."""
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001", "000002"]
    # Only 3 days of price bars from the window start -- nowhere near enough
    # trailing days for a horizon=5 forward return from any signal date in the
    # 2026-01-05..2026-01-09 window (5 signal dates).
    _add_price_bars(test_db, symbols, "2026-01-05", days=3)

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        return NewsSignalV2(
            composite=0.1,
            news_score=0.1,
            flow_score=None,
            confidence=0.8,
            degradation_flags=[],
            contributing_clusters=["c1"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    with pytest.raises(ValueError, match="price coverage insufficient"):
        tool.run_oos(
            symbols,
            "2026-01-05",
            "2026-01-09",
            lookback_days=1,
            tier="capable",
            db=test_db,
            session_factory=lambda: test_db,
            require_price_coverage=50.0,
        )

    # Default (no requirement) never raises; it just self-evidences the gap.
    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-09",
        lookback_days=1,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )
    coverage = result["meta"]["price_coverage"]
    assert coverage["coverage_pct"] == 0.0
    assert coverage["horizon"] == 5
    assert coverage["n_symbols"] == 2
    assert coverage["n_pairs_total"] == 10  # 5 tail signal dates x 2 symbols
    assert coverage["n_pairs_covered"] == 0
    assert coverage["window_dates"] == [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
    ]
    assert result["meta"]["require_price_coverage"] == 0.0


def test_m54_news_v2_oos_forward_return_gap_yields_none_not_stretched_horizon(test_db):
    """bug-3: a symbol with a price gap must not have its horizon silently
    stretched by walking its own (gap-shortened) date list. D0/D1/D3 has a
    hole at D2 in this symbol's own series. The calendar (built from the
    union across symbols, per _build_trading_calendar) does include D2 because
    a different symbol traded that day. With horizon=2 from D1, the true
    2nd-calendar-day target is D3 -- so this particular symbol/gap combo
    happens to still resolve. To exercise the actual gap-swallowing failure
    mode we pick a horizon that lands exactly on the missing D2 bar for this
    symbol: horizon=1 from D1 must target D2 (calendar position), find no bar
    for this symbol on D2, and return None -- NOT silently fall through to D3
    (which is what the old index-based logic would have done, since D3 was
    this symbol's very next available price row)."""
    from backend.tools import m54_news_v2_oos as tool

    d0, d1, d2, d3 = "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05"

    # gappy: no bar on d2 (e.g. a trading halt for this symbol).
    gappy_prices = {d0: 10.0, d1: 11.0, d3: 13.0}
    # a second symbol trades on d2, so the union calendar includes it.
    other_prices = {d0: 20.0, d1: 21.0, d2: 22.0, d3: 23.0}
    calendar = tool._build_trading_calendar({"GAPPY": gappy_prices, "OTHER": other_prices})
    assert calendar == [d0, d1, d2, d3]

    # Old (pre-fix) behaviour would walk GAPPY's own sorted dates [d0, d1, d3]:
    # idx(d1)=1, target_idx=1+1=2 -> d3 (wrong: that is a 2-trading-day gap,
    # not 1). The fixed function must instead resolve horizon=1 from d1 to the
    # calendar's very next day, d2 -- and since GAPPY has no bar on d2, return
    # None rather than silently substituting d3's price.
    assert tool._forward_return(gappy_prices, d1, 1, calendar) is None

    # Sanity: OTHER (no gap) resolves the same horizon/date cleanly and
    # matches the true 1-calendar-day-ahead value (d1 -> d2).
    assert tool._forward_return(other_prices, d1, 1, calendar) == pytest.approx(22.0 / 21.0 - 1.0)

    # horizon=2 from d1 lands on d3 (in-calendar position d1+2=d3) for both
    # symbols, since GAPPY does have a bar on d3 -- this is the correctly
    # "long way around the gap" answer, not a mislabeled 3-calendar-day span.
    assert tool._forward_return(gappy_prices, d1, 2, calendar) == pytest.approx(13.0 / 11.0 - 1.0)


def test_m54_news_v2_oos_forward_return_no_gap_uses_correct_nth_calendar_day(test_db):
    """No-gap symbol: horizon-day forward return must select exactly the Nth
    calendar day and compute the correct ratio."""
    from backend.tools import m54_news_v2_oos as tool

    dates = ["2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06"]
    prices = {d: 10.0 + i for i, d in enumerate(dates)}  # 10, 11, 12, 13, 14
    calendar = tool._build_trading_calendar({"CLEAN": prices})
    assert calendar == dates

    # horizon=3 from dates[0] ("2026-02-02", price 10.0) must land on
    # dates[3] ("2026-02-05", price 13.0), i.e. the 3rd calendar day forward.
    got = tool._forward_return(prices, dates[0], 3, calendar)
    assert got == pytest.approx(13.0 / 10.0 - 1.0)

    # horizon=1 from dates[1] ("2026-02-03", price 11.0) -> dates[2] (12.0).
    got2 = tool._forward_return(prices, dates[1], 1, calendar)
    assert got2 == pytest.approx(12.0 / 11.0 - 1.0)

    # signal_date not itself in calendar/prices (weekend) falls back to the
    # first calendar date >= signal_date, per the existing >= fallback.
    got3 = tool._forward_return(prices, "2026-02-01", 1, calendar)
    assert got3 == pytest.approx(11.0 / 10.0 - 1.0)

    # horizon runs past the end of the calendar -> None.
    assert tool._forward_return(prices, dates[-1], 1, calendar) is None
