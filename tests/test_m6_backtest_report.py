import pandas as pd


def test_build_validation_report_has_decision_gate():
    from backend.backtest.alphalens_qlib import build_validation_report

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
    assert report["gates"]["pass_ic"] is True
    assert report["recommendation"] == "eligible_for_quant_review"
