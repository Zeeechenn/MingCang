import json
import pickle

import pandas as pd
import pytest


def _write_dataset(path):
    path.mkdir()
    for name in ["train_data.pkl", "valid_data.pkl", "windows.csv"]:
        (path / name).write_text("x", encoding="utf-8")
    coverage = {
        "passed": True,
        "complete_symbols": 679,
        "context": 64,
        "pred_len": 5,
        "splits": {
            "train": {"windows": 318065},
            "valid": {"windows": 132274},
        },
    }
    (path / "coverage_report.json").write_text(json.dumps(coverage), encoding="utf-8")
    return coverage


def _write_training_dataset(path):
    path.mkdir()
    dates = pd.date_range("2020-01-01", periods=8, freq="D")
    train_data = {}
    rows = []
    for offset, symbol in enumerate(["300001", "300002", "300003"]):
        closes = [10.0 + offset + i * (0.2 + offset * 0.05) for i in range(len(dates))]
        frame = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.1 for c in closes],
                "low": [c - 0.1 for c in closes],
                "close": closes,
                "vol": [1000.0 + offset * 10.0] * len(dates),
                "amt": [c * (1000.0 + offset * 10.0) for c in closes],
            },
            index=dates,
        )
        train_data[symbol] = frame
        for anchor_idx in [2, 3, 4]:
            rows.append(
                {
                    "split": "train",
                    "symbol": symbol,
                    "context_start": dates[anchor_idx - 2].strftime("%Y-%m-%d"),
                    "anchor_date": dates[anchor_idx].strftime("%Y-%m-%d"),
                    "label_end": dates[anchor_idx + 1].strftime("%Y-%m-%d"),
                    "context_start_idx": anchor_idx - 2,
                    "anchor_idx": anchor_idx,
                    "label_end_idx": anchor_idx + 1,
                    "forward_return": closes[anchor_idx + 1] / closes[anchor_idx] - 1.0,
                }
            )

    with (path / "train_data.pkl").open("wb") as fh:
        pickle.dump(train_data, fh)
    with (path / "valid_data.pkl").open("wb") as fh:
        pickle.dump(train_data, fh)
    pd.DataFrame(rows).to_csv(path / "windows.csv", index=False)
    coverage = {
        "passed": True,
        "complete_symbols": 3,
        "context": 3,
        "pred_len": 1,
        "splits": {
            "train": {"windows": len(rows)},
            "valid": {"windows": 3},
        },
    }
    (path / "coverage_report.json").write_text(json.dumps(coverage), encoding="utf-8")
    return coverage


def test_path_a_launch_config_is_guarded_and_complete(tmp_path):
    from backend.tools.m27_kronos_path_a_launch import build_launch_config, parse_args

    data_dir = tmp_path / "data"
    coverage = _write_dataset(data_dir)
    output_dir = tmp_path / "model"

    args = parse_args([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(tmp_path / "logs"),
        "--write-launch-config",
        "--device",
        "mps",
        "--max-steps",
        "20",
    ])
    config = build_launch_config(args, coverage)

    assert config["starts_training"] is False
    assert config["writes_checkpoint"] is False
    assert config["decision"] == "launch_config_ready"
    assert config["dataset"]["complete_symbols"] == 679
    assert config["model"]["checkpoint_dir"] == str(output_dir / "checkpoints" / "best_model")
    assert config["runtime"]["device"] == "mps"
    assert config["training"]["max_steps"] == 20
    assert config["post_training_gate"]["m27_production_gate"]["icir_floor"] == 0.40
    assert config["post_training_gate"]["eval_command"][0] == ".venv_kronos/bin/python"
    assert config["post_training_gate"]["eval_command"][-1] == str(output_dir)
    promotion_requires = config["post_training_gate"]["promotion_requires"]
    assert str(output_dir / "checkpoints" / "best_model") in promotion_requires[0]
    assert "~/.mingcang/models/kronos_finetuned/checkpoints/best_model" not in promotion_requires[0]
    assert "--execute-training" in config["future_training_command"]


