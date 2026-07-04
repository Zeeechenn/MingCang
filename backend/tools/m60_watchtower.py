"""M60 Watchtower Phase 1 — postmarket detection CLI (zero LLM, deterministic).

Scans only the symbols already on the Phase 0 observation watchlist
(``backend.research.watchlist``) for three classes of "it started moving"
triggers, computed entirely from local data already in the SQLite DB:

  a. price/volume anomaly — |z-score| of today's return over the trailing
     ``watchtower_lookback_days`` distribution, or today's |return| beyond the
     ``watchtower_price_percentile`` percentile of that trailing distribution;
     volume ratio (today volume / trailing average volume) beyond threshold;
     an N-day new high breakout.
  b. sector resonance — within one watchlist theme, when a majority (>=
     ``watchtower_sector_resonance_min_ratio``) of priced members move up on
     the same day and those up-moving members average more than
     ``watchtower_sector_resonance_min_avg_pct`` gain. A single stock's move
     can be noise; a whole theme moving together is closer to a signal.
  c. news trigger — reuses ``backend.data.news_trigger.decide_trigger`` (M54
     L1, deterministic) with the day's own price_change_pct/volume_ratio fed
     in, so its own price/volume/announcement/policy/diversity-surge/
     materiality reasons all get a fair chance to fire from real data.

This module makes zero LLM calls and never writes to the database — it only
opens the configured SQLite file in read-only mode. A trigger here is
evidence for the Phase 2 LLM discretion layer, not a buy instruction: "触发≠
买入指令,待 LLM 确认层(Phase 2)".
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path, settings
from backend.data.news_clustering import cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_trigger import decide_trigger
from backend.research.watchlist import WATCHLIST_DIR, load_watchlists, themes_by_symbol

DEFAULT_OUTPUT_DIR = Path("/private/tmp")
OUTPUT_FILENAME_PREFIX = "m60_watchtower_"

TRIGGER_PRICE_Z = "price_z_anomaly"
TRIGGER_PRICE_PERCENTILE = "price_percentile_anomaly"
TRIGGER_VOLUME_RATIO = "volume_ratio_anomaly"
TRIGGER_NEW_HIGH = "new_high_breakout"
TRIGGER_SECTOR_RESONANCE = "sector_resonance"
TRIGGER_NEWS = "news_trigger"
TRIGGER_LHB_APPEARANCE = "lhb_appearance"
TRIGGER_FUND_FLOW_SURGE = "fund_flow_surge"


# ---------------------------------------------------------------------------
# Read-only SQLite helpers (same pattern as backend.tools.m59_panel)
# ---------------------------------------------------------------------------

def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _latest_price_date(con: sqlite3.Connection, symbols: list[str]) -> str | None:
    if not symbols or not _table_exists(con, "prices"):
        return None
    placeholders = ",".join("?" for _ in symbols)
    row = con.execute(
        f"SELECT MAX(date) FROM prices WHERE symbol IN ({placeholders})", symbols
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _price_history(con: sqlite3.Connection, symbol: str, as_of: str, limit: int) -> list[dict[str, Any]]:
    """Up to `limit` rows with date <= as_of, ascending by date (oldest first)."""
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return []
    rows = con.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (symbol, as_of, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _news_rows(con: sqlite3.Connection, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    if not _table_exists(con, "news"):
        return []
    cols = _columns(con, "news")
    required = {"symbol", "title", "url", "published_at"}
    if not required <= cols:
        return []
    select_cols = ["symbol", "title", "url", "published_at"]
    select_cols.append("source" if "source" in cols else "NULL AS source")
    select_cols.append("provider" if "provider" in cols else "NULL AS provider")
    rows = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM news
        WHERE symbol = ? AND published_at >= ? AND published_at <= ?
        ORDER BY published_at ASC
        """,
        (symbol, start, f"{end} 23:59:59"),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# a. Price/volume anomaly + new-high breakout
# ---------------------------------------------------------------------------

