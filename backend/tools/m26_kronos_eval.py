"""M26.2 Kronos 接入评估。

运行环境：.venv_kronos（含 torch, einops, huggingface_hub, safetensors, scipy）

用法（从 stock-sage 根目录）:
    .venv_kronos/bin/python backend/tools/m26_kronos_eval.py
    .venv_kronos/bin/python backend/tools/m26_kronos_eval.py --model kronos-mini
    .venv_kronos/bin/python backend/tools/m26_kronos_eval.py --context 400 --pred-len 5
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

# ── Kronos import (需从 repo 根或 vendor/kronos 跑) ──────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent
_KRONOS_DIR = _REPO_ROOT / "vendor" / "kronos"


def _load_kronos_classes() -> tuple[Any, Any, Any]:
    model_dir = _KRONOS_DIR / "model"
    if not model_dir.exists():
        raise RuntimeError(
            "Kronos is an optional local experiment dependency. "
            "Clone the upstream Kronos repo to vendor/kronos and run this tool "
            "with the local .venv_kronos environment."
        )
    if str(_KRONOS_DIR) not in sys.path:
        sys.path.insert(0, str(_KRONOS_DIR))
    from model import Kronos, KronosPredictor, KronosTokenizer

    return Kronos, KronosTokenizer, KronosPredictor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────
DB_PATH = _REPO_ROOT / "stock-sage.db"
UNIVERSE_PATH = _REPO_ROOT / "paper_trading" / "test2_universe.json"

# 与 M26.0 保持一致的验证窗口
EVAL_START = "2025-11-01"
EVAL_END = "2026-05-14"
EVERY_N_DAYS = 5          # 每 5 个交易日评估一次
PRED_LEN = 5              # 预测未来 5 个交易日

OUTPUT_DIR = Path.home() / ".stock-sage"
OUTPUT_JSON = OUTPUT_DIR / "m26_kronos_report.json"
OUTPUT_MD = OUTPUT_DIR / "m26_kronos_report.md"

# M26.0 LightGBM 基线（用于对比）
LGBM_IC = 0.020811
LGBM_ICIR = 0.186647
LGBM_IC_POS_RATIO = 0.540845
LGBM_MONOTONIC = False
M27_IC_FLOOR = 0.04
M27_ICIR_FLOOR = 0.40


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def load_universe() -> list[str]:
    data = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    rows = data.get("stocks", data) if isinstance(data, dict) else data
    return [r.get("symbol", r) if isinstance(r, dict) else str(r) for r in rows]


def load_prices(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """从 SQLite 读取 OHLCV，返回 {symbol: df(index=date_str)}。"""
    con = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(symbols))
    sql = f"""
        SELECT symbol, date, open, high, low, close, volume
        FROM prices
        WHERE symbol IN ({placeholders})
          AND date >= ? AND date <= ?
        ORDER BY symbol, date
    """
    df_all = pd.read_sql_query(sql, con, params=symbols + [start, end])
    con.close()

    result: dict[str, pd.DataFrame] = {}
    for sym, grp in df_all.groupby("symbol"):
        grp = grp.set_index("date").sort_index()
        grp.index = pd.to_datetime(grp.index)
        result[sym] = grp[["open", "high", "low", "close", "volume"]].astype(float)
    return result


def get_trading_dates(prices: dict[str, pd.DataFrame],
                      start: str, end: str) -> list[pd.Timestamp]:
    """取所有股票出现过的交易日，逐期推理时再筛选当日可用股票。"""
    all_dates: set[pd.Timestamp] = set()
    for df in prices.values():
        all_dates.update(pd.Timestamp(d) for d in df.index)
    if not all_dates:
        return []
    dates = sorted(d for d in all_dates
                   if pd.Timestamp(start) <= d <= pd.Timestamp(end))
    return dates


# ── 推理 ─────────────────────────────────────────────────────────────────────

def _resolve_finetuned_checkpoint(model_path: Path) -> Path:
    model_path = model_path.expanduser()
    if not model_path.exists():
        raise RuntimeError(
            f"Finetuned Kronos model path does not exist: {model_path}. "
            "Run M27.4 fine-tuning first or pass --finetuned-model-path."
        )
    checkpoint = model_path / "checkpoints" / "best_model"
    resolved = checkpoint if checkpoint.exists() else model_path
    manifest = resolved / "manifest.json"
    if manifest.exists():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Finetuned Kronos checkpoint manifest is invalid: {manifest}") from exc
        if payload.get("checkpoint_kind") == "stocksage_path_a_smoke_model":
            raise RuntimeError(
                f"Finetuned Kronos checkpoint is only a StockSage Path A smoke artifact: {resolved}. "
                "Run real M27.4 Kronos-small fine-tuning before m26_kronos_eval."
            )
    return resolved


def resolve_model_spec(
    model_name: str,
    *,
    finetuned_model_path: Path | None = None,
    tokenizer_path: Path | str | None = None,
) -> dict[str, Any]:
    hub_map = {
        "kronos-mini": ("NeoQuasar/Kronos-Tokenizer-2k", "NeoQuasar/Kronos-mini"),
        "kronos-small": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-small"),
        "kronos-base": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-base"),
    }
    if model_name == "kronos-finetuned":
        checkpoint = _resolve_finetuned_checkpoint(
            finetuned_model_path or Path.home() / ".stock-sage" / "models" / "kronos_finetuned"
        )
        if tokenizer_path is not None:
            tok_id: str | Path = tokenizer_path
        elif (checkpoint / "tokenizer").exists():
            tok_id = checkpoint / "tokenizer"
        else:
            tok_id = "NeoQuasar/Kronos-Tokenizer-base"
        return {
            "tokenizer_id": str(tok_id),
            "model_id": str(checkpoint),
            "model_source": "local_finetuned",
            "model_path": str(checkpoint),
        }
    if model_name not in hub_map:
        raise ValueError(f"Unknown model: {model_name}. Choose from {[*hub_map, 'kronos-finetuned']}")
    tok_id, mdl_id = hub_map[model_name]
    return {
        "tokenizer_id": tok_id,
        "model_id": mdl_id,
        "model_source": "hub_or_cache",
        "model_path": None,
    }


def build_predictor(
    model_name: str,
    context: int,
    *,
    finetuned_model_path: Path | None = None,
    tokenizer_path: Path | str | None = None,
) -> Any:
    Kronos, KronosTokenizer, KronosPredictor = _load_kronos_classes()
    spec = resolve_model_spec(
        model_name,
        finetuned_model_path=finetuned_model_path,
        tokenizer_path=tokenizer_path,
    )
    tok_id = spec["tokenizer_id"]
    mdl_id = spec["model_id"]
    logger.info("加载 tokenizer: %s", tok_id)
    tokenizer = KronosTokenizer.from_pretrained(tok_id)
    logger.info("加载模型: %s", mdl_id)
    model = Kronos.from_pretrained(mdl_id)
    predictor = KronosPredictor(model, tokenizer, max_context=context)
    logger.info("设备: %s", predictor.device)
    return predictor


def predict_returns(
    predictor: Any,
    prices: dict[str, pd.DataFrame],
    eval_dates: list[pd.Timestamp],
    context_len: int,
    pred_len: int,
) -> pd.DataFrame:
    """
    对每个评估日，取各股过去 context_len 条日线作为输入，预测未来 pred_len 天，
    返回 DataFrame: index=eval_date, columns=symbols, values=predicted_return。
    """
    symbols = sorted(prices.keys())
    records = []

    for eval_date in eval_dates:
        # 找 eval_date 在各股 index 中的位置
        x_dfs, x_ts_list, y_ts_list, valid_syms = [], [], [], []

        for sym in symbols:
            df = prices[sym]
            if eval_date not in df.index:
                continue
            idx = df.index.get_loc(eval_date)
            if idx < context_len - 1:
                continue
            # x: 包含 eval_date 当日收盘，预测 eval_date 之后 pred_len 个交易日
            x_df = df.iloc[idx - context_len + 1: idx + 1][["open", "high", "low", "close", "volume"]].copy()
            future = df.index[idx + 1: idx + pred_len + 1]
            if len(future) < pred_len:
                continue
            x_ts = pd.Series(x_df.index)
            y_ts = pd.Series(future)
            x_dfs.append(x_df)
            x_ts_list.append(x_ts)
            y_ts_list.append(y_ts)
            valid_syms.append(sym)

        if not valid_syms:
            continue

        # predict_batch 要求所有 series 同长 —— 上面已统一 context_len
        try:
            pred_dfs = predictor.predict_batch(
                df_list=x_dfs,
                x_timestamp_list=x_ts_list,
                y_timestamp_list=y_ts_list,
                pred_len=pred_len,
                T=1.0,
                top_p=0.9,
                sample_count=1,
                verbose=False,
            )
        except Exception as e:
            logger.warning("eval_date=%s 批量推理失败: %s，改单支", eval_date, e)
            pred_dfs = []
            for xdf, xts, yts in zip(x_dfs, x_ts_list, y_ts_list, strict=False):
                try:
                    pred_dfs.append(predictor.predict(xdf, xts, yts, pred_len,
                                                      T=1.0, top_p=0.9,
                                                      sample_count=1, verbose=False))
                except Exception as e2:
                    logger.warning("  单支失败: %s", e2)
                    pred_dfs.append(None)

        row: dict[str, float] = {}
        for sym, pred_df, x_df in zip(valid_syms, pred_dfs, x_dfs, strict=False):
            if pred_df is None or pred_df.empty:
                continue
            # 预测收益 = 预测期末收盘 / 实际 eval_date 收盘 - 1
            last_close = float(x_df["close"].iloc[-1])
            pred_close_end = float(pred_df["close"].iloc[-1])
            if last_close <= 0 or math.isnan(pred_close_end):
                continue
            row[sym] = pred_close_end / last_close - 1.0

        if row:
            records.append({"date": eval_date, **row})
        logger.info("  %s: %d 支预测完成", eval_date.date(), len(row))

    if not records:
        return pd.DataFrame()
    result = pd.DataFrame(records).set_index("date")
    return result


# ── 指标计算 ──────────────────────────────────────────────────────────────────

def compute_actual_returns(
    prices: dict[str, pd.DataFrame],
    eval_dates: list[pd.Timestamp],
    pred_len: int,
) -> pd.DataFrame:
    """实际未来 pred_len 日收益。"""
    symbols = sorted(prices.keys())
    records = []
    for eval_date in eval_dates:
        row: dict[str, float] = {}
        for sym in symbols:
            df = prices[sym]
            if eval_date not in df.index:
                continue
            idx = df.index.get_loc(eval_date)
            future_idx = idx + pred_len
            if future_idx >= len(df):
                continue
            close_now = float(df["close"].iloc[idx])
            close_fut = float(df["close"].iloc[future_idx])
            if close_now > 0:
                row[sym] = close_fut / close_now - 1.0
        if row:
            records.append({"date": eval_date, **row})
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).set_index("date")


def compute_ic_metrics(pred_ret: pd.DataFrame, actual_ret: pd.DataFrame
                       ) -> dict:
    """逐期计算 Spearman IC，汇总 IC / ICIR / IC>0 占比 / 单调性。"""
    common_dates = pred_ret.index.intersection(actual_ret.index)
    ic_series = []
    for dt in common_dates:
        p = pred_ret.loc[dt].dropna()
        a = actual_ret.loc[dt].dropna()
        common_syms = p.index.intersection(a.index)
        if len(common_syms) < 5:
            continue
        ic, _ = stats.spearmanr(p[common_syms], a[common_syms])
        if not math.isnan(ic):
            ic_series.append(ic)

    if not ic_series:
        return {"ic": float("nan"), "icir": float("nan"),
                "ic_pos_ratio": float("nan"), "monotonic": False,
                "ic_series_len": 0}

    ic_arr = np.array(ic_series)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 1e-9
    icir = ic_mean / (ic_std + 1e-9)
    ic_pos = float(np.mean(ic_arr > 0))

    # 分位收益分析
    quantile_returns = compute_quantile_returns(pred_ret, actual_ret, n_bins=5)
    monotonic = check_monotonic(quantile_returns)

    return {
        "ic": round(ic_mean, 6),
        "icir": round(icir, 6),
        "ic_pos_ratio": round(ic_pos, 6),
        "monotonic": monotonic,
        "ic_series_len": len(ic_series),
        "quantile_returns": quantile_returns,
    }


def compute_quantile_returns(pred_ret: pd.DataFrame, actual_ret: pd.DataFrame,
                              n_bins: int = 5) -> list[float]:
    common_dates = pred_ret.index.intersection(actual_ret.index)
    bin_returns: list[list[float]] = [[] for _ in range(n_bins)]

    for dt in common_dates:
        p = pred_ret.loc[dt].dropna()
        a = actual_ret.loc[dt].dropna()
        common_syms = p.index.intersection(a.index)
        if len(common_syms) < n_bins:
            continue
        p_sorted = p[common_syms].sort_values()
        bin_size = len(p_sorted) // n_bins
        for i in range(n_bins):
            syms_in_bin = p_sorted.iloc[i * bin_size: (i + 1) * bin_size].index
            bin_returns[i].extend(a[syms_in_bin].tolist())

    return [round(float(np.mean(b)) if b else float("nan"), 6) for b in bin_returns]


def check_monotonic(quantile_returns: list[float]) -> bool:
    valid = [v for v in quantile_returns if not math.isnan(v)]
    if len(valid) < 2:
        return False
    return all(valid[i] <= valid[i + 1] for i in range(len(valid) - 1))


# ── 报告生成 ──────────────────────────────────────────────────────────────────

def make_decision(metrics: dict) -> dict:
    ic = metrics.get("ic", float("nan"))
    icir = metrics.get("icir", float("nan"))
    monotonic = metrics.get("monotonic", False)

    beats_lgbm = (not math.isnan(ic) and ic >= LGBM_IC
                  and not math.isnan(icir) and icir >= LGBM_ICIR)
    gate_pass = (not math.isnan(ic) and ic >= 0.02
                 and not math.isnan(icir) and icir >= 0.15)
    m27_gate_pass = (
        not math.isnan(ic)
        and ic >= M27_IC_FLOOR
        and not math.isnan(icir)
        and icir >= M27_ICIR_FLOOR
        and bool(monotonic)
    )

    if beats_lgbm and monotonic:
        verdict = "replace_lgbm"
        action = "进入 M26.3 小权重验证，Kronos 优于 LightGBM 且分位单调"
    elif gate_pass and not beats_lgbm:
        verdict = "parallel_test"
        action = "通过 gate 但未超越 LightGBM，建议 M26.3 并行小权重观察"
    else:
        verdict = "defer"
        action = "未通过 IC gate 或分位不单调，暂不接入生产"

    return {
        "verdict": verdict,
        "action": action,
        "beats_lgbm_ic": beats_lgbm,
        "gate_pass": gate_pass,
        "m27_gate_pass": m27_gate_pass,
        "m27_gate": {
            "ic_floor": M27_IC_FLOOR,
            "icir_floor": M27_ICIR_FLOOR,
            "monotonic_required": True,
        },
    }


def build_report(metrics: dict, model_name: str, context_len: int,
                 pred_len: int, n_symbols: int, n_dates: int,
                 model_spec: dict[str, Any] | None = None) -> tuple[dict, str]:
    decision = make_decision(metrics)
    now = pd.Timestamp.utcnow().isoformat(timespec="seconds")

    report_json = {
        "generated_at": now,
        "model": model_name,
        "model_source": (model_spec or {}).get("model_source"),
        "model_path": (model_spec or {}).get("model_path"),
        "context_len": context_len,
        "pred_len": pred_len,
        "eval_window": f"{EVAL_START} ~ {EVAL_END}",
        "n_symbols": n_symbols,
        "n_eval_dates": n_dates,
        "kronos_metrics": metrics,
        "lgbm_baseline": {
            "ic": LGBM_IC,
            "icir": LGBM_ICIR,
            "ic_pos_ratio": LGBM_IC_POS_RATIO,
            "monotonic": LGBM_MONOTONIC,
        },
        "decision": decision,
    }

    qr = metrics.get("quantile_returns", [])
    qr_rows = "\n".join(
        f"| 桶{i} | {v:.3%} |" for i, v in enumerate(qr)
    )

    ic_vs = metrics.get("ic", float("nan"))
    icir_vs = metrics.get("icir", float("nan"))

    def _fmt(v):
        return f"{v:.6f}" if not math.isnan(v) else "N/A"

    md = f"""# M26.2 Kronos 评估报告

