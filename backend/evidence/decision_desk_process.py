"""Bounded local process execution for explicit decision-desk diagnostics.

This replaces in-memory communicate() capture. It limits request/output bytes and
wall time, kills the process group, and never waits for pipe EOF after timeout.
It cannot cancel a provider's remote request or certify filesystem permissions.
"""

from __future__ import annotations

import math
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes
    returncode: int
    termination: str
    elapsed_seconds: float
    input_bytes_written: int


def run_bounded_process(
    *,
    argv: list[str],
    payload: bytes,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    max_output_bytes: int = 8 * 1024 * 1024,
    max_request_bytes: int = 2 * 1024 * 1024,
) -> ProcessResult:
    """Run one POSIX process with explicit environment and bounded byte capture."""
    if os.name != "posix":
        raise RuntimeError("process-group isolation requires POSIX")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or not 0 < timeout <= 300
    ):
        raise ValueError("timeout must be finite and in (0, 300]")
    if any(
        type(n) is not int or not 1 <= n <= 64 * 1024 * 1024
        for n in (max_output_bytes, max_request_bytes)
    ):
        raise ValueError("byte limits must be integers in [1, 64 MiB]")
    if not isinstance(payload, bytes) or len(payload) > max_request_bytes:
        raise ValueError("request byte limit exceeded")
    if not argv or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in argv):
        raise ValueError("explicit argv required")
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise ValueError("explicit environment required")
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    written = total = 0
    termination = "completed"
    try:
        with selectors.DefaultSelector() as selector:
            for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            if payload:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
            while selector.get_map() or process.poll() is None:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    termination = "timeout_unknown_remote_completion"
                    break
                for key, _ in selector.select(min(remaining, 0.05)):
                    stream = cast(BinaryIO, key.fileobj)
                    if key.data == "stdin":
                        try:
                            written += os.write(stream.fileno(), payload[written : written + 65536])
                        except BrokenPipeError:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        except BlockingIOError:
                            continue
                        if written == len(payload):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        try:
                            chunk = os.read(
                                stream.fileno(), min(65536, max_output_bytes - total + 1)
                            )
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        allowed = max_output_bytes - total
                        captured[key.data].extend(chunk[:allowed])
                        total += min(len(chunk), allowed)
                        if len(chunk) > allowed:
                            termination = "output_limit_unknown_remote_completion"
                            break
                if termination != "completed":
                    break
    finally:
        # Also reap group children after an early-exiting parent. Closing local
        # pipes avoids an unbounded communicate() on escaped inherited handles.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        process.wait(timeout=1)
    if termination == "completed" and written != len(payload):
        termination = "input_incomplete_unknown_remote_completion"
    return ProcessResult(
        bytes(captured["stdout"]),
        bytes(captured["stderr"]),
        process.returncode,
        termination,
        time.monotonic() - started,
        written,
    )
