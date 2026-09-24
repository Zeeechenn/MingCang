from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import socket
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("joint_under_test", HERE / "joint.py")
joint = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(joint)


class JointPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mingcang-joint-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "result"
        self.mingcang = joint.REPO_ROOT

    def demo(self):
        args = argparse.Namespace(mingcang_root=str(self.mingcang), out_dir=str(self.out))
        output = io.StringIO()
        with (
            mock.patch.object(socket, "socket", side_effect=AssertionError("network call")),
            mock.patch.object(
                socket, "create_connection", side_effect=AssertionError("network call")
            ),
            redirect_stdout(output),
        ):
            result = joint.demo_command(args)
        self.demo_stdout = output.getvalue()
        return result

    def test_demo_runs_both_stages_offline_and_keeps_their_gates_separate(self):
        self.assertEqual(self.demo(), 0)
        manifest = json.loads((self.out / "joint-manifest.json").read_text())
        market = json.loads((self.out / "market-preflight.json").read_text())
        news = json.loads((self.out / "news-readiness.json").read_text())
        final_news_hash = hashlib.sha256(
            (self.out / "synthetic_inputs/news-synthetic.sqlite").read_bytes()
        ).hexdigest()
        plan = manifest["shared_raw_evidence_plan"]
        expected = set()
        for arm in market["arms"].values():
            expected.update(arm["candidate_symbols"])
            expected.update(arm["holding_symbols"])
        self.assertEqual(set(plan["symbols"]), expected)
        self.assertEqual(len(plan["symbols"]), len(expected))
        self.assertEqual(plan["scope"], "market_candidate_and_holding_plan_only")
        self.assertFalse(plan["news_forward_universe_included"])
        self.assertFalse(plan["evidence_queries_executed"])
        self.assertFalse(manifest["experiments"]["news_forward_protocol_frozen"])
        self.assertFalse(manifest["experiments"]["forward_calls_made"])
        self.assertEqual(news["gates"]["direction"]["status"], "blocked")
        self.assertEqual(manifest["economics"]["measured_savings"], None)
        self.assertTrue((self.out / "synthetic_inputs/market-synthetic.json").is_file())
        self.assertTrue((self.out / "synthetic_inputs/news-synthetic.sqlite").is_file())
        self.assertEqual(
            Path(news["snapshot"]["path"]),
            (self.out / "synthetic_inputs/news-synthetic.sqlite").resolve(),
        )
        self.assertEqual(news["snapshot"]["sha256"], final_news_hash)
        self.assertTrue(manifest["offline_preparation_execution_completed"])
        self.assertEqual(manifest["market_input_kind"], "synthetic")
        self.assertEqual(manifest["market_cutoff"], "2026-09-24T23:00:00+08:00")
        self.assertTrue(Path(manifest["market_input_path"]).is_file())
        self.assertEqual(manifest["effects"]["business_database_writes"], 0)
        self.assertTrue(manifest["effects"]["synthetic_fixture_database_created"])
        summary = json.loads(self.demo_stdout)
        self.assertEqual(
            summary["news_subgates"],
            {"data": "blocked", "runtime": "blocked", "review": "unknown", "cost": "unknown"},
        )
        self.assertFalse(summary["forward_ready"])
        self.assertLess(len(self.demo_stdout), 1500)

    def test_output_and_input_symlinks_are_rejected(self):
        self.out.mkdir()
        with self.assertRaisesRegex(joint.JointError, "new, non-symlink"):
            joint.fresh_output(self.out)
        target = self.root / "source.json"
        target.write_text("{}")
        alias = self.root / "alias.json"
        alias.symlink_to(target)
        with self.assertRaisesRegex(joint.JointError, "symlinks"):
            joint.source_file(alias, "market input")

    def test_outputs_inside_mingcang_are_rejected_before_creation(self):
        forbidden = self.root / "repo"
        forbidden.mkdir()
        destination = forbidden / "new-output"
        with self.assertRaisesRegex(joint.JointError, "outside the package and MingCang"):
            joint.fresh_output(destination, forbidden_roots=(forbidden,))
        self.assertFalse(destination.exists())

    def test_news_snapshot_sidecars_are_refused(self):
        snapshot = self.root / "news.sqlite"
        snapshot.write_bytes(b"snapshot")
        Path(str(snapshot) + "-shm").write_bytes(b"")
        with self.assertRaisesRegex(joint.JointError, "SQLite sidecars"):
            joint.reject_sqlite_sidecars(snapshot)

    def test_wrong_mingcang_root_is_rejected(self):
        with self.assertRaisesRegex(joint.JointError, "this checkout"):
            joint.verify_mingcang_root(self.root, joint.verify_registrations()[1])

    def test_market_session_must_match_news_as_of(self):
        fixture_spec = importlib.util.spec_from_file_location(
            "joint_fixture_date_test", joint.UNIVERSE_ROOT / "make_fixture.py"
        )
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        market = self.root / "market.json"
        market.write_text(json.dumps(fixture.build_fixture()), encoding="utf-8")
        news = self.root / "news.sqlite"
        with sqlite3.connect(news):
            pass
        args = argparse.Namespace(
            mingcang_root=str(self.mingcang),
            market_input=str(market),
            news_snapshot=str(news),
            as_of="2026-09-23",
            out_dir=str(self.out),
        )
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(joint.JointError, "market snapshot session"):
                joint.prepare_command(args)
        self.assertFalse(self.out.exists())

    def test_market_stage_failure_does_not_suppress_news_audit(self):
        db = self.root / "news.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
        db_hash = joint.sha256(db)
        bad = self.root / "market.json"
        bad.write_text('{"session":"broken", "session":"duplicate"}', encoding="utf-8")
        market_bytes = bad.read_bytes()
        report = joint._run(
            {}, market_bytes, bad, db, db_hash, "2026-09-24", self.mingcang, self.out
        )
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual(report["stages"]["market_universe"]["execution"], "failed")
        self.assertEqual(report["stages"]["news_readiness"]["execution"], "completed")
        self.assertTrue((self.out / "market-stage-error.json").is_file())
        self.assertTrue((self.out / "news-readiness.json").is_file())

    def test_public_prepare_retains_news_when_market_preparation_is_blocked(self):
        fixture_spec = importlib.util.spec_from_file_location(
            "joint_fixture_public_failure", joint.UNIVERSE_ROOT / "make_fixture.py"
        )
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        market = fixture.build_fixture()
        market.pop("rows")
        market_path = self.root / "market-missing-rows.json"
        market_path.write_text(json.dumps(market), encoding="utf-8")
        news_path = self.root / "news.sqlite"
        with sqlite3.connect(news_path) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
        args = argparse.Namespace(
            mingcang_root=str(self.mingcang),
            market_input=str(market_path),
            news_snapshot=str(news_path),
            as_of=market["session"],
            out_dir=str(self.out),
        )
        with redirect_stdout(io.StringIO()):
            status = joint.prepare_command(args)
        self.assertEqual(status, 2)
        manifest = json.loads((self.out / "joint-manifest.json").read_text())
        self.assertEqual(manifest["stages"]["market_universe"]["execution"], "failed")
        self.assertEqual(manifest["stages"]["news_readiness"]["execution"], "completed")
        self.assertTrue((self.out / "news-readiness.json").is_file())

    def test_news_failure_preserves_successful_market_preparation(self):
        fixture_spec = importlib.util.spec_from_file_location(
            "joint_fixture_for_test", joint.UNIVERSE_ROOT / "make_fixture.py"
        )
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        market = fixture.build_fixture()
        market_path = self.root / "market.json"
        market_bytes = json.dumps(market, ensure_ascii=False).encode()
        market_path.write_bytes(market_bytes)
        bad_db = self.root / "invalid.sqlite"
        bad_db.write_bytes(b"not a sqlite database")
        report = joint._run(
            market,
            market_bytes,
            market_path,
            bad_db,
            joint.sha256(bad_db),
            market["session"],
            self.mingcang,
            self.out,
        )
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual(report["stages"]["market_universe"]["execution"], "completed")
        self.assertEqual(report["stages"]["news_readiness"]["execution"], "failed")
        self.assertTrue((self.out / "market-preflight.json").is_file())
        self.assertTrue((self.out / "news-stage-error.json").is_file())

    def test_frozen_registrations_verify_before_preparation(self):
        original, protocol = joint.verify_registrations()
        self.assertEqual(set(original["files"]), joint.BASELINE_NAMES)
        self.assertEqual(
            protocol["news_auditor_sha256"],
            joint.sha256(joint.REPO_ROOT / protocol["news_auditor_relative_path"]),
        )

        original_read = joint.read_json

        def altered(path):
            result = original_read(path)
            if Path(path) == joint.UNIVERSE_ROOT / "registration.json":
                result["files"]["prepare.py"] = "0" * 64
            return result

        with mock.patch.object(joint, "read_json", side_effect=altered):
            with self.assertRaisesRegex(joint.JointError, "original frozen file hash mismatch"):
                joint.verify_registrations()

    def test_missing_registered_news_source_is_rejected(self):
        protocol = joint.verify_registrations()[1]
        protocol["news_auditor_relative_path"] = "backend/evidence/missing.py"
        with self.assertRaisesRegex(joint.JointError, "source is missing"):
            joint.verify_mingcang_root(joint.REPO_ROOT, protocol)

    def test_changed_registered_news_source_is_rejected(self):
        protocol = joint.verify_registrations()[1]
        relocated = self.root / "checkout"
        source = relocated / protocol["news_auditor_relative_path"]
        source.parent.mkdir(parents=True)
        source.write_text("changed source", encoding="utf-8")
        with mock.patch.object(joint, "REPO_ROOT", relocated):
            with self.assertRaisesRegex(
                joint.JointError, "registration hash mismatch: news_event_readiness.py"
            ):
                joint.verify_registrations()

    def test_default_output_is_unique_external_and_portable(self):
        with mock.patch.object(joint.tempfile, "gettempdir", return_value=str(self.root)):
            args = joint.parse_args(["check"])
        target = Path(args.out_dir)
        self.assertFalse(target.exists())
        self.assertNotEqual(target.parent, joint.REPO_ROOT)
        created = joint.fresh_output(target)
        self.assertTrue(created.is_dir())

    def test_optional_root_resolves_to_relocated_checkout_without_external_package(self):
        protocol = joint.verify_registrations()[1]
        self.assertEqual(joint.verify_mingcang_root(None, protocol), joint.REPO_ROOT)
        self.assertTrue((joint.UNIVERSE_ROOT / "prepare.py").is_file())
        self.assertTrue((joint.UNIVERSE_ROOT / "test_prepare.py").is_file())


if __name__ == "__main__":
    unittest.main()
