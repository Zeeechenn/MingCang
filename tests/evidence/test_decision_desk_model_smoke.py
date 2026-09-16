import json
import unicodedata

import pytest

from scripts.run_decision_desk_model_smoke import parse_events, protected_profile


def stream(extra=()):
    events = [
        *extra,
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
    ]
    return b"\n".join(json.dumps(e).encode() for e in events)


def test_cli_tokens_do_not_invent_resolved_model_or_cost():
    parsed = parse_events(stream())
    assert parsed["answer"] == {"ok": True}
    assert parsed["usage"]["input_tokens"] == 10
    assert parsed["resolved_model"] is None
    assert parsed["cost_cny"] is None
    assert parsed["failed"] is False


@pytest.mark.parametrize(
    "extra",
    [
        [{"type": "error", "message": "wrong model"}],
        [{"type": "item.completed", "item": {"type": "command_execution"}}],
        [{"type": "item.completed", "item": {"type": "mcp_tool_call"}}],
    ],
)
def test_errors_and_tools_cannot_be_accepted_as_fixed_input_quality(extra):
    assert parse_events(stream(extra))["failed"] is True


def test_missing_completion_fails():
    assert parse_events(b'{"type":"turn.started"}')["failed"] is True


def test_profile_quotes_paths(tmp_path):
    path = tmp_path / 'quotes"spaces '
    result = protected_profile([path])
    assert json.dumps(str(path.resolve())) in result
    assert "deny file-read* file-write*" in result


def test_profile_uses_literal_unicode_and_both_filesystem_normalizations(tmp_path):
    path = tmp_path / "中文é"
    profile = protected_profile([path])
    assert "中文" in profile
    assert "\\u4e2d" not in profile
    for form in ("NFC", "NFD"):
        assert json.dumps(unicodedata.normalize(form, str(path)), ensure_ascii=False) in profile


def test_provider_environment_excludes_runtime_keys(monkeypatch):
    from scripts.run_decision_desk_model_smoke import provider_environment

    monkeypatch.setenv("OPENAI_API_KEY", "runtime-key-not-for-codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "other-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:1234")
    env = provider_environment()
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["HTTPS_PROXY"] == "http://localhost:1234"


def test_os_profile_blocks_protected_reads_and_external_writes(tmp_path):
    import subprocess
    import sys

    if sys.platform != "darwin":
        pytest.skip("macOS Seatbelt profile")
    source, work = tmp_path / "source", tmp_path / "work"
    source.mkdir()
    work.mkdir()
    (source / "secret").write_text("fixture only")
    outside = tmp_path / "outside"
    code = f"""from pathlib import Path
for path, mode in [({str(source / "secret")!r}, 'r'), ({str(outside)!r}, 'w')]:
 try: open(path, mode)
 except PermissionError: pass
 else: raise AssertionError('unexpected access')
Path({str(work / "allowed")!r}).write_text('allowed')
print('isolation passed')
"""
    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            protected_profile([source], work_dir=work),
            sys.executable,
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (work / "allowed").read_text() == "allowed"
    assert not outside.exists()


def test_real_process_smoke_retains_diagnostic_without_fabricating_receipts(tmp_path):
    import sys
    from datetime import UTC, datetime

    from scripts.run_decision_desk_model_smoke import run_smoke

    if sys.platform != "darwin":
        pytest.skip("macOS Seatbelt profile")
    binary = tmp_path / "fake-provider"
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.buffer.read()\nprint({stream().decode()!r})\n"
    )
    binary.chmod(0o700)
    request = tmp_path / "request.json"
    request.write_text('{"synthetic":true}')
    receipt = run_smoke(
        binary=binary,
        request=request,
        output_root=tmp_path / "out",
        experiment="fake",
        arm="raw",
        attempt="first",
        cutoff=datetime.now(UTC),
        protected_paths=[request],
        timeout=5,
    )
    assert receipt["status"] == "failed"
    assert "resolved_model_required" in receipt["errors"]
    assert receipt["response"] is not None
    execution = json.loads((tmp_path / "out/fake/raw/first/execution.json").read_text())
    assert execution["termination"] == "completed"
    assert execution["remote_cancellation_confirmed"] is False
