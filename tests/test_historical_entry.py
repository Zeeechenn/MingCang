from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/research_checks"))
import historical  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    market = tmp_path / "market"
    market.mkdir()
    scope = {
        "decisions": ["20260817", "20260818"],
        "days": ["20260814", "20260817", "20260818"],
    }
    (market / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    for day in scope["days"]:
        (market / f"{day}.json").write_text("{}\n", encoding="utf-8")
        (market / f"{day}.receipt.json").write_text("{}\n", encoding="utf-8")
    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(b"immutable test snapshot")
    metadata = tmp_path / "stock_basic-L.json"
    metadata.write_text("[]\n", encoding="utf-8")
    return market, snapshot, metadata


def make_factor_source(tmp_path: Path) -> Path:
    factor = tmp_path / "factors"
    factor.mkdir()
    scope = {
        "decisions": ["20260817", "20260818"],
        "days": ["20260814", "20260817", "20260818"],
    }
    (factor / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    for day in scope["days"]:
        (factor / f"{day}.json").write_text("{}\n", encoding="utf-8")
        (factor / f"{day}.receipt.json").write_text("{}\n", encoding="utf-8")
    return factor


def test_cli_requires_all_explicit_real_history_inputs():
    with pytest.raises(SystemExit) as error:
        historical.main(["run"])
    assert error.value.code == 2


def test_market_and_news_decision_dates_must_match_exactly(tmp_path: Path):
    market, snapshot, _metadata = make_inputs(tmp_path)
    with pytest.raises(ValueError, match="exactly match market scope decisions"):
        historical.validate_inputs(market, snapshot, ["2026-08-17"])


def test_explicit_reuse_day_resolves_only_saved_preflight_pair(tmp_path: Path):
    market, snapshot, _metadata = make_inputs(tmp_path)
    scope = json.loads((market / "scope.json").read_text(encoding="utf-8"))
    scope["reuse_day"] = "20260814"
    (market / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    (market / "20260814.json").unlink()
    (market / "20260814.receipt.json").unlink()
    preflight = tmp_path / "source-preflight"
    preflight.mkdir()
    (preflight / "daily-20260814.json").write_text("{}\n", encoding="utf-8")
    (preflight / "daily-20260814.receipt.json").write_text("{}\n", encoding="utf-8")

    evidence = historical.validate_inputs(market, snapshot, ["2026-08-17", "2026-08-18"])

    assert preflight / "daily-20260814.json" in evidence["resolved_source_files"]


def test_duplicate_decision_dates_are_rejected():
    with pytest.raises(ValueError, match="must not contain duplicates"):
        historical.parse_decision_dates("2026-08-17,2026-08-17")


def test_news_models_missing_keeps_joint_run_partial_and_inputs_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    market, snapshot, metadata = make_inputs(tmp_path)
    candidate = tmp_path / "candidate"
    technical_script = candidate / "backend/backtest/historical_technical.py"
    news_script = candidate / "backend/evidence/historical_news_inputs.py"
    universe = candidate / "scripts/research_checks/universe/baseline-universe.json"
    for path in (technical_script, news_script, universe):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    monkeypatch.setattr(historical, "TECHNICAL_SCRIPT", technical_script)
    monkeypatch.setattr(historical, "NEWS_SCRIPT", news_script)
    monkeypatch.setattr(historical, "UNIVERSE", universe)
    out_dir = tmp_path / "results"
    commands: list[list[str]] = []

    def fake_runner(command):
        commands.append(list(command))
        if "--freeze-only" in command:
            target = Path(command[command.index("--out-dir") + 1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "protocol.json").write_text("{}\n", encoding="utf-8")
        elif "backend.evidence.historical_news_inputs" in command:
            target = Path(command[command.index("--out-dir") + 1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "manifest.json").write_text(
                json.dumps({"model_run": False}), encoding="utf-8"
            )
            (target / "raw_inputs.jsonl").write_text("", encoding="utf-8")
        else:
            target = Path(command[command.index("--out-dir") + 1])
            (target / "technical-baseline.json").write_text("{}\n", encoding="utf-8")
            (target / "feature-scores.jsonl").write_text("", encoding="utf-8")
            (target / "selection-manifest.json").write_text("{}\n", encoding="utf-8")

    before = {p: digest(p) for p in [snapshot, metadata, *market.iterdir()]}
    monkeypatch.chdir(tmp_path)
    code = historical.run(
        Path("market"),
        Path("snapshot.db"),
        Path("stock_basic-L.json"),
        Path("results"),
        ["2026-08-17", "2026-08-18"],
        runner=fake_runner,
    )
    out_dir = tmp_path / "results"
    after = {p: digest(p) for p in [snapshot, metadata, *market.iterdir()]}

    assert code == 4
    assert len(commands) == 3
    assert "--freeze-only" in commands[0]
    assert "--freeze-only" not in commands[1]
    assert "--factor-source" not in commands[0]
    assert "2026-08-17" in commands[2] and "2026-08-18" in commands[2]
    assert str(market.resolve()) in commands[0]
    assert str(snapshot.resolve()) in commands[2]
    status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "partial_news_models_blocked"
    assert status["news_models"] == {
        "legacy-fast": "not_run",
        "v2-full": "not_run",
        "v2-pyramid": "not_run",
    }
    assert status["inputs_unchanged"] is True
    assert before == after


def test_make_research_test_without_explicit_inputs_fails_before_running_checks():
    result = subprocess.run(
        ["make", "research-test"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "MARKET_SOURCE": "",
            "NEWS_SNAPSHOT": "",
            "INDUSTRY_METADATA": "",
            "DECISION_DATES": "",
            "OUT_DIR": "",
        },
    )
    assert result.returncode != 0
    assert "research-test requires MARKET_SOURCE" in result.stderr
    assert "joint.py check" not in result.stdout + result.stderr


def test_child_failure_writes_stage_specific_blocked_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    market, snapshot, metadata = make_inputs(tmp_path)
    candidate = tmp_path / "candidate"
    technical_script = candidate / "backend/backtest/historical_technical.py"
    news_script = candidate / "backend/evidence/historical_news_inputs.py"
    for path in (technical_script, news_script):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    monkeypatch.setattr(historical, "TECHNICAL_SCRIPT", technical_script)
    monkeypatch.setattr(historical, "NEWS_SCRIPT", news_script)
    out_dir = tmp_path / "failed-results"

    def fail_runner(command):
        raise subprocess.CalledProcessError(7, list(command))

    code = historical.run(
        market, snapshot, metadata, out_dir, ["2026-08-17", "2026-08-18"], runner=fail_runner
    )
    status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    assert code == 2
    assert status["status"] == "blocked"
    assert status["blocked_stage"] == "technical_freeze"
    assert status["child_returncode"] == 7


def test_optional_factor_source_is_scope_checked_and_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    market, snapshot, metadata = make_inputs(tmp_path)
    factor = make_factor_source(tmp_path)
    candidate = tmp_path / "candidate"
    technical_script = candidate / "backend/backtest/historical_technical.py"
    news_script = candidate / "backend/evidence/historical_news_inputs.py"
    for path in (technical_script, news_script):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    monkeypatch.setattr(historical, "TECHNICAL_SCRIPT", technical_script)
    monkeypatch.setattr(historical, "NEWS_SCRIPT", news_script)
    captured: list[list[str]] = []

    def fail_after_capture(command):
        captured.append(list(command))
        raise subprocess.CalledProcessError(9, list(command))

    result_dir = tmp_path / "factor-results"
    code = historical.run(
        market,
        snapshot,
        metadata,
        result_dir,
        ["2026-08-17", "2026-08-18"],
        runner=fail_after_capture,
        factor_source=factor,
    )
    assert code == 2
    assert "--factor-source" in captured[0]
    assert str(factor.resolve()) in captured[0]

    (factor / "20260818.receipt.json").unlink()
    invalid_output = tmp_path / "factor-results-invalid"
    calls = []
    with pytest.raises(ValueError, match="factor source is incomplete"):
        historical.run(
            market,
            snapshot,
            metadata,
            invalid_output,
            ["2026-08-17", "2026-08-18"],
            runner=lambda command: calls.append(list(command)),
            factor_source=factor,
        )
    assert calls == []
    assert not invalid_output.exists()