- generated_at: {now}
- model: {model_name}
- model_source: {(model_spec or {}).get("model_source") or "unknown"}
- model_path: {(model_spec or {}).get("model_path") or "N/A"}
- context_len: {context_len} bars | pred_len: {pred_len} bars
- eval_window: {EVAL_START} ~ {EVAL_END} / every_{EVERY_N_DAYS}_days
- symbols: {n_symbols} | eval_dates: {n_dates}

## Kronos vs LightGBM 同尺对比

| 指标 | Kronos ({model_name}) | LightGBM (M26.1 扩盘后) |
| --- | ---: | ---: |
| IC (Spearman) | {_fmt(ic_vs)} | {LGBM_IC:.6f} |
| ICIR | {_fmt(icir_vs)} | {LGBM_ICIR:.6f} |
| IC>0 占比 | {_fmt(metrics.get("ic_pos_ratio", float("nan")))} | {LGBM_IC_POS_RATIO:.6f} |
| 分位单调 | {"✅" if metrics.get("monotonic") else "❌"} | {"✅" if LGBM_MONOTONIC else "❌"} |
| IC 样本期数 | {metrics.get("ic_series_len", 0)} | — |

## Kronos 分位收益（桶0=最低预测收益 → 桶4=最高）

| 分位桶 | 净均值收益/期 |
| ---: | ---: |
{qr_rows}

