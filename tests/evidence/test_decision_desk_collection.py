from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from scripts.run_decision_desk_checks import collect, collect_inputs, sha, visible


def test_actual_sql_collection_excludes_future_fetched_rows_and_expired_labels(tmp_path):
    db = tmp_path / "snapshot.db"
    with sqlite3.connect(db) as con:
        con.executescript("""
            CREATE TABLE prices (symbol,market,date,open,high,low,close,volume,source,adjustment,fetched_at);
            CREATE TABLE financial_metrics (id,symbol,report_date,period_type,revenue,net_profit,
                operating_cf,roe,disclosure_date,fetched_at,source);
            CREATE TABLE long_term_labels (id,symbol,date,label,score,expires_at,created_at,quality);
            CREATE TABLE signals (symbol,date,composite_score,stop_loss,take_profit);
            INSERT INTO prices VALUES ('AAA','CN','2026-09-16',1,1,1,1,100,'source','qfq','2026-09-17');
            INSERT INTO financial_metrics VALUES (1,'AAA','2026-06-30','quarter',1,1,1,1,'2026-09-17','2026-09-15','source');
            INSERT INTO financial_metrics VALUES (2,'AAA','2026-03-31','quarter',1,1,1,1,'2026-04-30','2026-09-15','source');
            INSERT INTO long_term_labels VALUES (1,'AAA','2026-09-15','old',1,'2026-09-15','2026-09-15','trusted');
            INSERT INTO long_term_labels VALUES (2,'AAA','2026-09-16','future',2,'2026-09-20','2026-09-17','trusted');
            INSERT INTO signals VALUES ('AAA','official',42,1,2);
            INSERT INTO signals VALUES ('AAA','extra',99,1,2);
        """)
    before = sha(db)
    common, desk, quality = collect_inputs(db, {"stocks": [{"symbol": "AAA"}]}, "2026-09-16",
                                           datetime(2026, 9, 16, 16, tzinfo=UTC), "official")
    assert common["stocks"][0]["prices"] == []
    assert common["stocks"][0]["financial"]["report_date"] == "2026-03-31"
    assert desk["stocks"][0]["label"] is None
    assert [s["composite_score"] for s in desk["stocks"][0]["official_signals"]] == [42]
    assert "no_visible_price_on_requested_day" in quality["gaps"][0]["gaps"]
    assert common["memory"] == desk["memory"] == []
    assert sha(db) == before
    assert not (tmp_path / "snapshot.db-wal").exists()


def test_output_inside_live_repo_rejected_before_snapshot(tmp_path):
    with pytest.raises(ValueError, match="outside the live repository"):
        collect(source_db=tmp_path / "absent.db", repo_root=tmp_path,
                output_dir=tmp_path / "output", universe_path=tmp_path / "absent.json", as_of="2026-09-15")
    assert not (tmp_path / "output").exists()


def test_existing_output_never_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "manifest.json"
    marker.write_text(json.dumps({"keep": True}))
    with pytest.raises(FileExistsError):
        collect(source_db=tmp_path / "absent.db", repo_root=tmp_path / "repo",
                output_dir=out, universe_path=tmp_path / "absent.json", as_of="2026-09-15")
    assert json.loads(marker.read_text()) == {"keep": True}


def test_unknown_and_future_timestamp_fail_closed():
    cutoff = datetime(2026, 9, 16, tzinfo=UTC)
    assert not visible(None, cutoff)
    assert not visible("garbage", cutoff)
    assert not visible("2026-09-16T01:00:00Z", cutoff)
    assert visible("2026-09-16T07:00:00+08:00", cutoff)
