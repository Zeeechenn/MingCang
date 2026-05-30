import json


def _write_coverage(path, *, passed=True):
    payload = {
        "passed": passed,
        "requested_symbols": 2,
        "complete_symbols": 2 if passed else 1,
        "min_symbols": 2,
        "hard_failures": [] if passed else ["incomplete_symbols"],
        "splits": {
            "train": {"start": "2020-01-01", "end": "2024-12-31", "windows": 10},
            "valid": {"start": "2025-01-01", "end": "2025-10-31", "windows": 4},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_kronos_preflight_ready_for_confirmation_without_training(tmp_path):
    from backend.tools.m27_kronos_preflight import build_report

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ["train_data.pkl", "valid_data.pkl", "windows.csv"]:
        (data_dir / name).write_text("x", encoding="utf-8")
    coverage = data_dir / "coverage_report.json"
    _write_coverage(coverage)
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps([{"symbol": "000001"}, {"symbol": "000002"}]), encoding="utf-8")
    repo_root = tmp_path / "repo"
    (repo_root / "vendor" / "kronos").mkdir(parents=True)
    (repo_root / ".venv_kronos").mkdir()

    report = build_report(
        data_dir=data_dir,
        coverage_report_path=coverage,
        universe_path=universe,
        checkpoint_dir=tmp_path / "models" / "kronos_finetuned",
        repo_root=repo_root,
    )

    assert report["starts_training"] is False
    assert report["writes_checkpoint"] is False
    assert report["calls_external_api"] is False
    assert report["decision"]["decision"] == "ready_for_training_confirmation"
    assert report["coverage"]["complete_symbols"] == 2
    assert report["coverage"]["train_windows"] == 10
    assert report["coverage"]["valid_windows"] == 4
    assert "finetuned_checkpoint_missing_expected_before_first_training" in report["decision"]["warnings"]
    assert report["gate_policy"]["m27_production_gate"]["icir_floor"] == 0.4


def test_kronos_preflight_blocks_missing_data_and_failed_coverage(tmp_path):
    from backend.tools.m27_kronos_preflight import build_report

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    coverage = data_dir / "coverage_report.json"
    _write_coverage(coverage, passed=False)

    report = build_report(
        data_dir=data_dir,
        coverage_report_path=coverage,
        universe_path=tmp_path / "missing_universe.json",
        checkpoint_dir=tmp_path / "models" / "kronos_finetuned",
        repo_root=tmp_path,
    )

    assert report["decision"]["decision"] == "blocked_before_training"
    assert "missing_required_data_files" in report["decision"]["blockers"]
    assert "coverage_report_not_passed" in report["decision"]["blockers"]
    assert "coverage_report_has_hard_failures" in report["decision"]["blockers"]


def test_kronos_preflight_markdown_contains_stop_gates(tmp_path):
    from backend.tools.m27_kronos_preflight import build_report, report_to_markdown

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ["train_data.pkl", "valid_data.pkl", "windows.csv"]:
        (data_dir / name).write_text("x", encoding="utf-8")
    coverage = data_dir / "coverage_report.json"
    _write_coverage(coverage)

    report = build_report(
        data_dir=data_dir,
        coverage_report_path=coverage,
        universe_path=tmp_path / "missing_universe.json",
        checkpoint_dir=tmp_path / "models" / "kronos_finetuned",
        repo_root=tmp_path,
    )
    markdown = report_to_markdown(report)

    assert "M27.4 Kronos Preflight" in markdown
    assert "starts_training: False" in markdown
    assert "writes_checkpoint: False" in markdown
    assert "explicit approval" in markdown
