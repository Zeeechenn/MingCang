from __future__ import annotations

import json
import sqlite3

from backend.tools.m60_second_entry import build_second_entry_ledger


def _init_db(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
        """
    )
    return con


def _insert_prices(con, symbol, rows):
    for row in rows:
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                row["date"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
            ),
        )


def _rows(closes, *, start_day=1, lows=None, opens=None, volumes=None, high_pad=1.0):
    result = []
    for idx, close in enumerate(closes):
        day = start_day + idx
        low = lows[idx] if lows is not None and idx < len(lows) and lows[idx] is not None else close - 1.0
        open_price = opens[idx] if opens is not None and idx < len(opens) and opens[idx] is not None else close
        volume = volumes[idx] if volumes is not None and idx < len(volumes) and volumes[idx] is not None else 1000.0
        result.append(
            {
                "date": f"2026-01-{day:02d}",
                "open": open_price,
                "high": close + high_pad,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return result


def _watchtower(path, as_of, symbols):
    payload = {
        "schema_version": "m60_watchtower.v1",
        "as_of": as_of,
        "triggers": [
            {
                "symbol": symbol,
                "trigger_type": "new_high_breakout",
                "price": {"date": as_of, "close": 100.0},
                "detail": {},
            }
            for symbol in symbols
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _entry(ledger, symbol, variant):
    matches = [entry for entry in ledger["entries"] if entry["symbol"] == symbol and entry["variant"] == variant]
    assert len(matches) == 1
    return matches[0]


def test_v2_pullback_fills_on_third_day_ma5_touch_and_no_fill_when_missing(tmp_path):
    db_path = tmp_path / "m60.sqlite"
    with _init_db(db_path) as con:
        closes = [100.0 + i for i in range(25)]
        lows = [close - 0.2 for close in closes]
        lows[22] = 119.0  # 2026-01-23, first post-trigger low that touches its MA5=120.
        _insert_prices(con, "FILL", _rows(closes, lows=lows))

        no_fill_closes = [100.0 + i for i in range(25)]
        no_fill_lows = [close + 5.0 for close in no_fill_closes]
        _insert_prices(con, "NOFILL", _rows(no_fill_closes, lows=no_fill_lows))

    watchtower = _watchtower(tmp_path / "watchtower.json", "2026-01-20", ["FILL", "NOFILL"])

    ledger = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-01-25",
        watchtower_path=watchtower,
        ledger_path=tmp_path / "ledger.json",
    )

    filled = _entry(ledger, "FILL", "v2_pullback")
    assert filled["entry_status"] == "filled"
    assert filled["entry_date"] == "2026-01-23"
    assert filled["entry_price"] == 120.0

    no_fill = _entry(ledger, "NOFILL", "v2_pullback")
    assert no_fill["entry_status"] == "no_fill"
    assert no_fill["no_fill_reason"] == "no_ma5_touch_within_5d"


def test_v3_confirm_requires_volume_threshold_before_filling(tmp_path):
    db_path = tmp_path / "m60.sqlite"
    with _init_db(db_path) as con:
        closes = [100.0] * 19 + [110.0, 111.0, 112.0, 113.0, 114.0, 115.0]
        volumes = [1000.0] * len(closes)
        volumes[19] = 1000.0
        volumes[20] = 700.0  # new high, below T volume x0.8
        volumes[21] = 801.0  # next new high, passes
        _insert_prices(con, "VOL", _rows(closes, volumes=volumes))
    watchtower = _watchtower(tmp_path / "watchtower.json", "2026-01-20", ["VOL"])

    ledger = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-01-25",
        watchtower_path=watchtower,
        ledger_path=tmp_path / "ledger.json",
    )

    entry = _entry(ledger, "VOL", "v3_confirm")
    assert entry["entry_status"] == "filled"
    assert entry["entry_date"] == "2026-01-22"
    assert entry["entry_price"] == 112.0


def test_stop_loss_freezes_later_window_returns_at_initial_stop(tmp_path):
    db_path = tmp_path / "m60.sqlite"
    with _init_db(db_path) as con:
        closes = [100.0] * 20 + [100.0, 99.0, 98.0, 97.0, 96.0, 130.0, 131.0, 132.0, 133.0, 134.0, 135.0]
        lows = [99.0] * len(closes)
        lows[22] = 96.0
        opens = [100.0] * len(closes)
        opens[20] = 100.0
        _insert_prices(con, "STOP", _rows(closes, lows=lows, opens=opens, high_pad=1.0))
    watchtower = _watchtower(tmp_path / "watchtower.json", "2026-01-20", ["STOP"])

    ledger = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-01-31",
        watchtower_path=watchtower,
        ledger_path=tmp_path / "ledger.json",
    )

    entry = _entry(ledger, "STOP", "v1_immediate")
    assert entry["entry_status"] == "filled"
    assert entry["atr14_at_entry"] == 2.0
    assert entry["initial_stop_price"] == 97.0
    assert entry["stop_hit"] is True
    assert entry["stop_hit_date"] == "2026-01-23"
    assert entry["returns"]["d5"] == -0.03
    assert entry["returns"]["d10"] == -0.03


def test_idempotent_rerun_does_not_duplicate_and_preserves_existing_returns(tmp_path):
    db_path = tmp_path / "m60.sqlite"
    with _init_db(db_path) as con:
        closes = [100.0 + i for i in range(35)]
        _insert_prices(con, "IDEM", _rows(closes))
    watchtower = _watchtower(tmp_path / "watchtower.json", "2026-01-20", ["IDEM"])
    ledger_path = tmp_path / "ledger.json"

    first = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-01-26",
        watchtower_path=watchtower,
        ledger_path=ledger_path,
    )
    first_v1 = _entry(first, "IDEM", "v1_immediate")
    first_v1["returns"]["d5"] = 0.123456
    ledger_path.write_text(json.dumps(first, ensure_ascii=False, indent=2), encoding="utf-8")

    second = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-01-31",
        watchtower_path=watchtower,
        ledger_path=ledger_path,
    )

    assert len(second["entries"]) == 3
    second_v1 = _entry(second, "IDEM", "v1_immediate")
    assert second_v1["returns"]["d5"] == 0.123456
    assert second_v1["returns"]["d10"] is not None


def test_baselines_are_reported_alongside_variants(tmp_path):
    db_path = tmp_path / "m60.sqlite"
    with _init_db(db_path) as con:
        closes = [100.0 + i for i in range(42)]
        _insert_prices(con, "BASE", _rows(closes))
    watchtower = _watchtower(tmp_path / "watchtower.json", "2026-01-20", ["BASE"])

    ledger = build_second_entry_ledger(
        db_path=db_path,
        as_of="2026-02-10",
        watchtower_path=watchtower,
        ledger_path=tmp_path / "ledger.json",
    )

    assert ledger["baselines"]["no_entry"]["return"] == 0.0
    assert ledger["baselines"]["equal_weight_v1_pool"]["d5_n"] == 1
    assert ledger["baselines"]["equal_weight_v1_pool"]["d5"] is not None


def test_preregistered_hypothesis_matches_m29_registry_contract():
    from backend.tools import m29_hypothesis_registry
    from backend.tools.m60_second_entry import _second_entry_hypothesis

    report = m29_hypothesis_registry.build_registry()
    report["hypotheses"].append(_second_entry_hypothesis())

    assert m29_hypothesis_registry.validate_registry(report) == []
