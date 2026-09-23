import hashlib
import json
from pathlib import Path

import pytest

from backend.evidence.model_comparison import content_hash
from backend.tools.model_comparison import (
    inspect_registered_channel,
    inspect_trial,
    main,
    read_json,
)
from tests.test_model_comparison import fixture_bundle


def test_cli_replays_bundle_and_never_overwrites(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(fixture_bundle()))
    output = tmp_path / "report.json"
    assert main(["--input", str(source), "--output", str(output)]) == 0
    original = output.read_bytes()
    assert json.loads(original)["paired_decisions"] == 1
    assert main(["--input", str(source), "--output", str(output)]) == 2
    assert output.read_bytes() == original


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_json_rejected(tmp_path, raw):
    p = tmp_path / "input.json"
    p.write_text(raw)
    with pytest.raises(ValueError):
        read_json(p)


def test_symlink_input_rejected(tmp_path):
    p = tmp_path / "input.json"
    p.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(p)
    with pytest.raises(ValueError):
        read_json(link)


def test_inventory_rejects_corrupt_protocol_without_importing_trial(tmp_path):
    (tmp_path / "protocol.json").write_text("{}")
    (tmp_path / "protocol.sha256").write_text("bad")
    (tmp_path / "trial.py").write_text("raise RuntimeError('must never execute')")
    with pytest.raises(ValueError, match="protocol changed"):
        inspect_trial(tmp_path)


def test_bad_input_produces_no_report(tmp_path):
    p = tmp_path / "input.json"
    p.write_text("{}")
    output = tmp_path / "report.json"
    assert main(["--input", str(p), "--output", str(output)]) == 2
    assert not output.exists()


def test_inventory_symlink_root_rejected(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "root")
    with pytest.raises(ValueError):
        inspect_trial(Path(tmp_path / "link"))


def test_cli_account_is_one_arm_only(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(fixture_bundle()))
    output = tmp_path / "account.json"
    assert (
        main(
            [
                "--input",
                str(source),
                "--account-at",
                "2026-09-21T16:00:00+08:00",
                "--arm",
                "gpt6",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    account = json.loads(output.read_text())
    assert account["arm_id"] == "gpt6" and account["cash"] < 100000
    assert "claude" not in output.read_text()


def test_cli_request_context_keeps_own_account_and_blocked_status(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(fixture_bundle()))
    output = tmp_path / "request-context.json"
    assert main([
        "--input", str(source), "--account-at", "2026-09-21T16:00:00+08:00",
        "--arm", "gpt6", "--request-context", "--output", str(output),
    ]) == 0
    proposal = json.loads(output.read_text())
    assert proposal["economic_trial_activated"] is False
    assert proposal["account"]["cash"] < 100000
    assert "claude" not in output.read_text()


def test_v2_registry_hash_and_shared_budget_checked_without_provider(tmp_path):
    symbols = [f"{n:06d}" for n in range(25)]
    (tmp_path / "universe.json").write_text(json.dumps({
        "stocks": [{"symbol": symbol} for symbol in symbols]
    }))
    protocol = {"maximum_sessions": 60, "expires_at": "2026-12-31"}
    authorization = {"authorized": True, "scope": {
        "symbols": symbols, "excluded": ["real account", "real holdings"]
    }}
    (tmp_path / "authorization-20260920.json").write_text(json.dumps(authorization))
    (tmp_path / "candidates").mkdir()
    hashes = {}
    for name in ("trial_canonical_v2.py", "candidates/codex_transport_canonical.py"):
        path = tmp_path / name
        path.write_text("raise RuntimeError('provider must not run')")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    registration = {
        "parent_protocol_sha256": content_hash(protocol),
        "authorization_sha256": content_hash(authorization),
        "same_budget_and_ledger_root": True,
        "counts_existing_20260920_failure": True,
        "maximum_total_sessions": 60,
        "code_hashes": hashes,
    }
    (tmp_path / "canonical-v2-registration.json").write_text(json.dumps(registration))
    result = inspect_registered_channel(tmp_path, protocol)
    assert result["registered_code_verified"] == sorted(hashes)
    assert result["provider_identity_validated"] is False
    (tmp_path / "trial_canonical_v2.py").write_text("changed")
    with pytest.raises(ValueError, match="registered code changed"):
        inspect_registered_channel(tmp_path, protocol)