def test_path_a_default_output_is_smoke_namespace():
    from backend.tools.m27_kronos_path_a_launch import parse_args

    args = parse_args([])

    assert args.output_dir.name == "kronos_path_a_smoke"


def test_path_a_execute_training_refuses_canonical_finetuned_output(tmp_path, monkeypatch):
    from backend.tools import m27_kronos_path_a_launch as tool

    data_dir = tmp_path / "data"
    coverage = _write_dataset(data_dir)
    canonical_output = tmp_path / "models" / "kronos_finetuned"
    monkeypatch.setattr(tool, "DEFAULT_FINETUNED_OUTPUT_DIR", canonical_output)

    args = tool.parse_args([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(canonical_output),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
    ])
    config = tool.build_launch_config(args, coverage)

    assert config["decision"] == "blocked_before_training"
    assert "canonical_finetuned_output_reserved_for_real_kronos_checkpoint" in config["blockers"]
    assert config["starts_training"] is False
    assert config["writes_checkpoint"] is False
    assert config["post_training_gate"]["eval_command"][-1] == str(canonical_output)


def test_path_a_real_finetuned_allows_canonical_with_explicit_ack(tmp_path, monkeypatch):
    from backend.tools import m27_kronos_path_a_launch as tool

    data_dir = tmp_path / "data"
    coverage = _write_dataset(data_dir)
    canonical_output = tmp_path / "models" / "kronos_finetuned"
    monkeypatch.setattr(tool, "DEFAULT_FINETUNED_OUTPUT_DIR", canonical_output)

    args = tool.parse_args([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(canonical_output),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--artifact-kind",
        "real-finetuned",
        "--allow-canonical-finetuned",
    ])
    config = tool.build_launch_config(args, coverage)

    assert config["decision"] == "training_ready"
    assert config["starts_training"] is True
    assert config["writes_checkpoint"] is True
    assert config["blockers"] == []
    assert config["model"]["artifact_kind"] == "real-finetuned"
    assert "Kronos predictor next-token" in config["training"]["loss"]


def test_path_a_real_finetuned_requires_explicit_canonical_ack(tmp_path, monkeypatch):
    from backend.tools import m27_kronos_path_a_launch as tool

    data_dir = tmp_path / "data"
    coverage = _write_dataset(data_dir)
    canonical_output = tmp_path / "models" / "kronos_finetuned"
    monkeypatch.setattr(tool, "DEFAULT_FINETUNED_OUTPUT_DIR", canonical_output)

    args = tool.parse_args([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(canonical_output),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--artifact-kind",
        "real-finetuned",
    ])
    config = tool.build_launch_config(args, coverage)

    assert config["decision"] == "blocked_before_training"
    assert "missing_allow_canonical_finetuned" in config["blockers"]


def test_path_a_execute_training_runs_smoke_loop_and_writes_checkpoint(tmp_path):
    pytest.importorskip("torch")
    from backend.tools.m27_kronos_path_a_launch import main

    data_dir = tmp_path / "data"
    _write_training_dataset(data_dir)
    output_dir = tmp_path / "model"
    launch_config = tmp_path / "launch.json"

    code = main([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(tmp_path / "logs"),
        "--launch-config-output",
        str(launch_config),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--device",
        "mps",
        "--max-steps",
        "2",
        "--checkpoint-interval",
        "1",
        "--batch-size",
        "3",
        "--learning-rate",
        "0.001",
    ])

    assert code == 0
    payload = json.loads(launch_config.read_text(encoding="utf-8"))
    result = payload["training_result"]
    assert payload["decision"] == "training_completed"
    assert payload["starts_training"] is True
    assert payload["writes_checkpoint"] is True
    assert result["step"] == 2
    assert result["requested_device"] == "mps"
    assert result["actual_device"] in {"cpu", "mps"}
    assert (output_dir / "checkpoints" / "best_model" / "model.pt").exists()
    manifest = json.loads((output_dir / "checkpoints" / "best_model" / "manifest.json").read_text())
    assert manifest["checkpoint_kind"] == "mingcang_path_a_smoke_model"
    assert manifest["production_config_changed"] is False
    assert (tmp_path / "logs" / "mingcang_path_a_training_log.jsonl").exists()


