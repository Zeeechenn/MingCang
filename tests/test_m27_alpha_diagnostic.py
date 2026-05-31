import json

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


def test_event_ab_uses_offline_title_polarity_fallback():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    news_rows = []
    for day in range(5):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
            title = "公司公告获得重大合同并中标算力项目" if idx < 3 else "公司公告监管处罚并收到警示函"
            news_rows.append({
                "symbol": symbol,
                "title": title,
                "published_at": date,
                "sentiment_score": None,
            })

    report = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols={"A", "B", "C", "D", "E", "F"},
        label_col="label_3d",
    )

    assert report["status"] == "ok"
    assert report["blockers"] == []
    assert report["coverage"]["rows_with_news"] > 0
    assert report["coverage"]["rows_with_polarity"] > 0
    assert report["coverage"]["rows_with_fallback_polarity"] > 0
    assert report["coverage"]["rows_with_persisted_polarity"] == 0
    assert report["coverage"]["rows_with_cache_polarity"] == 0
    assert report["coverage"]["cache_miss_windows"] == report["coverage"]["rows_with_news"]
    assert report["coverage"]["polarity_sources"] == {"offline_title_lexicon_fallback": report["coverage"]["rows_with_polarity"]}
    assert report["coverage"]["rows_with_event_override"] > 0
    assert report["polarity"]["ic_days"] > 0
    assert report["polarity_event"]["ic_days"] > 0
    assert "cache_miss_windows_open" in report["pure_polarity_validation"]["gate_blockers"]
    assert "fallback_polarity_used" in report["pure_polarity_validation"]["gate_blockers"]
    assert report["delta_ic"] is not None


def test_event_ab_prefers_persisted_news_sentiment_score():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    news_rows = []
    for day in range(5):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
            news_rows.append({
                "symbol": symbol,
                "title": "公司普通经营动态",
                "published_at": date,
                "sentiment_score": 40 if idx < 3 else -40,
            })

    report = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols={"A", "B", "C", "D", "E", "F"},
        label_col="label_3d",
    )

    assert report["status"] == "ok"
    assert report["coverage"]["rows_with_persisted_polarity"] == report["coverage"]["rows_with_polarity"]
    assert report["coverage"]["rows_with_cache_polarity"] == 0
    assert report["coverage"]["rows_with_fallback_polarity"] == 0
    assert report["coverage"]["cache_miss_windows"] == 0
    assert report["coverage"]["polarity_sources"] == {"persisted_news_sentiment_score": report["coverage"]["rows_with_polarity"]}
    assert report["polarity"]["ic_days"] > 0


def test_event_ab_uses_sentiment_cache_before_title_fallback():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    news_rows = []
    for day in range(5):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
            title = "公司公告获得重大合同并中标算力项目" if idx < 3 else "公司公告监管处罚并收到警示函"
            news_rows.append({
                "symbol": symbol,
                "title": title,
                "published_at": date,
                "sentiment_score": None,
            })

    report = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols={"A", "B", "C", "D", "E", "F"},
        label_col="label_3d",
        sentiment_cache_lookup=lambda titles, symbol: {"sentiment": 0.7 if symbol in {"A", "B", "C"} else -0.7},
    )

    assert report["status"] == "ok"
    assert report["coverage"]["rows_with_cache_polarity"] == report["coverage"]["rows_with_polarity"]
    assert report["coverage"]["rows_with_fallback_polarity"] == 0
    assert report["coverage"]["cache_miss_windows"] == 0
    assert report["coverage"]["polarity_sources"] == {"sentiment_cache_exact_match": report["coverage"]["rows_with_polarity"]}
    assert report["polarity"]["ic_days"] > 0
    validation = report["pure_polarity_validation"]
    assert validation["orientation"] == "positive"
    assert validation["data_quality_blockers"] == []
    assert validation["passes_event_ab_gate"] is False
    assert "insufficient_ic_days" in validation["gate_blockers"]
    assert "variant_comparison" in report
    assert report["variant_comparison"]["production_unchanged"] is True


