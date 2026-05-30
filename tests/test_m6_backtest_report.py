import pandas as pd


def test_build_validation_report_has_decision_gate():
    from backend.backtest.alphalens_qlib import build_validation_report
    from backend.backtest.costs import A_SHARE_ROUND_TRIP_COST

    predictions = pd.DataFrame({
        "date": sum(([f"2026-01-0{d}"] * 5 for d in range(1, 6)), []),
        "symbol": [f"S{i}" for _ in range(5) for i in range(5)],
        "pred": [1, 2, 3, 4, 5] * 5,
        "label": [0.01, 0.02, 0.03, 0.04, 0.05] * 5,
    })

    report = build_validation_report(predictions, label="unit", sample={"n_stocks": 5, "n_rows": 25})

    assert report["label"] == "unit"
    assert report["sample"]["n_stocks"] == 5
    assert report["metrics"]["ic_mean"] > 0.9
    assert report["quantiles"][-1]["net_mean_return"] == round(0.05 - A_SHARE_ROUND_TRIP_COST, 6)
    assert report["equity_curve"]["points"]
    assert report["equity_curve"]["max_drawdown"] == 0.0
    assert report["gates"]["pass_ic"] is True
    assert report["gates"]["ic_floor"] == 0.02
    assert report["recommendation"] == "eligible_for_quant_review"


def test_build_validation_report_accepts_configurable_gate_floor():
    from backend.backtest.alphalens_qlib import build_validation_report

    predictions = pd.DataFrame({
        "date": sum(([f"2026-01-0{d}"] * 5 for d in range(1, 6)), []),
        "symbol": [f"S{i}" for _ in range(5) for i in range(5)],
        "pred": [1, 2, 3, 4, 5] * 5,
        "label": [0.01, 0.02, 0.03, 0.04, 0.05] * 5,
    })

    report = build_validation_report(predictions, ic_floor=1.1)

    assert report["gates"]["pass_ic"] is False
    assert report["gates"]["ic_floor"] == 1.1
    assert report["recommendation"] == "keep_quant_disabled"


def test_build_validation_report_recommendation_ignores_numeric_gate_metadata():
    from backend.backtest.alphalens_qlib import build_validation_report

    predictions = pd.DataFrame({
        "date": sum(([f"2026-01-0{d}"] * 5 for d in range(1, 6)), []),
        "symbol": [f"S{i}" for _ in range(5) for i in range(5)],
        "pred": [1, 2, 3, 4, 5] * 5,
        "label": [0.01, 0.02, 0.03, 0.04, 0.05] * 5,
    })

    report = build_validation_report(
        predictions,
        ic_floor=0.0,
        icir_floor=0.0,
        require_monotonic=True,
    )

    assert report["gates"]["pass"] is True
    assert report["recommendation"] == "eligible_for_quant_review"


def test_build_validation_report_can_disable_monotonic_requirement():
    from backend.backtest.alphalens_qlib import build_validation_report

    predictions = pd.DataFrame({
        "date": sum(([f"2026-01-0{d}"] * 5 for d in range(1, 6)), []),
        "symbol": [f"S{i}" for _ in range(5) for i in range(5)],
        "pred": [1, 2, 3, 4, 5] * 5,
        "label": [0.01, 0.05, 0.03, 0.04, 0.02] * 5,
    })

    report = build_validation_report(
        predictions,
        ic_floor=0.0,
        icir_floor=0.0,
        require_monotonic=False,
    )

    assert report["gates"]["pass_monotonic"] is False
    assert report["gates"]["pass"] is True
    assert report["recommendation"] == "eligible_for_quant_review"


def test_qlib_offline_config_keeps_production_quant_disabled():
    from backend.backtest.alphalens_qlib import data_coverage_report, offline_experiment_config
    from backend.config import settings
    from backend.data.qlib_data import FEATURE_COLS

    rows = []
    for symbol in ["300308", "688008"]:
        for day in ["2026-01-02", "2026-01-03"]:
            row = {"symbol": symbol, "date": pd.Timestamp(day), "label": 0.01}
            row.update({col: 1.0 for col in FEATURE_COLS})
            rows.append(row)
    panel = pd.DataFrame(rows)

    config = offline_experiment_config(panel)
    coverage = data_coverage_report(panel)

    assert config["purpose"] == "qlib_offline_recovery_only"
    assert config["production_quant_weight"] == settings.weight_quant == 0.0
    assert config["promotion_gate"]["ic_floor"] == settings.qlib_train_ic_floor
    assert config["random_seed"] == 42
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["missing_symbol_dates"] == 0
