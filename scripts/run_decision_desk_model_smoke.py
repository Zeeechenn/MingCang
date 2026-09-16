#!/usr/bin/env python3
"""One explicit Codex factual-quality attempt with retained, conservative receipts.

CLI events currently expose token use but no resolved-model or billed-cost
receipt. The existing evidence recorder therefore fails closed. Valid JSON may
still be inspected as a diagnostic; it is never certified treatment evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.evidence.decision_desk_process import run_bounded_process  # noqa: E402
from backend.evidence.decision_desk_recording import record_model_observation  # noqa: E402


def parse_events(data: bytes) -> dict[str, Any]:
    events = [json.loads(line) for line in data.splitlines() if line.strip()]
    items = [e.get("item", {}) for e in events if e.get("type") == "item.completed"]
    tools = [i.get("type") for i in items if i.get("type") not in {"agent_message", "reasoning"}]
    completed = [e for e in events if e.get("type") == "turn.completed"]
    failures = [e for e in events if e.get("type") in {"error", "turn.failed"}]
    messages = [i["text"] for i in items if i.get("type") == "agent_message"]
    answer = json.loads(messages[-1]) if messages else None
    return {"answer": answer, "usage": completed[-1].get("usage") if completed else None,
            "unexpected_items": tools, "failed": bool(failures or tools or not completed),
            "resolved_model": None, "cost_cny": None}


def protected_profile(paths: list[Path], *, work_dir: Path | None = None) -> str:
    # macOS filesystems can resolve a displayed NFC path using decomposed names.
    # Seatbelt matches strings; protect both forms and retain literal UTF-8.
    names = {unicodedata.normalize(form, str(p.resolve()))
             for p in paths for form in ("NFC", "NFD")}
    protected = " ".join(f"(subpath {json.dumps(name, ensure_ascii=False)})" for name in sorted(names))
    writes = ""
    if work_dir is not None:
        directory = json.dumps(str(work_dir.resolve()), ensure_ascii=False)
        writes = f'(deny file-write*) (allow file-write* (subpath {directory}) (literal "/dev/null")) '
    return f"(version 1) (allow default) {writes}(deny file-read* file-write* {protected})"


def provider_environment() -> dict[str, str]:
    """Keep CLI account discovery and proxy routing; omit runtime API credentials."""
    allowed = {"HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "CODEX_HOME",
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def run_smoke(*, binary: Path, request: Path, output_root: Path, experiment: str,
              arm: str, attempt: str, cutoff: datetime, protected_paths: list[Path],
              timeout: float = 120) -> dict[str, Any]:
    if not protected_paths:
        raise ValueError("protected_paths required")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
        raise ValueError("timeout must be in (0, 300]")
    attempt_dir = output_root / experiment / arm / attempt

    def provider(payload: bytes) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="mingcang-quality-model-") as work:
            profile = protected_profile(protected_paths, work_dir=Path(work))
            cmd = ["/usr/bin/sandbox-exec", "-p", profile, str(binary), "exec",
                   "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "-s", "read-only", "-m", "gpt-6-astra",
                   "-c", "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
                   "--json", "-"]
            (attempt_dir / "invocation.json").write_text(json.dumps({"argv": cmd, "timeout": timeout}))
            process = run_bounded_process(argv=cmd, payload=payload, cwd=Path(work),
                                          env=provider_environment(), timeout=timeout)
            stdout, stderr = process.stdout, process.stderr
            (attempt_dir / "provider_events.jsonl").write_bytes(stdout)
            (attempt_dir / "provider_stderr.txt").write_bytes(stderr)
            (attempt_dir / "execution.json").write_text(json.dumps({
                "termination": process.termination, "returncode": process.returncode,
                "elapsed_seconds": process.elapsed_seconds, "max_output_bytes": 8 * 1024 * 1024,
                "input_bytes_written": process.input_bytes_written, "input_bytes_expected": len(payload),
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "environment_keys": sorted(provider_environment()),
                "remote_cancellation_confirmed": False,
            }, indent=2))
            if process.termination != "completed":
                raise TimeoutError(f"provider_{process.termination}_no_retry")
            if process.returncode:
                raise RuntimeError(f"provider_exit_{process.returncode}_no_fallback")
            parsed = parse_events(stdout)
            (attempt_dir / "diagnostic.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
            if parsed["failed"]:
                raise RuntimeError("provider_failed_or_used_unrequested_tools")
            return {
                "resolved_model": parsed["resolved_model"],
                "response_bytes": json.dumps(parsed["answer"], ensure_ascii=False).encode(),
                "usage": {"model_calls": 1, "cost_cny": None, "tokens": parsed["usage"],
                          "billing_mode": "local_codex_account_unreported_cost"},
            }

    return record_model_observation(
        output_root=output_root, experiment_id=experiment, arm_id=arm, attempt_id=attempt,
        requested_model="gpt-6-astra", cutoff=cutoff, provider=provider,
        request_bytes=request.read_bytes(), budget={"max_model_calls": 1, "max_cost_cny": 0},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--arm", choices=["raw", "desk"], required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--protect", type=Path, action="append", required=True)
    args = parser.parse_args()
    receipt = run_smoke(binary=args.binary, request=args.request, output_root=args.output_root,
                        experiment=args.experiment, arm=args.arm, attempt=args.attempt,
                        cutoff=datetime.fromisoformat(args.cutoff), protected_paths=args.protect)
    print(json.dumps({"status": receipt["status"], "errors": receipt["errors"],
                      "scope": "diagnostic_only", "certifies_returns": False}, ensure_ascii=False))
    return 0 if receipt.get("response") else 1


if __name__ == "__main__":
    raise SystemExit(main())
