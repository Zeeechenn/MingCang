from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend.tools import p0r_nav_replay as tool


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database(path: Path, *, mixed_source: bool = False) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE signals (
            symbol TEXT, date TEXT, composite_score REAL,
            stop_loss REAL, take_profit REAL
        );
        CREATE TABLE prices (
            symbol TEXT, market TEXT, date TEXT, open REAL, high REAL,
            low REAL, close REAL, source TEXT, adjustment TEXT
        );
        CREATE TABLE stocks (symbol TEXT, industry TEXT);
        INSERT INTO stocks VALUES ('AAA', '电子');
        INSERT INTO stocks VALUES ('BBB', '银行');
        INSERT INTO signals VALUES ('AAA', 'official-1', 60, 8, 12);
        INSERT INTO signals VALUES ('BBB', 'research-1', 99, 8, 12);
        """
    )
    sources = ["provider_a", "provider_b" if mixed_source else "provider_a", "provider_a"]
    for index, day in enumerate(("2026-07-01", "2026-07-02", "2026-07-03")):
        connection.execute(
            "INSERT INTO prices VALUES ('AAA', 'CN', ?, 10, ?, 9, ?, ?, 'qfq')",
            (day, 11 + index, 10 + index, sources[index]),
        )
        connection.execute(
            "INSERT INTO prices VALUES ('BBB', 'CN', ?, 10, 11, 9, 10, 'provider_a', 'qfq')",
            (day,),
        )
    connection.commit()
    connection.close()
    return path


def _continuity(*, status: str = "insufficient_days") -> dict:
    return {
        "status": status,
        "implementation_since": "2026-07-01",
        "required_days": 20,
        "days": [
            {"date": "2026-07-01", "status": "complete", "batch_id": "official-1"},
            {"date": "2026-07-02", "status": "complete", "batch_id": "official-2"},
            {"date": "2026-07-03", "status": "complete", "batch_id": "official-3"},
        ],
    }


def test_build_evidence_uses_only_selected_authoritative_batch_and_never_writes(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "snapshot.db")
    before = _sha(database)

    result = tool.build_evidence(
        database,
        repo_root=tmp_path,
        continuity_result=_continuity(),
    )

    assert result["status"] == "evidence_only_continuity_open"
    assert result["production_unchanged"] is True
    assert result["writes_db"] is False
    assert result["snapshot"]["sha256_before"] == result["snapshot"]["sha256_after"]
    assert _sha(database) == before
    assert result["lineage"]["selected_days"][0]["signal_rows"] == 1
    assert set(result["lineage"]["price_by_symbol"]) == {"AAA"}
    assert result["nav_replay"]["fills"][0]["symbol"] == "AAA"


def test_mixed_price_source_blocks_return_readiness_but_still_returns_diagnostics(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "mixed.db", mixed_source=True)

    result = tool.build_evidence(
        database,
        repo_root=tmp_path,
        continuity_result=_continuity(status="complete"),
    )

    assert result["status"] == "blocked_price_basis"
    assert result["promotion_eligible"] is False
    issue = result["lineage"]["price_basis_issues"][0]
    assert issue["symbol"] == "AAA"
    assert issue["sources"] == ["provider_a", "provider_b"]
    assert "mixed_or_missing_source" in issue["reasons"]
    assert result["nav_replay"]["summary"]["fill_count"] > 0


def test_complete_continuity_and_clean_basis_remain_non_promoting_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path / "clean.db")

    result = tool.build_evidence(
        database,
        repo_root=tmp_path,
        continuity_result=_continuity(status="complete"),
    )

    assert result["status"] == "evidence_only"
    assert result["promotion_eligible"] is False
    assert result["lineage"]["price_basis_issues"] == []


def test_snapshot_with_sidecar_is_rejected(tmp_path: Path) -> None:
    database = _database(tmp_path / "wal.db")
    Path(f"{database}-wal").touch()
    with pytest.raises(ValueError, match="standalone SQLite snapshot"):
        tool.build_evidence(
            database,
            repo_root=tmp_path,
            continuity_result=_continuity(),
        )


def test_output_must_remain_temporary() -> None:
    with pytest.raises(ValueError, match="temporary directory"):
        tool._assert_temporary_output(Path("/Users/zeeechenn/p0r.json"))


def test_immutable_connection_rejects_writes(tmp_path: Path) -> None:
    database = _database(tmp_path / "readonly.db")
    with tool._connect_immutable(database) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connection.execute("UPDATE prices SET close=0")
