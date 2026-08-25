from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_daily_tests.sh"

# Fixed, deterministic target day used by every fake-repo scenario below.
# MINGCANG_ALLOW_NON_TODAY=1 bypasses the "must be today" guard so these tests
# do not depend on (or drift with) the machine's wall-clock date.
FAKE_DAY = "2026-08-25"


def _base_env(repo: Path, runtime: Path, *, allow_non_today: bool = True) -> dict[str, str]:
    env = {
        **os.environ,
        "MINGCANG_REPO_ROOT": str(repo),
        "MINGCANG_DAILY_RUNTIME_DIR": str(runtime),
        "MINGCANG_PYTHON": sys.executable,
    }
    if allow_non_today:
        env["MINGCANG_ALLOW_NON_TODAY"] = "1"
    return env


def test_daily_runner_rejects_a_concurrent_instance(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    lock = runtime / "pipeline.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(RUNNER), FAKE_DAY],
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
        ["bash", str(RUNNER), FAKE_DAY],
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
        ["bash", str(RUNNER), FAKE_DAY],
        cwd=ROOT,
        env=_base_env(repo, tmp_path / "runtime"),
        text=True,
        capture_output=True,
        check=False,
    )

    # Both ①(01_test2) and ④(04_live_broad) call the same broken stub, so both
    # tracks fail and the whole pipeline is aborted (not just one step/track).
    assert proc.returncode == 1
    assert "PIPELINE_ABORTED" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    state = json.loads((paper / f"_run_state_{FAKE_DAY.replace('-', '')}.json").read_text(encoding="utf-8"))
    assert state["status"] == "aborted"
    assert state["one_loop_status"] == "pending"
    # Track A's own per-track record still pins the exact failing step.
    assert state["tracks"]["one_loop"]["status"] == "aborted"
    assert state["tracks"]["one_loop"]["step"] == "01_test2"
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


def test_quota_check_full_abort_ignores_budget_marker() -> None:
    """quota_check 的全脚本停手条件只认真额度耗尽标记；本进程预算用尽的
    LLM_CALL_BUDGET_EXHAUSTED 绝不能触发同一条路径。"""
    text = RUNNER.read_text(encoding="utf-8")

    quota_start = text.index("quota_check() {")
    quota_end = text.index("\n}\n", quota_start)
    quota_body = text[quota_start:quota_end]
    assert "LLM_QUOTA_EXHAUSTED" in quota_body
    assert "额度耗尽" in quota_body
    assert "LLM_CALL_BUDGET_EXHAUSTED" not in quota_body
    assert "fail " in quota_body or "fail\t" in quota_body or "fail(" in quota_body

    budget_start = text.index("budget_check() {")
    budget_end = text.index("\n}\n", budget_start)
    budget_body = text[budget_start:budget_end]
    assert "LLM_CALL_BUDGET_EXHAUSTED" in budget_body
    # The non-fatal path must not call fail() -- only a summary warning.
    assert "fail " not in budget_body and "fail(" not in budget_body


# ─────────────────────────────────────────────────────────────────────────
# Fake-repo fixture: full branch coverage for the two-track pipeline.
# ─────────────────────────────────────────────────────────────────────────

_M63_STUB = '''\
import argparse, os, sys

p = argparse.ArgumentParser()
p.add_argument("--mode")
p.add_argument("--date")
p.add_argument("--no-llm", action="store_true")
args = p.parse_args()
exitcode = int(os.environ.get("STUB_PANEL_EXIT", "0"))
print(f"面板已写：postmarket_{args.date}.md")
sys.exit(exitcode)
'''

_TEST2_SIGNAL_RUNNER_STUB = '''\
import os, sys

argv = sys.argv[1:]
target_date = os.environ.get("STUB_TARGET_DATE", "")

if "--universe" not in argv:
    # ① test2 官方批次（无 --date 参数，永远跑"当天"——这里用桩注入的目标日）
    count = os.environ.get("STUB_STEP1_COUNT", "25")
    exitcode = int(os.environ.get("STUB_STEP1_EXIT", "0"))
    print(f"产信号 {count} · 跳过 0 · 失败 0")
    print(f"data_date=={target_date}")
    print("LLM_CALL_TOTAL claude 调用 5")
    sys.exit(exitcode)
elif "--multi-agent" in argv:
    # ⑦ 深评子集
    exitcode = int(os.environ.get("STUB_DEEP_EXIT", "0"))
    print("深评完成")
    print("LLM_CALL_TOTAL claude 调用 3")
    sys.exit(exitcode)
else:
    # ④ 实盘广筛
    exitcode = int(os.environ.get("STUB_LIVE_BROAD_EXIT", "0"))
    print("股票池 live 陈旧剔除 0")
    print("LLM_CALL_TOTAL claude 调用 2")
    sys.exit(exitcode)
'''

