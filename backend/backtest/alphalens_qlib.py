"""
Qlib (LightGBM Alpha) 有效性硬验证 — 阶段A 决策点

不依赖 alphalens 库（兼容性问题多）。自己实现 IC、ICIR、分层回测，
让 Qlib 模型的"45%权重"接受可审计的检验。

输出：
  • IC（Information Coefficient）：预测与未来5日收益的 Spearman 相关
  • ICIR：IC 的稳定性（均值/标准差）
  • 分层回测：按预测分位数分5组，看 Top-Bottom 是否有显著价差
  • Walk-forward：滚动训练-预测-评估

判断标准：
  • IC 均值 > 0.03 + ICIR > 0.3 + 分层单调性 → Qlib 有效，保留并升级
  • 否则 → 阶段B 把 Qlib 权重归零，技术60%+情感40%

用法：
  PYTHONPATH=. python3 backend/backtest/alphalens_qlib.py
  PYTHONPATH=. python3 backend/backtest/alphalens_qlib.py --walk-forward
"""
from __future__ import annotations
import argparse
import warnings
from typing import Any
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")

from backend.data.database import SessionLocal, Stock, Price
from backend.data.qlib_data import _build_features, FEATURE_COLS


def load_panel(db) -> pd.DataFrame:
    """构造跨股票面板：行 = (symbol, date)，列 = features + label"""
    stocks = db.query(Stock).filter(Stock.active == True, Stock.market == "CN").all()
    frames = []
    for s in stocks:
        rows = (db.query(Price)
                .filter(Price.symbol == s.symbol)
                .order_by(Price.date.asc()).all())
        if len(rows) < 120:
            continue
        df = pd.DataFrame([{
            "date": r.date,
            "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume or 0,
        } for r in rows]).set_index("date")
        df = _build_features(df)
        df["symbol"] = s.symbol
        df["name"] = s.name
        df["date"] = df.index
        frames.append(df.reset_index(drop=True))
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.dropna(subset=FEATURE_COLS + ["label"])
    panel["date"] = pd.to_datetime(panel["date"])
    return panel


def train_lgbm(X_train, y_train, X_val, y_val) -> Any:
    """Train a LightGBM regressor with early stopping on the validation set."""
    try:
        import lightgbm as lgb
    except ImportError:
        raise RuntimeError("缺少 lightgbm，pip install lightgbm")
    model = lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
        random_state=42, n_jobs=-1, verbose=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=0)])
    return model


def cross_sectional_ic(predictions: pd.DataFrame) -> pd.Series:
    """按日横截面 Spearman IC"""
    daily_ic = []
    for date, group in predictions.groupby("date"):
        if len(group) < 3 or group["pred"].std() < 1e-9 or group["label"].std() < 1e-9:
            continue
        ic, _ = spearmanr(group["pred"], group["label"])
        daily_ic.append((date, ic))
    return pd.Series(dict(daily_ic), name="ic")


def quantile_returns(predictions: pd.DataFrame, n_groups: int = 5) -> pd.DataFrame:
    """按预测值分位数分层，看每层的平均实际收益"""
    rows = []
    for date, group in predictions.groupby("date"):
        if len(group) < n_groups:
            continue
        group = group.copy()
        try:
            group["bucket"] = pd.qcut(group["pred"], n_groups, labels=False, duplicates="drop")
        except ValueError:
            continue
        for b, sub in group.groupby("bucket"):
            rows.append({"date": date, "bucket": int(b), "ret": sub["label"].mean()})
    return pd.DataFrame(rows)


def report(predictions: pd.DataFrame, label: str = "") -> None:
    """Print IC, ICIR, quantile returns, and verdict for a predictions DataFrame."""
    ic = cross_sectional_ic(predictions)
    if len(ic) < 5:
        print(f"  [{label}] IC 样本不足({len(ic)} 个交易日)，无法评估")
        return

    ic_mean = ic.mean()
    ic_std = ic.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0
    win = (ic > 0).mean()

    print(f"\n  ── {label} ──")
    print(f"    样本日数:    {len(ic)}")
    print(f"    IC 均值:    {ic_mean:+.4f}")
    print(f"    IC 标准差:   {ic_std:.4f}")
    print(f"    ICIR:       {icir:+.3f}")
    print(f"    IC > 0 占比: {win * 100:.1f}%")

    print("\n    分层回测（按预测值分5档，平均 5日前瞻收益）:")
    q = quantile_returns(predictions, n_groups=5)
    by_bucket = q.groupby("bucket")["ret"].agg(["mean", "count"])
    for b, row in by_bucket.iterrows():
        bar = "█" * max(1, int(row["mean"] * 1000))
        print(f"      第{b+1}档  收益 {row['mean']:+.4f}  样本 {int(row['count']):4d}  {bar}")

    if len(by_bucket) >= 2:
        spread = by_bucket["mean"].iloc[-1] - by_bucket["mean"].iloc[0]
        print(f"    Top - Bottom 价差: {spread:+.4f}")

    print("\n    ── 阶段A Qlib 验收 ──")
    pass_ic = ic_mean > 0.03
    pass_icir = icir > 0.3
    monotonic = by_bucket["mean"].is_monotonic_increasing if len(by_bucket) >= 3 else False
    print(f"    IC 均值 > 0.03?    {'✅' if pass_ic else '❌'}  (实际 {ic_mean:+.4f})")
    print(f"    ICIR > 0.3?        {'✅' if pass_icir else '❌'}  (实际 {icir:+.3f})")
    print(f"    分层单调递增?       {'✅' if monotonic else '❌'}")
    verdict = "保留并升级（阶段E 接 RD-Agent）" if (pass_ic and pass_icir) else "→ 阶段B 把 Qlib 权重归零，技术60%+情感40%"
    print(f"\n    建议: {verdict}")


