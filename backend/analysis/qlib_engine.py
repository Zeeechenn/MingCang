"""
LightGBM Alpha 量化引擎（Qlib-style，不依赖 Qlib 数据基础设施）

训练：python3 -m backend.analysis.qlib_engine --train
人工晋升：python3 -m backend.analysis.qlib_engine --promote-candidate REPORT --confirm-human REVIEWER
推理：qlib_score(df_raw) → dict  (score: -100 ~ +100)

模型文件：~/.mingcang/models/lgbm_alpha.pkl
"""
import hashlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.config import settings
from backend.data.qlib_data import FEATURE_COLS, PRODUCTION_FEATURE_COLS, build_inference_features

logger = logging.getLogger(__name__)

_MINGCANG_MODEL_DIR = Path.home() / ".mingcang" / "models"
MODEL_DIR = _MINGCANG_MODEL_DIR
MODEL_PATH = MODEL_DIR / "lgbm_alpha.pkl"
CANDIDATE_MODEL_PATH = MODEL_DIR / "lgbm_alpha_candidate.pkl"
CANDIDATE_REPORT_PATH = MODEL_DIR / "lgbm_alpha_candidate.validation.json"
PROMOTION_FORWARD_MAX_AGE_DAYS = 7
PROMOTION_FORWARD_MIN_OBSERVATIONS = 20
PROMOTION_MIN_COVERAGE_RATIO = 0.95


def daily_rank_groups(df: pd.DataFrame) -> list[int]:
    """Return LightGBM rank group sizes in current row order, grouped by date."""
    if "date" not in df.columns:
        return [len(df)]
    return df.groupby("date", sort=False).size().astype(int).tolist()


def make_rank_labels(df: pd.DataFrame) -> pd.Series:
    """Convert forward returns into per-date ordinal labels for LambdaRank."""
    if "date" not in df.columns:
        return df["label"].rank(method="first").sub(1).astype(int)
    return (
        df.groupby("date", sort=False)["label"]
        .rank(method="first")
        .sub(1)
        .astype(int)
    )


