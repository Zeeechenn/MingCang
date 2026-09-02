"""P0-B1 adversarial guards for the price-history rebase tool.

Every writable test target is a disposable SQLite file under pytest's temporary
directory. No configured database, signal, position, stop, weight, or ledger is
opened for writing.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from backend.tools import rebase_price_history as tool

DATES = [f"2026-07-{day:02d}" for day in range(8, 14)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_db(path: Path, symbols: tuple[str, ...] = ("600900",)) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            asset_key TEXT,
            market TEXT NOT NULL,
            currency TEXT,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            atr14 REAL,
            source TEXT,
            fetched_at TEXT,
            adjustment TEXT,
            UNIQUE(asset_key, date)
        );
        CREATE TABLE ledger_sentinel (value TEXT NOT NULL);
        INSERT INTO ledger_sentinel(value) VALUES ('must-not-change');
        """
    )
    for symbol in symbols:
        rows = []
        for offset, day in enumerate(DATES):
            close = 10.0 + offset
            rows.append((
                symbol, f"CN:{symbol}", "CN", "CNY", day,
                close, close + 0.5, close - 0.5, close, 1000.0,
                None, "provider_a", "2026-07-14T00:00:00", "qfq-old",
            ))
        connection.executemany(
            "INSERT INTO prices (symbol, asset_key, market, currency, date, open, high, "
            "low, close, volume, atr14, source, fetched_at, adjustment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    connection.commit()
    connection.close()
    return path


def _frame(
    *,
    source: str | None = "provider_a",
    adjustment: str | None = "qfq",
    clean: bool = False,
) -> pd.DataFrame:
    closes = [10.0 + offset if clean else 9.0 + offset for offset in range(len(DATES))]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 0.5 for value in closes],
            "low": [value - 0.5 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(DATES),
        },
        index=DATES,
    )
    frame.attrs["source"] = source
    frame.attrs["adjustment"] = adjustment
    frame.attrs["fetched_at"] = "2026-07-14T01:00:00"
    return frame


def _fetch(frame: pd.DataFrame, calls: list[str] | None = None):
    def fetch(symbol: str, market: str, *, days: int):
        if calls is not None:
            calls.append(symbol)
        return frame.copy()

    return fetch


def _prices(path: Path, symbol: str = "600900") -> list[tuple]:
    connection = sqlite3.connect(path)
    rows = connection.execute(
        "SELECT date, close, source, adjustment FROM prices "
        "WHERE symbol=? ORDER BY date", (symbol,),
    ).fetchall()
    sentinel = connection.execute("SELECT value FROM ledger_sentinel").fetchone()
    connection.close()
    assert sentinel == ("must-not-change",)
    return rows


def test_dry_run_is_hash_stable_and_reports_drift(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "plan.db")
    before = _sha256(database)

    result = tool.run_rebase(database, ["600900"], fetch_daily_fn=_fetch(_frame()))

    assert result["run_mode"] == "dry_run"
    assert result["counts"] == {"clean": 0, "drift": 1, "skipped": 0, "blocked": 0}
    assert result["writes_db"] is False
    assert result["writes_tables"] == []
    assert result["audits"][0]["cross_source"] is False
    assert result["database_sha256_before"] == result["database_sha256_after"] == before
    assert _sha256(database) == before
    assert _prices(database)[0][1] == 10.0


def test_read_only_connection_rejects_mutation(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "readonly.db")
    with tool._connect_read_only(database) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connection.execute("UPDATE prices SET close=0")


def test_parser_requires_explicit_database() -> None:
    with pytest.raises(SystemExit):
        tool._build_parser().parse_args(["--symbols", "600900"])


def test_cli_exit_codes_distinguish_drift_from_inconclusive() -> None:
    result = {"counts": {"clean": 0, "drift": 1, "skipped": 0, "blocked": 0}}
    assert tool._result_exit_code(result, execute=False) == 1
    assert tool._result_exit_code(result, execute=True) == 0
    result["counts"]["blocked"] = 1
    assert tool._result_exit_code(result, execute=False) == 2


def test_execute_requires_pinned_source_and_adjustment(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "pinning.db")
    with pytest.raises(tool.RebaseSafetyError, match="requires expected_source"):
        tool.run_rebase(
            database, ["600900"], execute=True, fetch_daily_fn=_fetch(_frame()),
        )


def test_execute_refuses_non_temporary_or_symlink_resolved_target(tmp_path: Path) -> None:
    outside = Path("/Users/zeeechenn/mingcang/mingcang.db")
    with pytest.raises(tool.RebaseSafetyError, match="temporary database copy"):
        tool._assert_temporary_execute_target(outside)

    link = tmp_path / "escape.db"
    link.symlink_to(outside)
    with pytest.raises(tool.RebaseSafetyError, match="temporary database copy"):
        tool._assert_temporary_execute_target(link)


@pytest.mark.parametrize(
    ("expected_source", "expected_adjustment", "message"),
    [
        ("provider_b", "qfq", "source mismatch"),
        ("provider_a", "hfq", "adjustment mismatch"),
    ],
)
def test_execute_fails_closed_on_provenance_mismatch(
    tmp_path: Path,
    expected_source: str,
    expected_adjustment: str,
    message: str,
) -> None:
    database = _create_db(tmp_path / f"{message.replace(' ', '-')}.db")
    before = _sha256(database)

    with pytest.raises(tool.RebaseSafetyError, match=message):
        tool.run_rebase(
            database,
            ["600900"],
            execute=True,
            expected_source=expected_source,
            expected_adjustment=expected_adjustment,
            fetch_daily_fn=_fetch(_frame()),
        )

    assert _sha256(database) == before
    assert list(tmp_path.glob("*.bak.*")) == []


