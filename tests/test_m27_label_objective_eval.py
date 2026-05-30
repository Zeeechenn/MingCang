import numpy as np
import pandas as pd


def _panel(rows_per_symbol=60):
    from backend.data.qlib_data import FEATURE_COLS

    symbols = ["A", "B", "C", "D", "E", "F"]
    rows = []
    for day in range(rows_per_symbol):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(symbols):
            row = {
                "date": date.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "industry": "tech" if idx < 3 else "finance",
                "close": 10 + day * (1 + idx / 20) + idx,
                "log_market_cap": float(idx),
            }
            for feature_idx, feature in enumerate(FEATURE_COLS):
                row.setdefault(feature, float(idx + feature_idx / 100 + day / 1000))
            rows.append(row)
    return pd.DataFrame(rows)


def test_neutralize_by_date_removes_industry_mean():
    from backend.tools.m27_label_objective_eval import add_objective_labels

    out = add_objective_labels(_panel(), 20)
    grouped_mean = out.groupby(["date", "industry"])["label_20d_industry_neutral"].mean().dropna()

    assert grouped_mean.abs().max() < 1e-9


def test_size_neutral_label_has_low_daily_size_correlation():
    from backend.tools.m27_label_objective_eval import add_objective_labels

    out = add_objective_labels(_panel(), 20).dropna(subset=["label_20d_size_neutral"])
    corrs = []
    stds = []
    for _, group in out.groupby("date"):
        if len(group) >= 5:
            stds.append(group["label_20d_size_neutral"].std())
            if group["label_20d_size_neutral"].std() > 1e-12:
                corrs.append(group["label_20d_size_neutral"].corr(group["log_market_cap"]))

    valid_corrs = [abs(corr) for corr in corrs if pd.notna(corr)]
    assert not valid_corrs or max(valid_corrs) < 1e-8
    assert max(stds) < 1e-8


def test_candidate_specs_cover_m27_1b_objectives():
    from backend.tools.m27_label_objective_eval import candidate_specs

    names = {spec["name"] for spec in candidate_specs(20)}

    assert "raw_20d_regression" in names
    assert "industry_size_neutral_20d_regression" in names
    assert "raw_20d_top_decile_classifier" in names
    assert "industry_size_neutral_20d_ranker_lambdarank" in names


def test_stride_predictions_keep_non_overlapping_dates():
    from backend.tools.m27_label_objective_eval import stride_predictions

    predictions = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=10).repeat(2),
        "symbol": ["A", "B"] * 10,
        "pred": range(20),
        "label": range(20),
    })

    out = stride_predictions(predictions, stride=3)

    assert out["date"].nunique() == 4
    assert str(out["date"].min().date()) == "2026-01-01"


def test_top_decile_metrics_report_lift():
    from backend.tools.m27_label_objective_eval import top_decile_metrics

    predictions = pd.DataFrame({
        "date": ["2026-01-01"] * 10 + ["2026-01-02"] * 10,
        "symbol": [str(i) for i in range(20)],
        "pred": list(range(10)) + list(range(10)),
        "label": list(range(10)) + list(range(10)),
    })

    metrics = top_decile_metrics(predictions, top_pct=0.10)

    assert metrics["precision"] == 1.0
    assert metrics["base_rate"] == 0.1
    assert metrics["lift_vs_base_rate"] == 10.0


def test_segment_breakdown_reports_raw_validation_by_industry():
    from backend.tools.m27_label_objective_eval import segment_breakdown

    rows = []
    for day in range(8):
        for idx in range(8):
            industry = "tech" if idx < 4 else "finance"
            label = float(idx) if industry == "tech" else float(8 - idx)
            rows.append({
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
                "symbol": f"{industry}-{idx}",
                "industry": industry,
                "pred": float(idx),
                "label": label,
            })
    predictions = pd.DataFrame(rows)

    breakdown = segment_breakdown(predictions, segment_col="industry", min_rows=10, min_dates=5)

    assert [row["segment"] for row in breakdown] == ["tech", "finance"]
    assert breakdown[0]["n_rows"] == 32
    assert breakdown[0]["n_symbols"] == 4
    assert breakdown[0]["ic_mean"] == 1.0
    assert breakdown[1]["ic_mean"] == -1.0


