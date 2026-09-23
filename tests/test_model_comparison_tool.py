import hashlib
import json
from pathlib import Path

import pytest

from backend.evidence.model_comparison import content_hash
from backend.tools.model_comparison import (
    inspect_candidate_v3_registration,
    inspect_registered_channel,
    inspect_trial,
    main,
    read_json,
)
from tests.test_model_comparison import candidate_v3_inputs, fixture_bundle


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


def test_v3_cli_preflight_is_read_only_and_never_exposes_full_request(tmp_path, monkeypatch):
    import backend.tools.model_comparison as tool

    bundle = fixture_bundle()
    params = candidate_v3_inputs(bundle)
    inventory = {
        "registered_channel": {"maximum_sessions": 60},
        "sessions": [{"day": "2026-09-20"}],
        "reserved_sessions": 1,
        "remaining_session_capacity": 59,
    }
    monkeypatch.setattr(
        tool, "inspect_candidate_v3_registration",
        lambda _: (params["registration"], params["protocol"], params["authorization"], inventory),
    )
    files = {}
    for name, value in (
        ("input", bundle), ("shared", params["shared_input"]),
        ("review", params["source_review"]),
    ):
        files[name] = tmp_path / (name + ".json")
        files[name].write_text(json.dumps(value))
    output = tmp_path / "preflight.json"
    argv = [
        "--input", str(files["input"]), "--output", str(output),
        "--candidate-v3-root", str(tmp_path), "--session-id", params["session_id"],
        "--account-at", params["cutoff"], "--arm", params["arm"],
        "--shared-input", str(files["shared"]), "--source-review", str(files["review"]),
    ]
    assert main(argv) == 0
    report = json.loads(output.read_text())
    assert report["status"] == "prepared_not_activated"
    assert report["model_calls"] == report["reservations_created"] == 0
    assert "own_prior_decisions" not in output.read_text()
    files["review"].write_text(json.dumps({**params["source_review"], "bundle_sha256": "0" * 64}))
    assert main([*argv[:3], str(tmp_path / "bad.json"), *argv[4:]]) == 2
    assert not (tmp_path / "bad.json").exists()


def test_v3_registration_hash_binds_candidate_code(tmp_path, monkeypatch):
    import backend.tools.model_comparison as tool

    params = candidate_v3_inputs(fixture_bundle())
    trial = tmp_path / "trial"
    trial.mkdir()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for name, value in (
        ("protocol.json", params["protocol"]),
        ("authorization-20260920.json", params["authorization"]),
        ("canonical-v2-registration.json", {"dummy": True}),
    ):
        (trial / name).write_text(json.dumps(value))
    inventory = {"registered_channel": {"maximum_sessions": 60}}
    monkeypatch.setattr(tool, "inspect_trial", lambda _: inventory)
    source = Path(tool.__file__).resolve().parents[2]
    names = ("backend/evidence/model_comparison.py", "backend/tools/model_comparison.py")
    registration = params["registration"] | {
        "ledger_root": str(trial.resolve()),
        "v2_registration_sha256": content_hash({"dummy": True}),
        "code_hashes": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names
        },
    }
    (candidate / "registration.json").write_text(json.dumps(registration))
    assert inspect_candidate_v3_registration(candidate)[0] == registration
    registration["code_hashes"][names[0]] = "0" * 64
    (candidate / "registration.json").write_text(json.dumps(registration))
    with pytest.raises(ValueError, match="candidate code changed"):
        inspect_candidate_v3_registration(candidate)