def test_malformed_ohlc_is_blocked_without_writes(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "bad-ohlc.db")
    frame = _frame()
    frame.loc[DATES[2], "high"] = frame.loc[DATES[2], "low"] - 1.0
    before = _sha256(database)

    result = tool.run_rebase(database, ["600900"], fetch_daily_fn=_fetch(frame))

    assert result["counts"]["blocked"] == 1
    assert "high is below" in result["audits"][0]["detail"]
    assert _sha256(database) == before


def test_sidecar_database_is_rejected_until_snapshotted(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "wal.db")
    Path(f"{database}-wal").touch()

    with pytest.raises(tool.RebaseSafetyError, match="standalone snapshot"):
        tool.run_rebase(database, ["600900"], fetch_daily_fn=_fetch(_frame()))


def test_execute_requires_full_stored_history_coverage(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "partial-window.db")
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO prices (symbol, asset_key, market, currency, date, open, high, low, "
        "close, volume, source, fetched_at, adjustment) "
        "VALUES ('600900', 'CN:600900', 'CN', 'CNY', '2026-07-01', 8, 8.5, 7.5, "
        "8, 1000, 'provider_a', '2026-07-14T00:00:00', 'qfq-old')"
    )
    connection.commit()
    connection.close()
    before = _sha256(database)

    with pytest.raises(tool.RebaseSafetyError, match="full stored-history coverage"):
        tool.run_rebase(
            database,
            ["600900"],
            execute=True,
            expected_source="provider_a",
            expected_adjustment="qfq",
            fetch_daily_fn=_fetch(_frame()),
        )

    assert _sha256(database) == before
    assert list(tmp_path.glob("*.bak.*")) == []


def test_cross_source_history_is_explicit_in_plan(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "mixed-source.db")
    connection = sqlite3.connect(database)
    connection.execute("UPDATE prices SET source='provider_b' WHERE id=1")
    connection.commit()
    connection.close()

    result = tool.run_rebase(database, ["600900"], fetch_daily_fn=_fetch(_frame()))

    assert result["audits"][0]["cross_source"] is True
    assert result["audits"][0]["stored_sources"] == ["provider_a", "provider_b"]


def test_execute_reuses_single_validated_fetch_and_creates_backup(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "execute.db")
    calls: list[str] = []

    result = tool.run_rebase(
        database,
        ["600900"],
        execute=True,
        expected_source="provider_a",
        expected_adjustment="qfq",
        fetch_daily_fn=_fetch(_frame(), calls),
    )

    assert calls == ["600900"]
    assert result["writes_db"] is True
    assert result["writes_tables"] == ["prices"]
    assert result["rows_deleted"] == len(DATES)
    assert result["rows_inserted"] == len(DATES)
    backup = Path(result["backup_path"])
    assert backup.is_file()
    assert _prices(backup)[0][1:] == (10.0, "provider_a", "qfq-old")
    assert _prices(database)[0][1:] == (9.0, "provider_a", "qfq")


def test_clean_execute_is_noop_without_backup(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "clean.db")
    before = _sha256(database)

    result = tool.run_rebase(
        database,
        ["600900"],
        execute=True,
        expected_source="provider_a",
        expected_adjustment="qfq",
        fetch_daily_fn=_fetch(_frame(clean=True)),
    )

    assert result["counts"]["clean"] == 1
    assert result["writes_db"] is False
    assert result["backup_path"] is None
    assert _sha256(database) == before


def test_multi_symbol_failure_rolls_back_all_price_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _create_db(tmp_path / "atomic.db", ("600900", "600547"))
    before_rows = {symbol: _prices(database, symbol) for symbol in ("600900", "600547")}
    original = tool._replace_symbol_prices

    def fail_second(connection: sqlite3.Connection, plan: tool._SymbolPlan):
        if plan.audit.symbol == "600547":
            raise RuntimeError("adversarial second-symbol failure")
        return original(connection, plan)

    monkeypatch.setattr(tool, "_replace_symbol_prices", fail_second)
    with pytest.raises(RuntimeError, match="second-symbol failure"):
        tool.run_rebase(
            database,
            ["600900", "600547"],
            execute=True,
            expected_source="provider_a",
            expected_adjustment="qfq",
            fetch_daily_fn=_fetch(_frame()),
        )

    assert {symbol: _prices(database, symbol) for symbol in before_rows} == before_rows
    assert len(list(tmp_path.glob("atomic.db.bak.*"))) == 1


def test_concurrent_database_change_invalidates_plan(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "race.db")

    def mutating_fetch(symbol: str, market: str, *, days: int):
        connection = sqlite3.connect(database)
        connection.execute("UPDATE prices SET volume=volume+1 WHERE id=1")
        connection.commit()
        connection.close()
        return _frame()

    with pytest.raises(tool.RebaseSafetyError, match="changed during read-only planning"):
        tool.run_rebase(database, ["600900"], fetch_daily_fn=mutating_fetch)


def test_missing_provenance_is_blocked(tmp_path: Path) -> None:
    database = _create_db(tmp_path / "missing-provenance.db")
    result = tool.run_rebase(
        database,
        ["600900"],
        fetch_daily_fn=_fetch(_frame(source=None)),
    )
    assert result["counts"]["blocked"] == 1
    assert "requires source and adjustment" in result["audits"][0]["detail"]
