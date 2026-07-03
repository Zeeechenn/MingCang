import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from backend.data.database import Price
from backend.data.news_fusion import NewsSignalV2
from backend.data.news_layer_v2 import PYRAMID_NOT_TRIGGERED
from backend.data.news_models import RawNews


def _universe_file(tmp_path, symbols):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {"stocks": [{"symbol": s, "name": f"name-{s}"} for s in symbols]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _raw_news(symbol: str, url: str, *, title: str = "标题", content: str = "正文") -> RawNews:
    return RawNews(
        title=title,
        url=url,
        published_at=datetime(2026, 6, 29, 9, 0, 0),
        source="mock",
        symbol=symbol,
        content=content,
        provider="mock",
    )


def _add_price_bars(db, symbols: list[str], start: str, days: int = 30) -> None:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    for sym_index, symbol in enumerate(symbols):
        for offset in range(days):
            day = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            close = 10.0 + sym_index + offset * 0.1
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


def test_run_daily_accrual_scores_new_date_and_reports_progress(test_db, tmp_path, monkeypatch):
    from backend.tools import m54_daily_accrual as tool

    symbols = ["000001", "000002"]
    universe = _universe_file(tmp_path, symbols)
    fetch_calls: list[str] = []

    def fake_cn(symbol: str, limit: int) -> list[RawNews]:
        fetch_calls.append(symbol)
        return [_raw_news(symbol, f"https://example.test/{symbol}/cn")]

    monkeypatch.setattr(tool, "fetch_stock_news_cn", fake_cn)
    monkeypatch.setattr(tool, "fetch_stock_news_anspire", lambda symbol, name: [])
    monkeypatch.setattr(tool, "fetch_news_ifind", lambda symbol, name: [])

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        flags = [PYRAMID_NOT_TRIGGERED] if symbol == "000002" else []
        return NewsSignalV2(
            composite=0.3,
            news_score=0.3,
            flow_score=None,
            confidence=0.9,
            degradation_flags=flags,
            contributing_clusters=["c"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    result = tool.run_daily_accrual(
        date="2026-06-29",  # Monday
        universe_path=universe,
        ns="test_ns",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert result["ok"] is True
    assert result["market_open"] is True
    assert sorted(fetch_calls) == symbols
    assert result["content_inserted"] == 2
    assert result["n_scored_new"] == 2
    assert result["n_cache_hit_skipped"] == 0
    assert result["n_triggered"] == 1
    assert result["n_not_triggered"] == 1
    assert result["trigger_rate"] == pytest.approx(0.5)

    progress = result["progress"]
    assert progress["namespace"] == "test_ns"
    assert progress["n_cached_rows"] == 2
    # PYRAMID_NOT_TRIGGERED is excluded from IC (same EXCLUDE_FROM_IC set the
    # OOS harness uses) -- only the 000001 row is IC-eligible.
    assert progress["n_ic_eligible_rows"] == 1
    assert progress["gate"]["h3d"]["min_required"] == 20
    assert progress["gate"]["h5d"]["min_required"] == 20

    cached = test_db.execute(
        text("SELECT COUNT(*) FROM m54_oos_score_cache WHERE namespace='test_ns'")
    ).scalar()
    assert cached == 2


def test_run_daily_accrual_idempotent_rerun_skips_rescoring_and_refetch(
    test_db, tmp_path, monkeypatch
):
    from backend.tools import m54_daily_accrual as tool

    symbols = ["000001"]
    universe = _universe_file(tmp_path, symbols)

    monkeypatch.setattr(
        tool,
        "fetch_stock_news_cn",
        lambda symbol, limit: [_raw_news(symbol, "https://example.test/000001/cn")],
    )
    monkeypatch.setattr(tool, "fetch_stock_news_anspire", lambda symbol, name: [])
    monkeypatch.setattr(tool, "fetch_news_ifind", lambda symbol, name: [])

    calls = 0

    def fake_score(symbol, as_of, lookback_days, db, *, tier="capable", flow_value=None):
        nonlocal calls
        calls += 1
        return NewsSignalV2(
            composite=0.1,
            news_score=0.1,
            flow_score=None,
            confidence=0.8,
            degradation_flags=[],
            contributing_clusters=["c"],
        )

    monkeypatch.setattr(tool, "news_v2_score_from_db", fake_score)

    kwargs = dict(
        date="2026-06-29",
        universe_path=universe,
        ns="idem_ns",
        db=test_db,
        session_factory=lambda: test_db,
    )
    first = tool.run_daily_accrual(**kwargs)
    second = tool.run_daily_accrual(**kwargs)

    assert calls == 1  # scored exactly once across both runs
    assert first["content_inserted"] == 1
    assert second["content_inserted"] == 0  # URL dedup in save_news_to_db
    assert first["n_scored_new"] == 1
    assert second["n_scored_new"] == 0
    assert second["n_cache_hit_skipped"] == 1
    assert first["progress"]["n_cached_rows"] == second["progress"]["n_cached_rows"] == 1

    cached = test_db.execute(
        text("SELECT COUNT(*) FROM m54_oos_score_cache WHERE namespace='idem_ns'")
    ).scalar()
    assert cached == 1


def test_run_daily_accrual_weekend_is_noop(test_db, tmp_path, monkeypatch):
    from backend.tools import m54_daily_accrual as tool

    symbols = ["000001"]
    universe = _universe_file(tmp_path, symbols)

    def boom(*args, **kwargs):
        raise AssertionError("fetch/score must not run on a non-trading date")

    monkeypatch.setattr(tool, "fetch_stock_news_cn", boom)
    monkeypatch.setattr(tool, "fetch_stock_news_anspire", boom)
    monkeypatch.setattr(tool, "fetch_news_ifind", boom)
    monkeypatch.setattr(tool, "news_v2_score_from_db", boom)

    result = tool.run_daily_accrual(
        date="2026-06-28",  # Sunday
        universe_path=universe,
        ns="weekend_ns",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert result["ok"] is True
    assert result["market_open"] is False
    assert "progress" in result

    cached = test_db.execute(text("SELECT COUNT(*) FROM m54_oos_score_cache")).scalar()
    assert cached == 0


def test_compute_progress_empty_namespace_reports_zero_ic_days(test_db):
    from backend.tools import m54_daily_accrual as tool

    progress = tool.compute_progress(
        ns="never_run_ns", db=test_db, session_factory=lambda: test_db
    )

    assert progress["n_cached_rows"] == 0
    assert progress["window"] is None
    assert progress["gate"]["h3d"] == {
        "ic_days": 0,
        "min_required": 20,
        "remaining_ic_days": 20,
        "approx_trading_days_remaining": 60,
    }
    assert progress["gate"]["h5d"]["remaining_ic_days"] == 20
    assert progress["gate"]["passed"] is False


def test_compute_progress_computes_ic_days_from_cached_scores_and_prices(test_db):
    from backend.tools import m54_daily_accrual as tool
    from backend.tools import m54_news_v2_oos as oos_tool

    symbols = ["000001", "000002", "000003"]
    _add_price_bars(test_db, symbols, "2026-01-01", days=40)
    oos_tool._ensure_score_cache_schema(test_db)

    dates: list[str] = []
    cur = datetime(2026, 1, 1)
    while len(dates) < 15:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    for i, sig_date in enumerate(dates):
        for symbol in symbols:
            oos_tool._score_cache_set(
                test_db,
                namespace="prog_ns",
                symbol=symbol,
                sig_date=sig_date,
                lookback_days=3,
                tier="capable",
                score={
                    "score": 0.1 * ((i + symbols.index(symbol)) % 3),
                    "news_score": 0.1,
                    "flow_score": None,
                    "confidence": 0.9,
                    "degradation_flags": [],
                },
            )

    progress = tool.compute_progress(
        ns="prog_ns",
        lookback_days=3,
        tier="capable",
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert progress["n_cached_rows"] == 15 * 3
    assert progress["n_ic_eligible_rows"] == 15 * 3
    assert progress["gate"]["h3d"]["ic_days"] > 0
    assert progress["gate"]["h3d"]["remaining_ic_days"] == max(
        0, 20 - progress["gate"]["h3d"]["ic_days"]
    )
    assert progress["gate"]["h5d"]["ic_days"] >= 0