_BUILD_LABELS_STUB = '''\
import os, sys

exitcode = int(os.environ.get("STUB_LABELS_EXIT", "0"))
if os.environ.get("STUB_LABELS_BUDGET_EXHAUSTED") == "1":
    print("LLM_CALL_BUDGET_EXHAUSTED 本进程调用预算 120 次已用尽：后续调用一律短路。")
print("完成：标签已刷新")
print("LLM_CALL_TOTAL claude 调用 1")
sys.exit(exitcode)
'''

_AB_RUNNER_STUB = '''\
import os, sys

exitcode = int(os.environ.get("STUB_AB_EXIT", "0"))
print("AB 回放完成")
print("汇总：ok")
sys.exit(exitcode)
'''

_LIVE_SUBSET_STUB = '''\
import json, os, sys
from pathlib import Path

day = sys.argv[1]
exitcode = int(os.environ.get("STUB_FUNNEL_EXIT", "0"))
out = Path("live_trading") / f"_live_subset_{day}.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"stocks": [{"symbol": "600000"}]}), encoding="utf-8")
print("漏斗完成")
sys.exit(exitcode)
'''

_SNAPSHOT_STUB = '''\
import argparse, os, sys

p = argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--destination")
args = p.parse_args()
exitcode = int(os.environ.get("STUB_SNAPSHOT_EXIT", "0"))
if exitcode == 0:
    open(args.destination, "wb").close()
sys.exit(exitcode)
'''

_AUDIT_STUB = '''\
import argparse, json, os, sys

p = argparse.ArgumentParser()
p.add_argument("--db")
p.add_argument("--implementation-since")
p.add_argument("--output")
args = p.parse_args()
exitcode = int(os.environ.get("STUB_AUDIT_EXIT", "0"))
status = os.environ.get("STUB_AUDIT_STATUS", "complete")
target_date = os.environ.get("STUB_TARGET_DATE", "")
payload = {
    "days": [
        {
            "date": target_date,
            "status": status,
            "blockers": [] if status == "complete" else ["stub-blocker"],
        }
    ],
    "metrics": {"close_confirmed_days": 20},
}
with open(args.output, "w", encoding="utf-8") as f:
    json.dump(payload, f)
sys.exit(exitcode)
'''

_LIVE_GATE_STUB = '''\
import argparse, json, os, sys

p = argparse.ArgumentParser()
p.add_argument("--date")
p.add_argument("--db", default=None)
p.add_argument("--universe", default=None)
p.add_argument("--state", default=None)
p.add_argument("--min-coverage", default=None)
p.add_argument("--json-out", default=None)
args = p.parse_args()
exitcode = int(os.environ.get("STUB_GATE_EXIT", "0"))
if args.json_out:
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump({"status": "pass" if exitcode == 0 else "fail", "exit": exitcode}, f)
sys.exit(exitcode)
'''


def _build_fake_repo(tmp_path: Path) -> Path:
    """搭一个假 repo：把脚本会调用的每个命令都换成可控 stub，行为由环境变量控制。"""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "paper_trading").mkdir()
    (repo / "live_trading").mkdir()
    (repo / "backend" / "tools").mkdir(parents=True)

    shutil.copy2(ROOT / "scripts" / "update_daily_pipeline_state.py", repo / "scripts")

    (repo / "scripts" / "live_track_gate.py").write_text(_LIVE_GATE_STUB, encoding="utf-8")
    (repo / "scripts" / "sqlite_consistent_snapshot.py").write_text(_SNAPSHOT_STUB, encoding="utf-8")
    (repo / "scripts" / "audit_one_loop_continuity.py").write_text(_AUDIT_STUB, encoding="utf-8")

    (repo / "paper_trading" / "test2_signal_runner.py").write_text(
        _TEST2_SIGNAL_RUNNER_STUB, encoding="utf-8"
    )
    (repo / "paper_trading" / "build_longterm_labels.py").write_text(
        _BUILD_LABELS_STUB, encoding="utf-8"
    )
    (repo / "paper_trading" / "test2_ab_runner.py").write_text(_AB_RUNNER_STUB, encoding="utf-8")

    (repo / "live_trading" / "live_subset.py").write_text(_LIVE_SUBSET_STUB, encoding="utf-8")
    (repo / "live_trading" / "live_universe.json").write_text(
        json.dumps({"stocks": []}), encoding="utf-8"
    )
    (repo / "live_trading" / "live_state.json").write_text(
        json.dumps({"positions": []}), encoding="utf-8"
    )

    (repo / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "backend" / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "backend" / "tools" / "m63_daily.py").write_text(_M63_STUB, encoding="utf-8")

    conn = sqlite3.connect(str(repo / "mingcang.db"))
    conn.execute("CREATE TABLE long_term_labels (symbol TEXT, label TEXT)")
    conn.execute("INSERT INTO long_term_labels (symbol, label) VALUES ('600000', '买入')")
    conn.commit()
    conn.close()

    return repo


