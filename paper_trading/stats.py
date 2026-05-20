"""Machine-readable statistics for paper-trading markdown ledgers."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


@dataclass
class PaperPosition:
    symbol: str
    name: str
    entry_date: str
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    status: str
    exit_date: str | None
    exit_price: float | None
    return_pct: float | None
    exit_reason: str | None = None
    fees_pct: float = 0.2
    gross_return_pct: float | None = None
    net_return_pct: float | None = None
    holding_days: int | None = None
    signal_snapshot: dict | None = None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _num(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return float(match.group(0)) if match else None


def _price(text: str) -> float | None:
    raw = text or ""
    if "开盘" in raw or "收盘" in raw:
        return None
    return _num(raw)


def _symbol_name(text: str) -> tuple[str, str]:
    parts = (text or "").split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else parts[0]


def _exit_reason(status: str) -> str | None:
    plain = status.replace("*", "")
    if "止损" in plain:
        return "stop_loss"
    if "止盈" in plain and "上移" not in plain:
        return "take_profit"
    if "平仓" in plain:
        return "manual_close"
    if "卖出" in plain:
        return "sell"
    return None


def _holding_days(entry_date: str, exit_date: str | None) -> int | None:
    if not entry_date or not exit_date:
        return None
    try:
        return (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days
    except ValueError:
        return None


def parse_positions_table(path: str | Path) -> list[PaperPosition]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    positions: list[PaperPosition] = []
    in_table = False
    headers: list[str] = []
    for line in lines:
        if not line.strip().startswith("|"):
            if in_table and positions:
                break
            continue
        cells = _cells(line)
        if "股票" in cells and "买入日" in cells and "状态" in cells:
            headers = cells
            in_table = True
            continue
        if in_table and all(set(cell) <= {"-", ":"} for cell in cells if cell):
            continue
        if in_table and len(cells) >= len(headers):
            row = dict(zip(headers, cells))
            symbol, name = _symbol_name(row.get("股票", ""))
            status = row.get("状态", "")
            exit_date = None if row.get("平仓日") in {"—", "-", ""} else row.get("平仓日")
            net_return = _num(row.get("盈亏%", ""))
            fees = 0.2 if exit_date or _exit_reason(status) else 0.0
            positions.append(PaperPosition(
                symbol=symbol,
                name=name,
                entry_date=row.get("买入日", ""),
                entry_price=_price(row.get("买入价", "")),
                stop_loss=_num(row.get("止损价", "")),
                take_profit=_num(row.get("止盈价", "")),
                status=status,
                exit_date=exit_date,
                exit_price=_num(row.get("平仓价", "")),
                return_pct=net_return,
                exit_reason=_exit_reason(status),
                fees_pct=fees,
                gross_return_pct=round(net_return + fees, 4) if net_return is not None and fees else net_return,
                net_return_pct=net_return,
                holding_days=_holding_days(row.get("买入日", ""), exit_date),
                signal_snapshot={},
            ))
    return positions


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for item in returns:
        equity += item
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 4)


def _profit_factor(returns: list[float]) -> float | None:
    gains = sum(x for x in returns if x > 0)
    losses = abs(sum(x for x in returns if x < 0))
    if not losses:
        return None
    return round(gains / losses, 4)


def group_summary(positions: list[PaperPosition], key: str) -> dict:
    groups: dict[str, list[PaperPosition]] = {}
    for p in positions:
        value = getattr(p, key, None) or "unknown"
        groups.setdefault(value, []).append(p)
    return {name: compute_summary(rows) for name, rows in sorted(groups.items())}


def compute_summary(positions: list[PaperPosition]) -> dict:
    closed_markers = ("已止损", "已止盈", "已平仓", "已卖出", "平仓")
    closed = [p for p in positions if p.exit_date or any(marker in p.status for marker in closed_markers)]
    open_positions = [p for p in positions if p not in closed and "待入场" not in p.status]
    realized = [p.net_return_pct for p in closed if p.net_return_pct is not None]
    gross = [p.gross_return_pct for p in closed if p.gross_return_pct is not None]
    floating = [p.return_pct for p in open_positions if p.return_pct is not None]
    wins = [x for x in realized if x > 0]
    losses = [x for x in realized if x < 0]
    return {
        "total_positions": len(positions),
        "closed_positions": len(closed),
        "open_positions": len(open_positions),
        "realized_gross_return_pct": round(sum(gross), 4) if gross else 0.0,
        "realized_fees_pct": round(sum(p.fees_pct for p in closed), 4) if closed else 0.0,
        "realized_return_pct": round(sum(realized), 4) if realized else 0.0,
        "open_return_pct": round(sum(floating), 4) if floating else 0.0,
        "realized_win_rate_pct": round(len(wins) / len(realized) * 100, 2) if realized else None,
        "avg_realized_return_pct": round(sum(realized) / len(realized), 4) if realized else None,
        "avg_open_return_pct": round(sum(floating) / len(floating), 4) if floating else None,
        "profit_factor": _profit_factor(realized),
        "max_drawdown_pct": _max_drawdown(realized),
        "max_single_loss_pct": min(losses) if losses else None,
    }


def build_report(paths: list[str | Path]) -> dict:
    ledgers = []
    all_positions: list[PaperPosition] = []
    for path in paths:
        positions = parse_positions_table(path)
        all_positions.extend(positions)
        ledgers.append({
            "path": str(path),
            "positions": [asdict(p) for p in positions],
            "summary": compute_summary(positions),
            "by_exit_reason": group_summary(positions, "exit_reason"),
        })
    return {
        "summary": compute_summary(all_positions),
        "by_exit_reason": group_summary(all_positions, "exit_reason"),
        "ledgers": ledgers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["paper_trading/test1.md", "paper_trading/test2.md"])
    args = parser.parse_args()
    print(json.dumps(build_report(args.paths), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
