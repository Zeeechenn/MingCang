import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from backend.analysis import qlib_engine


class _FakeRegressor:
    def __init__(self, **kwargs):
        pass

    def fit(self, *args, **kwargs):
        return self

    def predict(self, values):
        return np.linspace(-0.01, 0.01, len(values))


def _training_panel() -> pd.DataFrame:
    rows = 250
    panel = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=rows),
        "symbol": [f"{index % 10:06d}" for index in range(rows)],
        "label": np.linspace(-0.02, 0.02, rows),
    })
    for feature in qlib_engine.FEATURE_COLS:
        panel[feature] = np.linspace(0.0, 1.0, rows)
    return panel


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_report(candidate_path) -> dict:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    return {
        "candidate_model": {
            "path": str(candidate_path),
            "sha256": _sha256(candidate_path),
        },
        "validation": {
            "metrics": {"ic_mean": 0.08, "icir": 0.8},
            "gates": {"pass_monotonic": True},
        },
        "promotion_contract": {
            "performance": {"passed": True},
            "nonoverlap": {
                "passed": True,
                "train_end": "2026-05-31",
                "forward_start": "2026-06-06",
            },
            "stride": {
                "passed": True,
                "prediction_stride_days": 5,
                "label_horizon_days": 5,
            },
            "fresh_forward": {
                "passed": True,
                "evaluated_at": now,
                "max_age_days": 7,
                "observations": 20,
            },
            "provenance": {
                "passed": True,
                "dataset_sha256": "a" * 64,
                "code_version": "test-version",
            },
            "data_quality": {
                "passed": True,
                "coverage_ratio": 1.0,
                "feature_null_cells": 0,
            },
            "blockers": [],
            "promotable": True,
        },
    }


def test_train_writes_candidate_only_and_preserves_production(monkeypatch, tmp_path):
    from backend.backtest import alphalens_qlib
    from backend.data import qlib_data

    candidate_path = tmp_path / "candidate.pkl"
    production_path = tmp_path / "production.pkl"
    saved_paths = []

    monkeypatch.setitem(sys.modules, "lightgbm", SimpleNamespace(
        LGBMRegressor=_FakeRegressor,
        early_stopping=lambda **kwargs: object(),
        log_evaluation=lambda **kwargs: object(),
    ))
    monkeypatch.setattr(qlib_data, "build_training_data", lambda db, include_inactive=False: _training_panel())
    monkeypatch.setattr(alphalens_qlib, "build_validation_report", lambda *args, **kwargs: {
        "metrics": {"ic_mean": 0.08, "icir": 0.8},
        "gates": {"pass_monotonic": True},
    })
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)
    monkeypatch.setattr(qlib_engine, "CANDIDATE_REPORT_PATH", tmp_path / "candidate.validation.json")
    monkeypatch.setattr(qlib_engine, "MODEL_PATH", production_path)
    monkeypatch.setattr(qlib_engine, "_save_model", lambda model, path: saved_paths.append(path))
    monkeypatch.setattr(qlib_engine, "_sha256_file", lambda path: "candidate-sha")

    assert qlib_engine.train(object()) is True
    assert saved_paths == [candidate_path]


def test_train_writes_non_promoting_candidate_validation_artifact(monkeypatch, tmp_path):
    from backend.backtest import alphalens_qlib
    from backend.data import qlib_data

    candidate_path = tmp_path / "candidate.pkl"
    report_path = tmp_path / "candidate.validation.json"
    monkeypatch.setitem(sys.modules, "lightgbm", SimpleNamespace(
        LGBMRegressor=_FakeRegressor,
        early_stopping=lambda **kwargs: object(),
        log_evaluation=lambda **kwargs: object(),
    ))
    monkeypatch.setattr(qlib_data, "build_training_data", lambda db, include_inactive=False: _training_panel())
    monkeypatch.setattr(alphalens_qlib, "build_validation_report", lambda *args, **kwargs: {
        "metrics": {"ic_mean": 0.08, "icir": 0.8},
        "gates": {"pass_monotonic": True},
    })
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)
    monkeypatch.setattr(qlib_engine, "CANDIDATE_REPORT_PATH", report_path, raising=False)
    monkeypatch.setattr(qlib_engine, "_save_model", lambda model, path: path.write_bytes(b"candidate"))

    assert qlib_engine.train(object()) is True

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate_model"]["sha256"]
    assert report["candidate_model"]["path"] == str(candidate_path)
    assert report["promotion_contract"]["promotable"] is False
    assert "fresh_forward_validation_missing" in report["promotion_contract"]["blockers"]


def test_promote_candidate_requires_explicit_human_confirmation(tmp_path):
    with pytest.raises(ValueError, match="human confirmation"):
        qlib_engine.promote_candidate(tmp_path / "validated.json", confirmed_by="")


def test_promote_candidate_rejects_missing_promotion_contract(tmp_path):
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps({"candidate_model": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="promotion contract"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rejects_failed_fresh_forward_gate(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["fresh_forward"]["passed"] = False
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="fresh_forward"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rechecks_performance_metrics(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["validation"]["metrics"]["ic_mean"] = 0.0
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="performance"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rejects_any_reported_blocker(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["blockers"] = ["price_rows_missing_provenance"]
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="blockers"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rechecks_nonoverlap_dates(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["nonoverlap"]["forward_start"] = "2026-05-30"
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="nonoverlap"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rechecks_forward_stride(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["stride"]["prediction_stride_days"] = 1
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="stride"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rechecks_forward_freshness(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["fresh_forward"]["evaluated_at"] = (
        datetime.now(UTC) - timedelta(days=30)
    ).isoformat(timespec="seconds")
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="fresh_forward"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_requires_provenance_evidence(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["provenance"]["dataset_sha256"] = ""
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="provenance"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_rechecks_data_quality(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    candidate_path.write_bytes(b"candidate")
    report = _validated_report(candidate_path)
    report["promotion_contract"]["data_quality"]["feature_null_cells"] = 1
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)

    with pytest.raises(ValueError, match="data_quality"):
        qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")


def test_promote_candidate_atomically_replaces_production_and_clears_cache(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.pkl"
    production_path = tmp_path / "production.pkl"
    joblib.dump(_FakeRegressor(), candidate_path)
    production_path.write_bytes(b"old-production")
    report = _validated_report(candidate_path)
    report_path = tmp_path / "validated.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    cache = {
        "path_mtime": 123,
        "model": object(),
        "feature_cols": ["stale"],
        "disabled_reason": "stale",
    }
    monkeypatch.setattr(qlib_engine, "CANDIDATE_MODEL_PATH", candidate_path)
    monkeypatch.setattr(qlib_engine, "MODEL_PATH", production_path)
    monkeypatch.setattr(qlib_engine, "_MODEL_CACHE", cache)

    result = qlib_engine.promote_candidate(report_path, confirmed_by="reviewer")

    assert result["status"] == "promoted"
    assert result["confirmed_by"] == "reviewer"
    assert production_path.read_bytes() == candidate_path.read_bytes()
    assert candidate_path.exists()
    assert cache == {
        "path_mtime": None,
        "model": None,
        "feature_cols": None,
        "disabled_reason": None,
    }
    assert qlib_engine.settings.weight_quant == 0.0


def test_promote_candidate_cli_requires_named_human_confirmation(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.analysis.qlib_engine",
            "--promote-candidate",
            str(tmp_path / "validated.json"),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "human confirmation" in (result.stdout + result.stderr)