def test_segment_specific_candidates_are_non_promoting_and_sample_gated(monkeypatch):
    from backend.data.qlib_data import FEATURE_COLS
    from backend.tools import m27_label_objective_eval as tool

    industries = {
        "Communications Equipment": ["CE1", "CE2", "CE3"],
        "Semiconductors": ["SC1", "SC2", "SC3"],
        "Tiny Segment": ["TS1", "TS2"],
    }
    rows = []
    for day in range(80):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for industry, symbols in industries.items():
            for idx, symbol in enumerate(symbols):
                row = {
                    "date": date,
                    "symbol": symbol,
                    "industry": industry,
                    "label_20d": float(day + idx),
                }
                for feature_idx, feature in enumerate(FEATURE_COLS):
                    row[feature] = float(day / 100 + idx + feature_idx / 1000)
                rows.append(row)
    panel = pd.DataFrame(rows)

    seen_segments = []

    def fake_fit_predict(train_df, val_df, *, objective, target_label_col, n_estimators):
        assert objective == "regression"
        assert train_df["industry"].nunique() == 1
        assert val_df["industry"].nunique() == 1
        assert n_estimators == 7
        seen_segments.append(train_df["industry"].iloc[0])
        return np.asarray(val_df[target_label_col]), {"status": "ok", "best_iteration": 1}

    def fake_validation_report(predictions, label, sample):
        if "Semiconductors" in label:
            icir = 1.2
        elif "Communications Equipment" in label:
            icir = 0.8
        else:
            icir = -0.1
        return {
            "label": label,
            "sample": sample,
            "metrics": {"ic_mean": icir / 10, "icir": icir},
            "gates": {"pass": icir > 1.0},
        }

    monkeypatch.setattr(tool, "_fit_predict", fake_fit_predict)
    monkeypatch.setattr(tool, "build_validation_report", fake_validation_report)

    result = tool.evaluate_segment_specific_candidates(
        panel,
        horizon=20,
        n_estimators=7,
        min_rows=100,
        min_symbols=3,
        min_validation_rows=10,
    )

    assert result["non_promoting"] is True
    assert result["promotable"] is False
    assert result["run_mode"] == "exploratory_sample_limited"
    assert result["sample_limited"] is True
    assert "cannot promote" in result["note"]
    assert "expand sample" in result["promotion_blocker"]
    assert [candidate["segment"] for candidate in result["candidates"]] == [
        "Semiconductors",
        "Communications Equipment",
    ]
    assert all(candidate["promotable"] is False for candidate in result["candidates"])
    assert all(candidate["sample_limited"] is True for candidate in result["candidates"])
    assert {candidate["segment"] for candidate in result["candidates"]} == set(seen_segments)
    assert result["candidates"][0]["sample"]["n_rows"] == 240
    assert result["candidates"][0]["sample"]["n_symbols"] == 3
    assert result["best_by_segment_col"]["industry"]["segment"] == "Semiconductors"
    assert result["skipped"][0]["segment"] == "Tiny Segment"
    assert result["skipped"][0]["status"] == "insufficient_segment_sample"


def test_top_decile_labels_use_ceil_count_per_date():
    from backend.tools.m27_label_objective_eval import TOP_DECILE_PCT, _top_decile_labels

    rows = []
    for date, count in [("2026-01-01", 10), ("2026-01-02", 11), ("2026-01-03", 5)]:
        for value in range(count):
            rows.append({"date": date, "symbol": f"{date}-{value}", "label": value})
    data = pd.DataFrame(rows)

    labels = _top_decile_labels(data, "label", top_pct=TOP_DECILE_PCT)
    actual = labels.groupby(data["date"]).sum().astype(int).to_dict()
    expected = {
        date: max(1, int(np.ceil(count * TOP_DECILE_PCT)))
        for date, count in data.groupby("date").size().items()
    }

    assert actual == expected
    assert data.loc[(data["date"] == "2026-01-01") & labels.eq(1), "label"].tolist() == [9]


