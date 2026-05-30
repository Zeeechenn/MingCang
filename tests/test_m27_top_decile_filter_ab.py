import numpy as np
import pandas as pd


def _panel(rows_per_symbol=70):
    from backend.data.qlib_data import FEATURE_COLS

    symbols = ["A", "B", "C", "D", "E", "F"]
    rows = []
    for day in range(rows_per_symbol):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(symbols):
            row = {
                "date": date,
                "symbol": symbol,
                "close": 10 + day + idx,
                "log_market_cap": float(idx),
            }
            for feature_idx, feature in enumerate(FEATURE_COLS):
                row[feature] = float(idx + feature_idx / 100 + day / 1000)
            rows.append(row)
    return pd.DataFrame(rows)


def test_filter_top_decile_candidates_keeps_daily_ceil_count():
    from backend.tools.m27_top_decile_filter_ab import filter_top_decile_candidates

    predictions = pd.DataFrame({
        "date": ["2026-01-01"] * 10 + ["2026-01-02"] * 11,
        "symbol": [str(i) for i in range(21)],
        "pred": list(range(10)) + list(range(11)),
        "label": list(range(10)) + list(range(11)),
    })

    filtered = filter_top_decile_candidates(predictions, top_pct=0.10)

    assert filtered.groupby("date").size().to_dict() == {
        "2026-01-01": 1,
        "2026-01-02": 2,
    }
    assert filtered["label"].tolist() == [9, 10, 9]


def test_build_candidate_ab_compares_baseline_and_filtered_candidates():
    from backend.tools.m27_top_decile_filter_ab import build_candidate_ab

    rows = []
    for day in range(4):
        for idx in range(10):
            rows.append({
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
                "symbol": f"S{idx}",
                "pred": float(idx),
                "label": float(idx) / 100,
            })
    predictions = pd.DataFrame(rows)

    result = build_candidate_ab(predictions, horizon=2, top_pct=0.10)

    assert result["baseline_entry_candidates"]["candidate_count"] == 40
    assert result["top_decile_filtered_candidates"]["candidate_count"] == 4
    assert result["baseline_entry_candidates"]["mean_forward_return"] == 0.045
    assert result["top_decile_filtered_candidates"]["mean_forward_return"] == 0.09
    assert result["delta_filtered_minus_baseline"]["mean_forward_return"] == 0.045
    assert result["non_overlapping_stride"]["stride"] == 2
    assert result["non_overlapping_stride"]["top_decile_filtered_candidates"]["candidate_count"] == 2


def test_build_report_is_non_promoting_and_production_unchanged(monkeypatch):
    from backend.tools import m27_top_decile_filter_ab as tool

    def fake_fit_predict(train_df, val_df, *, objective, target_label_col, n_estimators):
        assert objective == "top_decile_classifier"
        assert target_label_col == "label_20d"
        assert n_estimators == 5
        return np.arange(len(val_df), dtype=float), {"status": "ok", "best_iteration": 1}

    monkeypatch.setattr(tool, "_fit_predict", fake_fit_predict)
    monkeypatch.setattr(
        tool,
        "build_validation_report",
        lambda predictions, label, sample: {
            "label": label,
            "sample": sample,
            "metrics": {"ic_mean": 0.1, "icir": 0.2},
            "gates": {"pass": False, "pass_monotonic": True},
        },
    )

    report = tool.build_report(
        _panel(),
        panel_meta={"n_rows": 420, "n_symbols": 6, "cache_hit": True, "start": "2026-01-01", "end": "2026-03-11"},
        horizon=20,
        n_estimators=5,
    )
    markdown = tool.report_to_markdown(report)

    assert report["milestone"] == "M27.1c"
    assert report["run_mode"] == "offline_read_only_validation"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["classifier"]["status"] == "ok"
    assert report["classifier_raw_return_validation"]["gates"]["pass"] is False
    assert report["candidate_ab"]["baseline_entry_candidates"]["candidate_count"] > 0
    assert report["candidate_ab"]["top_decile_filtered_candidates"]["candidate_count"] > 0
    assert report["decision"]["decision"] == "production_unchanged"
    assert "M27.1c Top-Decile Filter A/B" in markdown
    assert "non_promoting: True" in markdown
    assert "production_unchanged: True" in markdown
    assert "writes_db: False" in markdown


def test_build_report_handles_fit_failure_without_candidate_ab(monkeypatch):
    from backend.tools import m27_top_decile_filter_ab as tool

    monkeypatch.setattr(
        tool,
        "_fit_predict",
        lambda *args, **kwargs: (None, {"status": "single_class_label"}),
    )

    report = tool.build_report(
        _panel(),
        panel_meta={"n_rows": 420, "n_symbols": 6},
        horizon=20,
        n_estimators=5,
    )

    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["classifier"]["status"] == "single_class_label"
    assert report["classifier_raw_return_validation"] is None
    assert report["candidate_ab"] is None
