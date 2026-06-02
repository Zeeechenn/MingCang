"""Guarded M27.4 StockSage Path A launch config and smoke training runner.

This tool turns the reviewed Kronos dataset into a machine-readable launch
config and training plan. When explicitly requested, it can also run a small
StockSage-owned Path A smoke loop over the reviewed dataset and write a local
checkpoint without using ignored vendor code as the delivery entrypoint.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import random
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_DATASET_DIR = Path.home() / ".stock-sage" / "m27_kronos_reviewed_data"
DEFAULT_FINETUNED_OUTPUT_DIR = Path.home() / ".stock-sage" / "models" / "kronos_finetuned"
DEFAULT_OUTPUT_DIR = Path.home() / ".stock-sage" / "models" / "kronos_path_a_smoke"
DEFAULT_LOG_DIR = Path.home() / ".stock-sage" / "logs" / "m27_kronos_path_a"
DEFAULT_CONFIG_NAME = "stocksage_path_a_launch_config.json"
DEFAULT_PLAN_NAME = "stocksage_path_a_training_plan.json"
DEFAULT_LOG_NAME = "stocksage_path_a_training_log.jsonl"
DEFAULT_SUMMARY_NAME = "stocksage_path_a_training_summary.json"
REQUIRED_DATA_FILES = ["train_data.pkl", "valid_data.pkl", "windows.csv", "coverage_report.json"]
FEATURE_COLUMNS = ["open", "high", "low", "close", "vol", "amt"]
TIME_FEATURE_COLUMNS = ["minute", "hour", "weekday", "day", "month"]
M27_GATE_POLICY = {"ic_floor": 0.04, "icir_floor": 0.40, "monotonic_required": True}
REAL_FINETUNED_CHECKPOINT_KIND = "stocksage_kronos_finetuned_model"
SMOKE_CHECKPOINT_KIND = "stocksage_path_a_smoke_model"
_REPO_ROOT = Path(__file__).parent.parent.parent
_KRONOS_DIR = _REPO_ROOT / "vendor" / "kronos"


class PathATrainingBlocked(RuntimeError):
    """Raised when a training request would violate the guarded launcher policy."""


def validate_dataset(dataset_dir: Path) -> dict[str, Any]:
    dataset_dir = dataset_dir.expanduser()
    missing = [name for name in REQUIRED_DATA_FILES if not (dataset_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing dataset files under {dataset_dir}: {missing}")
    report = json.loads((dataset_dir / "coverage_report.json").read_text(encoding="utf-8"))
    if not report.get("passed"):
        raise RuntimeError(f"coverage_report.json did not pass: {report.get('hard_failures')}")
    return report


def check_loss_wiring() -> dict[str, Any]:
    try:
        from backend.analysis.kronos_losses import path_a_loss  # noqa: F401
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "reason": None}


def _resolve_launch_config_path(args: argparse.Namespace) -> Path:
    if args.launch_config_output is not None:
        return args.launch_config_output.expanduser()
    return args.output_dir.expanduser() / DEFAULT_CONFIG_NAME


def _resolve_plan_path(args: argparse.Namespace) -> Path:
    if args.training_plan_output is not None:
        return args.training_plan_output.expanduser()
    return args.output_dir.expanduser() / DEFAULT_PLAN_NAME


def _future_training_command(args: argparse.Namespace) -> list[str]:
    command = [
        ".venv_kronos/bin/python",
        "-m",
        "backend.tools.m27_kronos_path_a_launch",
        "--dataset-dir",
        str(args.dataset_dir),
        "--output-dir",
        str(args.output_dir),
        "--pretrained-model",
        args.pretrained_model,
        "--tokenizer",
        args.tokenizer,
        "--device",
        args.device,
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--max-steps",
        str(args.max_steps),
        "--learning-rate",
        str(args.learning_rate),
        "--checkpoint-interval",
        str(args.checkpoint_interval),
        "--ack-long-run",
        "--ack-model-write",
        "--execute-training",
    ]
    if args.resume_from is not None:
        command.extend(["--resume-from", str(args.resume_from)])
    if args.skip_existing:
        command.append("--skip-existing")
    if args.artifact_kind == "real-finetuned":
        command.extend(["--artifact-kind", "real-finetuned", "--allow-canonical-finetuned"])
    return command


def _coverage_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    splits = coverage.get("splits") or {}
    train = splits.get("train") or {}
    valid = splits.get("valid") or {}
    return {
        "complete_symbols": coverage.get("complete_symbols"),
        "train_windows": train.get("windows"),
        "valid_windows": valid.get("windows"),
        "context": coverage.get("context"),
        "pred_len": coverage.get("pred_len"),
    }


def _is_canonical_finetuned_output(path: Path) -> bool:
    return path.expanduser().resolve() == DEFAULT_FINETUNED_OUTPUT_DIR.expanduser().resolve()


def _is_real_finetuned_request(args: argparse.Namespace) -> bool:
    return args.artifact_kind == "real-finetuned"


def build_training_plan(args: argparse.Namespace, coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.4",
        "dataset_dir": str(args.dataset_dir.expanduser()),
        "output_dir": str(args.output_dir.expanduser()),
        "pretrained_model": args.pretrained_model,
        "tokenizer": args.tokenizer,
        "lambda_rank": args.lambda_rank,
        "lambda_recon": args.lambda_recon,
        "loss": (
            "Kronos predictor next-token reconstruction loss"
            if args.artifact_kind == "real-finetuned"
            else "lambda_rank * ListMLE(predicted cross-section returns) + lambda_recon * reconstruction_mse"
        ),
        "coverage": _coverage_summary(coverage),
    }


def build_launch_config(args: argparse.Namespace, coverage: dict[str, Any]) -> dict[str, Any]:
    output_dir = args.output_dir.expanduser()
    checkpoint_dir = output_dir / "checkpoints" / "best_model"
    loss_wiring = check_loss_wiring()
    blockers: list[str] = []
    skip_existing_checkpoint = bool(args.execute_training and args.skip_existing and checkpoint_dir.exists())
    if args.execute_training and not args.ack_long_run:
        blockers.append("missing_ack_long_run")
    if args.execute_training and not args.ack_model_write:
        blockers.append("missing_ack_model_write")
    canonical_requested = args.execute_training and _is_canonical_finetuned_output(output_dir)
    if canonical_requested and not (_is_real_finetuned_request(args) and args.allow_canonical_finetuned):
        blockers.append("canonical_finetuned_output_reserved_for_real_kronos_checkpoint")
    if args.execute_training and _is_real_finetuned_request(args) and not args.allow_canonical_finetuned:
        blockers.append("missing_allow_canonical_finetuned")
    if args.execute_training and _is_real_finetuned_request(args) and args.resume_from is not None:
        blockers.append("real_finetuned_resume_not_implemented")
    if (
        args.execute_training
        and not _is_real_finetuned_request(args)
        and not skip_existing_checkpoint
        and not loss_wiring["available"]
    ):
        blockers.append("loss_wiring_unavailable")
    if args.execute_training and checkpoint_dir.exists() and not args.skip_existing:
        blockers.append("existing_best_checkpoint")
    if args.execute_training and not blockers and not skip_existing_checkpoint:
        decision = "training_ready"
    elif skip_existing_checkpoint and not blockers:
        decision = "skipped_existing_checkpoint"
    else:
        decision = "blocked_before_training" if blockers else "launch_config_ready"

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.4",
        "tool": "backend.tools.m27_kronos_path_a_launch",
        "starts_training": args.execute_training and not blockers and not skip_existing_checkpoint,
        "writes_checkpoint": args.execute_training and not blockers and not skip_existing_checkpoint,
        "execute_training_requested": args.execute_training,
        "decision": decision,
        "blockers": blockers,
        "dataset": {
            "dataset_dir": str(args.dataset_dir.expanduser()),
            "train_data": str(args.dataset_dir.expanduser() / "train_data.pkl"),
            "valid_data": str(args.dataset_dir.expanduser() / "valid_data.pkl"),
            "windows": str(args.dataset_dir.expanduser() / "windows.csv"),
            "coverage_report": str(args.dataset_dir.expanduser() / "coverage_report.json"),
            **_coverage_summary(coverage),
        },
        "model": {
            "pretrained_model": args.pretrained_model,
            "tokenizer": args.tokenizer,
            "artifact_kind": args.artifact_kind,
            "output_dir": str(output_dir),
            "checkpoint_dir": str(checkpoint_dir),
            "resume_from": None if args.resume_from is None else str(args.resume_from.expanduser()),
            "checkpoint_exists": checkpoint_dir.exists(),
        },
        "runtime": {
            "device": args.device,
            "seed": args.seed,
            "num_workers": args.num_workers,
            "log_dir": str(args.log_dir.expanduser()),
        },
        "training": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "max_steps": args.max_steps,
            "learning_rate": args.learning_rate,
            "warmup_ratio": args.warmup_ratio,
            "lambda_rank": args.lambda_rank,
            "lambda_recon": args.lambda_recon,
            "loss": (
                "Kronos predictor next-token reconstruction loss"
                if _is_real_finetuned_request(args)
                else "lambda_rank * ListMLE(predicted cross-section returns) + lambda_recon * reconstruction_mse"
            ),
            "loss_wiring": loss_wiring,
        },
        "resume_policy": {
            "resume_from": None if args.resume_from is None else str(args.resume_from.expanduser()),
            "skip_existing": args.skip_existing,
            "write_every_n_steps": args.checkpoint_interval,
            "best_checkpoint": str(checkpoint_dir),
            "overwrite_existing_checkpoint": False,
        },
        "post_training_gate": {
            "eval_command": [
                ".venv_kronos/bin/python",
                "-m",
                "backend.tools.m26_kronos_eval",
                "--model",
                "kronos-finetuned",
                "--finetuned-model-path",
                str(output_dir),
            ],
            "m27_production_gate": M27_GATE_POLICY,
            "promotion_requires": [
                f"real Kronos-compatible checkpoint under this launch output_dir: {checkpoint_dir}",
                "M27 production gate pass on the same evaluation scale using the output_dir eval command",
                "explicit human review before production signal-profile changes",
            ],
        },
        "future_training_command": _future_training_command(args),
    }


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _import_torch() -> Any:
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(
            "PyTorch is required for --execute-training. Run this launcher with "
            ".venv_kronos/bin/python or install the optional Kronos training runtime."
        ) from exc
    return torch


def _select_device(requested: str, torch: Any) -> tuple[Any, str | None]:
    if requested == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda"), None
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps"), None
        return torch.device("cpu"), "auto_selected_cpu"
    if requested == "cuda":
        if torch.cuda.is_available():
            return torch.device("cuda"), None
        return torch.device("cpu"), "requested_cuda_unavailable_fell_back_to_cpu"
    if requested == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps"), None
        return torch.device("cpu"), "requested_mps_unavailable_fell_back_to_cpu"
    return torch.device("cpu"), None


def _prepare_panel(frame: pd.DataFrame) -> pd.DataFrame:
    panel = frame.copy()
    panel.index = pd.to_datetime(panel.index)
    if "volume" in panel.columns and "vol" not in panel.columns:
        panel = panel.rename(columns={"volume": "vol"})
    for col in ["open", "high", "low", "close"]:
        if col not in panel.columns:
            raise ValueError(f"panel is missing required column {col!r}")
    if "vol" not in panel.columns:
        panel["vol"] = 0.0
    if "amt" not in panel.columns:
        panel["amt"] = panel["close"] * panel["vol"]
    for col in FEATURE_COLUMNS:
        panel[col] = pd.to_numeric(panel[col], errors="coerce")
    panel = panel.sort_index().replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS)
    return panel[FEATURE_COLUMNS].astype("float32")


def _time_features(index: pd.DatetimeIndex) -> np.ndarray:
    return np.column_stack(
        [
            index.minute,
            index.hour,
            index.weekday,
            index.day,
            index.month,
        ]
    ).astype(np.float32)


def _load_training_frames(dataset_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    dataset_dir = dataset_dir.expanduser()
    with (dataset_dir / "train_data.pkl").open("rb") as fh:
        raw_panels = pickle.load(fh)  # noqa: S301 - trusted StockSage-generated training data.
    if not isinstance(raw_panels, dict):
        raise ValueError("train_data.pkl must contain a symbol -> DataFrame mapping")

    panels = {str(symbol).zfill(6): _prepare_panel(frame) for symbol, frame in raw_panels.items()}
    windows = pd.read_csv(dataset_dir / "windows.csv")
    required = {"split", "symbol", "context_start", "anchor_date", "forward_return"}
    missing = required - set(windows.columns)
    if missing:
        raise ValueError(f"windows.csv missing required columns: {sorted(missing)}")
    windows = windows[windows["split"] == "train"].copy()
    windows["symbol"] = windows["symbol"].astype(str).str.zfill(6)
    windows["anchor_date"] = pd.to_datetime(windows["anchor_date"])
    windows["context_start"] = pd.to_datetime(windows["context_start"])
    windows["forward_return"] = pd.to_numeric(windows["forward_return"], errors="coerce")
    windows = windows.dropna(subset=["anchor_date", "context_start", "forward_return"])
    if windows.empty:
        raise ValueError("windows.csv contains no usable train windows")
    return panels, windows.sort_values(["anchor_date", "symbol"])


def _load_sequence_training_frames(dataset_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    panels, windows = _load_training_frames(dataset_dir)
    required = {"context_start_idx", "anchor_idx", "label_end_idx"}
    missing = required - set(windows.columns)
    if missing:
        raise ValueError(f"windows.csv missing required sequence index columns: {sorted(missing)}")
    for col in ["context_start_idx", "anchor_idx", "label_end_idx"]:
        windows[col] = pd.to_numeric(windows[col], errors="coerce")
    windows = windows.dropna(subset=["context_start_idx", "anchor_idx", "label_end_idx"]).copy()
    if windows.empty:
        raise ValueError("windows.csv contains no usable indexed train windows")
    return panels, windows


def _window_sequence(panel: pd.DataFrame, row: pd.Series, *, clip: float = 5.0) -> tuple[np.ndarray, np.ndarray] | None:
    start = int(row["context_start_idx"])
    anchor = int(row["anchor_idx"])
    end = int(row["label_end_idx"]) + 1
    if start < 0 or anchor < start or end <= anchor:
        return None
    context = panel.iloc[start:end]
    if context.empty or len(context) != end - start:
        return None
    values = context[FEATURE_COLUMNS].to_numpy(dtype=np.float32, copy=True)
    if values.ndim != 2 or values.shape[0] < 3:
        return None
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    past_len = min(max(anchor - start + 1, 1), len(values))
    past = values[:past_len]
    mean = past.mean(axis=0)
    std = past.std(axis=0)
    std = np.where(std < 1e-5, 1.0, std)
    normalized = np.clip((values - mean) / std, -clip, clip).astype(np.float32)
    stamps = _time_features(pd.DatetimeIndex(context.index))
    if not np.isfinite(normalized).all() or not np.isfinite(stamps).all():
        return None
    return normalized, stamps


def _sample_sequence_batch(
    *,
    rng: random.Random,
    panels: dict[str, pd.DataFrame],
    windows: pd.DataFrame,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    xs: list[np.ndarray] = []
    stamps: list[np.ndarray] = []
    attempts = 0
    max_attempts = max(batch_size * 20, 100)
    while len(xs) < batch_size and attempts < max_attempts:
        attempts += 1
        row = windows.iloc[rng.randrange(len(windows))]
        panel = panels.get(str(row["symbol"]).zfill(6))
        if panel is None:
            continue
        arrays = _window_sequence(panel, row)
        if arrays is None:
            continue
        x, stamp = arrays
        xs.append(x)
        stamps.append(stamp)
    if not xs:
        raise ValueError("could not sample any trainable Kronos sequence windows")
    min_len = min(x.shape[0] for x in xs)
    xs = [x[-min_len:] for x in xs]
    stamps = [stamp[-min_len:] for stamp in stamps]
    return np.stack(xs), np.stack(stamps)


def _window_arrays(panel: pd.DataFrame, row: pd.Series) -> tuple[np.ndarray, np.ndarray] | None:
    context = panel.loc[pd.Timestamp(row["context_start"]): pd.Timestamp(row["anchor_date"])]
    if context.empty and {"context_start_idx", "anchor_idx"}.issubset(row.index):
        start = int(row["context_start_idx"])
        end = int(row["anchor_idx"]) + 1
        context = panel.iloc[start:end]
    if context.empty:
        return None

    values = context[FEATURE_COLUMNS].to_numpy(dtype=np.float32, copy=True)
    if values.ndim != 2 or values.shape[0] == 0:
        return None
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    normalized = (values - mean) / std
    if values.shape[0] > 1:
        close_return = values[-1, 3] / max(abs(float(values[0, 3])), 1e-6) - 1.0
        vol_return = values[-1, 4] / max(abs(float(values[0, 4])), 1e-6) - 1.0
    else:
        close_return = 0.0
        vol_return = 0.0
    features = np.concatenate(
        [
            normalized[-1],
            normalized.mean(axis=0),
            normalized.std(axis=0),
            np.array([close_return, vol_return], dtype=np.float32),
        ]
    ).astype(np.float32)
    target = normalized[-1].astype(np.float32)
    if not np.isfinite(features).all() or not np.isfinite(target).all():
        return None
    return features, target


def _build_training_examples(dataset_dir: Path) -> list[dict[str, Any]]:
    panels, windows = _load_training_frames(dataset_dir)
    examples: list[dict[str, Any]] = []
    for _, row in windows.iterrows():
        panel = panels.get(str(row["symbol"]).zfill(6))
        if panel is None:
            continue
        arrays = _window_arrays(panel, row)
        if arrays is None:
            continue
        features, reconstruction_target = arrays
        examples.append(
            {
                "anchor_date": pd.Timestamp(row["anchor_date"]).strftime("%Y-%m-%d"),
                "symbol": str(row["symbol"]).zfill(6),
                "features": features,
                "reconstruction_target": reconstruction_target,
                "target_return": float(row["forward_return"]),
            }
        )
    if not examples:
        raise ValueError("no trainable Path A windows could be built from the dataset")
    return examples


def _group_examples(examples: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for example in examples:
        grouped.setdefault(str(example["anchor_date"]), []).append(example)
    return [sorted(items, key=lambda item: item["symbol"]) for _, items in sorted(grouped.items())]


def _build_model(torch: Any, input_dim: int, reconstruction_dim: int) -> Any:
    nn = torch.nn

    class PathASmokeModel(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            hidden = max(8, min(64, input_dim * 2))
            self.backbone = nn.Sequential(
                nn.Linear(input_dim, hidden),
                nn.ReLU(),
                nn.Linear(hidden, hidden),
                nn.ReLU(),
            )
            self.score_head = nn.Linear(hidden, 1)
            self.reconstruction_head = nn.Linear(hidden, reconstruction_dim)

        def forward(self, features: Any) -> tuple[Any, Any]:
            encoded = self.backbone(features)
            return self.score_head(encoded).squeeze(-1), self.reconstruction_head(encoded)

    return PathASmokeModel()


def _load_kronos_classes() -> tuple[Any, Any]:
    model_dir = _KRONOS_DIR / "model"
    if not model_dir.exists():
        raise RuntimeError("Kronos vendor checkout is missing under vendor/kronos")
    if str(_KRONOS_DIR) not in sys.path:
        sys.path.insert(0, str(_KRONOS_DIR))
    from model import Kronos, KronosTokenizer

    return Kronos, KronosTokenizer


def _save_kronos_pretrained_checkpoint(
    *,
    checkpoint_dir: Path,
    model: Any,
    metadata: dict[str, Any],
) -> None:
    checkpoint_dir = checkpoint_dir.expanduser()
    if checkpoint_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing checkpoint: {checkpoint_dir}")
    checkpoint_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = checkpoint_dir.with_name(f"{checkpoint_dir.name}.tmp")
    if tmp_dir.exists():
        raise FileExistsError(f"temporary checkpoint path already exists: {tmp_dir}")
    model.save_pretrained(tmp_dir)
    (tmp_dir / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_dir.rename(checkpoint_dir)


def _write_log(log_path: Path, payload: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": datetime.now(UTC).isoformat(timespec="seconds"), **payload}
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _resolve_checkpoint_file(path: Path) -> Path:
    path = path.expanduser()
    if path.is_dir():
        path = path / "model.pt"
    if not path.exists():
        raise FileNotFoundError(f"checkpoint does not exist: {path}")
    return path


def _save_checkpoint(
    *,
    checkpoint_dir: Path,
    model: Any,
    optimizer: Any,
    torch: Any,
    metadata: dict[str, Any],
) -> None:
    checkpoint_dir = checkpoint_dir.expanduser()
    if checkpoint_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing checkpoint: {checkpoint_dir}")
    checkpoint_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = checkpoint_dir.with_name(f"{checkpoint_dir.name}.tmp")
    if tmp_dir.exists():
        raise FileExistsError(f"temporary checkpoint path already exists: {tmp_dir}")
    tmp_dir.mkdir(parents=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "metadata": metadata,
        },
        tmp_dir / "model.pt",
    )
    (tmp_dir / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_dir.rename(checkpoint_dir)


def _load_checkpoint(
    *,
    checkpoint_path: Path,
    model: Any,
    optimizer: Any,
    torch: Any,
    device: Any,
) -> dict[str, Any]:
    checkpoint_file = _resolve_checkpoint_file(checkpoint_path)
    payload = torch.load(checkpoint_file, map_location=device)
    model.load_state_dict(payload["model_state_dict"])
    optimizer.load_state_dict(payload["optimizer_state_dict"])
    return dict(payload.get("metadata") or {})


def _validate_training_args(args: argparse.Namespace) -> None:
    if args.epochs < 1:
        raise ValueError("--epochs must be >= 1")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    if args.max_steps < 1:
        raise ValueError("--max-steps must be >= 1 for --execute-training")
    if args.checkpoint_interval < 1:
        raise ValueError("--checkpoint-interval must be >= 1")
    if args.learning_rate <= 0 or not math.isfinite(args.learning_rate):
        raise ValueError("--learning-rate must be a positive finite number")
    if args.lambda_rank < 0 or args.lambda_recon < 0:
        raise ValueError("--lambda-rank and --lambda-recon must be non-negative")


def execute_training_loop(args: argparse.Namespace, coverage: dict[str, Any]) -> dict[str, Any]:
    _validate_training_args(args)
    output_dir = args.output_dir.expanduser()
    checkpoint_root = output_dir / "checkpoints"
    best_checkpoint = checkpoint_root / "best_model"
    log_path = args.log_dir.expanduser() / DEFAULT_LOG_NAME
    summary_path = args.log_dir.expanduser() / DEFAULT_SUMMARY_NAME

    if best_checkpoint.exists():
        if args.skip_existing:
            result = {
                "status": "skipped_existing_checkpoint",
                "decision": "skipped_existing_checkpoint",
                "wrote_checkpoint": False,
                "best_checkpoint": str(best_checkpoint),
                "reason": "best checkpoint already exists and --skip-existing was set",
            }
            _write_log(log_path, {"event": "skip_existing", **result})
            write_json(summary_path, result)
            return result
        raise PathATrainingBlocked(f"refusing to overwrite existing checkpoint: {best_checkpoint}")

    from backend.analysis.kronos_losses import path_a_loss

    torch = _import_torch()
    device, fallback_reason = _select_device(args.device, torch)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    examples = _build_training_examples(args.dataset_dir)
    groups = _group_examples(examples)
    input_dim = int(examples[0]["features"].shape[0])
    reconstruction_dim = int(examples[0]["reconstruction_target"].shape[0])
    model = _build_model(torch, input_dim, reconstruction_dim).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)

    start_step = 0
    resumed_from = None
    best_loss = float("inf")
    if args.resume_from is not None:
        metadata = _load_checkpoint(
            checkpoint_path=args.resume_from,
            model=model,
            optimizer=optimizer,
            torch=torch,
            device=device,
        )
        start_step = int(metadata.get("step") or 0)
        best_loss = float(metadata.get("best_loss") or metadata.get("loss") or best_loss)
        resumed_from = str(args.resume_from.expanduser())
    if start_step >= args.max_steps:
        raise ValueError("--max-steps must be greater than the resumed checkpoint step")

    _write_log(
        log_path,
        {
            "event": "training_start",
            "requested_device": args.device,
            "actual_device": str(device),
            "fallback_reason": fallback_reason,
            "examples": len(examples),
            "cross_sections": len(groups),
            "start_step": start_step,
            "target_max_steps": args.max_steps,
            "resume_from": resumed_from,
        },
    )

    current_step = start_step
    best_step_checkpoint: Path | None = None
    last_checkpoint_step: int | None = None
    latest_metrics: dict[str, float] = {}

    def save_step_checkpoint(step: int, epoch_number: int) -> None:
        nonlocal best_loss, best_step_checkpoint, last_checkpoint_step
        improved = latest_metrics["loss"] <= best_loss
        if improved:
            best_loss = latest_metrics["loss"]
        step_checkpoint = checkpoint_root / f"step_{step:06d}"
        metadata = {
            "milestone": "M27.4",
            "tool": "backend.tools.m27_kronos_path_a_launch",
            "checkpoint_kind": "stocksage_path_a_smoke_model",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "step": step,
            "epoch": epoch_number,
            "loss": latest_metrics["loss"],
            "rank_loss": latest_metrics["rank_loss"],
            "reconstruction_loss": latest_metrics["reconstruction_loss"],
            "best_loss": best_loss,
            "input_dim": input_dim,
            "reconstruction_dim": reconstruction_dim,
            "requested_device": args.device,
            "actual_device": str(device),
            "fallback_reason": fallback_reason,
            "resume_from": resumed_from,
            "coverage": _coverage_summary(coverage),
            "m27_production_gate": M27_GATE_POLICY,
            "production_config_changed": False,
        }
        _save_checkpoint(
            checkpoint_dir=step_checkpoint,
            model=model,
            optimizer=optimizer,
            torch=torch,
            metadata=metadata,
        )
        _write_log(log_path, {"event": "checkpoint", "path": str(step_checkpoint), **metadata})
        last_checkpoint_step = step
        if improved or best_step_checkpoint is None:
            best_step_checkpoint = step_checkpoint

    completed_epoch = 0
    for epoch in range(args.epochs):
        completed_epoch = epoch + 1
        random.Random(args.seed + epoch).shuffle(groups)
        for group in groups:
            if current_step >= args.max_steps:
                break
            batch = group[: args.batch_size]
            features = torch.tensor(
                np.stack([item["features"] for item in batch]),
                dtype=torch.float32,
                device=device,
            )
            target_returns = torch.tensor(
                [[item["target_return"] for item in batch]],
                dtype=torch.float32,
                device=device,
            )
            reconstruction_target = torch.tensor(
                np.stack([item["reconstruction_target"] for item in batch]),
                dtype=torch.float32,
                device=device,
            )

            optimizer.zero_grad(set_to_none=True)
            predicted_scores, reconstruction_prediction = model(features)
            breakdown = path_a_loss(
                predicted_scores=predicted_scores.unsqueeze(0),
                target_returns=target_returns,
                reconstruction_prediction=reconstruction_prediction.unsqueeze(0),
                reconstruction_target=reconstruction_target.unsqueeze(0),
                lambda_rank=args.lambda_rank,
                lambda_recon=args.lambda_recon,
            )
            breakdown.total.backward()
            optimizer.step()
            current_step += 1

            latest_metrics = {
                "loss": float(breakdown.total.detach().cpu()),
                "rank_loss": float(breakdown.rank.detach().cpu()),
                "reconstruction_loss": float(breakdown.recon.detach().cpu()),
            }
            should_checkpoint = current_step % args.checkpoint_interval == 0 or current_step == args.max_steps
            if should_checkpoint:
                save_step_checkpoint(current_step, epoch + 1)
        if current_step >= args.max_steps:
            break

    if current_step == start_step:
        raise RuntimeError("training loop made no progress")
    if last_checkpoint_step != current_step:
        save_step_checkpoint(current_step, completed_epoch)
    if best_step_checkpoint is None:
        raise RuntimeError("training loop finished without writing a checkpoint")
    shutil.copytree(best_step_checkpoint, best_checkpoint)

    result = {
        "status": "training_completed",
        "decision": "training_completed",
        "wrote_checkpoint": True,
        "step": current_step,
        "start_step": start_step,
        "epochs_requested": args.epochs,
        "max_steps": args.max_steps,
        "checkpoint_interval": args.checkpoint_interval,
        "best_loss": best_loss,
        "latest_metrics": latest_metrics,
        "requested_device": args.device,
        "actual_device": str(device),
        "fallback_reason": fallback_reason,
        "best_checkpoint": str(best_checkpoint),
        "best_step_checkpoint": str(best_step_checkpoint),
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "resume_from": resumed_from,
        "production_config_changed": False,
    }
    _write_log(log_path, {"event": "training_completed", **result})
    write_json(summary_path, result)
    return result


def execute_real_finetuned_training_loop(args: argparse.Namespace, coverage: dict[str, Any]) -> dict[str, Any]:
    _validate_training_args(args)
    output_dir = args.output_dir.expanduser()
    checkpoint_root = output_dir / "checkpoints"
    best_checkpoint = checkpoint_root / "best_model"
    log_path = args.log_dir.expanduser() / DEFAULT_LOG_NAME
    summary_path = args.log_dir.expanduser() / DEFAULT_SUMMARY_NAME

    if best_checkpoint.exists():
        if args.skip_existing:
            result = {
                "status": "skipped_existing_checkpoint",
                "decision": "skipped_existing_checkpoint",
                "wrote_checkpoint": False,
                "best_checkpoint": str(best_checkpoint),
                "reason": "best checkpoint already exists and --skip-existing was set",
            }
            _write_log(log_path, {"event": "skip_existing", **result})
            write_json(summary_path, result)
            return result
        raise PathATrainingBlocked(f"refusing to overwrite existing checkpoint: {best_checkpoint}")

    torch = _import_torch()
    device, fallback_reason = _select_device(args.device, torch)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    panels, windows = _load_sequence_training_frames(args.dataset_dir)
    Kronos, KronosTokenizer = _load_kronos_classes()
    tokenizer = KronosTokenizer.from_pretrained(args.tokenizer)
    tokenizer.eval().to(device)
    model = Kronos.from_pretrained(args.pretrained_model)
    model.to(device)
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    rng = random.Random(args.seed)

    _write_log(
        log_path,
        {
            "event": "real_finetuned_training_start",
            "requested_device": args.device,
            "actual_device": str(device),
            "fallback_reason": fallback_reason,
            "symbols": len(panels),
            "train_windows": int(len(windows)),
            "target_max_steps": args.max_steps,
            "artifact_kind": args.artifact_kind,
        },
    )

    best_loss = float("inf")
    best_checkpoint_loss = float("inf")
    best_step_checkpoint: Path | None = None
    latest_metrics: dict[str, float] = {}

    for step in range(1, args.max_steps + 1):
        batch_x, batch_stamp = _sample_sequence_batch(
            rng=rng,
            panels=panels,
            windows=windows,
            batch_size=args.batch_size,
        )
        x_tensor = torch.tensor(batch_x, dtype=torch.float32, device=device)
        stamp_tensor = torch.tensor(batch_stamp, dtype=torch.float32, device=device)

        with torch.no_grad():
            token_seq_0, token_seq_1 = tokenizer.encode(x_tensor, half=True)
        token_in = [token_seq_0[:, :-1], token_seq_1[:, :-1]]
        token_out = [token_seq_0[:, 1:], token_seq_1[:, 1:]]

        optimizer.zero_grad(set_to_none=True)
        logits = model(token_in[0], token_in[1], stamp_tensor[:, :-1, :])
        loss, s1_loss, s2_loss = model.head.compute_loss(logits[0], logits[1], token_out[0], token_out[1])
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=3.0)
        optimizer.step()

        latest_metrics = {
            "loss": float(loss.detach().cpu()),
            "s1_loss": float(s1_loss.detach().cpu()),
            "s2_loss": float(s2_loss.detach().cpu()),
        }
        improved = latest_metrics["loss"] <= best_loss
        if improved:
            best_loss = latest_metrics["loss"]

        should_checkpoint = step % args.checkpoint_interval == 0 or step == args.max_steps
        if should_checkpoint:
            step_checkpoint = checkpoint_root / f"step_{step:06d}"
            metadata = {
                "milestone": "M27.4",
                "tool": "backend.tools.m27_kronos_path_a_launch",
                "checkpoint_kind": REAL_FINETUNED_CHECKPOINT_KIND,
                "artifact_kind": args.artifact_kind,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "step": step,
                "loss": latest_metrics["loss"],
                "s1_loss": latest_metrics["s1_loss"],
                "s2_loss": latest_metrics["s2_loss"],
                "best_loss": best_loss,
                "best_observed_loss": best_loss,
                "checkpoint_selection_loss": latest_metrics["loss"],
                "pretrained_model": args.pretrained_model,
                "tokenizer": args.tokenizer,
                "requested_device": args.device,
                "actual_device": str(device),
                "fallback_reason": fallback_reason,
                "coverage": _coverage_summary(coverage),
                "m27_production_gate": M27_GATE_POLICY,
                "production_config_changed": False,
            }
            _save_kronos_pretrained_checkpoint(
                checkpoint_dir=step_checkpoint,
                model=model,
                metadata=metadata,
            )
            _write_log(log_path, {"event": "real_finetuned_checkpoint", "path": str(step_checkpoint), **metadata})
            checkpoint_improved = latest_metrics["loss"] <= best_checkpoint_loss
            if checkpoint_improved:
                best_checkpoint_loss = latest_metrics["loss"]
                best_step_checkpoint = step_checkpoint

    if best_step_checkpoint is None:
        raise RuntimeError("real finetuned training loop finished without writing a checkpoint")
    shutil.copytree(best_step_checkpoint, best_checkpoint)

    result = {
        "status": "training_completed",
        "decision": "training_completed",
        "wrote_checkpoint": True,
        "artifact_kind": args.artifact_kind,
        "checkpoint_kind": REAL_FINETUNED_CHECKPOINT_KIND,
        "step": args.max_steps,
        "start_step": 0,
        "epochs_requested": args.epochs,
        "max_steps": args.max_steps,
        "checkpoint_interval": args.checkpoint_interval,
        "best_loss": best_loss,
        "best_observed_loss": best_loss,
        "best_checkpoint_loss": best_checkpoint_loss,
        "latest_metrics": latest_metrics,
        "requested_device": args.device,
        "actual_device": str(device),
        "fallback_reason": fallback_reason,
        "best_checkpoint": str(best_checkpoint),
        "best_step_checkpoint": str(best_step_checkpoint),
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "resume_from": None,
        "production_config_changed": False,
    }
    _write_log(log_path, {"event": "real_finetuned_training_completed", **result})
    write_json(summary_path, result)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    coverage = validate_dataset(args.dataset_dir)
    args.output_dir.expanduser().mkdir(parents=True, exist_ok=True)
    if args.write_launch_config or args.ack_long_run or args.execute_training:
        args.log_dir.expanduser().mkdir(parents=True, exist_ok=True)
    plan_path = write_json(_resolve_plan_path(args), build_training_plan(args, coverage))
    launch_config_path = None
    launch_config = None
    if args.write_launch_config or args.ack_long_run or args.execute_training:
        launch_config = build_launch_config(args, coverage)
        launch_config_path = write_json(_resolve_launch_config_path(args), launch_config)
    training_result = None
    if args.execute_training:
        if launch_config is None:
            launch_config = build_launch_config(args, coverage)
            launch_config_path = write_json(_resolve_launch_config_path(args), launch_config)
        if launch_config["blockers"]:
            training_result = {
                "status": "blocked_before_training",
                "decision": "blocked_before_training",
                "wrote_checkpoint": False,
                "blockers": launch_config["blockers"],
            }
        elif launch_config["decision"] == "skipped_existing_checkpoint":
            training_result = (
                execute_real_finetuned_training_loop(args, coverage)
                if _is_real_finetuned_request(args)
                else execute_training_loop(args, coverage)
            )
        else:
            training_result = (
                execute_real_finetuned_training_loop(args, coverage)
                if _is_real_finetuned_request(args)
                else execute_training_loop(args, coverage)
            )
        launch_config["training_result"] = training_result
        launch_config["decision"] = training_result["decision"]
        launch_config["starts_training"] = training_result["status"] == "training_completed"
        launch_config["writes_checkpoint"] = bool(training_result["wrote_checkpoint"])
        launch_config_path = write_json(_resolve_launch_config_path(args), launch_config)
    return {
        "training_plan_path": str(plan_path),
        "launch_config_path": None if launch_config_path is None else str(launch_config_path),
        "launch_config": launch_config,
        "training_result": training_result,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--training-plan-output", type=Path)
    parser.add_argument("--launch-config-output", type=Path)
    parser.add_argument("--pretrained-model", default="NeoQuasar/Kronos-small")
    parser.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    parser.add_argument("--device", choices=["auto", "mps", "cuda", "cpu"], default="auto")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--checkpoint-interval", type=int, default=100)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--artifact-kind", choices=["smoke", "real-finetuned"], default="smoke")
    parser.add_argument("--allow-canonical-finetuned", action="store_true")
    parser.add_argument("--lambda-rank", type=float, default=0.7)
    parser.add_argument("--lambda-recon", type=float, default=0.3)
    parser.add_argument("--ack-long-run", action="store_true")
    parser.add_argument("--ack-model-write", action="store_true")
    parser.add_argument("--write-launch-config", action="store_true")
    parser.add_argument("--execute-training", action="store_true")
    parser.add_argument("--print", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    print(f"wrote training plan: {result['training_plan_path']}")
    if result["launch_config_path"]:
        print(f"wrote launch config: {result['launch_config_path']}")
    if args.print:
        print(json.dumps(result["launch_config"] or {}, ensure_ascii=False, indent=2))
    if args.execute_training:
        training_result = result["training_result"] or {}
        if training_result.get("status") == "training_completed":
            print(f"training completed; checkpoint: {training_result['best_checkpoint']}")
            return 0
        if training_result.get("status") == "skipped_existing_checkpoint":
            print(f"skipped existing checkpoint: {training_result['best_checkpoint']}")
            return 0
        print(f"blocked: {training_result.get('blockers') or training_result.get('reason')}")
        return 2
    if not args.ack_long_run:
        print("dry-run only; pass --ack-long-run before requesting a training launch config.")
    else:
        print("launch config is ready, but no training was started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