def _time_split(df: pd.DataFrame, split_ratio: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by date so a trading day is never split across train/validation."""
    if "date" not in df.columns:
        split = int(len(df) * split_ratio)
        return df.iloc[:split], df.iloc[split:]

    ordered = df.sort_values(["date", "symbol"] if "symbol" in df.columns else ["date"])
    dates = pd.Series(ordered["date"].drop_duplicates().values)
    split_idx = max(1, int(len(dates) * split_ratio))
    split_date = dates.iloc[split_idx - 1]
    train_df = ordered[ordered["date"] <= split_date]
    val_df = ordered[ordered["date"] > split_date]
    if val_df.empty:
        split = int(len(ordered) * split_ratio)
        return ordered.iloc[:split], ordered.iloc[split:]
    return train_df, val_df


_MODEL_CACHE: dict = {
    "path_mtime": None,
    "model": None,
    "feature_cols": None,
    "disabled_reason": None,
}


def _model_feature_count(model: Any) -> int | None:
    return getattr(model, "n_features_in_", getattr(model, "n_features_", None))


def _load_model_unchecked(path: Path = MODEL_PATH) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, None
    try:
        return joblib.load(path), None
    except Exception as e:
        return None, f"load_error: {e}"


def _feature_cols_for_model(model: Any) -> tuple[list[str] | None, dict[str, Any]]:
    actual = _model_feature_count(model)
    status = {
        "n_features_model": actual,
        "n_features_current_candidate": len(FEATURE_COLS),
        "n_features_production": len(PRODUCTION_FEATURE_COLS),
    }
    if actual is None:
        return list(FEATURE_COLS), {
            **status,
            "n_features_validation": len(FEATURE_COLS),
            "model_dim_status": "unknown_assume_current_candidate_feature_cols",
        }
    if actual == len(FEATURE_COLS):
        return list(FEATURE_COLS), {
            **status,
            "n_features_validation": len(FEATURE_COLS),
            "model_dim_status": "current_candidate_feature_cols",
        }
    if actual == len(PRODUCTION_FEATURE_COLS):
        return list(PRODUCTION_FEATURE_COLS), {
            **status,
            "n_features_validation": len(PRODUCTION_FEATURE_COLS),
            "model_dim_status": "legacy_production_feature_cols",
        }
    return None, {**status, "model_dim_status": "feature_dim_mismatch"}


def _load_model() -> Any | None:
    """Load LightGBM model from disk, returning None if missing/corrupt/dim-mismatch.

    Caches result (keyed by mtime) and only warns once per model version so a
    stale feature-dim model doesn't spam logs on every inference call.
    """
    if not MODEL_PATH.exists():
        # 2026-06-06 rebrand 曾因路径切换+模型未迁移触发无声降级近一个月：
        # 文件缺失和加载失败一样属于降级，必须显式告警（一次，不刷屏）。
        if _MODEL_CACHE["path_mtime"] != "missing":
            _MODEL_CACHE["path_mtime"] = "missing"
            _MODEL_CACHE["model"] = None
            _MODEL_CACHE["feature_cols"] = None
            _MODEL_CACHE["disabled_reason"] = "model_file_missing"
            logger.warning(
                "quant model file missing at %s — quant_score degrades to "
                "momentum placeholder (placeholder_v0)",
                MODEL_PATH,
            )
        return None

    mtime = MODEL_PATH.stat().st_mtime
    if _MODEL_CACHE["path_mtime"] == mtime:
        return _MODEL_CACHE["model"]

    _MODEL_CACHE["path_mtime"] = mtime
    _MODEL_CACHE["model"] = None
    _MODEL_CACHE["feature_cols"] = None
    _MODEL_CACHE["disabled_reason"] = None

    model, load_error = _load_model_unchecked()
    if load_error:
        _MODEL_CACHE["disabled_reason"] = load_error
        logger.warning("load model failed: %s — falling back to momentum", load_error)
        return None

    feature_cols, dim_info = _feature_cols_for_model(model)
    if feature_cols is None:
        actual = dim_info.get("n_features_model")
        _MODEL_CACHE["disabled_reason"] = (
            f"dim_mismatch: model={actual} "
            f"current={len(FEATURE_COLS)} production={len(PRODUCTION_FEATURE_COLS)}"
        )
        logger.warning(
            "Qlib 模型特征维度不匹配 (model=%s, current=%d, production=%d)，已禁用模型并使用动量 fallback；请重训模型",
            actual, len(FEATURE_COLS), len(PRODUCTION_FEATURE_COLS),
        )
        return None

    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["feature_cols"] = feature_cols
    return model


def _momentum_fallback(df: pd.DataFrame) -> dict:
    """模型未训练时的动量占位评分"""
    df = add_all_factors(df)
    last = df.iloc[-1]
    mom5  = (last["close"] / df["close"].iloc[-6]  - 1) * 100 if len(df) >= 6 else 0.0
    mom20 = (last["close"] / df["close"].iloc[-21] - 1) * 100 if len(df) >= 21 else 0.0
    score = float(np.clip((mom5 * 0.6 + mom20 * 0.4) * 5, -100, 100))
    return {
        "score": round(score, 1),
        "model": "placeholder_v0",
        "momentum_5d": round(float(mom5), 2),
        "momentum_20d": round(float(mom20), 2),
    }


def _validation_predictions(
    model,
    val_df: pd.DataFrame,
    feature_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Build validation predictions in the format shared with Qlib validation reports."""
    feature_cols = feature_cols or FEATURE_COLS
    return pd.DataFrame({
        "date": val_df["date"].values if "date" in val_df.columns else range(len(val_df)),
        "symbol": val_df["symbol"].values if "symbol" in val_df.columns else ["__SINGLE__"] * len(val_df),
        "pred": model.predict(val_df[feature_cols]),
        "label": val_df["label"].values,
    })


def _passes_promotion_gate(report: dict, runtime_settings=None) -> bool:
    """Return whether a trained candidate may replace the production model."""
    runtime_settings = settings if runtime_settings is None else runtime_settings
    metrics = report.get("metrics") or {}
    gates = report.get("gates") or {}
    ic = float(metrics.get("ic_mean") or 0.0)
    icir = float(metrics.get("icir") or 0.0)
    monotonic = bool(gates.get("pass_monotonic"))
    pass_ic = ic >= runtime_settings.qlib_train_ic_floor
    pass_icir = icir >= runtime_settings.qlib_train_icir_floor
    pass_monotonic = monotonic or not runtime_settings.qlib_train_require_monotonic
    return pass_ic and pass_icir and pass_monotonic


def _save_model(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def promote_candidate(report_path: Path, *, confirmed_by: str) -> dict:
    """Promote a separately validated candidate after explicit human confirmation."""
    if not confirmed_by.strip():
        raise ValueError("explicit human confirmation is required")
    report = json.loads(Path(report_path).expanduser().read_text(encoding="utf-8"))
    contract = report.get("promotion_contract")
    if not isinstance(contract, dict):
        raise ValueError("validated promotion contract is required")
    required_gates = (
        "performance",
        "nonoverlap",
        "stride",
        "fresh_forward",
        "provenance",
        "data_quality",
    )
    failed_gates = [
        name
        for name in required_gates
        if not isinstance(contract.get(name), dict)
        or contract[name].get("passed") is not True
    ]
    if failed_gates:
        raise ValueError(f"promotion contract gates failed or missing: {', '.join(failed_gates)}")
    if not _passes_promotion_gate(report.get("validation") or {}):
        raise ValueError("promotion performance metrics do not satisfy current thresholds")
    blockers = contract.get("blockers")
    if not isinstance(blockers, list) or blockers:
        raise ValueError("promotion contract blockers must be an empty list")
    if contract.get("promotable") is not True:
        raise ValueError("promotion contract must explicitly mark the candidate promotable")
    nonoverlap = contract["nonoverlap"]
    try:
        train_end = datetime.fromisoformat(str(nonoverlap["train_end"]))
        forward_start = datetime.fromisoformat(str(nonoverlap["forward_start"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("nonoverlap evidence requires valid train_end and forward_start") from exc
    if train_end >= forward_start:
        raise ValueError("nonoverlap evidence overlaps the training and forward windows")
    stride = contract["stride"]
    try:
        prediction_stride_days = int(stride["prediction_stride_days"])
        label_horizon_days = int(stride["label_horizon_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("stride evidence requires integer prediction_stride_days and label_horizon_days") from exc
    if label_horizon_days <= 0 or prediction_stride_days < label_horizon_days:
        raise ValueError("stride evidence allows overlapping forward labels")
    fresh_forward = contract["fresh_forward"]
    try:
        evaluated_at = datetime.fromisoformat(str(fresh_forward["evaluated_at"]))
        max_age_days = int(fresh_forward["max_age_days"])
        observations = int(fresh_forward["observations"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("fresh_forward evidence is incomplete") from exc
    if evaluated_at.tzinfo is None:
        raise ValueError("fresh_forward evaluated_at must include a timezone")
    age = datetime.now(UTC) - evaluated_at.astimezone(UTC)
    if (
        max_age_days <= 0
        or max_age_days > PROMOTION_FORWARD_MAX_AGE_DAYS
        or age.total_seconds() < 0
        or age > timedelta(days=max_age_days)
        or observations < PROMOTION_FORWARD_MIN_OBSERVATIONS
    ):
        raise ValueError("fresh_forward evidence is stale or insufficient")
    provenance = contract["provenance"]
    dataset_sha256 = str(provenance.get("dataset_sha256") or "")
    code_version = str(provenance.get("code_version") or "").strip()
    if (
        len(dataset_sha256) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in dataset_sha256)
        or not code_version
    ):
        raise ValueError("provenance evidence requires dataset_sha256 and code_version")
    data_quality = contract["data_quality"]
    try:
        coverage_ratio = float(data_quality["coverage_ratio"])
        feature_null_cells = int(data_quality["feature_null_cells"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("data_quality evidence is incomplete") from exc
    if coverage_ratio < PROMOTION_MIN_COVERAGE_RATIO or feature_null_cells != 0:
        raise ValueError("data_quality evidence does not meet coverage and null requirements")
    candidate_meta = report.get("candidate_model")
    if not isinstance(candidate_meta, dict):
        raise ValueError("candidate model metadata is required")
    try:
        reported_candidate_path = Path(candidate_meta["path"]).expanduser().resolve()
        expected_candidate_path = CANDIDATE_MODEL_PATH.expanduser().resolve()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate model path metadata is invalid") from exc
    if reported_candidate_path != expected_candidate_path:
        raise ValueError("candidate model path does not match the configured candidate artifact")
    if not CANDIDATE_MODEL_PATH.exists():
        raise ValueError("candidate model artifact is missing")
    reported_sha256 = str(candidate_meta.get("sha256") or "")
    actual_sha256 = _sha256_file(CANDIDATE_MODEL_PATH)
    if reported_sha256 != actual_sha256:
        raise ValueError("candidate model sha256 does not match the validated artifact")
    candidate_model, load_error = _load_model_unchecked(CANDIDATE_MODEL_PATH)
    if load_error or candidate_model is None:
        raise ValueError(f"candidate model cannot be loaded: {load_error or 'empty model'}")
    feature_cols, dim_info = _feature_cols_for_model(candidate_model)
    if feature_cols is None:
        raise ValueError(f"candidate model feature dimension is incompatible: {dim_info}")
    if float(settings.weight_quant) != 0.0:
        raise ValueError("production weight_quant must remain 0 during model promotion")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_suffix(f"{MODEL_PATH.suffix}.promote.tmp")
    try:
        with CANDIDATE_MODEL_PATH.open("rb") as source, temporary.open("wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, MODEL_PATH)
    finally:
        temporary.unlink(missing_ok=True)

    _MODEL_CACHE.update({
        "path_mtime": None,
        "model": None,
        "feature_cols": None,
        "disabled_reason": None,
    })
    promoted_at = datetime.now(UTC).isoformat(timespec="seconds")
    logger.warning(
        "candidate model promoted by %s at %s; production weight_quant remains 0",
        confirmed_by,
        promoted_at,
    )
    return {
        "status": "promoted",
        "confirmed_by": confirmed_by.strip(),
        "promoted_at": promoted_at,
        "model_path": str(MODEL_PATH),
        "candidate_sha256": actual_sha256,
        "validation_report": str(Path(report_path).expanduser()),
        "production_weight_quant": float(settings.weight_quant),
    }


def qlib_score(df_raw: pd.DataFrame, symbol: str | None = None, db=None) -> dict:
    """
    输入日线 OHLCV DataFrame，返回量化信号得分字典。
    score: -100 ~ +100
    """
    model = _load_model()

    if model is None:
        return _momentum_fallback(df_raw)

    try:
        feats = build_inference_features(df_raw, symbol=symbol, db=db)
        feature_cols = _MODEL_CACHE.get("feature_cols") or FEATURE_COLS
        feats = feats[feature_cols]
        if feats.isnull().any():
            logger.debug("inference features contain NaN, using fallback")
            return _momentum_fallback(df_raw)

        X = pd.DataFrame([feats], columns=feature_cols)
        raw_pred = float(model.predict(X)[0])        # 预测 5 日前瞻收益
        # ±5% 映射为 ±100 分（超出截断）
        score = float(np.clip(raw_pred * 2000, -100, 100))
        return {
            "score": round(score, 1),
            "model": "lgbm_alpha_v1",
            "raw_pred": round(raw_pred, 4),
        }
    except Exception as e:
        logger.warning("qlib_score inference error: %s", e)
        return _momentum_fallback(df_raw)


def train(
    db,
    n_estimators: int = 300,
    learning_rate: float = 0.05,
    model_type: str = "regression",
    include_inactive: bool = False,
) -> bool:
    """
    训练 LightGBM Alpha 模型并保存到磁盘。
    调用方：
      - 调度器（每周六 09:00）
      - 手动：python3 -m backend.analysis.qlib_engine --train
      - API：POST /api/model/train
      - M26.1 扩盘重训：python3 -m backend.analysis.qlib_engine --train --include-inactive

    include_inactive: True 时纳入 active=False 的扩盘股（M26.1 用，不影响生产自选股）。
    Returns True on success.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        logger.error("lightgbm 未安装，运行：pip3 install lightgbm")
        return False

    from backend.data.qlib_data import build_training_data

    logger.info("构建训练数据… include_inactive=%s", include_inactive)
    df = build_training_data(db, include_inactive=include_inactive)

    if len(df) < 200:
        logger.warning(
            "训练数据不足（%d 行），跳过。需要 ≥200 行（建议先回填至少 1 年数据）。",
            len(df),
        )
        return False

    train_df, val_df = _time_split(df)
    X_train, X_val = train_df[FEATURE_COLS], val_df[FEATURE_COLS]

    if model_type == "ranker":
        y_train = make_rank_labels(train_df)
        y_val = make_rank_labels(val_df)
        model = lgb.LGBMRanker(
            objective="lambdarank",
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            label_gain=list(range(int(max(y_train.max(), y_val.max())) + 1)),
            num_leaves=63,
            min_child_samples=50,
            subsample=0.8,
            colsample_bytree=0.7,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(
            X_train,
            y_train,
            group=daily_rank_groups(train_df),
            eval_set=[(X_val, y_val)],
            eval_group=[daily_rank_groups(val_df)],
            callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
    else:
        y_train, y_val = train_df["label"], val_df["label"]
        model = lgb.LGBMRegressor(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )

    # Information Coefficient（预测与实际收益的相关性）
    preds = model.predict(X_val)
    ic = float(pd.Series(preds).corr(pd.Series(val_df["label"].values)))
    logger.info(
        "训练完成 | 模型: %s | 样本: %d 行（训练 %d / 验证 %d）| IC = %.4f",
        model_type, len(df), len(train_df), len(val_df), ic,
    )

    _save_model(model, CANDIDATE_MODEL_PATH)
    logger.info("候选模型已保存：%s", CANDIDATE_MODEL_PATH)

    from backend.backtest.alphalens_qlib import build_validation_report

    validation = build_validation_report(
        _validation_predictions(model, val_df),
        label=f"train_candidate:{model_type}",
        sample={
            "n_rows": len(df),
            "train_rows": len(train_df),
            "validation_rows": len(val_df),
            "n_stocks": int(df["symbol"].nunique()) if "symbol" in df.columns else 1,
        },
    )
    metrics = validation.get("metrics") or {}
    logger.info(
        "候选模型验证 | IC=%s ICIR=%s monotonic=%s",
        metrics.get("ic_mean"),
        metrics.get("icir"),
        (validation.get("gates") or {}).get("pass_monotonic"),
    )
    data_quality_passed = bool(
        not df[FEATURE_COLS + ["label"]].isna().any().any()
        and len(train_df) > 0
        and len(val_df) > 0
    )
    training_blockers = [
        "stride_validation_missing",
        "fresh_forward_validation_missing",
        "provenance_validation_missing",
    ]
    if not _passes_promotion_gate(validation):
        training_blockers.append("performance_gate_failed")
    if not data_quality_passed:
        training_blockers.append("data_quality_gate_failed")
    candidate_report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "candidate_model": {
            "path": str(CANDIDATE_MODEL_PATH),
            "sha256": _sha256_file(CANDIDATE_MODEL_PATH),
            "model_type": model_type,
            "feature_count": len(FEATURE_COLS),
        },
        "validation": validation,
        "promotion_contract": {
            "performance": {"passed": _passes_promotion_gate(validation)},
            "nonoverlap": {
                "passed": bool(
                    "date" in train_df.columns
                    and "date" in val_df.columns
                    and train_df["date"].max() < val_df["date"].min()
                ),
            },
            "stride": {"passed": False},
            "fresh_forward": {"passed": False},
            "provenance": {"passed": False},
            "data_quality": {"passed": data_quality_passed},
            "blockers": training_blockers,
            "promotable": False,
        },
    }
    _write_json_atomic(candidate_report, CANDIDATE_REPORT_PATH)
    logger.info("候选模型验证报告已保存：%s", CANDIDATE_REPORT_PATH)
    logger.info("候选模型训练完成，等待独立人工晋升；生产模型未变更：%s", MODEL_PATH)
    return True


if __name__ == "__main__":
    import argparse
    import json
    import logging as _logging
    import sys

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--ranker", action="store_true")
    parser.add_argument("--include-inactive", action="store_true",
                        help="纳入 active=False 的扩盘股训练（M26.1 用）")
    parser.add_argument("--validate-production", action="store_true")
    parser.add_argument("--promote-candidate", type=Path, metavar="REPORT")
    parser.add_argument("--confirm-human", default="", metavar="REVIEWER")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()

    if args.train:
        from backend.data.database import SessionLocal
        db = SessionLocal()
        try:
            ok = train(db,
                       model_type="ranker" if args.ranker else "regression",
                       include_inactive=args.include_inactive)
            sys.exit(0 if ok else 1)
        finally:
            db.close()

    if args.validate_production:
        from backend.backtest.quant_baseline import build_current_model_validation
        from backend.data.database import SessionLocal

        db = SessionLocal()
        try:
            report = build_current_model_validation(db)
        finally:
            db.close()
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.json_output:
            out = Path(args.json_output).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
            print(f"production validation report written: {out}")
        else:
            print(payload)
        sys.exit(0 if report.get("status") == "ok" else 1)

    if args.promote_candidate:
        try:
            result = promote_candidate(
                args.promote_candidate,
                confirmed_by=args.confirm_human,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("candidate promotion rejected: %s", exc)
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    parser.print_help()
    sys.exit(1)
