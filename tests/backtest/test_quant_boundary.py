"""Production quant boundary tests."""

import pandas as pd


class TinyJoblibModel:
    n_features_in_ = 1

    def predict(self, frame):
        return [0.42] * len(frame)


def test_m26_baseline_defaults_to_test2_universe():
    from backend.tools import m26_quant_baseline

    assert m26_quant_baseline.DEFAULT_UNIVERSE_PATH.name == "test2_universe.json"
    assert m26_quant_baseline.M27_TEST3_UNIVERSE_PATH.name == "test3_universe.json"


def test_model_save_and_load_use_joblib_roundtrip(tmp_path):
    from backend.analysis import qlib_engine

    path = tmp_path / "model.pkl"

    qlib_engine._save_model(TinyJoblibModel(), path)
    model, error = qlib_engine._load_model_unchecked(path)

    assert error is None
    assert model.n_features_in_ == 1
    assert model.predict([object(), object()]) == [0.42, 0.42]


def test_production_validation_uses_legacy_feature_cols_for_legacy_model(monkeypatch):
    from backend.analysis import qlib_engine
    from backend.backtest import alphalens_qlib
    from backend.data import qlib_data
    from backend.tools import m26_quant_baseline

    class LegacyModel:
        n_features_in_ = len(qlib_data.PRODUCTION_FEATURE_COLS)

        def predict(self, frame):
            assert list(frame.columns) == qlib_data.PRODUCTION_FEATURE_COLS
            return [0.01] * len(frame)

    rows = []
    for day in range(10):
        date = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)).strftime("%Y-%m-%d")
        for symbol_idx, symbol in enumerate(["300001", "300002", "300003"]):
            row = {
                "date": date,
                "symbol": symbol,
                "label": 0.001 * (day + symbol_idx),
            }
            row.update({
                feature: float(day + symbol_idx / 10)
                for feature in qlib_data.FEATURE_COLS
            })
            rows.append(row)
    panel = pd.DataFrame(rows)

    def fake_validation_report(predictions, label, sample):
        assert not predictions.empty
        assert sample["n_features_validation"] == len(qlib_data.PRODUCTION_FEATURE_COLS)
        return {
            "label": label,
            "sample": sample,
            "metrics": {"ic_mean": 0.01, "icir": 0.1},
            "gates": {"pass": False, "pass_monotonic": False},
            "quantiles": [],
        }

    monkeypatch.setattr(qlib_engine, "_load_model_unchecked", lambda: (LegacyModel(), None))
    def fake_training_data(db, include_inactive=True, feature_cols=None):
        assert feature_cols == qlib_data.PRODUCTION_FEATURE_COLS
        return panel

    monkeypatch.setattr(qlib_data, "build_training_data", fake_training_data)
    monkeypatch.setattr(alphalens_qlib, "build_validation_report", fake_validation_report)

    report = m26_quant_baseline.build_current_model_validation(db=None)

    assert report["status"] == "ok"
    assert report["model"]["model_dim_status"] == "legacy_production_feature_cols"
    assert report["model"]["n_features_validation"] == len(qlib_data.PRODUCTION_FEATURE_COLS)


def test_qlib_score_uses_legacy_feature_cols_for_legacy_model(monkeypatch):
    from backend.analysis import qlib_engine
    from backend.data import qlib_data

    class LegacyModel:
        n_features_in_ = len(qlib_data.PRODUCTION_FEATURE_COLS)

        def predict(self, frame):
            assert list(frame.columns) == qlib_data.PRODUCTION_FEATURE_COLS
            return [0.0123]

    df = pd.DataFrame({
        "open": range(1, 301),
        "high": range(2, 302),
        "low": range(0, 300),
        "close": range(1, 301),
        "volume": [1000.0 + i for i in range(300)],
    })

    qlib_engine._MODEL_CACHE.update({
        "path_mtime": None,
        "model": None,
        "feature_cols": None,
        "disabled_reason": None,
    })

    class DummyModelPath:
        def exists(self):
            return True

        def stat(self):
            return type("Stat", (), {"st_mtime": 1.0})()

    monkeypatch.setattr(qlib_engine, "MODEL_PATH", DummyModelPath())
    monkeypatch.setattr(qlib_engine, "_load_model_unchecked", lambda: (LegacyModel(), None))

    try:
        result = qlib_engine.qlib_score(df)
    finally:
        qlib_engine._MODEL_CACHE.update({
            "path_mtime": None,
            "model": None,
            "feature_cols": None,
            "disabled_reason": None,
        })

    assert result["model"] == "lgbm_alpha_v1"
    assert result["raw_pred"] == 0.0123


def test_inference_sector_strength_z_matches_training_panel(test_db):
    from backend.data.database import Price, Stock
    from backend.data.qlib_data import build_inference_features, build_training_data

    symbols = ["300001", "300002"]
    for symbol in symbols:
        test_db.add(Stock(symbol=symbol, name=symbol, market="CN", industry="电子", active=True))

    dates = [(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(150)]
    target_rows = []
    for i, date in enumerate(dates):
        target_close = 100.0 + i * 0.8 + (i % 9) * 0.7
        peer_close = 90.0 + i * 0.3 + (i % 5) * 0.2
        target_rows.append({
            "date": date,
            "open": target_close - 0.2,
            "high": target_close + 0.5,
            "low": target_close - 0.5,
            "close": target_close,
            "volume": 1000.0 + i,
        })
        for symbol, close in [("300001", target_close), ("300002", peer_close)]:
            test_db.add(Price(
                symbol=symbol,
                date=date,
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1000.0 + i,
            ))
    test_db.commit()

    panel = build_training_data(test_db, min_rows=80)
    target_date = dates[130]
    training_row = panel[(panel["symbol"] == "300001") & (panel["date"] == target_date)].iloc[0]
    inference_frame = pd.DataFrame(target_rows[:131])

    feats = build_inference_features(inference_frame, symbol="300001", db=test_db)

    assert round(float(feats["sector_rel_strength_20_z"]), 10) == round(
        float(training_row["sector_rel_strength_20_z"]),
        10,
    )