def test_evaluate_candidate_passes_shared_top_decile_pct_to_metrics(monkeypatch):
    from backend.tools import m27_label_objective_eval as tool

    panel = tool.add_objective_labels(_panel(rows_per_symbol=110), 20)
    spec = next(
        candidate for candidate in tool.candidate_specs(20)
        if candidate["name"] == "raw_20d_top_decile_classifier"
    )
    captured = {}

    def fake_fit_predict(train_df, val_df, *, objective, target_label_col, n_estimators):
        assert objective == "top_decile_classifier"
        labels = tool._top_decile_labels(train_df, target_label_col)
        actual = labels.groupby(train_df["date"]).sum().astype(int).to_dict()
        expected = {
            date: max(1, int(np.ceil(count * tool.TOP_DECILE_PCT)))
            for date, count in train_df.groupby("date").size().items()
        }
        assert actual == expected
        return np.arange(len(val_df)), {"status": "ok", "best_iteration": 1}

    def fake_top_decile_metrics(predictions, *, top_pct):
        captured["top_pct"] = top_pct
        return {"top_pct": top_pct}

    monkeypatch.setattr(tool, "_fit_predict", fake_fit_predict)
    monkeypatch.setattr(tool, "top_decile_metrics", fake_top_decile_metrics)
    monkeypatch.setattr(
        tool,
        "build_validation_report",
        lambda predictions, label, sample: {"label": label, "metrics": {}, "gates": {}},
    )

    result = tool.evaluate_candidate(panel, spec, n_estimators=5)

    assert result["status"] == "ok"
    assert captured["top_pct"] == tool.TOP_DECILE_PCT
    assert result["top_decile_metrics"]["top_pct"] == tool.TOP_DECILE_PCT
    assert "industry" in result["segment_breakdown"]
    assert {row["segment"] for row in result["segment_breakdown"]["industry"]} == {"finance", "tech"}


def test_panel_cache_rebuilds_when_feature_metadata_changes(monkeypatch, tmp_path):
    from backend.tools import m27_label_objective_eval as tool

    monkeypatch.setattr(tool, "DEFAULT_CACHE_DIR", tmp_path)
    cache_path, meta_path = tool._cache_paths(active_only=True, min_rows=11)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": ["2026-01-01"], "symbol": ["STALE"]}).to_pickle(cache_path)
    meta_path.write_text(
        '{"feature_count": 1, "feature_cols_hash": "stale", "feature_cols": ["old_feature"]}',
        encoding="utf-8",
    )

    calls = {"count": 0}
    fresh_panel = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["FRESH"]})

    def fake_build_training_data(db, *, min_rows, include_inactive):
        assert min_rows == 11
        assert include_inactive is False
        calls["count"] += 1
        return fresh_panel

    monkeypatch.setattr(tool, "build_training_data", fake_build_training_data)

    panel, meta = tool.load_or_build_panel(object(), active_only=True, min_rows=11)
    cached_panel, cached_meta = tool.load_or_build_panel(object(), active_only=True, min_rows=11)

    assert calls["count"] == 1
    assert meta["cache_hit"] is False
    assert meta["feature_cols"] == list(tool.FEATURE_COLS)
    assert cached_meta["cache_hit"] is True
    pd.testing.assert_frame_equal(panel, fresh_panel)
    pd.testing.assert_frame_equal(cached_panel, fresh_panel)


