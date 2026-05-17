import pandas as pd


def test_daily_rank_groups_follow_training_dates():
    from backend.analysis.qlib_engine import daily_rank_groups

    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-03", "2026-01-03"],
        "label": [0.01, 0.02, -0.01, 0.03, 0.01, -0.02],
    })

    groups = daily_rank_groups(df)

    assert groups == [2, 1, 3]


def test_make_rank_labels_are_cross_sectional_per_date():
    from backend.analysis.qlib_engine import make_rank_labels

    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-02"],
        "label": [0.02, -0.01, 0.01, 0.05],
    })

    labels = make_rank_labels(df)

    assert labels.tolist() == [2, 0, 1, 0]
