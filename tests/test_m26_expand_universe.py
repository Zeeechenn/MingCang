import pandas as pd


def test_m26_expand_universe_retrain_includes_inactive(monkeypatch):
    from backend.analysis import qlib_engine
    from backend.data import database
    from backend.tools import m26_expand_universe

    class DummyDB:
        def close(self):
            pass

    train_calls = []

    def fake_train(db, *, include_inactive=False, **kwargs):
        train_calls.append(include_inactive)
        return True

    dates = pd.date_range("2026-01-01", periods=60).strftime("%Y-%m-%d")
    frame = pd.DataFrame(
        {
            "open": [10.0] * 60,
            "high": [10.2] * 60,
            "low": [9.9] * 60,
            "close": [10.1] * 60,
            "volume": [1000.0] * 60,
        },
        index=dates,
    )

    monkeypatch.setattr(database, "SessionLocal", lambda: DummyDB())
    monkeypatch.setattr(m26_expand_universe, "fetch_stock_history", lambda symbol, days: (frame, "unit"))
    monkeypatch.setattr(m26_expand_universe, "_upsert_stock", lambda db, symbol, name: None)
    monkeypatch.setattr(m26_expand_universe, "_write_prices", lambda db, symbol, df: len(df))
    monkeypatch.setattr(qlib_engine, "train", fake_train)

    stats = m26_expand_universe.run(
        symbols={"300001": "测试股"},
        retrain=True,
        delay=0.0,
    )

    assert stats["added"] == 1
    assert train_calls == [True]