def test_build_report_uses_non_promoting_fit_path(monkeypatch):
    from backend.tools import m27_label_objective_eval as tool

    panel = _panel(rows_per_symbol=70)

    def fake_fit_predict(train_df, val_df, *, objective, target_label_col, n_estimators):
        assert objective in {"regression", "top_decile_classifier", "ranker_lambdarank"}
        assert n_estimators == 5
        return np.asarray(val_df[target_label_col]), {"status": "ok", "best_iteration": 1}

    monkeypatch.setattr(tool, "_fit_predict", fake_fit_predict)

    report = tool.build_report(
        panel,
        panel_meta={"n_rows": len(panel), "n_symbols": 6, "cache_hit": False, "start": "2026-01-01", "end": "2026-03-11"},
        horizon=20,
        n_estimators=5,
    )
    markdown = tool.report_to_markdown(report)

    assert report["purpose"].startswith("M27.1b")
    assert len(report["candidates"]) == 9
    assert all(candidate["status"] == "ok" for candidate in report["candidates"])
    assert "raw_return_stride_validation" in report["candidates"][0]
    assert "top_decile_metrics" in report["candidates"][0]
    assert "segment_breakdown" in report["candidates"][0]
    assert report["sector_industry_specific_candidates"]["non_promoting"] is True
    assert report["sector_industry_specific_candidates"]["promotable"] is False
    assert report["sector_industry_specific_candidates"]["min_validation_rows"] == 50
    assert "M27.1b Label/Objective Evaluation" in markdown
    assert "Sector/Industry-Specific Offline Candidates" in markdown
    assert "non_promoting: True" in markdown
    assert "promotable: False" in markdown
    assert "sample_limited: False" in markdown
    assert "Best Raw Candidate Segment Breakdown" in markdown


def test_build_report_propagates_segment_validation_floor(monkeypatch):
    from backend.tools import m27_label_objective_eval as tool

    panel = _panel(rows_per_symbol=70)
    captured = {}

    monkeypatch.setattr(
        tool,
        "evaluate_candidate",
        lambda panel, spec, *, n_estimators: {
            **spec,
            "status": "ok",
            "raw_return_validation": {"metrics": {"icir": 0.0}, "gates": {"pass": False}},
            "target_validation": {"gates": {"pass": False}},
            "top_decile_metrics": {},
        },
    )

    def fake_segment_candidates(panel, *, horizon, n_estimators, min_rows, min_symbols, min_validation_rows):
        captured.update({
            "horizon": horizon,
            "n_estimators": n_estimators,
            "min_rows": min_rows,
            "min_symbols": min_symbols,
            "min_validation_rows": min_validation_rows,
        })
        return {
            "non_promoting": True,
            "promotable": False,
            "run_mode": "exploratory_sample_limited",
            "sample_limited": True,
            "promotion_blocker": "exploratory/sample-limited segment run; expand sample before promotion",
            "note": "exploratory/sample-limited offline validation only; cannot promote",
            "min_rows": min_rows,
            "min_symbols": min_symbols,
            "min_validation_rows": min_validation_rows,
            "candidates": [],
        }

    monkeypatch.setattr(tool, "evaluate_segment_specific_candidates", fake_segment_candidates)

    report = tool.build_report(
        panel,
        panel_meta={"n_rows": len(panel), "n_symbols": 6},
        horizon=20,
        n_estimators=9,
        segment_min_rows=80,
        segment_min_symbols=3,
        segment_min_validation_rows=12,
    )
    markdown = tool.report_to_markdown(report)

    assert captured == {
        "horizon": 20,
        "n_estimators": 9,
        "min_rows": 80,
        "min_symbols": 3,
        "min_validation_rows": 12,
    }
    assert report["sector_industry_specific_candidates"]["min_validation_rows"] == 12
    assert "12 validation rows" in markdown
    assert "run_mode: exploratory_sample_limited" in markdown
    assert "cannot promote" in markdown


def test_parse_args_exposes_segment_sample_floors(monkeypatch):
    from backend.tools import m27_label_objective_eval as tool

    monkeypatch.setattr(
        "sys.argv",
        [
            "m27_label_objective_eval",
            "--segment-min-symbols",
            "3",
            "--segment-min-rows",
            "120",
            "--segment-min-validation-rows",
            "15",
        ],
    )

    args = tool.parse_args()

    assert args.segment_min_symbols == 3
    assert args.segment_min_rows == 120
    assert args.segment_min_validation_rows == 15
