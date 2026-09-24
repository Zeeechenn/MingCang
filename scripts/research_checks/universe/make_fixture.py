"""Build explicitly synthetic, offline universe fixtures for prepare.py."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SESSION = "2026-09-24"
INDUSTRIES = (
    "半导体", "银行", "医药", "新能源", "电力设备", "有色金属",
    "消费电子", "机械设备", "食品饮料", "通信", "汽车", "化工",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_fixture(extra_count: int = 100) -> dict:
    if extra_count < 75:
        raise ValueError("extra_count must be at least 75 so the fixture has 100+ rows")
    baseline = load_json(ROOT / "baseline-universe.json")
    fixed = [stock["symbol"] for stock in baseline["stocks"]]
    used = set(fixed)
    extras = []
    number = 1
    while len(extras) < extra_count:
        code = f"{600000 + number:06d}"
        number += 1
        if code not in used:
            used.add(code)
            extras.append(code)
    expected = fixed + extras
    rows = []
    for index, symbol in enumerate(expected):
        # Values are deterministic fixture values, never fetched or represented as quotes.
        rows.append({
            "symbol": symbol,
            "data_date": SESSION,
            "source": "synthetic-fixture",
            "exchange": ("SSE" if symbol.startswith("6") else
                         "BSE" if symbol.startswith(("4", "8")) else "SZSE"),
            "security_type": "A_SHARE",
            "industry": INDUSTRIES[index % len(INDUSTRIES)],
            "industry_version": "synthetic-v1",
            "raw_sha256": sha256(f"synthetic:{SESSION}:{symbol}".encode()),
            "published_at": f"{SESSION}T15:10:00+08:00",
            "observed_at": f"{SESSION}T15:30:00+08:00",
            "features_as_of": f"{SESSION}T15:20:00+08:00",
            "industry_as_of": f"{SESSION}T15:00:00+08:00",
            "adjustment_basis": "pit_total_return",
            "amount_unit": "CNY",
            "is_st": index == 0,
            "halted": index == 1,
            "listing_sessions": 500 + index,
            "history_sessions": 400 + index,
            "close_raw": 10.0 + (index % 90) / 10,
            "amount20_cny": 80_000_000 + index * 1_000_000,
            "volatility20": 0.1 + (index % 20) / 100,
            "return20": -0.1 + (index % 40) / 100,
            "return60": -0.2 + (index % 60) / 100,
        })
    return {
        "kind": "synthetic",
        "session": SESSION,
        "cutoff": f"{SESSION}T23:00:00+08:00",
        "scope": "CN_A_SH_SZ_BJ",
        "is_trading_session": True,
        "calendar_sha256": sha256(f"synthetic-calendar:{SESSION}".encode()),
        "universe_effective_date": SESSION,
        "universe_observed_at": f"{SESSION}T15:31:00+08:00",
        "universe_source": "synthetic fixture generator; no market data source",
        "industry_version": "synthetic-v1",
        "expected_symbols": expected,
        "provider_total": len(expected),
        "pagination_complete": True,
        "universe_sha256": sha256(json.dumps(sorted(expected), ensure_ascii=False,
                                                  sort_keys=True, separators=(",", ":"))
                                   .encode("utf-8")),
        "rows": rows,
        "missing_symbols": [],
        "synthetic_holdings": {"A": [fixed[0]], "B": [fixed[1]]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        fixture = build_fixture()
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(fixture, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"fixture refused: {exc}\n")
    print(f"synthetic fixture written: {args.out} ({len(fixture['rows'])} rows; no real market data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
