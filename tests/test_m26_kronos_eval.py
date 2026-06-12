import pandas as pd
import pytest


def test_kronos_trading_dates_use_union_not_full_intersection():
    from backend.tools.m26_kronos_eval import get_trading_dates

    prices = {
        "300001": pd.DataFrame(index=pd.to_datetime(["2026-01-01", "2026-01-02"])),
        "300002": pd.DataFrame(index=pd.to_datetime(["2026-01-02", "2026-01-03"])),
    }

    dates = get_trading_dates(prices, "2026-01-01", "2026-01-03")

    assert [d.strftime("%Y-%m-%d") for d in dates] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]


def test_kronos_load_prices_missing_db_does_not_create_file(tmp_path, monkeypatch):
    from backend.tools import m26_kronos_eval

    missing_db = tmp_path / "missing.db"
    monkeypatch.setattr(m26_kronos_eval, "DB_PATH", missing_db)

    with pytest.raises(FileNotFoundError):
        m26_kronos_eval.load_prices(["300001"], "2026-01-01", "2026-01-02")

    assert not missing_db.exists()


def test_kronos_predict_returns_aligns_input_and_label_horizon():
    from backend.tools.m26_kronos_eval import predict_returns

    class FakePredictor:
        def predict_batch(
            self,
            *,
            df_list,
            x_timestamp_list,
            y_timestamp_list,
            pred_len,
            T,
            top_p,
            sample_count,
            verbose,
        ):
            assert x_timestamp_list[0].iloc[-1] == pd.Timestamp("2026-01-03")
            assert y_timestamp_list[0].tolist() == [
                pd.Timestamp("2026-01-04"),
                pd.Timestamp("2026-01-05"),
            ]
            last_close = float(df_list[0]["close"].iloc[-1])
            return [
                pd.DataFrame(
                    {"close": [last_close * 1.05, last_close * 1.10]},
                    index=y_timestamp_list[0],
                )
            ]

    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = {
        "300001": pd.DataFrame(
            {
                "open": [10.0, 11.0, 12.0, 13.0, 14.0],
                "high": [10.5, 11.5, 12.5, 13.5, 14.5],
                "low": [9.5, 10.5, 11.5, 12.5, 13.5],
                "close": [10.0, 11.0, 12.0, 13.0, 14.0],
                "volume": [1000.0] * 5,
            },
            index=idx,
        )
    }

    out = predict_returns(
        FakePredictor(),
        prices,
        [pd.Timestamp("2026-01-03")],
        context_len=3,
        pred_len=2,
    )

    assert round(float(out.loc[pd.Timestamp("2026-01-03"), "300001"]), 6) == 0.1


def test_kronos_finetuned_model_path_resolves_checkpoint(tmp_path):
    from backend.tools.m26_kronos_eval import resolve_model_spec

    checkpoint = tmp_path / "checkpoints" / "best_model"
    checkpoint.mkdir(parents=True)

    spec = resolve_model_spec("kronos-finetuned", finetuned_model_path=tmp_path)

    assert spec["model_source"] == "local_finetuned"
    assert spec["model_path"] == str(checkpoint)
    assert spec["model_id"] == str(checkpoint)


def test_kronos_finetuned_model_path_missing_is_clear(tmp_path):
    import pytest

    from backend.tools.m26_kronos_eval import resolve_model_spec

    with pytest.raises(RuntimeError, match="Finetuned Kronos model path does not exist"):
        resolve_model_spec("kronos-finetuned", finetuned_model_path=tmp_path / "missing")


def test_kronos_finetuned_model_path_rejects_smoke_checkpoint(tmp_path):
    import json

    import pytest

    from backend.tools.m26_kronos_eval import resolve_model_spec

    checkpoint = tmp_path / "checkpoints" / "best_model"
    checkpoint.mkdir(parents=True)
    (checkpoint / "manifest.json").write_text(
        json.dumps({"checkpoint_kind": "mingcang_path_a_smoke_model"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="smoke artifact"):
        resolve_model_spec("kronos-finetuned", finetuned_model_path=tmp_path)
