"""
LightGBM Alpha 量化引擎（Qlib-style，不依赖 Qlib 数据基础设施）

训练：python3 -m backend.analysis.qlib_engine --train
推理：qlib_score(df_raw) → dict  (score: -100 ~ +100)

模型文件：~/.stock-sage/models/lgbm_alpha.pkl
"""
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.config import settings
from backend.data.qlib_data import FEATURE_COLS, PRODUCTION_FEATURE_COLS, build_inference_features

logger = logging.getLogger(__name__)

MODEL_DIR = Path.home() / ".stock-sage" / "models"
MODEL_PATH = MODEL_DIR / "lgbm_alpha.pkl"
CANDIDATE_MODEL_PATH = MODEL_DIR / "lgbm_alpha_candidate.pkl"


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
    if not _passes_promotion_gate(validation):
        logger.warning(
            "候选模型未通过 promotion gate，保留旧生产模型：IC=%s (floor %.4f), ICIR=%s (floor %.4f), monotonic=%s",
            metrics.get("ic_mean"),
            settings.qlib_train_ic_floor,
            metrics.get("icir"),
            settings.qlib_train_icir_floor,
            (validation.get("gates") or {}).get("pass_monotonic"),
        )
        return False

    _save_model(model, MODEL_PATH)
    _MODEL_CACHE.update({"path_mtime": None, "model": None, "feature_cols": None, "disabled_reason": None})
    logger.info("候选模型通过 promotion gate，已晋升为生产模型：%s", MODEL_PATH)
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
        from backend.data.database import SessionLocal
        from backend.tools.m26_quant_baseline import build_current_model_validation

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

    parser.print_help()
    sys.exit(1)
