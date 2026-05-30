import pandas as pd


def _sample_panel():
    rows = []
    for day in range(8):
        for idx, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
            strength = idx - 2.5
            close = 10 + day + idx * 0.1
            rows.append({
                "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)).strftime("%Y-%m-%d"),
                "symbol": symbol,
                "industry": "tech" if idx < 3 else "finance",
                "close": close,
                "mom_5": strength,
                "mom_20": strength,
                "volatility_20": idx / 10,
                "rev_mom_12_1_z": -strength,
            })
    return pd.DataFrame(rows)


def test_safe_spearman_handles_constant_input():
    from backend.tools.m27_alpha_diagnostic import _safe_spearman

    assert _safe_spearman(pd.Series([1, 1, 1]), pd.Series([1, 2, 3])) is None
    assert _safe_spearman(pd.Series([1, 2, 3]), pd.Series([3, 2, 1])) == -1.0


def test_horizon_labels_are_symbol_local_forward_returns():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels

    panel = _sample_panel()
    out = add_horizon_labels(panel, [3])
    first_a = out[(out["symbol"] == "A") & (out["date"] == pd.Timestamp("2026-01-01"))].iloc[0]

    assert round(first_a["label_3d"], 6) == round((13 / 10) - 1, 6)
    assert out[out["symbol"] == "A"]["label_3d"].isna().tail(3).all()


def test_single_factor_diagnostics_orients_negative_factor():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, single_factor_diagnostics

    panel = _sample_panel()
    panel = add_horizon_labels(panel, [3])
    table = single_factor_diagnostics(panel, ["mom_5", "rev_mom_12_1_z"], "label_3d")
    by_feature = {row["feature"]: row for row in table}

    assert by_feature["mom_5"]["orientation"] == "negative"
    assert by_feature["rev_mom_12_1_z"]["orientation"] == "positive"
    assert by_feature["mom_5"]["ic_days"] > 0


def test_ranker_label_distribution_reports_group_pressure():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, ranker_label_distribution

    panel = add_horizon_labels(_sample_panel(), [3])
    report = ranker_label_distribution(panel, "label_3d")

    assert report["n_dates"] == 5
    assert report["max_daily_group"] == 6
    assert report["max_label"] == 5
    assert report["label_gain_required"] == 6


def test_markdown_report_contains_diagnosis_sections():
    from backend.tools.m27_alpha_diagnostic import build_report, report_to_markdown

    panel = _sample_panel()
    report = build_report(panel, horizons=[3], top_n=3)
    markdown = report_to_markdown(report)

    assert "M27.1 Alpha Diagnostic Report" in markdown
    assert "Top 5d Single Factors" in markdown
    assert "Ranker Label Distribution" in markdown
