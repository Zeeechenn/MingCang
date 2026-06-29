import json
from datetime import datetime, timedelta

from sqlalchemy import text

from backend.data.database import NewsItem, Price
from backend.data.news_fusion import DEGRADED, NewsSignalV2


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
