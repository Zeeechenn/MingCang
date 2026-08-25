#!/usr/bin/env python3
"""Track B（实盘）数据门：只读、零 LLM、零网络。

One Loop（Track A）因面板/审计/证据合同失败时，实盘照跑；但如果失败的根因是
行情陈旧或数据源大面积故障，实盘也必须停——不能为了出单拿陈旧价做决策。

两道门，全过才算 pass：
  B1 覆盖率门：当日「有新鲜信号」的支数 / live 池支数 >= --min-coverage。
     这道门只负责抓「数据源大面积故障、整池不可信」，不负责抓「少数几支没取到」：
     入场是可选的——某支陈旧就自然掉出漏斗（广筛写库前已 fail-closed 剔除），
     少一个候选不会造成错误决策；不能将就的是出场，那由 B2 单独兜。
     阈值 0.80 的依据（2026-08-25 实测 8 个交易日）：正常日 6 天全 1.000，
     异常日两天分别是 0.893（08-25 免费源 429 限流）与 0.821（07-20）。
     0.90 会把这两天的实盘整条停掉；0.80 放行局部缺口、拦住半个池子级别的故障。
     「有新鲜信号」= 该 symbol 在 signals 表里有 data_timestamp 落在目标日的行，
     且该 symbol 在 prices 表里的最新 bar 日期 == 目标日。
     （口径照抄 live_trading/live_subset.py 第 1 节：signals 用 data_timestamp
     过滤，prices 用 max(date) 与目标日比较——不是 signals.date。）
  B2 持仓硬门：live_state.json 的 positions[].symbol 每一支，最新 bar 日期
     必须 == 目标日。任意一支陈旧 → fail（stale_holdings）。
     持仓为空 → 自动通过。state 文件读不到 / JSON 坏了 → fail-closed
     （holdings_unreadable）：判不出持仓是否新鲜时，不能默认放行去做出场决策。

⚠️ 这道门只对「当天」有意义：新鲜度判据是 prices 表里 max(date) == 目标日，
拿它去查历史日会因为库里已存在更晚的 bar 而恒判 0 覆盖（不是真的没数据）。
流水线本身已经拒绝非今日日期；手工调用请只传今天。

退出码（接线契约，不得更改）：0 = pass，5 = fail（门没过），2 = 用法/IO 错误。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "live_track_gate.v1"

REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_PASS = 0
EXIT_FAIL = 5
EXIT_USAGE_ERROR = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="目标交易日 YYYY-MM-DD")
    parser.add_argument("--db", default="mingcang.db", help="sqlite 数据库路径（默认相对仓库根 mingcang.db）")
    parser.add_argument(
        "--universe",
        default="live_trading/live_universe.json",
        help="live 池 universe json（默认相对仓库根）",
    )
    parser.add_argument(
        "--state",
        default="live_trading/live_state.json",
        help="实盘持仓状态 json（默认相对仓库根）",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.80,
        help="B1 覆盖率门阈值（默认 0.80；依据见模块 docstring：正常日实测 1.000，"
        "异常日 0.893/0.821，该阈值放行局部缺口、拦住整池级故障）",
    )
    parser.add_argument("--json-out", default=None, help="可选：把 JSON 判决写到此文件")
    return parser


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _load_universe_symbols(universe_path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(universe_path.read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    out: dict[str, dict[str, Any]] = {}
    for s in stocks:
        sym = str(s.get("symbol") or "").strip()
        if sym:
            out[sym] = s
    return out


def _fresh_signal_symbols(conn: sqlite3.Connection, day: str, symbols: list[str]) -> set[str]:
    """symbol 在 signals 表里有 data_timestamp == day 的行。

    口径照抄 live_trading/live_subset.py 第 1 节：
      select symbol, ... from signals where data_timestamp=? and symbol in (...)
    """
    if not symbols:
        return set()
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"select distinct symbol from signals where data_timestamp=? and symbol in ({placeholders})",
        [day, *symbols],
    ).fetchall()
    return {r[0] for r in rows}


def _latest_bar_dates(conn: sqlite3.Connection, symbols: list[str]) -> dict[str, str | None]:
    """symbol -> prices 表里的最新 bar 日期（max(date)）。

    口径照抄 live_trading/live_subset.py 第 1 节：
      select max(date) from prices where symbol=?
    按 symbol 批量取，语义与逐支查询等价。
    """
    result: dict[str, str | None] = {s: None for s in symbols}
    if not symbols:
        return result
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"select symbol, max(date) from prices where symbol in ({placeholders}) group by symbol",
        symbols,
    ).fetchall()
    for sym, max_date in rows:
        result[sym] = max_date
    return result


def _load_holdings(state_path: Path) -> tuple[list[str] | None, str | None]:
    """返回 (持仓 symbol 列表, error)。

    error is None on success (empty list means 空仓). 读不到/坏 JSON 时返回
    (None, "holdings_unreadable") —— fail-closed。
    """
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "holdings_unreadable"
    positions = data.get("positions")
    if positions is None:
        positions = []
    if not isinstance(positions, list):
        return None, "holdings_unreadable"
    symbols: list[str] = []
    for pos in positions:
        if not isinstance(pos, dict):
            return None, "holdings_unreadable"
        sym = str(pos.get("symbol") or "").strip()
        if sym:
            symbols.append(sym)
    return symbols, None


def run_gate(
    *,
    day: str,
    db_path: Path,
    universe_path: Path,
    state_path: Path,
    min_coverage: float,
) -> dict[str, Any]:
    live_syms = _load_universe_symbols(universe_path)
    universe_size = len(live_syms)
    symbol_list = list(live_syms.keys())

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        fresh_signal = _fresh_signal_symbols(conn, day, symbol_list)
        bar_dates = _latest_bar_dates(conn, symbol_list)

        fresh_symbols = sorted(
            s for s in symbol_list if s in fresh_signal and bar_dates.get(s) == day
        )
        missing_symbols = sorted(s for s in symbol_list if s not in fresh_symbols)

        coverage_ratio = (len(fresh_symbols) / universe_size) if universe_size else 1.0

        holdings, holdings_error = _load_holdings(state_path)
        stale_holdings: list[str] = []
        holdings_list: list[str] = []

        if holdings_error is None:
            holdings_list = holdings or []
            if holdings_list:
                held_bar_dates = _latest_bar_dates(conn, holdings_list)
                stale_holdings = sorted(
                    s for s in holdings_list if held_bar_dates.get(s) != day
                )
    finally:
        conn.close()

    reasons: list[str] = []
    if coverage_ratio < min_coverage:
        reasons.append("low_coverage")
    if stale_holdings:
        reasons.append("stale_holdings")
    if holdings_error is not None:
        reasons.append(holdings_error)

    verdict = "pass" if not reasons else "fail"

    return {
        "schema_version": SCHEMA_VERSION,
        "date": day,
        "universe_size": universe_size,
        "fresh_signal_symbols": len(fresh_symbols),
        "coverage_ratio": round(coverage_ratio, 6),
        "min_coverage": min_coverage,
        "missing_symbols": missing_symbols,
        "holdings": holdings_list,
        "stale_holdings": stale_holdings,
        "verdict": verdict,
        "reasons": reasons,
    }


def _print_summary(result: dict[str, Any]) -> None:
    day = result["date"]
    print(f"=== 实盘门（Track B）判决 {day} ===")
    print(
        f"[B1 覆盖率] live池 {result['universe_size']} 支 · 有新鲜信号 "
        f"{result['fresh_signal_symbols']} 支 · 覆盖率 {result['coverage_ratio']:.3f} "
        f"（阈值 {result['min_coverage']:.2f}）"
    )
    if result["missing_symbols"]:
        print(f"  缺新鲜信号: {', '.join(result['missing_symbols'])}")
        if result["fresh_signal_symbols"] == 0:
            print(
                "  提示：整池 0 覆盖通常是把这道门用在了历史日——新鲜度判据是 "
                "max(date)==目标日，库里存在更晚的 bar 时历史日必然判 0。只传今天。"
            )
    else:
        print("  ✅ 全部有新鲜信号")

    if "holdings_unreadable" in result["reasons"]:
        print("[B2 持仓硬门] ⛔ 持仓状态文件读不到或损坏 → fail-closed")
    elif not result["holdings"]:
        print("[B2 持仓硬门] 空仓 → 自动通过")
    elif result["stale_holdings"]:
        print(f"[B2 持仓硬门] ⛔ 陈旧持仓: {', '.join(result['stale_holdings'])}")
    else:
        print(f"[B2 持仓硬门] ✅ 持仓 {len(result['holdings'])} 支全部新鲜")

    print(f"--- 判决: {result['verdict'].upper()}" + (f"（原因: {', '.join(result['reasons'])}）" if result["reasons"] else ""))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    db_path = _resolve(args.db)
    universe_path = _resolve(args.universe)
    state_path = _resolve(args.state)

    if not db_path.exists():
        print(f"用法/IO 错误：数据库不存在 {db_path}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    if not universe_path.exists():
        print(f"用法/IO 错误：universe 文件不存在 {universe_path}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        result = run_gate(
            day=args.date,
            db_path=db_path,
            universe_path=universe_path,
            state_path=state_path,
            min_coverage=args.min_coverage,
        )
    except (OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"用法/IO 错误：{exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    _print_summary(result)

    if args.json_out:
        out_path = _resolve(args.json_out)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"用法/IO 错误：无法写入 --json-out {out_path}（{exc}）", file=sys.stderr)
            return EXIT_USAGE_ERROR

    return EXIT_PASS if result["verdict"] == "pass" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
