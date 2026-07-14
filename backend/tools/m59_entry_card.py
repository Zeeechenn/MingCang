"""M59 deterministic entry-condition cards.

Pure arithmetic helper for pre-entry condition display. It reads local price
rows only, never calls an LLM, and never mutates signals, positions, or orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path, settings
from backend.workflows.render import assert_no_trade_words, format_cn_number

DEFAULT_LEDGER_PATH = Path("paper_trading/m60_out/second_entry_ledger.json")
VARIANT_LABELS = {
    "v1_immediate": "V1 立即",
    "v2_pullback": "V2 回踩",
    "v3_confirm": "V3 放量确认",
}
DEFAULT_VALIDATION_NOTE = "影子验证中,样本满20前三规则并列展示"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_price(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _price_rows(con: sqlite3.Connection, symbol: str, as_of: str) -> list[dict[str, Any]]:
    required = {"symbol", "date", "high", "low", "close", "volume"}
    if not _table_exists(con, "prices") or not required <= _columns(con, "prices"):
        return []
    rows = con.execute(
        """
        SELECT date, high, low, close, volume
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date ASC
        """,
        (symbol, as_of),
    ).fetchall()
    return [dict(row) for row in rows]


def _latest_price_date(con: sqlite3.Connection) -> str | None:
    if not _table_exists(con, "prices") or "date" not in _columns(con, "prices"):
        return None
    row = con.execute("SELECT MAX(date) FROM prices").fetchone()
    return str(row[0]) if row and row[0] else None


def _atr14(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 15:
        return None
    window = rows[-15:]
    true_ranges: list[float] = []
    for idx in range(1, len(window)):
        high = _to_float(window[idx].get("high"))
        low = _to_float(window[idx].get("low"))
        prev_close = _to_float(window[idx - 1].get("close"))
        if high is None or low is None or prev_close is None:
            return None
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return round(sum(true_ranges) / len(true_ranges), 4)


def _ma5(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 5:
        return None
    closes = [_to_float(row.get("close")) for row in rows[-5:]]
    if any(close is None for close in closes):
        return None
    return sum(close for close in closes if close is not None) / 5


def _avg5_volume(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 5:
        return None
    volumes = [_to_float(row.get("volume")) for row in rows[-5:]]
    if any(volume is None for volume in volumes):
        return None
    return sum(volume for volume in volumes if volume is not None) / 5


def _high5(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 5:
        return None
    highs = [_to_float(row.get("high")) for row in rows[-5:]]
    if any(high is None for high in highs):
        return None
    return max(high for high in highs if high is not None)


def _ledger_status(path: Path) -> dict[str, Any]:
    base: dict[str, Any] = {
        "path": str(path),
        "sample_count": 0,
        "recommended_variant": None,
        "status": "missing",
    }
    if not path.exists():
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**base, "status": f"invalid:{exc.__class__.__name__}"}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {**base, "status": "invalid:entries"}
    samples = {
        (str(entry.get("symbol")), str(entry.get("trigger_date")))
        for entry in entries
        if isinstance(entry, dict) and entry.get("symbol") and entry.get("trigger_date")
    }
    winner = None
    for container_key in ("conclusion", "summary", "validation", "result"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        winner = (
            container.get("winning_variant")
            or container.get("winner")
            or container.get("recommended_variant")
            or container.get("best_variant")
        )
        if winner:
            break
    if winner not in VARIANT_LABELS:
        winner = None
    sample_count = len(samples)
    return {
        **base,
        "sample_count": sample_count,
        "recommended_variant": winner if sample_count >= 20 else None,
        "status": "ok",
    }


def _validation_note(variant: str, ledger: dict[str, Any]) -> str:
    winner = ledger.get("recommended_variant")
    if winner == variant:
        return f"影子验证中,样本满20后推荐:{VARIANT_LABELS[variant]}"
    if winner:
        return "影子验证中"
    if ledger.get("sample_count", 0) >= 20:
        return "影子验证中,暂无胜出结论"
    return DEFAULT_VALIDATION_NOTE


def _risk_distance(trigger_price: float, stop_price: float) -> float:
    return max(0.0, trigger_price - stop_price)


def _sizing(trigger_price: float, stop_price: float) -> dict[str, Any]:
    budget_pct = settings.entry_risk_budget_pct
    budget_fraction = budget_pct / 100.0
    distance = _risk_distance(trigger_price, stop_price)
    formula = f"资金×{budget_fraction:.3f}/{distance:.2f}(向下取百股)" if distance > 0 else "止损距离为0,无法计算"
    result: dict[str, Any] = {
        "risk_budget_pct": budget_pct,
        "risk_budget_fraction": budget_fraction,
        "risk_distance": round(distance, 2),
        "formula": formula,
        "account_size": settings.entry_account_size,
        "reference_shares": None,
        "reference_amount": None,
        "position_limit_hint": None,
    }
    account_size = settings.entry_account_size
    if account_size is None or distance <= 0:
        return result
    raw_shares = account_size * budget_fraction / distance
    reference_shares = int(math.floor(raw_shares / 100.0) * 100)
    reference_amount = round(reference_shares * trigger_price, 2)
    result["reference_shares"] = reference_shares
    result["reference_amount"] = reference_amount
    max_amount = account_size * settings.max_position_per_stock
    if reference_amount > max_amount:
        result["position_limit_hint"] = (
            f"参考金额{format_cn_number(reference_amount)}超过单票上限"
            f"{format_cn_number(max_amount)}({settings.max_position_per_stock:.0%})"
        )
    return result


def _variant(variant: str, trigger_price: float, stop_price: float, ledger: dict[str, Any], **extra: Any) -> dict[str, Any]:
    risk_distance = _risk_distance(trigger_price, stop_price)
    return {
        "variant": variant,
        "label": VARIANT_LABELS[variant],
        "trigger_price": _round_price(trigger_price),
        "stop_price": _round_price(stop_price),
        "risk_distance": round(risk_distance, 2),
        "validation_note": _validation_note(variant, ledger),
        "sizing": _sizing(trigger_price, stop_price),
        **extra,
    }


def build_entry_card(
    symbol: str,
    as_of: str | None,
    con: sqlite3.Connection,
    *,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    resolved_as_of = as_of or _latest_price_date(con)
    if resolved_as_of is None:
        return {
            "symbol": symbol,
            "as_of": as_of,
            "status": "missing_data",
            "message": "数据缺失,无法算条件卡",
            "missing": ["as_of"],
        }

    rows = _price_rows(con, symbol, resolved_as_of)
    missing: list[str] = []
    if not rows:
        missing.append("price")
    atr = _atr14(rows)
    ma5 = _ma5(rows)
    avg_volume = _avg5_volume(rows)
    high5 = _high5(rows)
    latest = rows[-1] if rows else {}
    current = _to_float(latest.get("close"))
    if current is None:
        missing.append("close")
    if atr is None:
        missing.append("atr14")
    if ma5 is None:
        missing.append("ma5")
    if avg_volume is None:
        missing.append("avg5_volume")
    if high5 is None:
        missing.append("high5")
    if missing:
        return {
            "symbol": symbol,
            "as_of": resolved_as_of,
            "status": "missing_data",
            "message": "数据缺失,无法算条件卡",
            "missing": missing,
        }

    ledger = _ledger_status(Path(ledger_path))
    assert current is not None and atr is not None and ma5 is not None and avg_volume is not None and high5 is not None
    volume_threshold = avg_volume * 1.5
    variants = [
        _variant("v1_immediate", current, current - 1.5 * atr, ledger, trigger_text=f"当前价 {current:.2f}"),
        _variant(
            "v2_pullback",
            ma5,
            ma5 - 1.5 * atr,
            ledger,
            trigger_text=f"回踩 {ma5:.2f} 元(MA5)企稳则触发",
        ),
        _variant(
            "v3_confirm",
            high5,
            high5 - 1.5 * atr,
            ledger,
            trigger_text=f"放量确认 {format_cn_number(volume_threshold)}股 + 站上 {high5:.2f} 元",
            volume_threshold=round(volume_threshold, 2),
            volume_threshold_display=format_cn_number(volume_threshold),
            stand_above_price=_round_price(high5),
        ),
    ]
    return {
        "symbol": symbol,
        "as_of": resolved_as_of,
        "status": "ok",
        "price_date": str(latest.get("date")),
        "current_price": _round_price(current),
        "atr14": round(atr, 4),
        "ma5": _round_price(ma5),
        "avg5_volume": round(avg_volume, 2),
        "high5": _round_price(high5),
        "ledger": ledger,
        "variants": variants,
        "note": "observe_only_zero_llm",
    }


def _format_sizing(sizing: dict[str, Any]) -> str:
    distance = sizing.get("risk_distance")
    budget_pct = sizing.get("risk_budget_pct")
    prefix = f"若单笔风险预算=资金×{budget_pct}%,止损距离 {distance:.2f} 元 → "
    if sizing.get("account_size") is None:
        return prefix + f"参考股数={sizing.get('formula')}"
    parts = [
        prefix + f"参考股数={format_cn_number(sizing.get('reference_shares'))}",
        f"参考金额={format_cn_number(sizing.get('reference_amount'))}",
    ]
    if sizing.get("position_limit_hint"):
        parts.append(str(sizing["position_limit_hint"]))
    return "; ".join(parts)


def render_entry_card_compact(card: dict[str, Any]) -> list[str]:
    if card.get("status") != "ok":
        return [str(card.get("message") or "数据缺失,无法算条件卡")]
    lines = []
    for item in card.get("variants") or []:
        lines.append(
            f"{item.get('label')}: {item.get('trigger_text')}; "
            f"风险线 {item.get('stop_price'):.2f}; {_format_sizing(item.get('sizing') or {})}; "
            f"{item.get('validation_note')}"
        )
    assert_no_trade_words("\n".join(lines))
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic M59 entry-condition card.")
    parser.add_argument("symbol")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)

    db_path = args.db if args.db is not None else default_sqlite_path()
    with _connect_readonly(db_path) as con:
        card = build_entry_card(args.symbol, args.as_of, con, ledger_path=args.ledger)
    if args.format == "json":
        print(json.dumps(card, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n".join(render_entry_card_compact(card)))


if __name__ == "__main__":
    main()