## 决策

- verdict: **{decision["verdict"]}**
- action: {decision["action"]}
- gate_pass (IC≥0.02 & ICIR≥0.15): {"✅" if decision["gate_pass"] else "❌"}
- m27_gate_pass (IC≥0.04 & ICIR≥0.40 & monotonic): {"✅" if decision["m27_gate_pass"] else "❌"}
- beats_lgbm (IC & ICIR 均≥ LightGBM): {"✅" if decision["beats_lgbm_ic"] else "❌"}
"""

    return report_json, md


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="kronos-small",
                        choices=["kronos-mini", "kronos-small", "kronos-base", "kronos-finetuned"],
                        help="Kronos 模型变体（默认 kronos-small）")
    parser.add_argument("--finetuned-model-path", type=Path,
                        default=Path.home() / ".stock-sage" / "models" / "kronos_finetuned",
                        help="--model kronos-finetuned 时的本地模型目录")
    parser.add_argument("--tokenizer-path", type=Path, default=None,
                        help="可选本地 tokenizer 目录")
    parser.add_argument("--context", type=int, default=400,
                        help="输入上下文长度（bars，默认 400，≤512）")
    parser.add_argument("--pred-len", type=int, default=PRED_LEN,
                        help=f"预测步数（默认 {PRED_LEN}）")
    args = parser.parse_args()

    logger.info("═══ M26.2 Kronos 评估开始 ═══")
    logger.info("模型: %s | 上下文: %d bars | 预测: %d bars",
                args.model, args.context, args.pred_len)

    model_spec = resolve_model_spec(
        args.model,
        finetuned_model_path=args.finetuned_model_path,
        tokenizer_path=args.tokenizer_path,
    )

    # 1. 加载 universe + 价格
    symbols = load_universe()
    logger.info("Universe: %d 支 (%s … %s)", len(symbols), symbols[0], symbols[-1])

    # 价格需要回溯 context_len+pred_len 天的额外历史
    lookback_start = (date.fromisoformat(EVAL_START)
                      - timedelta(days=args.context * 2)).isoformat()
    prices = load_prices(symbols, lookback_start,
                         (date.fromisoformat(EVAL_END)
                          + timedelta(days=args.pred_len * 3)).isoformat())
    logger.info("已加载 %d 支股票价格", len(prices))

    # 2. 取评估日列表（eval_start ~ eval_end 内每 N 个交易日取一个）
    all_dates = get_trading_dates(prices, EVAL_START, EVAL_END)
    eval_dates = all_dates[::EVERY_N_DAYS]
    logger.info("评估日: %d 个（首: %s 末: %s）",
                len(eval_dates), eval_dates[0].date() if eval_dates else "—",
                eval_dates[-1].date() if eval_dates else "—")

    # 3. 加载模型
    predictor = build_predictor(
        args.model,
        args.context,
        finetuned_model_path=args.finetuned_model_path,
        tokenizer_path=args.tokenizer_path,
    )

    # 4. 批量推理
    logger.info("开始逐期推理 …")
    pred_ret = predict_returns(predictor, prices, eval_dates,
                               args.context, args.pred_len)

    # 5. 计算实际收益
    actual_ret = compute_actual_returns(prices, eval_dates, args.pred_len)

    if pred_ret.empty or actual_ret.empty:
        logger.error("预测或实际收益为空，退出")
        return 1

    # 6. IC 指标
    logger.info("计算 IC / ICIR …")
    metrics = compute_ic_metrics(pred_ret, actual_ret)
    logger.info("IC=%.4f | ICIR=%.4f | IC>0=%.1f%% | monotonic=%s",
                metrics["ic"], metrics["icir"],
                metrics["ic_pos_ratio"] * 100, metrics["monotonic"])

    # 7. 生成报告
    report_json, report_md = build_report(
        metrics, args.model, args.context, args.pred_len,
        n_symbols=len(symbols),
        n_dates=len(eval_dates),
        model_spec=model_spec,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report_json, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    OUTPUT_MD.write_text(report_md, encoding="utf-8")
    logger.info("报告已写入: %s", OUTPUT_MD)

    print("\n" + report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
