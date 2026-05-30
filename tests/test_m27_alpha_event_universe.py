import pandas as pd


def test_m27_alpha_factors_are_finite_for_short_panels():
    from backend.analysis.alpha_factors import (
        M27_ALPHA_FEATURE_COLS,
        add_single_stock_alpha_factors,
    )

    df = pd.DataFrame({
        "open": range(1, 121),
        "high": range(2, 122),
        "low": range(0, 120),
        "close": range(1, 121),
        "volume": [1000 + (i % 7) * 100 for i in range(120)],
    })

    out = add_single_stock_alpha_factors(df)

    assert {
        "rev_mom_12_1_z",
        "turnover_anomaly_z",
        "price_volume_divergence_z",
        "sector_rel_strength_20_z",
    } == set(M27_ALPHA_FEATURE_COLS)
    assert out[M27_ALPHA_FEATURE_COLS].iloc[-1].notna().all()


def test_event_taxonomy_scores_events_and_falls_back_to_polarity():
    from backend.analysis.event_taxonomy import apply_event_score, build_event_extraction_prompt

    positive = apply_event_score(
        {"sentiment": -0.1, "key_events": []},
        ["公司公告获得重大合同并中标算力项目"],
    )
    neutral = apply_event_score({"sentiment": 0.2, "key_events": []}, ["普通经营动态"])

    assert positive["event_score_mode"] == "event_override"
    assert positive["event_score"] > 0
    assert positive["event_types"][0]["code"] == "major_contract"
    assert neutral["event_score_mode"] == "sentiment_fallback"
    assert neutral["event_score"] == 0.2
    assert "major_contract" in build_event_extraction_prompt("300308", ["中标"])


def test_aggregate_uses_event_score_only_when_event_overrides(monkeypatch):
    from backend.config import settings
    from backend.decision.aggregator import aggregate

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "multi_agent_enabled", False)
    monkeypatch.setattr(settings, "long_term_constraints_enabled", False)

    result = aggregate(
        quant_score=0.0,
        technical_result={"score": 0.0, "latest": {}, "limit": {}},
        sentiment_score=0.1,
        sentiment_result={
            "sentiment": 0.1,
            "event_score": 0.8,
            "event_score_mode": "event_override",
            "event_types": [{"code": "major_contract"}],
        },
        close=10.0,
        atr=1.0,
    )
    fallback = aggregate(
        quant_score=0.0,
        technical_result={"score": 0.0, "latest": {}, "limit": {}},
        sentiment_score=0.1,
        sentiment_result={
            "sentiment": 0.1,
            "event_score": 0.8,
            "event_score_mode": "sentiment_fallback",
            "event_types": [],
        },
        close=10.0,
        atr=1.0,
    )

    assert result["breakdown"]["sentiment"] == 80.0
    assert result["event_signal"]["event_score"] == 0.8
    assert fallback["breakdown"]["sentiment"] == 10.0


def test_aggregate_v2_uses_event_score_in_agent_path(monkeypatch):
    from backend.config import settings
    from backend.decision.aggregator import aggregate_v2

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "research_director_enabled", False)
    monkeypatch.setattr(settings, "multi_round_debate_enabled", False)
    monkeypatch.setattr(settings, "long_term_constraints_enabled", False)

    result = aggregate_v2(
        quant_result={"score": 0.0},
        technical_result={"score": 0.0, "latest": {}, "limit": {}},
        sentiment_result={
            "sentiment": 0.1,
            "event_score": 0.8,
            "event_score_mode": "event_override",
            "event_types": [{"code": "major_contract"}],
            "key_events": [],
        },
        close=10.0,
        atr=1.0,
    )

    assert result["breakdown"]["sentiment"] == 80.0
    assert result["breakdown"]["sentiment_raw"] == 80.0


def test_m27_test3_universe_filters_turnover_and_balances_sectors(test_db):
    from backend.data.database import MarketSnapshot, Price, Stock
    from backend.tools.m27_build_test3_universe import build_universe

    for symbol, sector, volume in [
        ("300001", "电子", 2_000.0),
        ("300002", "电子", 1.0),
        ("600001", "银行", 3_000.0),
    ]:
        test_db.add(Stock(symbol=symbol, name=symbol, market="CN", industry=sector, active=False))
        test_db.add(MarketSnapshot(
            symbol=symbol,
            date="2026-01-01",
            shares_outstanding=100_000.0,
        ))
        for i in range(5):
            test_db.add(Price(
                symbol=symbol,
                date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=volume,
            ))
    test_db.commit()

    payload = build_universe(
        test_db,
        target_size=2,
        min_bars=5,
        min_turnover=0.005,
        min_avg_traded_value=1_000_000.0,
        max_per_sector=1,
    )

    symbols = {row["symbol"] for row in payload["stocks"]}
    assert symbols == {"300001", "600001"}
    assert payload["coverage"]["selected_count"] == 2
