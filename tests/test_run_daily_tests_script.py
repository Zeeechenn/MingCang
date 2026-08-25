from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_daily_tests.sh"


def _base_env(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        **os.environ,
        "MINGCANG_REPO_ROOT": str(repo),
        "MINGCANG_DAILY_RUNTIME_DIR": str(runtime),
        "MINGCANG_PYTHON": sys.executable,
    }


def test_daily_runner_rejects_a_concurrent_instance(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    lock = runtime / "pipeline.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(RUNNER), "2026-08-25"],
        cwd=ROOT,
        env=_base_env(ROOT, runtime),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 3
    assert "已有每日流水线运行中" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout


def test_daily_runner_does_not_steal_a_lock_before_owner_is_written(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    lock = runtime / "pipeline.lock"
    lock.mkdir(parents=True)

    proc = subprocess.run(
        ["bash", str(RUNNER), "2026-08-25"],
        cwd=ROOT,
        env=_base_env(ROOT, runtime),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 3
    assert "锁正在初始化或损坏" in proc.stdout
    assert lock.exists()


def test_daily_runner_records_abort_and_never_prints_done_on_command_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    paper = repo / "paper_trading"
    scripts.mkdir(parents=True)
    paper.mkdir()
    shutil.copy2(ROOT / "scripts" / "update_daily_pipeline_state.py", scripts)
    (paper / "test2_signal_runner.py").write_text(
        "raise SystemExit(9)\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(RUNNER), "2026-08-25"],
        cwd=ROOT,
        env=_base_env(repo, tmp_path / "runtime"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "PIPELINE_ABORTED" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    state = json.loads((paper / "_run_state_20260825.json").read_text(encoding="utf-8"))
    assert state["status"] == "aborted"
    assert state["current_step"] == "01_test2"
    assert state["one_loop_status"] == "pending"
    assert not (tmp_path / "runtime" / "pipeline.lock").exists()


def test_daily_runner_uses_consistent_snapshot_and_explicit_terminal_markers() -> None:
    text = RUNNER.read_text(encoding="utf-8")

    assert "sqlite_consistent_snapshot.py" in text
    assert "cp mingcang.db" not in text
    assert 'say "ONE_LOOP_COMPLETE"' in text
    assert 'say "PIPELINE_DONE"' in text
    assert text.index('write_state complete "pipeline finished"') < text.index(
        'say "PIPELINE_DONE"'
    )