def _daily_returns(closes: list[float]) -> list[float]:
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev not in (None, 0) and cur is not None:
            returns.append((cur / prev - 1.0) * 100.0)
    return returns


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile, pct in [0, 1]. No numpy dependency."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def compute_price_volume_signals(
    history: list[dict[str, Any]],
    *,
    lookback_days: int | None = None,
    volume_lookback_days: int | None = None,
    new_high_lookback_days: int | None = None,
    z_threshold: float | None = None,
    percentile_threshold: float | None = None,
    volume_ratio_threshold: float | None = None,
) -> dict[str, Any]:
    """Pure function: history must be ascending-by-date, most recent row last.

    Returns a dict with the computed values and boolean trigger flags, plus a
    `flags` list documenting any missing-data degradation (never silently
    skipped).
    """
    lookback_days = settings.watchtower_lookback_days if lookback_days is None else lookback_days
    volume_lookback_days = (
        settings.watchtower_volume_lookback_days if volume_lookback_days is None else volume_lookback_days
    )
    new_high_lookback_days = (
        settings.watchtower_new_high_lookback_days if new_high_lookback_days is None else new_high_lookback_days
    )
    z_threshold = settings.watchtower_price_z_threshold if z_threshold is None else z_threshold
    percentile_threshold = (
        settings.watchtower_price_percentile if percentile_threshold is None else percentile_threshold
    )
    volume_ratio_threshold = (
        settings.watchtower_volume_ratio_threshold if volume_ratio_threshold is None else volume_ratio_threshold
    )

    flags: list[str] = []
    result: dict[str, Any] = {
        "as_of_date": history[-1]["date"] if history else None,
        "close": None,
        "daily_return_pct": None,
        "z_score": None,
        "z_triggered": False,
        "percentile_cutoff_pct": None,
        "percentile_triggered": False,
        "volume": None,
        "volume_ratio": None,
        "volume_triggered": False,
        "new_high_triggered": False,
        "new_high_window_days": new_high_lookback_days,
        "flags": flags,
    }
    if len(history) < 2:
        flags.append("missing:insufficient_price_history")
        return result

    today = history[-1]
    result["close"] = today.get("close")
    result["volume"] = today.get("volume")

    closes = [row.get("close") for row in history]
    if closes[-1] is None or closes[-2] in (None, 0):
        flags.append("missing:close")
    else:
        result["daily_return_pct"] = (closes[-1] / closes[-2] - 1.0) * 100.0

    trailing_closes = closes[:-1][-(lookback_days + 1):]
    trailing_returns = _daily_returns([c for c in trailing_closes if c is not None])
    if result["daily_return_pct"] is not None and len(trailing_returns) >= 30:
        mean = statistics.fmean(trailing_returns)
        stdev = statistics.pstdev(trailing_returns)
        if stdev > 0:
            result["z_score"] = (result["daily_return_pct"] - mean) / stdev
            result["z_triggered"] = abs(result["z_score"]) > z_threshold
        abs_sorted = sorted(abs(r) for r in trailing_returns)
        cutoff = _percentile(abs_sorted, percentile_threshold)
        result["percentile_cutoff_pct"] = cutoff
        if cutoff is not None:
            result["percentile_triggered"] = abs(result["daily_return_pct"]) > cutoff
    elif result["daily_return_pct"] is not None:
        flags.append("missing:insufficient_return_history_for_distribution")

    volumes = [row.get("volume") for row in history[:-1]][-volume_lookback_days:]
    valid_volumes = [v for v in volumes if v is not None]
    if today.get("volume") is not None and len(valid_volumes) >= max(5, volume_lookback_days // 2):
        avg_volume = statistics.fmean(valid_volumes)
        if avg_volume > 0:
            result["volume_ratio"] = today["volume"] / avg_volume
            result["volume_triggered"] = result["volume_ratio"] > volume_ratio_threshold
    elif today.get("volume") is not None:
        flags.append("missing:insufficient_volume_history")

    window_closes = [row.get("close") for row in history[:-1]][-new_high_lookback_days:]
    valid_window_closes = [c for c in window_closes if c is not None]
    if closes[-1] is not None and len(valid_window_closes) >= max(5, new_high_lookback_days // 2):
        result["new_high_triggered"] = closes[-1] > max(valid_window_closes)
    elif closes[-1] is not None:
        flags.append("missing:insufficient_window_history_for_new_high")

    return result


# ---------------------------------------------------------------------------
# b. Sector resonance
# ---------------------------------------------------------------------------

def compute_sector_resonance(
    member_returns: dict[str, float | None],
    *,
    min_ratio: float | None = None,
    min_avg_pct: float | None = None,
) -> dict[str, Any]:
    """member_returns: symbol -> daily_return_pct (None where price data missing).

    Resonance is deliberately one-directional (up only): the watchlist encodes
    a bull thesis, so "同向" here means "同涨" — a whole theme selling off
    together is a different (not yet built) signal, not sector resonance.
    """
    min_ratio = settings.watchtower_sector_resonance_min_ratio if min_ratio is None else min_ratio
    min_avg_pct = settings.watchtower_sector_resonance_min_avg_pct if min_avg_pct is None else min_avg_pct

    priced = {symbol: pct for symbol, pct in member_returns.items() if pct is not None}
    missing = [symbol for symbol, pct in member_returns.items() if pct is None]
    up_members = {symbol: pct for symbol, pct in priced.items() if pct > 0}

    n_priced = len(priced)
    up_ratio = (len(up_members) / n_priced) if n_priced else None
    avg_up_pct = statistics.fmean(up_members.values()) if up_members else None

    triggered = bool(
        n_priced
        and up_ratio is not None
        and up_ratio >= min_ratio
        and avg_up_pct is not None
        and avg_up_pct > min_avg_pct
    )
    return {
        "n_members": len(member_returns),
        "n_priced": n_priced,
        "n_up": len(up_members),
        "up_ratio": up_ratio,
        "avg_up_pct": avg_up_pct,
        "triggered": triggered,
        "up_member_symbols": sorted(up_members),
        "missing_price_symbols": missing,
        "min_ratio": min_ratio,
        "min_avg_pct": min_avg_pct,
    }


# ---------------------------------------------------------------------------
# c. News trigger (reuses M54 L1 decide_trigger)
# ---------------------------------------------------------------------------

def _build_news_evidence(rows: list[dict[str, Any]]) -> list[NewsEvidence]:
    evidence: list[NewsEvidence] = []
    for row in rows:
        published_raw = row.get("published_at")
        if not published_raw:
            continue
        try:
            published_at = datetime.fromisoformat(str(published_raw).replace("Z", ""))
        except ValueError:
            continue
        source_name = row.get("source") or row.get("provider") or "unknown"
        provider = row.get("provider") or row.get("source") or "unknown"
        evidence.append(
            NewsEvidence(
                symbol=str(row["symbol"]),
                title=str(row["title"]),
                url=str(row["url"]),
                published_at=published_at,
                source_name=str(source_name),
                provider=str(provider),
            )
        )
    return evidence


def compute_news_trigger(
    con: sqlite3.Connection,
    symbol: str,
    as_of: str,
    *,
    news_lookback_days: int | None = None,
    price_change_pct: float | None = None,
    volume_ratio: float | None = None,
):
    news_lookback_days = (
        settings.watchtower_news_lookback_days if news_lookback_days is None else news_lookback_days
    )
    as_of_date = date.fromisoformat(as_of)
    start_date = date.fromordinal(as_of_date.toordinal() - news_lookback_days)
    rows = _news_rows(con, symbol, start_date.isoformat(), as_of)
    evidence = _build_news_evidence(rows)
    clusters = [c for c in cluster_evidence(evidence) if c.symbol == symbol]
    as_of_dt = datetime.combine(as_of_date, datetime.min.time())
    return decide_trigger(
        symbol,
        as_of_dt,
        clusters,
        price_change_pct=price_change_pct,
        volume_ratio=volume_ratio,
    )


# ---------------------------------------------------------------------------
# d. M61 category trigger supplements (DB-only)
# ---------------------------------------------------------------------------

def _lhb_trigger_rows(con: sqlite3.Connection, symbol: str, as_of: str) -> list[dict[str, Any]]:
    if not _table_exists(con, "lhb_records"):
        return []
    cols = _columns(con, "lhb_records")
    required = {"symbol", "trade_date"}
    if not required <= cols:
        return []
    rows = con.execute(
        """
        SELECT trade_date,
               reason,
               net_buy_amount
        FROM lhb_records
        WHERE symbol = ?
          AND date(trade_date) = date(?)
        ORDER BY id ASC
        """,
        (symbol, as_of),
    ).fetchall()
    return [dict(row) for row in rows]


def compute_fund_flow_surge(
    con: sqlite3.Connection,
    symbol: str,
    as_of: str,
    *,
    min_rows: int = 25,
    lookback_rows: int = 60,
    recent_days: int = 5,
    z_threshold: float = 2.0,
) -> dict[str, Any] | None:
    if not _table_exists(con, "fund_flows"):
        return None
    cols = _columns(con, "fund_flows")
    if not {"symbol", "trade_date", "main_net"} <= cols:
        return None
    rows = con.execute(
        """
        SELECT trade_date, main_net
        FROM fund_flows
        WHERE symbol = ?
          AND date(trade_date) <= date(?)
          AND main_net IS NOT NULL
        ORDER BY date(trade_date) DESC
        LIMIT ?
        """,
        (symbol, as_of, lookback_rows),
    ).fetchall()
    values = [float(row["main_net"]) for row in reversed(rows)]
    if len(values) < min_rows or len(values) < recent_days * 2:
        return None

    recent_sum = sum(values[-recent_days:])
    historical = values[:-recent_days]
    rolling_sums = [
        sum(historical[idx : idx + recent_days])
        for idx in range(0, len(historical) - recent_days + 1)
    ]
    if len(rolling_sums) < 2:
        return None
    mean = statistics.fmean(rolling_sums)
    stdev = statistics.pstdev(rolling_sums)
    if stdev <= 0:
        return None
    z_score = (recent_sum - mean) / stdev
    if abs(z_score) < z_threshold:
        return None
    return {
        "z_score": z_score,
        "recent_5d_main_net_sum": recent_sum,
        "distribution_mean": mean,
        "distribution_stdev": stdev,
        "rows_used": len(values),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_watchtower_report(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    watchlist_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return an m60_watchtower.v1 payload without writing the database."""
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    entries, watchlist_errors = load_watchlists(watchlist_dir) if watchlist_dir is not None else load_watchlists()
    symbol_to_themes = themes_by_symbol(entries)
    all_symbols = sorted(symbol_to_themes)

    config = {
        "watchtower_lookback_days": settings.watchtower_lookback_days,
        "watchtower_price_z_threshold": settings.watchtower_price_z_threshold,
        "watchtower_price_percentile": settings.watchtower_price_percentile,
        "watchtower_volume_ratio_threshold": settings.watchtower_volume_ratio_threshold,
        "watchtower_volume_lookback_days": settings.watchtower_volume_lookback_days,
        "watchtower_new_high_lookback_days": settings.watchtower_new_high_lookback_days,
        "watchtower_news_lookback_days": settings.watchtower_news_lookback_days,
        "watchtower_sector_resonance_min_ratio": settings.watchtower_sector_resonance_min_ratio,
        "watchtower_sector_resonance_min_avg_pct": settings.watchtower_sector_resonance_min_avg_pct,
    }

    with _connect_readonly(resolved_db) as con:
        resolved_as_of = as_of or _latest_price_date(con, all_symbols) or date.today().isoformat()

        per_symbol_pv: dict[str, dict[str, Any]] = {}
        for symbol in all_symbols:
            history = _price_history(con, symbol, resolved_as_of, settings.watchtower_lookback_days + 1)
            per_symbol_pv[symbol] = compute_price_volume_signals(history)

        triggers: list[dict[str, Any]] = []

        # a. price/volume anomaly + new high, per symbol
        for symbol in all_symbols:
            pv = per_symbol_pv[symbol]
            themes = symbol_to_themes.get(symbol, [])
            price_snapshot = {"date": pv["as_of_date"], "close": pv["close"]}
            if pv["z_triggered"]:
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_PRICE_Z,
                        "value": pv["z_score"],
                        "detail": {"daily_return_pct": pv["daily_return_pct"], "z_score": pv["z_score"]},
                        "price": price_snapshot,
                    }
                )
            if pv["percentile_triggered"]:
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_PRICE_PERCENTILE,
                        "value": pv["daily_return_pct"],
                        "detail": {
                            "daily_return_pct": pv["daily_return_pct"],
                            "percentile_cutoff_pct": pv["percentile_cutoff_pct"],
                        },
                        "price": price_snapshot,
                    }
                )
            if pv["volume_triggered"]:
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_VOLUME_RATIO,
                        "value": pv["volume_ratio"],
                        "detail": {"volume_ratio": pv["volume_ratio"], "volume": pv["volume"]},
                        "price": price_snapshot,
                    }
                )
            if pv["new_high_triggered"]:
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_NEW_HIGH,
                        "value": pv["close"],
                        "detail": {"window_days": pv["new_high_window_days"]},
                        "price": price_snapshot,
                    }
                )
            for row in _lhb_trigger_rows(con, symbol, resolved_as_of):
                reason = row.get("reason") or "未列明"
                card = f"龙虎榜上榜: {reason}, 净买 {row.get('net_buy_amount')}"
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_LHB_APPEARANCE,
                        "value": row.get("net_buy_amount"),
                        "detail": {
                            "trade_date": row.get("trade_date"),
                            "reason": row.get("reason"),
                            "net_buy_amount": row.get("net_buy_amount"),
                        },
                        "card": card,
                        "price": price_snapshot,
                    }
                )
            flow = compute_fund_flow_surge(con, symbol, resolved_as_of)
            if flow is not None:
                z_score = flow["z_score"]
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": themes,
                        "trigger_type": TRIGGER_FUND_FLOW_SURGE,
                        "value": z_score,
                        "detail": flow,
                        "card": f"主力资金异动 z={z_score:.2f}",
                        "price": price_snapshot,
                    }
                )

        # b. sector resonance, per theme
        resonance_by_theme: dict[str, dict[str, Any]] = {}
        for entry in entries:
            theme_key = entry["theme_key"]
            member_returns = {
                symbol: per_symbol_pv[symbol]["daily_return_pct"] for symbol in entry["symbols"]
            }
            resonance = compute_sector_resonance(member_returns)
            resonance_by_theme[theme_key] = resonance
            if resonance["triggered"]:
                for symbol in resonance["up_member_symbols"]:
                    triggers.append(
                        {
                            "symbol": symbol,
                            "themes": [theme_key],
                            "trigger_type": TRIGGER_SECTOR_RESONANCE,
                            "value": resonance["avg_up_pct"],
                            "detail": {
                                "up_ratio": resonance["up_ratio"],
                                "avg_up_pct": resonance["avg_up_pct"],
                                "n_priced": resonance["n_priced"],
                                "n_up": resonance["n_up"],
                            },
                            "price": {
                                "date": per_symbol_pv[symbol]["as_of_date"],
                                "close": per_symbol_pv[symbol]["close"],
                            },
                        }
                    )

        # c. news trigger, per symbol (reuses M54 L1 decide_trigger)
        for symbol in all_symbols:
            pv = per_symbol_pv[symbol]
            decision = compute_news_trigger(
                con,
                symbol,
                resolved_as_of,
                price_change_pct=pv["daily_return_pct"],
                volume_ratio=pv["volume_ratio"],
            )
            if decision.triggered:
                triggers.append(
                    {
                        "symbol": symbol,
                        "themes": symbol_to_themes.get(symbol, []),
                        "trigger_type": TRIGGER_NEWS,
                        "value": None,
                        "detail": {"reasons": decision.reasons, "main_cause": (
                            decision.attribution_card.main_cause if decision.attribution_card else None
                        )},
                        "price": {"date": pv["as_of_date"], "close": pv["close"]},
                    }
                )

    triggers.sort(key=lambda t: (t["symbol"], t["trigger_type"]))
    triggered_symbols = sorted({t["symbol"] for t in triggers})
    no_trigger_symbols = [s for s in all_symbols if s not in triggered_symbols]

    return {
        "schema_version": "m60_watchtower.v1",
        "as_of": resolved_as_of,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "watchlist_dir": str(watchlist_dir) if watchlist_dir is not None else str(WATCHLIST_DIR),
        "watchlist_errors": watchlist_errors,
        "config": config,
        "themes": [
            {"theme_key": e["theme_key"], "title": e["title"], "symbols": e["symbols"]} for e in entries
        ],
        "sector_resonance": resonance_by_theme,
        "triggers": triggers,
        "triggered_symbols": triggered_symbols,
        "no_trigger_symbols": no_trigger_symbols,
        "summary": {
            "n_symbols_scanned": len(all_symbols),
            "n_triggers": len(triggers),
            "n_triggered_symbols": len(triggered_symbols),
            "text": (
                "今日清单内无触发"
                if not triggers
                else f"今日清单内 {len(triggered_symbols)}/{len(all_symbols)} 只触发,共 {len(triggers)} 条"
            ),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        report["summary"]["text"],
        "",
        f"# M60 观察哨 ({report['as_of']})",
        "",
        "触发≠买入指令,待 LLM 确认层(Phase 2)裁量。",
        "",
        "## 观察清单",
    ]
    if report["watchlist_errors"]:
        lines.append("清单加载错误(未静默丢弃):")
        for error in report["watchlist_errors"]:
            lines.append(f"- {error}")
    for theme in report["themes"]:
        resonance = report["sector_resonance"].get(theme["theme_key"], {})
        lines.append(
            f"- {theme['title']} ({theme['theme_key']}): {', '.join(theme['symbols'])} | "
            f"板块共振: {'触发' if resonance.get('triggered') else '未触发'} "
            f"(up_ratio={resonance.get('up_ratio')}, avg_up_pct={resonance.get('avg_up_pct')})"
        )
    lines.extend(["", "## 触发明细"])
    if not report["triggers"]:
        lines.append("今日清单内无触发。")
    else:
        lines.append("| symbol | theme | 触发类型 | 数值 | 当日收盘 |")
        lines.append("|---|---|---|---:|---:|")
        for trigger in report["triggers"]:
            trigger_label = trigger.get("card") or trigger["trigger_type"]
            lines.append(
                f"| {trigger['symbol']} | {','.join(trigger['themes'])} | {trigger_label} | "
                f"{trigger['value']} | {trigger['price'].get('close')} |"
            )
    lines.extend(["", "## 今日无触发标的"])
    lines.append(", ".join(report["no_trigger_symbols"]) or "(无)")
    return "\n".join(lines)


def _default_output_paths(as_of: str, output_dir: Path) -> tuple[Path, Path]:
    stem = f"{OUTPUT_FILENAME_PREFIX}{as_of}"
    return output_dir / f"{stem}.json", output_dir / f"{stem}.md"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the M60 postmarket watchtower scan.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--as-of", default=None, help="Scan date YYYY-MM-DD; defaults to latest available price date")
    parser.add_argument("--watchlist-dir", type=Path, default=None, help="Watchlist JSON directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Where to write JSON+Markdown output")
    parser.add_argument("--no-write", action="store_true", help="Print only; skip writing output files")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Also run the Phase 2 LLM confirmation layer over today's triggers "
            "(backend.research.watchtower_confirm). Off by default so a plain "
            "scan never burns LLM tokens; each run makes at most one LLM call "
            "per unique triggered symbol."
        ),
    )
    args = parser.parse_args(argv)

    report = build_watchtower_report(db_path=args.db, as_of=args.as_of, watchlist_dir=args.watchlist_dir)
    markdown = render_markdown(report)

    if not args.no_write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path, md_path = _default_output_paths(report["as_of"], args.output_dir)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")

    print(markdown)

    if args.confirm:
        from backend.research.watchtower_confirm import (
            build_confirmation_report,
            render_markdown as render_confirm_markdown,
            _default_output_paths as _confirm_output_paths,
        )

        db = None
        close_db = False
        try:
            from backend.data.database import SessionLocal

            db = SessionLocal()
            close_db = True
        except Exception:
            db = None
        try:
            confirm_report = build_confirmation_report(
                watchtower_report=report,
                db_path=args.db,
                watchlist_dir=args.watchlist_dir,
                db=db,
            )
        finally:
            if close_db and db is not None:
                db.close()

        confirm_markdown = render_confirm_markdown(confirm_report)
        if not args.no_write:
            confirm_json_path, confirm_md_path = _confirm_output_paths(
                confirm_report["as_of"] or report["as_of"], args.output_dir
            )
            confirm_json_path.write_text(
                json.dumps(confirm_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            confirm_md_path.write_text(confirm_markdown, encoding="utf-8")
            print(f"wrote {confirm_json_path}")
            print(f"wrote {confirm_md_path}")
        print(confirm_markdown)


if __name__ == "__main__":
    main()
