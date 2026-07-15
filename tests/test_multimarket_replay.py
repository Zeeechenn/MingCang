import pandas as pd


def _frame() -> pd.DataFrame:
    close = [100 + index * 0.7 for index in range(130)]
    return pd.DataFrame({
        "open": [value * 1.001 for value in close],
        "high": [value * 1.01 for value in close],
        "low": [value * 0.99 for value in close],
        "close": close,
        "volume": [1000 + (index % 7) * 50 for index in range(130)],
    }, index=[f"2026-{index // 28 + 1:02d}-{index % 28 + 1:02d}" for index in range(130)])


def test_replay_rules_and_cost_models_differ_by_market():
    from backend.backtest.multimarket_replay import replay_frame, replay_rule

    assert replay_rule("CN") != replay_rule("HK") != replay_rule("US")
    results = {market: replay_frame(_frame(), market=market) for market in ("CN", "HK", "US")}
    assert all(row["status"] == "ok" for row in results.values())
    assert len({row["cost_model_version"] for row in results.values()}) == 3
    assert results["CN"]["rule"]["max_hold_bars"] == 20
    assert results["HK"]["rule"]["require_volume_confirmation"] is True
    assert results["US"]["rule"]["entry_momentum"] == 0.05


def test_market_replay_uses_asset_keys_and_same_pool_baseline(test_db):
    from backend.backtest.multimarket_replay import run_market_replay
    from backend.data.database import Price, Stock

    stock = Stock(symbol="AAPL", name="Apple", market="US", active=True)
    test_db.add(stock)
    test_db.commit()
    for date_str, row in _frame().iterrows():
        test_db.add(Price(
            symbol="AAPL",
            market="US",
            date=date_str,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        ))
    test_db.commit()
    result = run_market_replay(test_db, ["US:AAPL"], as_of="2026-05-18")
    assert result["same_pool_equal_weight"] is True
    assert result["symbols_ok"] == 1
    assert result["results"][0]["asset_key"] == "US:AAPL"
