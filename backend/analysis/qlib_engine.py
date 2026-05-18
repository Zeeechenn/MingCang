"""
LightGBM Alpha 量化引擎（Qlib-style，不依赖 Qlib 数据基础设施）

训练：python3 -m backend.analysis.qlib_engine --train
推理：qlib_score(df_raw) → dict  (score: -100 ~ +100)

模型文件：~/.stock-sage/models/lgbm_alpha.pkl
"""
import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from backend.analysis.factors import add_all_factors
from backend.data.qlib_data import FEATURE_COLS, build_inference_features

logger = logging.getLogger(__name__)

MODEL_DIR = Path.home() / ".stock-sage" / "models"
MODEL_PATH = MODEL_DIR / "lgbm_alpha.pkl"


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


_MODEL_CACHE: dict = {"path_mtime": None, "model": None, "disabled_reason": None}


def _load_model() -> object | None:
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
    _MODEL_CACHE["disabled_reason"] = None

    try:
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
    except Exception as e:
        _MODEL_CACHE["disabled_reason"] = f"load_error: {e}"
        logger.warning("load model failed: %s — falling back to momentum", e)
        return None

    expected = len(FEATURE_COLS)
    actual = getattr(model, "n_features_in_", getattr(model, "n_features_", None))
    if actual is not None and actual != expected:
        _MODEL_CACHE["disabled_reason"] = f"dim_mismatch: model={actual} cols={expected}"
        logger.warning(
            "Qlib 模型特征维度不匹配 (model=%d, FEATURE_COLS=%d)，已禁用模型并使用动量 fallback；请重训模型",
            actual, expected,
        )
        return None

    _MODEL_CACHE["model"] = model
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
        if feats.isnull().any():
            logger.debug("inference features contain NaN, using fallback")
            return _momentum_fallback(df_raw)

        X = pd.DataFrame([feats], columns=FEATURE_COLS)
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
) -> bool:
    """
    训练 LightGBM Alpha 模型并保存到磁盘。
    调用方：
      - 调度器（每周六 09:00）
      - 手动：python3 -m backend.analysis.qlib_engine --train
      - API：POST /api/model/train

    Returns True on success.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        logger.error("lightgbm 未安装，运行：pip3 install lightgbm")
        return False

    from backend.data.qlib_data import build_training_data

    logger.info("构建训练数据…")
    df = build_training_data(db)

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

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    logger.info("模型已保存：%s", MODEL_PATH)
    return True


if __name__ == "__main__":
    import sys
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    if "--train" in sys.argv:
        from backend.data.database import SessionLocal
        db = SessionLocal()
        try:
            ok = train(db, model_type="ranker" if "--ranker" in sys.argv else "regression")
            sys.exit(0 if ok else 1)
        finally:
            db.close()
    else:
        print("用法: python3 -m backend.analysis.qlib_engine --train [--ranker]")
        sys.exit(1)
