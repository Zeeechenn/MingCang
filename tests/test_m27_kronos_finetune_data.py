import pickle

import pandas as pd


def _price_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        index=idx,
    )


def test_m27_kronos_windows_respect_context_pred_len_and_split_dates():
    from backend.tools.m27_kronos_finetune_data import build_windows_for_symbol

    windows = build_windows_for_symbol(
        "300001",
        _price_frame([1, 2, 3, 4, 5, 6, 7, 8]),
        split="train",
        split_start="2020-01-03",
        split_end="2020-01-07",
        context=3,
        pred_len=2,
    )

    assert len(windows) == 3
    assert windows[0].context_start == "2020-01-01"
    assert windows[0].anchor_date == "2020-01-03"
    assert windows[0].label_end == "2020-01-05"
    assert round(windows[0].forward_return, 6) == round(5 / 3 - 1, 6)
    assert windows[-1].label_end == "2020-01-07"


def test_m27_kronos_coverage_fails_loudly_on_missing_or_incomplete_data():
    from backend.tools.m27_kronos_finetune_data import build_coverage_report

    windows = pd.DataFrame(
        [
            {
                "split": "train",
                "symbol": "300001",
                "forward_return": 0.01,
            }
        ]
    )
    report = build_coverage_report(
        requested_symbols=["300001", "300002"],
        panels={"300001": _price_frame([1, 2, 3, 4])},
        per_symbol={
            "300001": {
                "bars": 4,
                "first_date": "2020-01-01",
                "last_date": "2020-01-04",
                "train_windows": 1,
                "valid_windows": 0,
                "status": "insufficient_split_windows",
            }
        },
        windows=windows,
        min_symbols=2,
        context=3,
        pred_len=1,
        train_start="2020-01-01",
        train_end="2020-01-03",
        valid_start="2020-01-04",
        valid_end="2020-01-04",
        allow_partial=False,
    )

    assert report["passed"] is False
    assert report["missing_symbols"] == ["300002"]
    assert any("complete_symbols" in failure for failure in report["hard_failures"])


def test_m27_kronos_write_outputs_slices_train_and_valid_panels(tmp_path):
    from backend.tools.m27_kronos_finetune_data import write_outputs

    panels = {"300001": _price_frame([1, 2, 3, 4, 5, 6, 7, 8])}
    windows = pd.DataFrame(
        [
            {
                "split": "train",
                "symbol": "300001",
                "context_start": "2020-01-01",
                "label_end": "2020-01-05",
            },
            {
                "split": "valid",
                "symbol": "300001",
                "context_start": "2020-01-04",
                "label_end": "2020-01-08",
            },
        ]
    )

    write_outputs(tmp_path, panels, windows, {"passed": True})

    with (tmp_path / "train_data.pkl").open("rb") as fh:
        train_data = pickle.load(fh)
    with (tmp_path / "valid_data.pkl").open("rb") as fh:
        valid_data = pickle.load(fh)

    assert train_data["300001"].index.min().strftime("%Y-%m-%d") == "2020-01-01"
    assert train_data["300001"].index.max().strftime("%Y-%m-%d") == "2020-01-05"
    assert valid_data["300001"].index.min().strftime("%Y-%m-%d") == "2020-01-04"
    assert valid_data["300001"].index.max().strftime("%Y-%m-%d") == "2020-01-08"


def test_m27_kronos_cli_defaults_match_roadmap():
    from backend.tools.m27_kronos_finetune_data import parse_args

    args = parse_args([])

    assert args.context == 400
    assert args.pred_len == 5
    assert args.train_start == "2020-01-01"
    assert args.train_end == "2024-12-31"
    assert args.valid_start == "2025-01-01"
    assert args.valid_end == "2025-10-31"
    assert args.min_symbols == 707
