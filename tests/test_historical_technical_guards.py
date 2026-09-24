from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_test_support import load_historical_technical

baseline = load_historical_technical()


class TechnicalBaselineV3Tests(unittest.TestCase):
    def test_top_decile_selection_does_not_replace_missing_future_label(self) -> None:
        scored_at_decision = [
            {"symbol": "000001", "technical_score": 10.0},
            {"symbol": "000002", "technical_score": 9.0},
            {"symbol": "000003", "technical_score": 8.0},
            {"symbol": "000004", "technical_score": 7.0},
            *[
                {"symbol": f"{symbol:06d}", "technical_score": 4.0 - symbol / 100.0}
                for symbol in range(5, 21)
            ],
        ]
        selected = baseline._freeze_top_decile(scored_at_decision)
        # A future-label table omits the second selected name. Selection remains fixed.
        labeled = {"000001": 0.01, "000003": 0.99, "000004": 0.50}
        selected_with_labels = [symbol for symbol in selected if symbol in labeled]
        self.assertEqual(selected, ["000001", "000002"])
        self.assertEqual(selected_with_labels, ["000001"])
        self.assertNotIn("000003", selected_with_labels)

    def test_invalid_ohlcv_is_retained_as_explicit_failure(self) -> None:
        valid = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100.0}
        self.assertIsNone(baseline._validate_bar(valid))
        cases = [
            ({**valid, "open": float("nan")}, "nonfinite_ohlcv"),
            ({**valid, "close": 0.0}, "nonpositive_ohlc"),
            ({**valid, "high": 10.0}, "invalid_high"),
            ({**valid, "low": 10.2}, "invalid_low"),
            ({**valid, "volume": -1.0}, "negative_volume"),
            ({**valid, "volume": None}, "missing_ohlcv"),
        ]
        for bar, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(baseline._validate_bar(bar), reason)

    def test_receipt_mutation_is_rejected_before_reading_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = "20260817"
            data = {
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "vol",
                    ],
                    "items": [["000001.SZ", day, 10.0, 11.0, 9.0, 10.5, 10.0, 100.0]],
                },
            }
            data_path = root / f"{day}.json"
            receipt_path = root / f"{day}.receipt.json"
            data_path.write_text(json.dumps(data), encoding="utf-8")
            receipt_path.write_text(json.dumps({"api_code": 0, "rows": 1}), encoding="utf-8")
            protocol = {
                "source": {
                    "days": [day],
                    "daily_receipts": {
                        day: {
                            "sha256": baseline.sha256(data_path),
                            "receipt_sha256": baseline.sha256(receipt_path),
                            "data_path": str(data_path),
                            "receipt_path": str(receipt_path),
                            "rows": 1,
                        },
                    },
                },
            }
            baseline._load_rows(root, protocol)
            receipt_path.write_text(json.dumps({"api_code": 0, "rows": 2}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen source file changed"):
                baseline._load_rows(root, protocol)


if __name__ == "__main__":
    unittest.main()