def test_path_a_execute_training_refuses_to_overwrite_existing_checkpoint(tmp_path):
    pytest.importorskip("torch")
    from backend.tools.m27_kronos_path_a_launch import main

    data_dir = tmp_path / "data"
    _write_training_dataset(data_dir)
    output_dir = tmp_path / "model"
    best_model = output_dir / "checkpoints" / "best_model"
    best_model.mkdir(parents=True)
    sentinel = best_model / "manifest.json"
    sentinel.write_text('{"sentinel": true}\n', encoding="utf-8")
    launch_config = tmp_path / "launch.json"

    code = main([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(tmp_path / "logs"),
        "--launch-config-output",
        str(launch_config),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--max-steps",
        "1",
    ])

    assert code == 2
    payload = json.loads(launch_config.read_text(encoding="utf-8"))
    assert payload["decision"] == "blocked_before_training"
    assert "existing_best_checkpoint" in payload["blockers"]
    assert sentinel.read_text(encoding="utf-8") == '{"sentinel": true}\n'


def test_path_a_execute_training_skips_existing_checkpoint_when_requested(tmp_path):
    from backend.tools.m27_kronos_path_a_launch import main

    data_dir = tmp_path / "data"
    _write_dataset(data_dir)
    output_dir = tmp_path / "model"
    best_model = output_dir / "checkpoints" / "best_model"
    best_model.mkdir(parents=True)
    sentinel = best_model / "manifest.json"
    sentinel.write_text('{"sentinel": true}\n', encoding="utf-8")
    launch_config = tmp_path / "launch.json"

    code = main([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(tmp_path / "logs"),
        "--launch-config-output",
        str(launch_config),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--skip-existing",
    ])

    assert code == 0
    payload = json.loads(launch_config.read_text(encoding="utf-8"))
    assert payload["decision"] == "skipped_existing_checkpoint"
    assert payload["training_result"]["wrote_checkpoint"] is False
    assert sentinel.read_text(encoding="utf-8") == '{"sentinel": true}\n'


def test_path_a_execute_training_resumes_from_prior_checkpoint(tmp_path):
    pytest.importorskip("torch")
    from backend.tools.m27_kronos_path_a_launch import main

    data_dir = tmp_path / "data"
    _write_training_dataset(data_dir)
    first_output = tmp_path / "first_model"
    second_output = tmp_path / "second_model"

    first_code = main([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(first_output),
        "--log-dir",
        str(tmp_path / "logs1"),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--max-steps",
        "1",
        "--checkpoint-interval",
        "1",
        "--learning-rate",
        "0.001",
    ])
    assert first_code == 0

    launch_config = tmp_path / "resume_launch.json"
    second_code = main([
        "--dataset-dir",
        str(data_dir),
        "--output-dir",
        str(second_output),
        "--log-dir",
        str(tmp_path / "logs2"),
        "--launch-config-output",
        str(launch_config),
        "--execute-training",
        "--ack-long-run",
        "--ack-model-write",
        "--resume-from",
        str(first_output / "checkpoints" / "best_model"),
        "--max-steps",
        "2",
        "--checkpoint-interval",
        "1",
        "--learning-rate",
        "0.001",
    ])

    assert second_code == 0
    payload = json.loads(launch_config.read_text(encoding="utf-8"))
    result = payload["training_result"]
    assert result["start_step"] == 1
    assert result["step"] == 2
    assert result["resume_from"] == str(first_output / "checkpoints" / "best_model")
    assert (second_output / "checkpoints" / "best_model" / "model.pt").exists()