def test_event_ab_writes_exact_cache_miss_title_windows(tmp_path):
    from backend.analysis.sentiment import _cache_key
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    output_path = tmp_path / "cache_missing.json"
    news_rows = [
        {
            "symbol": "A",
            "title": "公司公告获得重大合同并中标算力项目",
            "published_at": pd.Timestamp("2026-01-01"),
            "sentiment_score": None,
        },
        {
            "symbol": "A",
            "title": "公司公告员工持股计划",
            "published_at": pd.Timestamp("2026-01-02"),
            "sentiment_score": None,
        },
    ]

    report = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols={"A"},
        label_col="label_3d",
        min_names=1,
        cache_missing_output=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    first_window_titles = ["公司公告获得重大合同并中标算力项目"]
    cache_key, titles_hash = _cache_key(first_window_titles, "A")

    assert report["coverage"]["cache_miss_windows"] == payload["cache_miss_windows"]
    assert report["cache_miss_output"] == {"path": str(output_path), "windows": payload["cache_miss_windows"]}
    assert payload["cache_miss_windows"] > 0
    assert payload["windows"][0] == {
        "symbol": "A",
        "date": "2026-01-01",
        "titles": first_window_titles,
        "cache_key": cache_key,
        "titles_hash": titles_hash,
        "news_count": 1,
        "fallback_source": "offline_title_lexicon_fallback",
        "polarity_source": "offline_title_lexicon_fallback",
        "event_score_mode": "event_override",
    }


def test_event_ab_prefers_persisted_news_score_over_sentiment_cache():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    news_rows = []
    for day in range(5):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for idx, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
            news_rows.append({
                "symbol": symbol,
                "title": "公司公告获得重大合同并中标算力项目",
                "published_at": date,
                "sentiment_score": 40 if idx < 3 else -40,
            })

    report = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols={"A", "B", "C", "D", "E", "F"},
        label_col="label_3d",
        sentiment_cache_lookup=lambda titles, symbol: {"sentiment": -0.9},
    )

    assert report["status"] == "ok"
    assert report["coverage"]["rows_with_persisted_polarity"] == report["coverage"]["rows_with_polarity"]
    assert report["coverage"]["rows_with_cache_polarity"] == 0
    assert report["coverage"]["rows_with_fallback_polarity"] == 0
    assert report["coverage"]["cache_miss_windows"] == 0
    assert report["coverage"]["polarity_sources"] == {"persisted_news_sentiment_score": report["coverage"]["rows_with_polarity"]}


def test_event_ab_handles_missing_news_rows():
    from backend.tools.m27_alpha_diagnostic import add_horizon_labels, event_ab_diagnostics

    panel = add_horizon_labels(_sample_panel(), [3])
    report = event_ab_diagnostics(
        panel,
        [],
        universe_symbols={"A", "B", "C", "D", "E", "F"},
        label_col="label_3d",
    )

    assert report["status"] == "blocked"
    assert report["coverage"]["rows_with_news"] == 0
    assert report["coverage"]["cache_miss_windows"] == 0
    assert "no_test3_news_rows" in report["blockers"]
    assert report["polarity"]["ic_days"] == 0
    assert report["polarity_event"]["ic_days"] == 0


def test_event_ab_variant_gate_is_rendered_in_markdown():
    from backend.tools.m27_alpha_diagnostic import (
        add_horizon_labels,
        build_report,
        event_ab_diagnostics,
        report_to_markdown,
    )

    panel = add_horizon_labels(_sample_panel(), [3])
    scores = {"A": 0.9, "B": 0.6, "C": 0.3, "D": -0.3, "E": -0.6, "F": -0.9}
    news_rows = []
    for day in range(5):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for symbol in ["A", "B", "C", "D", "E", "F"]:
            news_rows.append({
                "symbol": symbol,
                "title": "公司普通经营动态",
                "published_at": date,
                "sentiment_score": None,
            })

    event_ab = event_ab_diagnostics(
        panel,
        news_rows,
        universe_symbols=set(scores),
        label_col="label_3d",
        sentiment_cache_lookup=lambda titles, symbol: {"sentiment": scores[symbol]},
    )
    report = build_report(panel, horizons=[3], top_n=3, event_ab=event_ab)
    markdown = report_to_markdown(report)

    assert event_ab["event_ab_gate"]["min_quantile_buckets"] == 5
    assert event_ab["event_ab_gate"]["n_variants_tested"] == 2
    assert "multiple_comparison_warning" in event_ab["event_ab_gate"]
    assert event_ab["pure_polarity_validation"]["passes_quantile_sample"] is True
    assert "top-bottom" in markdown
    assert "monotonic" in markdown
    assert "multiple_comparison_warning" in markdown
    assert "pure_polarity" in markdown
    assert "polarity_plus_event" in markdown
    assert "gate_blockers" in markdown
