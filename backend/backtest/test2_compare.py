"""Independent test2-v2 comparison for the M68 news-pyramid shadow arm.

The tool derives A/B/C results over the common window beginning with the first
real M68 shadow row.  It never reads or writes ``test2_ab_state.json`` and does
not backfill pyramid decisions before they were recorded.  A/B use official
signals; C uses the same mechanical B contract with only the recorded pyramid
sentiment leg substituted.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any

from backend.backtest.test2_models import (
    FRAMEWORKS,
    POSITION_PCT,
    Framework,
    FrameworkResult,
    PriceBar,
    Signal,
    broad_sector,
)
from backend.backtest.test2_replay import (
    equal_weight_buy_hold,
    holding_state,
    pct,
    replay,
    result_summary,
)
from backend.config import default_sqlite_path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test2_universe.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "paper_trading" / "m68_out"
DEFAULT_JSON = DEFAULT_OUTPUT_DIR / "test2_pyramid_shadow_state.json"
DEFAULT_MD = DEFAULT_OUTPUT_DIR / "test2_pyramid_shadow.md"
PROFILE = "production_mirror"
SCHEMA_VERSION = "m68.test2-pyramid-shadow.v1"
MIN_PRICE_COVERAGE = 0.80
PYRAMID_FRAMEWORK = Framework(
    "C_pyramid_shadow",
    "C组 pyramid_shadow",
    0.0,
    0.60,
    0.40,
    25.0,
)


@dataclass(frozen=True)
class ShadowRow:
    symbol: str
    as_of: str
    status: str
    legacy_signal_date: str | None
    quant_score: float | None
    technical_score: float | None
    stop_loss: float | None
    take_profit: float | None
    pyramid_sentiment_score: float | None
    counterfactual_composite: float | None
    event_risk_level: str
    would_change_action: bool

    @property
    def valid_direction(self) -> bool:
        return bool(
            self.status == "evidence"
            and self.legacy_signal_date
            and self.legacy_signal_date[:10] == self.as_of
            and self.technical_score is not None
            and self.pyramid_sentiment_score is not None
            and self.counterfactual_composite is not None
        )


def _connect_ro(db_path: str | Path) -> sqlite3.Connection:
    resolved = Path(db_path).resolve()
    con = sqlite3.connect(f"file:{resolved}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_universe(path: str | Path) -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    sectors: dict[str, str] = {}
    for item in payload.get("stocks", []):
        symbol = str(item["symbol"])
        names[symbol] = str(item.get("name") or symbol)
        sectors[symbol] = broad_sector(str(item.get("sector") or ""))
    if not names:
        raise ValueError("test2 universe is empty")
    return names, sectors


def _placeholders(values: dict[str, str]) -> str:
    return ",".join("?" for _ in values)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _close_confirmed_end(
    con: sqlite3.Connection,
    universe: dict[str, str],
    requested_end: str,
) -> tuple[str | None, dict[str, Any]]:
    required = max(1, math.ceil(len(universe) * MIN_PRICE_COVERAGE))
    rows = con.execute(
        f"""
        SELECT date, COUNT(DISTINCT symbol) AS covered
        FROM prices
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND date <= ?
        GROUP BY date
        ORDER BY date DESC
        """,
        (*universe.keys(), requested_end),
    ).fetchall()
    selected = next((row for row in rows if int(row["covered"]) >= required), None)
    return (
        str(selected["date"]) if selected is not None else None,
        {
            "requested_end": requested_end,
            "minimum_ratio": MIN_PRICE_COVERAGE,
            "required_symbols": required,
            "covered_symbols": int(selected["covered"]) if selected is not None else 0,
            "universe_size": len(universe),
        },
    )


def _load_prices(
    con: sqlite3.Connection,
    universe: dict[str, str],
    start: str,
    end: str,
) -> dict[tuple[str, str], PriceBar]:
    rows = con.execute(
        f"""
        SELECT symbol, date, open, high, low, close
        FROM prices
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND date >= ? AND date <= ?
        ORDER BY date, symbol
        """,
        (*universe.keys(), start, end),
    ).fetchall()
    return {
        (str(row["symbol"]), str(row["date"])): PriceBar(
            symbol=str(row["symbol"]),
            date=str(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
        if all(row[key] is not None for key in ("open", "high", "low", "close"))
    }


def _load_official_signals(
    con: sqlite3.Connection,
    universe: dict[str, str],
    start: str,
    end: str,
) -> list[Signal]:
    rows = con.execute(
        f"""
        SELECT symbol, date, quant_score, technical_score, sentiment_score,
               stop_loss, take_profit
        FROM signals
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND substr(date, 1, 10) >= ? AND substr(date, 1, 10) <= ?
        ORDER BY date, symbol
        """,
        (*universe.keys(), start, end),
    ).fetchall()
    return [
        Signal(
            symbol=str(row["symbol"]),
            name=universe[str(row["symbol"])],
            date=str(row["date"]),
            quant=float(row["quant_score"] or 0.0),
            tech=float(row["technical_score"] or 0.0),
            sent=float(row["sentiment_score"] or 0.0),
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
        )
        for row in rows
    ]


def _load_shadow_rows(
    con: sqlite3.Connection,
    universe: dict[str, str],
    end: str,
) -> list[ShadowRow]:
    if not _table_exists(con, "news_shadow_runs"):
        return []
    rows = con.execute(
        f"""
        SELECT ns.symbol, ns.as_of, ns.status, ns.legacy_signal_date,
               s.quant_score, s.technical_score, s.stop_loss, s.take_profit,
               ns.pyramid_sentiment_score, ns.counterfactual_composite,
               ns.event_risk_level, ns.would_change_action
        FROM news_shadow_runs AS ns
        LEFT JOIN signals AS s ON s.id = ns.legacy_signal_id
        WHERE ns.profile = ?
          AND ns.symbol IN ({_placeholders(universe)})
          AND ns.as_of <= ?
        ORDER BY ns.as_of, ns.symbol
        """,
        (PROFILE, *universe.keys(), end),
    ).fetchall()
    return [
        ShadowRow(
            symbol=str(row["symbol"]),
            as_of=str(row["as_of"]),
            status=str(row["status"]),
            legacy_signal_date=row["legacy_signal_date"],
            quant_score=row["quant_score"],
            technical_score=row["technical_score"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            pyramid_sentiment_score=row["pyramid_sentiment_score"],
            counterfactual_composite=row["counterfactual_composite"],
            event_risk_level=str(row["event_risk_level"] or "unavailable"),
            would_change_action=bool(row["would_change_action"]),
        )
        for row in rows
    ]


def _pyramid_signals(
    rows: list[ShadowRow],
    universe: dict[str, str],
) -> list[Signal]:
    """Emit one row per recorded symbol-day; invalid direction rows stay neutral."""
    signals: list[Signal] = []
    for row in rows:
        signals.append(
            Signal(
                symbol=row.symbol,
                name=universe[row.symbol],
                date=row.as_of,
                quant=float(row.quant_score or 0.0) if row.valid_direction else 0.0,
                tech=float(row.technical_score or 0.0) if row.valid_direction else 0.0,
                sent=(
                    float(row.pyramid_sentiment_score or 0.0)
                    if row.valid_direction
                    else 0.0
                ),
                stop_loss=row.stop_loss,
                take_profit=row.take_profit,
            )
        )
    return signals


def _concentration(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
) -> dict[str, Any]:
    contributions: list[tuple[str, float]] = [
        (trade.symbol, trade.net_return_pct * POSITION_PCT)
        for trade in result.closed_trades
    ]
    for holding in result.open_holdings:
        bars = [
            bar
            for (symbol, _), bar in prices.items()
            if symbol == holding.symbol
        ]
        if bars:
            latest = max(bars, key=lambda item: item.date)
            contributions.append(
                (holding.symbol, pct(latest.close, holding.entry_price) * POSITION_PCT)
            )
    if not contributions:
        return {"symbol": None, "weighted_contribution_pct": None, "absolute_share_pct": None}
    symbol, contribution = max(contributions, key=lambda item: abs(item[1]))
    absolute_total = sum(abs(value) for _, value in contributions)
    return {
        "symbol": symbol,
        "weighted_contribution_pct": round(contribution, 2),
        "absolute_share_pct": (
            round(abs(contribution) / absolute_total * 100.0, 2)
            if absolute_total
            else None
        ),
    }


def _serialize_result(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
) -> dict[str, Any]:
    return {
        "label": result.framework.label,
        "weights": {
            "quant": result.framework.quant_weight,
            "technical": result.framework.tech_weight,
            "sentiment": result.framework.sent_weight,
        },
        "entry_threshold": result.framework.entry_threshold,
        "summary": result_summary(result, prices),
        "largest_absolute_contribution": _concentration(result, prices),
        "open_holdings": [holding_state(item, prices) for item in result.open_holdings],
        "closed_trades": [item.__dict__ for item in result.closed_trades],
        "daily_entries": result.daily_entries,
    }


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return round(numerator / denominator, 4) if denominator else None


def _forward_outcomes(
    rows: list[ShadowRow],
    prices: dict[tuple[str, str], PriceBar],
) -> dict[str, Any]:
    by_symbol: dict[str, list[PriceBar]] = {}
    for (symbol, _), bar in prices.items():
        by_symbol.setdefault(symbol, []).append(bar)
    for bars in by_symbol.values():
        bars.sort(key=lambda item: item.date)

    output: dict[str, Any] = {}
    for horizon in (1, 3, 5):
        observations: list[tuple[ShadowRow, float]] = []
        for row in rows:
            if not row.valid_direction:
                continue
            bars = by_symbol.get(row.symbol, [])
            date_index = next(
                (index for index, bar in enumerate(bars) if bar.date == row.as_of),
                None,
            )
            if date_index is None or date_index + horizon >= len(bars):
                continue
            base = bars[date_index].close
            if base == 0:
                continue
            future_return = (bars[date_index + horizon].close / base - 1.0) * 100.0
            observations.append((row, future_return))
        scores = [float(row.counterfactual_composite or 0.0) for row, _ in observations]
        returns = [future_return for _, future_return in observations]
        directional = [
            (score > 0 and future_return > 0) or (score < 0 and future_return < 0)
            for score, future_return in zip(scores, returns, strict=True)
            if score != 0 and future_return != 0
        ]
        elevated = [
            abs(future_return)
            for row, future_return in observations
            if row.event_risk_level in {"high", "medium"}
        ]
        baseline = [
            abs(future_return)
            for row, future_return in observations
            if row.event_risk_level not in {"high", "medium"}
        ]
        output[f"h{horizon}"] = {
            "n": len(observations),
            "n_dates": len({row.as_of for row, _ in observations}),
            "direction_spearman_ic": _correlation(
                _average_ranks(scores),
                _average_ranks(returns),
            ),
            "direction_hit_rate": (
                round(sum(directional) / len(directional), 4)
                if directional
                else None
            ),
            "event_risk": {
                "elevated_n": len(elevated),
                "elevated_mean_abs_return_pct": round(fmean(elevated), 4) if elevated else None,
                "baseline_n": len(baseline),
                "baseline_mean_abs_return_pct": round(fmean(baseline), 4) if baseline else None,
                "abs_return_lift_pct_points": (
                    round(fmean(elevated) - fmean(baseline), 4)
                    if elevated and baseline
                    else None
                ),
            },
        }
    return output


def build_comparison(
    *,
    db_path: str | Path,
    universe_path: str | Path,
    as_of: str,
) -> dict[str, Any]:
    universe, sectors = _load_universe(universe_path)
    with _connect_ro(db_path) as con:
        end, close_gate = _close_confirmed_end(con, universe, as_of)
        if end is None:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no close-confirmed test2 price date met the coverage gate",
                "close_gate": close_gate,
            }
        shadow_rows = _load_shadow_rows(con, universe, end)
        if not shadow_rows:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no recorded M68 rows; C arm starts only from first real shadow date",
                "close_gate": close_gate,
            }
        start = min(row.as_of for row in shadow_rows)
        prices = _load_prices(con, universe, start, end)
        official_signals = _load_official_signals(con, universe, start, end)

    ab_results = replay(
        official_signals,
        prices,
        set(universe),
        frameworks=FRAMEWORKS,
        sectors=sectors,
    )
    c_results = replay(
        _pyramid_signals(shadow_rows, universe),
        prices,
        set(universe),
        frameworks={PYRAMID_FRAMEWORK.key: PYRAMID_FRAMEWORK},
        sectors=sectors,
    )
    all_results = {**ab_results, **c_results}
    serialized = {
        key: _serialize_result(result, prices)
        for key, result in all_results.items()
    }
    b_total = serialized["B_quant_off"]["summary"]["weighted_total_pct"]
    c_total = serialized[PYRAMID_FRAMEWORK.key]["summary"]["weighted_total_pct"]
    shadow_dates = sorted({row.as_of for row in shadow_rows})
    expected_rows = len(shadow_dates) * len(universe)
    status_counts = Counter(row.status for row in shadow_rows)
    valid_rows = [row for row in shadow_rows if row.valid_direction]
    return {
        "ok": True,
        "skipped": False,
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE,
            "generated_for": as_of,
            "window": {"start": start, "end": end},
            "epoch_rule": (
                "independent C arm; common-window A/B are freshly derived; "
                "original test2_ab_state.json is never read or written"
            ),
            "lookahead_rule": (
                "no pyramid backfill before first recorded row; only DB-confirmed closes "
                "at or before requested as-of are evaluated"
            ),
            "write_boundary": "derived JSON/Markdown under paper_trading/m68_out only",
            "close_gate": close_gate,
        },
        "coverage": {
            "shadow_dates": len(shadow_dates),
            "recorded_rows": len(shadow_rows),
            "expected_rows": expected_rows,
            "row_coverage": round(len(shadow_rows) / expected_rows, 4) if expected_rows else 0.0,
            "statuses": dict(sorted(status_counts.items())),
            "valid_direction_rows": len(valid_rows),
            "neutral_no_decision_rows": len(shadow_rows) - len(valid_rows),
            "would_change_action": sum(row.would_change_action for row in shadow_rows),
            "event_risk": dict(sorted(Counter(row.event_risk_level for row in shadow_rows).items())),
        },
        "benchmark": equal_weight_buy_hold(prices, set(universe), start, end),
        "arms": serialized,
        "comparison": {
            "c_minus_b_weighted_total_pct": round(float(c_total) - float(b_total), 2),
            "interpretation": (
                "diagnostic shadow comparison only; sparse/neutral C days are explicit "
                "and no return difference authorizes production promotion"
            ),
        },
        "outcomes": _forward_outcomes(shadow_rows, prices),
        "judgment": (
            "A-share emotion/news is evaluated separately: event risk against future "
            "absolute moves; direction against IC/hit rate. Event usefulness cannot be "
            "used as evidence that sentiment alone predicts direction."
        ),
        "promotion": {
            "eligible": False,
            "reason": (
                "C is shadow-only; direction still requires M54 IC>=0.04, ICIR>=0.40, "
                "monotonic buckets, >=20 non-overlapping IC days, cross-regime evidence, "
                "clean provenance, and owner confirmation"
            ),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    if report.get("skipped"):
        return f"# M68 test2 v2 金字塔对比\n\n- 未运行：{report['reason']}\n"
    meta = report["meta"]
    lines = [
        "# M68 test2 v2 金字塔对比",
        "",
        f"- 共同窗口：{meta['window']['start']} ~ {meta['window']['end']}",
        "- C 臂从首条真实 shadow row 开始，不回填；原 test2 A/B state 不读不写。",
        "- 新闻/情绪对事件波动与涨跌方向分账评估，不互相代替。",
        "",
        "## 共同窗口三臂",
        "",
        "| 臂 | 已平仓 | 持仓 | 仓位加权合计 | 最大单票绝对贡献占比 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, arm in report["arms"].items():
        summary = arm["summary"]
        concentration = arm["largest_absolute_contribution"]
        share = concentration["absolute_share_pct"]
        lines.append(
            f"| {key} | {summary['closed']} | {summary['open']} | "
            f"{summary['weighted_total_pct']:+.2f}% | "
            f"{share:.2f}% |" if share is not None else
            f"| {key} | {summary['closed']} | {summary['open']} | "
            f"{summary['weighted_total_pct']:+.2f}% | — |"
        )
    lines.extend(
        [
            "",
            f"- C-B：{report['comparison']['c_minus_b_weighted_total_pct']:+.2f} 个百分点",
            f"- 同池等权持有：{report['benchmark']['return_pct']:+.2f}%",
            "",
            "## 数据健康",
            "",
            f"- shadow 日：{report['coverage']['shadow_dates']}",
            f"- row 覆盖：{report['coverage']['recorded_rows']}/{report['coverage']['expected_rows']} "
            f"({report['coverage']['row_coverage']:.1%})",
            f"- 有效方向行：{report['coverage']['valid_direction_rows']}",
            f"- 中性/无决策行：{report['coverage']['neutral_no_decision_rows']}",
            "",
            "## 方向与事件风险分账",
            "",
            "| 窗口 | n/日 | 方向 Spearman IC | 方向命中率 | 事件风险组绝对涨跌 | 基线组绝对涨跌 | 差值 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for horizon, outcome in report["outcomes"].items():
        risk = outcome["event_risk"]
        values = [
            outcome["direction_spearman_ic"],
            outcome["direction_hit_rate"],
            risk["elevated_mean_abs_return_pct"],
            risk["baseline_mean_abs_return_pct"],
            risk["abs_return_lift_pct_points"],
        ]
        rendered = ["—" if value is None else f"{value:+.4f}" for value in values]
        lines.append(
            f"| {horizon} | {outcome['n']}/{outcome['n_dates']} | "
            + " | ".join(rendered)
            + " |"
        )
    lines.extend(["", f"> {report['judgment']}", "", f"> 晋级：HOLD。{report['promotion']['reason']}"])
    return "\n".join(lines) + "\n"


def write_outputs(
    report: dict[str, Any],
    *,
    json_path: str | Path = DEFAULT_JSON,
    md_path: str | Path = DEFAULT_MD,
) -> tuple[Path, Path]:
    json_target = Path(json_path)
    md_target = Path(md_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    md_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_target.write_text(_markdown(report), encoding="utf-8")
    return json_target, md_target


def build_and_write_comparison(
    *,
    db_path: str | Path,
    universe_path: str | Path = DEFAULT_UNIVERSE,
    as_of: str,
    json_path: str | Path = DEFAULT_JSON,
    md_path: str | Path = DEFAULT_MD,
) -> dict[str, Any]:
    if not Path(universe_path).is_file():
        return {
            "ok": True,
            "skipped": True,
            "reason": f"local test2 universe not found: {universe_path}",
        }
    report = build_comparison(
        db_path=db_path,
        universe_path=universe_path,
        as_of=as_of,
    )
    json_target, md_target = write_outputs(
        report,
        json_path=json_path,
        md_path=md_path,
    )
    return {
        **report,
        "artifacts": {"json": str(json_target), "markdown": str(md_target)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run independent test2-v2 A/B/C comparison for the M68 pyramid shadow.",
    )
    parser.add_argument("--db", type=Path, default=default_sqlite_path())
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args(argv)
    payload = build_and_write_comparison(
        db_path=args.db,
        universe_path=args.universe,
        as_of=args.as_of,
        json_path=args.json_out,
        md_path=args.md_out,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
