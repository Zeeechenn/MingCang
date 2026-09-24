"""Offline contract tests for prepare.py; every file write stays in temp dirs."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("universe_prepare", HERE / "prepare.py")
prepare_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(prepare_module)
fixture_module_spec = importlib.util.spec_from_file_location("make_fixture", HERE / "make_fixture.py")
fixture_module = importlib.util.module_from_spec(fixture_module_spec)
assert fixture_module_spec.loader is not None
fixture_module_spec.loader.exec_module(fixture_module)


def load_repo_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def fresh_fixture():
    return fixture_module.build_fixture()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrepareInputTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fresh_fixture()
        self.baseline = load_repo_json("baseline-universe.json")
        self.policy = load_repo_json("protocol.json")

    def call_prepare(self, snapshot=None, baseline=None, policy=None):
        return prepare_module.prepare(snapshot or self.snapshot,
                                      baseline or self.baseline,
                                      policy or self.policy)

    def test_fixture_has_125_explicitly_synthetic_rows_and_exact_baseline(self):
        fixed = {s["symbol"] for s in self.baseline["stocks"]}
        expected = set(self.snapshot["expected_symbols"])
        self.assertEqual(len(self.snapshot["rows"]), 125)
        self.assertEqual(len(fixed), 25)
        self.assertTrue(fixed <= expected)
        self.assertEqual(self.snapshot["session"], "2026-09-24")
        self.assertEqual(self.snapshot["kind"], "synthetic")
        self.assertTrue(all(r["source"] == "synthetic-fixture" for r in self.snapshot["rows"]))
        self.assertGreaterEqual(len({r["industry"] for r in self.snapshot["rows"]}), 10)

    def test_happy_path_is_only_offline_prepared(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network used")), \
             mock.patch.object(socket, "create_connection", side_effect=AssertionError("network used")), \
             mock.patch.object(sqlite3, "connect", side_effect=AssertionError("database used")):
            result = self.call_prepare()
        self.assertEqual(result["status"], "offline_prepared")
        self.assertEqual(result["expected"], 125)
        self.assertEqual(result["received"], 125)
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["runtime_model_calls"], 0)
        self.assertEqual(result["runtime_provider_calls"], 0)
        self.assertIsNone(result["token_usage"])
        self.assertIsNone(result["billed_cost"])
        self.assertFalse(result["outbound_ready"])

    def test_future_session_and_future_row_timestamp_are_rejected_or_invalidated(self):
        future = copy.deepcopy(self.snapshot)
        future["session"] = "2026-09-25"
        with self.assertRaises(prepare_module.InvalidInput):
            self.call_prepare(snapshot=future)

        future_row = copy.deepcopy(self.snapshot)
        symbol = future_row["rows"][-1]["symbol"]
        future_row["rows"][-1]["observed_at"] = "2026-09-25T09:00:00+08:00"
        result = self.call_prepare(snapshot=future_row)
        self.assertIn(symbol, result["invalid"])

    def test_future_feature_timestamp_is_invalidated(self):
        snapshot = copy.deepcopy(self.snapshot)
        symbol = snapshot["rows"][-1]["symbol"]
        snapshot["rows"][-1]["features_as_of"] = "2026-09-25T09:00:00+08:00"
        result = self.call_prepare(snapshot=snapshot)
        self.assertIn(symbol, result["invalid"])

    def test_universe_denominator_and_pagination_must_be_complete(self):
        truncated = copy.deepcopy(self.snapshot)
        truncated["pagination_complete"] = False
        with self.assertRaisesRegex(prepare_module.InvalidInput, "truncated"):
            self.call_prepare(snapshot=truncated)

        missing_fixed_from_manifest = copy.deepcopy(self.snapshot)
        fixed_symbol = self.baseline["stocks"][0]["symbol"]
        missing_fixed_from_manifest["expected_symbols"].remove(fixed_symbol)
        missing_fixed_from_manifest["provider_total"] -= 1
        missing_fixed_from_manifest["universe_sha256"] = prepare_module.digest(
            sorted(missing_fixed_from_manifest["expected_symbols"]))
        with self.assertRaisesRegex(prepare_module.InvalidInput, "fixed baseline"):
            self.call_prepare(snapshot=missing_fixed_from_manifest)

    def test_coverage_uses_full_manifest_denominator_at_and_below_98_percent(self):
        # 25 fixed + 75 synthetic names gives an exact 100-name denominator.
        threshold_fixture = fixture_module.build_fixture(extra_count=75)
        at_least_threshold = copy.deepcopy(threshold_fixture)
        extras = [s for s in at_least_threshold["expected_symbols"]
                  if s not in {x["symbol"] for x in self.baseline["stocks"]}]
        missing = set(extras[:2])
        at_least_threshold["rows"] = [r for r in at_least_threshold["rows"]
                                       if r["symbol"] not in missing]
        at_least_threshold["missing_symbols"] = sorted(missing)
        result = self.call_prepare(snapshot=at_least_threshold)
        self.assertEqual(result["expected"], 100)
        self.assertEqual(result["received"], 98)
        self.assertEqual(result["coverage"], 0.98)
        self.assertNotIn("coverage_below_98_percent", result["blockers"])

        below = copy.deepcopy(threshold_fixture)
        missing = set(extras[:3])
        below["rows"] = [r for r in below["rows"] if r["symbol"] not in missing]
        below["missing_symbols"] = sorted(missing)
        result = self.call_prepare(snapshot=below)
        self.assertEqual(result["coverage"], 0.97)
        self.assertIn("coverage_below_98_percent", result["blockers"])

    def test_fixed_25_missing_row_blocks_even_when_full_market_coverage_is_high(self):
        snapshot = copy.deepcopy(self.snapshot)
        symbol = self.baseline["stocks"][2]["symbol"]
        snapshot["rows"] = [r for r in snapshot["rows"] if r["symbol"] != symbol]
        snapshot["missing_symbols"] = [symbol]
        result = self.call_prepare(snapshot=snapshot)
        self.assertAlmostEqual(result["coverage"], 124 / 125)
        self.assertIn("fixed_baseline_missing_or_invalid", result["blockers"])

    def test_st_and_halted_holdings_remain_visible_in_arm_payloads(self):
        result = self.call_prepare()
        for arm, expected_reason in (("A", "ST"), ("B", "halted")):
            payload = result["arms"][arm]["payload"]
            held = result["arms"][arm]["holding_symbols"][0]
            card = next(card for card in payload["cards"] if card["symbol"] == held)
            self.assertTrue(card["holding"])
            self.assertEqual(card["exclusion"], expected_reason)
            self.assertFalse(card["entry_candidate"])

    def test_equal_candidate_caps_and_industry_caps_apply_to_both_arms(self):
        result = self.call_prepare()
        for arm in ("A", "B"):
            symbols = result["arms"][arm]["candidate_symbols"]
            self.assertLessEqual(len(symbols), self.policy["candidate_limit"])
            rows = {r["symbol"]: r for r in self.snapshot["rows"]}
            counts = {}
            for symbol in symbols:
                sector = rows[symbol]["industry"]
                counts[sector] = counts.get(sector, 0) + 1
            self.assertTrue(all(n <= self.policy["sector_candidate_limit"]
                                for n in counts.values()))

        one_sector = copy.deepcopy(self.snapshot)
        for row in one_sector["rows"]:
            row["industry"] = "single-sector"
        result = self.call_prepare(snapshot=one_sector)
        self.assertEqual(result["arms"]["A"]["candidate_count"], 4)
        self.assertEqual(result["arms"]["B"]["candidate_count"], 4)

    def test_common_full_universe_ranking_is_identical_between_arms(self):
        snapshot = copy.deepcopy(self.snapshot)
        shared_symbol = self.baseline["stocks"][2]["symbol"]
        snapshot["synthetic_holdings"] = {"A": [shared_symbol], "B": [shared_symbol]}
        result = self.call_prepare(snapshot=snapshot)
        a_cards = {c["symbol"]: c for c in result["arms"]["A"]["payload"]["cards"]}
        b_cards = {c["symbol"]: c for c in result["arms"]["B"]["payload"]["cards"]}
        self.assertIn(shared_symbol, a_cards)
        self.assertIn(shared_symbol, b_cards)
        self.assertEqual(a_cards[shared_symbol]["screen_score"],
                         b_cards[shared_symbol]["screen_score"])

    def test_payload_byte_limit_blocks_oversized_prompts(self):
        policy = copy.deepcopy(self.policy)
        policy["payload_bytes_per_arm"] = 100
        result = self.call_prepare(policy=policy)
        self.assertIn("A_payload_budget_exceeded", result["blockers"])
        self.assertIn("B_payload_budget_exceeded", result["blockers"])

    def test_nonfinite_boolean_and_duplicate_values_are_refused(self):
        with self.assertRaises(prepare_module.InvalidInput):
            prepare_module.number(float("nan"), "x")
        with self.assertRaises(prepare_module.InvalidInput):
            prepare_module.number(True, "x")

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(prepare_module.InvalidInput, "nonfinite"):
                prepare_module.load(path)
            path.write_text('{"value": 1, "value": 2}', encoding="utf-8")
            with self.assertRaisesRegex(prepare_module.InvalidInput, "duplicate JSON key"):
                prepare_module.load(path)

        duplicate_symbol = copy.deepcopy(self.snapshot)
        duplicate_symbol["expected_symbols"].append(duplicate_symbol["expected_symbols"][0])
        with self.assertRaisesRegex(prepare_module.InvalidInput, "duplicate symbols"):
            self.call_prepare(snapshot=duplicate_symbol)

    def test_duplicate_row_symbol_and_duplicate_missing_symbol_are_refused(self):
        duplicate = copy.deepcopy(self.snapshot)
        duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
        with self.assertRaisesRegex(prepare_module.InvalidInput, "duplicate symbols"):
            self.call_prepare(snapshot=duplicate)

        duplicate_missing = copy.deepcopy(self.snapshot)
        duplicate_missing["missing_symbols"] = ["000001", "000001"]
        with self.assertRaisesRegex(prepare_module.InvalidInput, "duplicate symbols"):
            self.call_prepare(snapshot=duplicate_missing)

    def test_future_outcome_extra_field_does_not_enter_model_payload(self):
        snapshot = copy.deepcopy(self.snapshot)
        first = self.call_prepare(snapshot=snapshot)
        symbol = first["arms"]["B"]["candidate_symbols"][0]
        row = next(row for row in snapshot["rows"] if row["symbol"] == symbol)
        row["future_return_1d"] = 0.75
        result = self.call_prepare(snapshot=snapshot)
        b_cards = {card["symbol"]: card for card in result["arms"]["B"]["payload"]["cards"]}
        self.assertIn(symbol, b_cards)
        self.assertTrue(b_cards[symbol]["entry_candidate"])
        self.assertNotIn("future_return_1d", b_cards[symbol])
        self.assertNotIn("future_return_1d", json.dumps(result["arms"]["B"]["payload"],
                                                          ensure_ascii=False))

    def test_invalid_row_fields_block_when_the_row_is_a_holding(self):
        mutations = (
            ("is_st", None),
            ("close_raw", True),
            ("amount_unit", "USD"),
            ("industry_as_of", "2026-09-25T09:00:00+08:00"),
            ("features_as_of", "2026-09-24T14:59:00+08:00"),
            ("industry_version", "synthetic-v2"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                snapshot = copy.deepcopy(self.snapshot)
                symbol = snapshot["rows"][-1]["symbol"]
                next(row for row in snapshot["rows"] if row["symbol"] == symbol)[field] = value
                snapshot["synthetic_holdings"]["A"] = [symbol]
                result = self.call_prepare(snapshot=snapshot)
                self.assertGreaterEqual(result["coverage"], 0.98)
                self.assertIn(symbol, result["invalid"])
                self.assertIn("A_holding_data_missing_or_invalid", result["blockers"])
                self.assertEqual(result["status"], "blocked")

    def test_missing_holding_blocks_even_when_market_coverage_exceeds_98_percent(self):
        snapshot = copy.deepcopy(self.snapshot)
        symbol = snapshot["rows"][-1]["symbol"]
        snapshot["rows"] = [row for row in snapshot["rows"] if row["symbol"] != symbol]
        snapshot["missing_symbols"] = [symbol]
        snapshot["synthetic_holdings"]["A"] = [symbol]
        result = self.call_prepare(snapshot=snapshot)
        self.assertEqual(result["coverage"], 124 / 125)
        self.assertNotIn("coverage_below_98_percent", result["blockers"])
        self.assertIn("A_holding_data_missing_or_invalid", result["blockers"])
        self.assertEqual(result["status"], "blocked")

    def test_row_order_does_not_change_rankings_and_ties_break_by_symbol(self):
        snapshot = copy.deepcopy(self.snapshot)
        for row in snapshot["rows"]:
            row["return20"] = 0.01
            row["return60"] = 0.02
            row["amount20_cny"] = 100_000_000
            row["volatility20"] = 0.1
        shuffled = copy.deepcopy(snapshot)
        shuffled["rows"] = list(reversed(shuffled["rows"]))
        normal_result = self.call_prepare(snapshot=snapshot)
        shuffled_result = self.call_prepare(snapshot=shuffled)
        by_symbol = {row["symbol"]: row for row in snapshot["rows"]}

        def tie_order(candidates):
            out, sectors = [], {}
            for symbol in sorted(candidates):
                sector = by_symbol[symbol]["industry"]
                if sectors.get(sector, 0) >= self.policy["sector_candidate_limit"]:
                    continue
                out.append(symbol)
                sectors[sector] = sectors.get(sector, 0) + 1
                if len(out) == self.policy["candidate_limit"]:
                    break
            return out

        for arm in ("A", "B"):
            normal = normal_result["arms"][arm]
            reversed_rows = shuffled_result["arms"][arm]
            self.assertEqual(normal["candidate_symbols"], reversed_rows["candidate_symbols"])
            eligible = {row["symbol"] for row in snapshot["rows"]
                        if not row["is_st"] and not row["halted"]
                        and (arm == "B" or row["symbol"] in
                             {stock["symbol"] for stock in self.baseline["stocks"]})}
            self.assertEqual(normal["candidate_symbols"], tie_order(eligible))
            normal_scores = {card["symbol"]: card["screen_score"]
                             for card in normal["payload"]["cards"]}
            shuffled_scores = {card["symbol"]: card["screen_score"]
                               for card in reversed_rows["payload"]["cards"]}
            self.assertEqual(normal_scores, shuffled_scores)

    def test_external_unverified_input_never_activates_outbound_or_economics(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["kind"] = "external_unverified"
        result = self.call_prepare(snapshot=snapshot)
        self.assertFalse(result["economic_activation"])
        self.assertFalse(result["outbound_ready"])


class PrepareCliTests(unittest.TestCase):
    def make_cli_copy(self, folder: Path, *, tamper_registration=False, omit_runner=False):
        for name in ("prepare.py", "protocol.json", "baseline-universe.json"):
            (folder / name).write_bytes((HERE / name).read_bytes())
        files = {name: digest_file(folder / name)
                 for name in ("prepare.py", "protocol.json", "baseline-universe.json")}
        if tamper_registration:
            files["protocol.json"] = "0" * 64
        if omit_runner:
            del files["prepare.py"]
        (folder / "registration.json").write_text(
            json.dumps({"files": files}, sort_keys=True), encoding="utf-8")

    def run_cli(self, folder: Path, *args):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(folder / "prepare.py"), *map(str, args)],
                              cwd=folder, env=env, text=True, capture_output=True, timeout=30)

    def test_cli_requires_known_flags_and_writes_exclusively(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.make_cli_copy(folder)
            input_path = folder / "fixture.json"
            input_path.write_text(json.dumps(fresh_fixture(), ensure_ascii=False), encoding="utf-8")
            output_path = folder / "out.json"
            unknown = self.run_cli(folder, "--input", input_path, "--out", output_path, "--surprise")
            self.assertEqual(unknown.returncode, 2)
            self.assertFalse(output_path.exists())

            first = self.run_cli(folder, "--input", input_path, "--out", output_path)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"],
                             "offline_prepared")
            original_bytes = output_path.read_bytes()
            second = self.run_cli(folder, "--input", input_path, "--out", output_path)
            self.assertEqual(second.returncode, 2)
            self.assertIn("File exists", second.stderr)
            self.assertEqual(output_path.read_bytes(), original_bytes)

    def test_registration_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.make_cli_copy(folder, tamper_registration=True)
            input_path = folder / "fixture.json"
            input_path.write_text(json.dumps(fresh_fixture(), ensure_ascii=False), encoding="utf-8")
            output_path = folder / "out.json"
            result = self.run_cli(folder, "--input", input_path, "--out", output_path)
            self.assertEqual(result.returncode, 2)
            self.assertIn("registration hash mismatch", result.stderr)
            self.assertFalse(output_path.exists())

    def test_registration_missing_runner_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.make_cli_copy(folder, omit_runner=True)
            input_path = folder / "fixture.json"
            input_path.write_text(json.dumps(fresh_fixture(), ensure_ascii=False), encoding="utf-8")
            output_path = folder / "out.json"
            result = self.run_cli(folder, "--input", input_path, "--out", output_path)
            self.assertEqual(result.returncode, 2)
            self.assertIn("registration must bind exact runner", result.stderr)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
