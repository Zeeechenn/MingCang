from __future__ import annotations

import os
import subprocess
import sys

import pytest

from backend.evidence.decision_desk_process import run_bounded_process


def invoke(tmp_path, code, payload=b"", **kwargs):
    return run_bounded_process(
        argv=[sys.executable, "-c", code],
        payload=payload,
        cwd=tmp_path,
        env={"PATH": os.defpath},
        timeout=kwargs.pop("timeout", 2),
        **kwargs,
    )


def test_exact_binary_io_and_explicit_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MINGCANG_TEST_SECRET", "must-not-reach-child")
    result = invoke(
        tmp_path,
        "import os,sys; assert 'MINGCANG_TEST_SECRET' not in os.environ; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stderr.buffer.write(b'error\\x00')",
        b"input\x00\xff",
    )
    assert result.stdout == b"input\x00\xff"
    assert result.stderr == b"error\x00"
    assert result.returncode == 0 and result.termination == "completed"


def test_timeout_with_ignored_term_and_child_preserves_partial_bytes(tmp_path):
    result = invoke(
        tmp_path,
        "import os,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); os.write(1,b'partial'); os.fork(); time.sleep(20)",
        timeout=0.2,
    )
    assert result.termination == "timeout_unknown_remote_completion"
    assert result.stdout == b"partial"
    assert result.elapsed_seconds < 1.5
    assert result.returncode != 0


def test_stdin_backpressure_is_bounded(tmp_path):
    result = invoke(
        tmp_path, "import time; time.sleep(20)", payload=b"x" * 1024 * 1024, timeout=0.2
    )
    assert result.termination == "timeout_unknown_remote_completion"
    assert result.elapsed_seconds < 1.5


@pytest.mark.parametrize("fd", [1, 2])
def test_output_flood_is_capped_in_memory_and_killed(tmp_path, fd):
    result = invoke(
        tmp_path, f'import os\nwhile True: os.write({fd}, b"x"*65536)', max_output_bytes=1024
    )
    assert len(result.stdout) + len(result.stderr) == 1024
    assert result.termination == "output_limit_unknown_remote_completion"
    assert result.elapsed_seconds < 1.5


def test_detached_pipe_holder_cannot_extend_timeout(tmp_path):
    # Own fixture detaches to reproduce inherited pipe EOF hanging; cleanup is explicit.
    pidfile = tmp_path / "detached.pid"
    code = f'import os,time\nif os.fork()==0:\n os.setsid(); open({str(pidfile)!r},"w").write(str(os.getpid())); time.sleep(20)\nelse: time.sleep(20)'
    try:
        result = invoke(tmp_path, code, timeout=0.3)
        assert result.elapsed_seconds < 1.5
        assert result.termination == "timeout_unknown_remote_completion"
    finally:
        if pidfile.exists():
            os.kill(int(pidfile.read_text()), 9)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, True, 301])
def test_invalid_timeout_never_starts_child(tmp_path, monkeypatch, timeout):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("started invalid attempt"))
    with pytest.raises(ValueError, match="timeout"):
        invoke(tmp_path, "pass", timeout=timeout)


def test_oversized_input_rejected_before_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("started oversized attempt")
    )
    with pytest.raises(ValueError, match="request byte"):
        invoke(tmp_path, "pass", payload=b"large", max_request_bytes=1)


def test_nonzero_exit_is_retained(tmp_path):
    result = invoke(tmp_path, 'import sys; sys.stderr.write("fail"); sys.exit(7)')
    assert result.returncode == 7 and result.stderr == b"fail"


def test_early_stdin_close_does_not_claim_complete_input(tmp_path):
    result = invoke(tmp_path, 'import os; os.close(0); os.write(1,b"early answer")', payload=b'x' * 1024 * 1024)
    assert result.termination == 'input_incomplete_unknown_remote_completion'
    assert result.input_bytes_written < 1024 * 1024
    assert result.stdout == b'early answer'
