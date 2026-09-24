from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_test_support import load_historical_technical

baseline = load_historical_technical()


def _bar(day: str, close: float, code: str = "000001.SZ") -> dict:
    return {
        "symbol": "000001",
        "ts_code": code,
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "pre_close": close,
        "volume": 100.0,
        "invalid_reason": None,
    }


class FactorModeTests(unittest.TestCase):
    def test_calculate_uses_adjusted_split_label_and_keeps_selected_missing_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = []
            cursor = date(2026, 5, 4)
            while len(days) < 66:
                if cursor.weekday() < 5:
                    days.append(cursor.strftime("%Y%m%d"))
                cursor += timedelta(days=1)
            decision = days[60]
            symbols = [f"{value:06d}" for value in range(1, 26)]
            codes = {symbol: f"{symbol}.SZ" for symbol in symbols}
            by_day = {}
            for index, day in enumerate(days):
                day_rows = {}
                for symbol in symbols:
                    if symbol == "000002" and index == 63:
                        continue
                    close = 50.0 if symbol == "000001" and index >= 62 else 100.0
                    previous_close = 50.0 if symbol == "000001" and index >= 62 else 100.0
                    day_rows[symbol] = {
                        "symbol": symbol,
                        "ts_code": codes[symbol],
                        "date": day,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "pre_close": previous_close if index > 0 else close,
                        "volume": 1000.0,
                        "invalid_reason": None,
                    }
                by_day[day] = day_rows

            factor_root = root / "factor-source"
            factor_root.mkdir()
            (factor_root / "scope.json").write_text(
                json.dumps(
                    {
                        "provider": "Tushare",
                        "api": "adj_factor",
                        "days": days,
                        "source_fallback": False,
                        "automatic_retries": 0,
                    }
                ),
                encoding="utf-8",
            )
            for index, day in enumerate(days):
                items = [
                    [codes[symbol], day, 2.0 if symbol == "000001" and index >= 62 else 1.0]
                    for symbol in symbols
                ]
                payload = {
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date", "adj_factor"],
                        "items": items,
                    },
                }
                data_path = factor_root / f"{day}.json"
                data_path.write_text(json.dumps(payload), encoding="utf-8")
                receipt = {
                    "api_code": 0,
                    "rows": len(items),
                    "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
                }
                (factor_root / f"{day}.receipt.json").write_text(
                    json.dumps(receipt), encoding="utf-8"
                )
            factor_map, factor_manifest = baseline._load_factor_source(factor_root, days)
            fixed_path = root / "fixed25.json"
            fixed_path.write_text(
                json.dumps(
                    {"stocks": [{"symbol": symbol, "sector": "test"} for symbol in symbols]}
                ),
                encoding="utf-8",
            )
            industry_path = root / "industries.json"
            industry_path.write_text(
                json.dumps(
                    {
                        "data": {
                            "fields": ["ts_code", "industry"],
                            "items": [[codes[symbol], "test"] for symbol in symbols],
                        }
                    }
                ),
                encoding="utf-8",
            )
            out_dir = root / "results"
            out_dir.mkdir()
            protocol = {
                "source": {
                    "factor_source": factor_manifest,
                    "daily_receipts": {day: {"sha256": f"raw-{day}"} for day in days},
                },
                "decisions": [decision],
            }
            (out_dir / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")

            with (
                patch.object(baseline, "_load_rows", return_value=(days, by_day)),
                patch.object(
                    baseline,
                    "_load_technical_score",
                    side_effect=lambda symbol, window: (26 - int(symbol), None),
                ),
            ):
                report = baseline.calculate(
                    root, out_dir, fixed_path, industry_path, protocol, factor_root
                )

            selections = json.loads((out_dir / "selection-manifest.json").read_text())
            selected = selections["by_universe_and_decision"]["all_market_observed"][decision]
            self.assertEqual(selected, ["000001", "000002", "000003"])
            h3 = report["direction_statistics"]["all_market_observed"]["h3"]["daily"][0]
            self.assertEqual(h3["selected_top_decile_candidates_frozen_pre_label"], 3)
            self.assertEqual(h3["selected_top_decile_excluded_labels_no_replacement"], 1)
            self.assertEqual(h3["selected_top_decile_valid_labels"], 2)
            # The split symbol's -50% raw-price move becomes 0% after factors.
            self.assertEqual(
                h3["selected_top_decile_mean_return_pct_conditional_on_valid_label"], 0.0
            )
            exclusions = report["label_denominators_by_decision"]["all_market_observed"][decision][
                "h3"
            ]
            self.assertEqual(exclusions["missing_bar_in_horizon"], 1)

    def test_decision_features_ignore_future_factor_perturbation_and_split_is_flat(self) -> None:
        rows = [_bar("20260817", 100.0), _bar("20260818", 50.0)]
        first = {
            ("000001.SZ", "20260817"): 1.0,
            ("000001.SZ", "20260818"): 2.0,
            ("000001.SZ", "20260819"): 3.0,
        }
        perturbed_future = {**first, ("000001.SZ", "20260819"): 9876.0}
        normalized = baseline._factor_adjusted_window(rows, first)
        perturbed = baseline._factor_adjusted_window(rows, perturbed_future)
        self.assertEqual([r["close"] for r in normalized], [r["close"] for r in perturbed])
        self.assertAlmostEqual(normalized[0]["close"], normalized[1]["close"])
        adjusted_label = (rows[-1]["close"] * first[("000001.SZ", "20260818")]) / (
            rows[0]["close"] * first[("000001.SZ", "20260817")]
        ) - 1.0
        self.assertAlmostEqual(adjusted_label, 0.0)
        self.assertAlmostEqual(rows[-1]["close"] / rows[0]["close"] - 1.0, -0.5)

    def test_missing_factor_excludes_symbol_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing factor"):
            baseline._factor_adjusted_window(
                [_bar("20260817", 10.0), _bar("20260818", 11.0)], {("000001.SZ", "20260817"): 1.0}
            )

    def test_invalid_raw_ohlcv_is_rejected_before_factor_helper(self) -> None:
        bad = _bar("20260817", 10.0)
        bad["volume"] = -1.0
        with self.assertRaisesRegex(ValueError, "invalid raw OHLCV"):
            baseline._factor_adjusted_window([bad], {("000001.SZ", "20260817"): 1.0})

    def test_factor_data_mutation_without_receipt_refresh_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scope.json").write_text(
                json.dumps(
                    {
                        "provider": "tushare",
                        "api": "adj_factor",
                        "days": ["20260817"],
                        "source_fallback": False,
                        "automatic_retries": 0,
                    }
                )
            )
            payload = {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "adj_factor"],
                    "items": [["000001.SZ", "20260817", 1.0]],
                },
            }
            data = root / "20260817.json"
            data.write_text(json.dumps(payload))
            (root / "20260817.receipt.json").write_text(
                json.dumps({"api_code": 0, "rows": 1, "sha256": baseline.sha256(data)})
            )
            data.write_text(
                json.dumps(
                    {
                        **payload,
                        "data": {**payload["data"], "items": [["000001.SZ", "20260817", 2.0]]},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "receipt hash mismatch"):
                baseline._load_factor_source(root, ["20260817"])

    def test_duplicate_full_factor_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scope.json").write_text(
                json.dumps(
                    {
                        "provider": "tushare",
                        "api": "adj_factor",
                        "days": ["20260817"],
                        "source_fallback": False,
                        "automatic_retries": 0,
                    }
                )
            )
            payload = {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "adj_factor"],
                    "items": [["000001.SZ", "20260817", 1.0], ["000001.SZ", "20260817", 1.0]],
                },
            }
            data = root / "20260817.json"
            data.write_text(json.dumps(payload))
            (root / "20260817.receipt.json").write_text(
                json.dumps({"api_code": 0, "rows": 2, "sha256": baseline.sha256(data)})
            )
            with self.assertRaisesRegex(ValueError, "duplicate full factor key"):
                baseline._load_factor_source(root, ["20260817"])

    def test_factor_scope_dates_must_exactly_match_market_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scope.json").write_text(
                json.dumps(
                    {
                        "provider": "tushare",
                        "api": "adj_factor",
                        "days": ["20260817", "20260818"],
                        "source_fallback": False,
                        "automatic_retries": 0,
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "exactly match"):
                baseline._load_factor_source(root, ["20260817"])


if __name__ == "__main__":
    unittest.main()
