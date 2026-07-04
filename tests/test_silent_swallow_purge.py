from __future__ import annotations

from datetime import datetime

import pandas as pd


def test_default_flow_provider_missing_module_emits_degradation_and_returns_none(monkeypatch, test_db):
    from backend.data import news_fusion
    from backend.data.degradation import DegradationEvent

    def missing_module(name: str):
        raise ImportError("m52 missing")

    real_emit = news_fusion.emit_degradation
    monkeypatch.setattr(news_fusion, "import_module", missing_module)
    monkeypatch.setattr(
        news_fusion,
        "emit_degradation",
        lambda *args, **kwargs: real_emit(*args, db=test_db, **kwargs),
    )

    result = news_fusion._default_flow_provider("600519", datetime(2026, 1, 2))

    assert result is None
    event = test_db.query(DegradationEvent).one()
    assert event.component == "news_fusion"
    assert event.category == "fund_flow"
    assert event.provider == "m52_flow_floor"
    assert "m52 missing" in event.error


def test_attach_market_features_flags_null_derived_placeholder_constants(monkeypatch, test_db):
    from backend.data.database import MarketSnapshot
    from backend.data.degradation import DegradationEvent
    from backend.data.market_features import FAKE_FEATURE_FLAGS, attach_market_features

    emitted: list[tuple] = []

    def capture_emit(*args, **kwargs):
        emitted.append((args, kwargs))
        from backend.data.degradation import emit_degradation as real_emit

        kwargs.setdefault("db", test_db)
        return real_emit(*args, **kwargs)

    monkeypatch.setattr("backend.data.market_features.emit_degradation", capture_emit)

    test_db.add(
        MarketSnapshot(
            symbol="600519",
            date="2026-01-02",
            market_cap=100.0,
            float_market_cap=80.0,
            shares_outstanding=10.0,
            margin_balance=5.0,
            north_net_buy=None,
            large_order_net_inflow=None,
            source="unit_test",
        )
    )
    test_db.commit()

    df = pd.DataFrame({"date": ["2026-01-02"], "close": [10.0]})
    out = attach_market_features(df, "600519", test_db)

    assert out.loc[0, "north_net_buy"] == 0.0
    assert out.loc[0, "large_order_net_inflow"] == 0.0
    assert FAKE_FEATURE_FLAGS["north_net_buy"]["placeholder"] is True
    assert FAKE_FEATURE_FLAGS["large_order_net_inflow"]["placeholder"] is True
    assert {call[0][0] for call in emitted} == {"market_features"}
    assert {
        event.provider for event in test_db.query(DegradationEvent).order_by(DegradationEvent.provider).all()
    } == {"large_order_net_inflow", "north_net_buy"}