def _scenario_env(repo: Path, runtime: Path, **stub_overrides: str) -> dict[str, str]:
    env = _base_env(repo, runtime)
    env["STUB_TARGET_DATE"] = FAKE_DAY
    env.update(stub_overrides)
    return env


def _run(repo: Path, runtime: Path, **stub_overrides: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RUNNER), FAKE_DAY],
        cwd=ROOT,
        env=_scenario_env(repo, runtime, **stub_overrides),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_args(
    repo: Path, runtime: Path, argv: list[str], **stub_overrides: str
) -> subprocess.CompletedProcess:
    """Like `_run` but with a caller-controlled argv (for --one-loop-only /
    positional-order scenarios) instead of the hardcoded `[FAKE_DAY]`."""
    return subprocess.run(
        ["bash", str(RUNNER), *argv],
        cwd=ROOT,
        env=_scenario_env(repo, runtime, **stub_overrides),
        text=True,
        capture_output=True,
        check=False,
    )


def test_scenario_all_green_reports_pipeline_done(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run(repo, tmp_path / "runtime")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PIPELINE_DONE" in proc.stdout
    assert "ONE_LOOP_COMPLETE" in proc.stdout
    assert "LIVE_TRACK_SKIPPED" not in proc.stdout


def test_scenario_step1_incomplete_aborts_track_a_skips_ab_but_live_track_runs(
    tmp_path: Path,
) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run(repo, tmp_path / "runtime", STUB_STEP1_COUNT="21")

    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "PIPELINE_PARTIAL" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    assert "⑧ 跳过" in proc.stdout
    assert "ONE_LOOP_COMPLETE" not in proc.stdout
    # Track B (live) still ran to completion since the data gate passed.
    assert "Track B（实盘 ④⑤⑥⑦）：✅ 成功" in proc.stdout


def test_scenario_live_gate_fails_skips_567_but_track_a_completes(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run(repo, tmp_path / "runtime", STUB_GATE_EXIT="5")

    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "PIPELINE_PARTIAL" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    assert "LIVE_TRACK_SKIPPED" in proc.stdout
    assert "ONE_LOOP_COMPLETE" in proc.stdout
    assert "Track A（One Loop ①②③⑧）：✅ 成功" in proc.stdout


def test_scenario_step1_fails_and_gate_fails_aborts_whole_pipeline(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run(repo, tmp_path / "runtime", STUB_STEP1_COUNT="21", STUB_GATE_EXIT="5")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PIPELINE_ABORTED" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    assert "PIPELINE_PARTIAL" not in proc.stdout


def test_scenario_non_today_date_rejected_before_any_step(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    env = {
        **os.environ,
        "MINGCANG_REPO_ROOT": str(repo),
        "MINGCANG_DAILY_RUNTIME_DIR": str(tmp_path / "runtime"),
        "MINGCANG_PYTHON": sys.executable,
        "STUB_TARGET_DATE": "2020-01-01",
    }
    # Deliberately no MINGCANG_ALLOW_NON_TODAY override.
    proc = subprocess.run(
        ["bash", str(RUNNER), "2020-01-01"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "PIPELINE_ABORTED" in proc.stdout
    assert "没有 --date 参数" in proc.stdout
    # No step ever ran: no log files, no lock, no state file.
    assert not (repo / "paper_trading" / "_test2_20200101.log").exists()
    assert not (tmp_path / "runtime" / "pipeline.lock").exists()


# ─────────────────────────────────────────────────────────────────────────
# --one-loop-only: run Track A (①②③⑧) only, never touch Track B (④⑤⑥⑦).
# ─────────────────────────────────────────────────────────────────────────


def test_scenario_one_loop_only_all_green_skips_track_b(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run_args(repo, tmp_path / "runtime", [FAKE_DAY, "--one-loop-only"])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ONE_LOOP_ONLY_DONE" in proc.stdout
    assert "ONE_LOOP_COMPLETE" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    assert "PIPELINE_PARTIAL" not in proc.stdout
    assert "PIPELINE_ABORTED" not in proc.stdout

    # Track B never ran: none of its stubs left artifacts or log lines behind.
    stamp = FAKE_DAY.replace("-", "")
    assert not (repo / "live_trading" / f"_live_broad_{stamp}.log").exists()
    assert not (repo / "live_trading" / f"_live_subset_{FAKE_DAY}.json").exists()
    assert not (repo / "paper_trading" / f"_longterm_labels_{stamp}.log").exists()
    assert not (repo / "live_trading" / f"_live_deep_{stamp}.log").exists()
    assert not (repo / "live_trading" / f"_live_deep_subset_{FAKE_DAY}.json").exists()
    assert "④ 实盘广筛" not in proc.stdout
    assert "⑤ 漏斗" not in proc.stdout
    assert "⑥ 长期标签" not in proc.stdout
    assert "子集深评" not in proc.stdout
    assert "股票池 live 陈旧剔除" not in proc.stdout  # ④ stub's own output line

    state = json.loads(
        (repo / "paper_trading" / f"_run_state_{stamp}.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "complete"
    # Track B is recorded as intentionally not attempted, never "complete".
    assert state["tracks"]["live"]["status"] != "complete"
    assert "--one-loop-only" in state["tracks"]["live"]["message"]


def test_scenario_one_loop_only_step1_incomplete_aborts_and_skips_ab(
    tmp_path: Path,
) -> None:
    repo = _build_fake_repo(tmp_path)
    proc = _run_args(
        repo, tmp_path / "runtime", [FAKE_DAY, "--one-loop-only"], STUB_STEP1_COUNT="21"
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PIPELINE_ABORTED" in proc.stdout
    assert "PIPELINE_DONE" not in proc.stdout
    assert "PIPELINE_PARTIAL" not in proc.stdout
    assert "ONE_LOOP_ONLY_DONE" not in proc.stdout
    assert "ONE_LOOP_COMPLETE" not in proc.stdout
    assert "⑧ 跳过" in proc.stdout

    # Track B still never ran, even though Track A failed.
    stamp = FAKE_DAY.replace("-", "")
    assert not (repo / "live_trading" / f"_live_broad_{stamp}.log").exists()


def test_scenario_one_loop_only_rerun_appends_instead_of_truncating(
    tmp_path: Path,
) -> None:
    repo = _build_fake_repo(tmp_path)
    runtime = tmp_path / "runtime"
    stamp = FAKE_DAY.replace("-", "")

    summary_path = repo / "paper_trading" / f"_run_summary_{stamp}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        "=== 明仓跑测试 2026-08-25 ===\nPREVIOUS_ATTEMPT_MARKER 21/25\n",
        encoding="utf-8",
    )

    state_path = repo / "paper_trading" / f"_run_state_{stamp}.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "daily_pipeline.v1",
                "date": FAKE_DAY,
                "started_at": "2026-08-25T00:00:00+00:00",
                "events": [
                    {
                        "at": "2026-08-25T00:00:00+00:00",
                        "status": "aborted",
                        "step": "01_test2",
                        "message": "prior partial attempt",
                    }
                ],
                "one_loop_status": "pending",
                "tracks": {
                    "one_loop": {
                        "status": "aborted",
                        "step": "01_test2",
                        "message": "prior partial attempt",
                        "updated_at": "2026-08-25T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    proc = _run_args(repo, runtime, [FAKE_DAY, "--one-loop-only"])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ONE_LOOP_ONLY_DONE" in proc.stdout

    summary_text = summary_path.read_text(encoding="utf-8")
    assert "PREVIOUS_ATTEMPT_MARKER 21/25" in summary_text
    assert "重跑 Track A" in summary_text
    assert "--one-loop-only" in summary_text

    state = json.loads(state_path.read_text(encoding="utf-8"))
    # Prior event history survived -- state is merged across the same date,
    # never wiped by `rm -f` for this mode.
    assert any(e["message"] == "prior partial attempt" for e in state["events"])


def test_scenario_one_loop_only_flag_position_independent(tmp_path: Path) -> None:
    repo_a = _build_fake_repo(tmp_path / "case-a")
    proc_a = _run_args(repo_a, tmp_path / "runtime-a", ["--one-loop-only", FAKE_DAY])
    assert proc_a.returncode == 0, proc_a.stdout + proc_a.stderr
    assert "ONE_LOOP_ONLY_DONE" in proc_a.stdout

    repo_b = _build_fake_repo(tmp_path / "case-b")
    proc_b = _run_args(repo_b, tmp_path / "runtime-b", [FAKE_DAY, "--one-loop-only"])
    assert proc_b.returncode == 0, proc_b.stdout + proc_b.stderr
    assert "ONE_LOOP_ONLY_DONE" in proc_b.stdout