def single_split(panel: pd.DataFrame, split_ratio: float = 0.8) -> None:
    """单次时间切分：前 80% 训练，后 20% 评估"""
    panel = panel.sort_values("date").reset_index(drop=True)
    split = int(len(panel) * split_ratio)
    train = panel.iloc[:split]
    test = panel.iloc[split:]

    # 训练集再切 80/20 用于早停
    inner_split = int(len(train) * 0.8)
    X_tr, y_tr = train.iloc[:inner_split][FEATURE_COLS], train.iloc[:inner_split]["label"]
    X_val, y_val = train.iloc[inner_split:][FEATURE_COLS], train.iloc[inner_split:]["label"]
    model = train_lgbm(X_tr, y_tr, X_val, y_val)

    preds = pd.DataFrame({
        "date": test["date"].values,
        "symbol": test["symbol"].values,
        "pred": model.predict(test[FEATURE_COLS]),
        "label": test["label"].values,
    })
    print(f"\n  训练日期: {train['date'].min().date()} ~ {train['date'].max().date()}  ({len(train)} 行)")
    print(f"  测试日期: {test['date'].min().date()} ~ {test['date'].max().date()}  ({len(test)} 行)")
    report(preds, label="时序切分 80/20")


def walk_forward(panel: pd.DataFrame, train_months: int = 12, test_months: int = 2) -> pd.DataFrame:
    """滚动训练-测试，更接近实盘 walk-forward"""
    panel = panel.sort_values("date").reset_index(drop=True)
    start = panel["date"].min()
    end = panel["date"].max()
    all_preds = []
    cur = start + pd.DateOffset(months=train_months)
    iteration = 0
    while cur + pd.DateOffset(months=test_months) <= end:
        train_mask = (panel["date"] >= start) & (panel["date"] < cur)
        test_mask = (panel["date"] >= cur) & (panel["date"] < cur + pd.DateOffset(months=test_months))
        train = panel[train_mask]
        test = panel[test_mask]
        if len(train) < 200 or len(test) < 20:
            cur += pd.DateOffset(months=test_months)
            continue
        inner_split = int(len(train) * 0.8)
        X_tr, y_tr = train.iloc[:inner_split][FEATURE_COLS], train.iloc[:inner_split]["label"]
        X_val, y_val = train.iloc[inner_split:][FEATURE_COLS], train.iloc[inner_split:]["label"]
        model = train_lgbm(X_tr, y_tr, X_val, y_val)
        all_preds.append(pd.DataFrame({
            "date": test["date"].values,
            "symbol": test["symbol"].values,
            "pred": model.predict(test[FEATURE_COLS]),
            "label": test["label"].values,
        }))
        iteration += 1
        cur += pd.DateOffset(months=test_months)
    if not all_preds:
        print("walk-forward 数据不足")
        return
    print(f"\n  walk-forward 共 {iteration} 个窗口")
    report(pd.concat(all_preds, ignore_index=True), label="Walk-Forward")


def main() -> None:
    """CLI entry point: load panel data and run Qlib validation."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--walk-forward", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("\n构建面板数据…")
        panel = load_panel(db)
        if panel.empty:
            print("无可用数据")
            return
        print(f"  面板规模: {len(panel)} 行 × {len(FEATURE_COLS)} 特征 + label")
        print(f"  股票数:   {panel['symbol'].nunique()}")
        print(f"  日期跨度: {panel['date'].min().date()} ~ {panel['date'].max().date()}")

        print("\n" + "=" * 70)
        print("  Qlib (LightGBM Alpha) 有效性验证 — 阶段A 决策点")
        print("=" * 70)

        single_split(panel)
        if args.walk_forward:
            walk_forward(panel)
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
