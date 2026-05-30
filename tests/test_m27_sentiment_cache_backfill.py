import json
import sqlite3


def _write_plan(path, export_path):
    from backend.analysis.sentiment import _cache_key

    title_a = ["公司公告获得重大合同"]
    title_b = ["公司公告收到监管处罚", "公司公告警示函"]
    key_a, hash_a = _cache_key(title_a, "300001")
    key_b, hash_b = _cache_key(title_b, "600001")
    export_payload = {
        "generated_at": "2026-05-31T00:00:00+00:00",
        "cache_miss_windows": 3,
        "windows": [
            {
                "symbol": "300001",
                "date": "2026-01-01",
                "titles": title_a,
                "cache_key": key_a,
                "titles_hash": hash_a,
                "news_count": 1,
            },
            {
                "symbol": "300001",
                "date": "2026-01-02",
                "titles": title_a,
                "cache_key": key_a,
                "titles_hash": hash_a,
                "news_count": 1,
            },
            {
                "symbol": "600001",
                "date": "2026-01-01",
                "titles": title_b,
                "cache_key": key_b,
                "titles_hash": hash_b,
                "news_count": 2,
            },
        ],
    }
    export_path.write_text(json.dumps(export_payload, ensure_ascii=False), encoding="utf-8")
    plan_payload = {
        "input": {"path": str(export_path), "exported_cache_miss_windows": 3},
        "summary": {
            "total_windows": 3,
            "unique_symbols": 2,
            "deduped_cache_keys": 2,
            "duplicate_windows": 1,
            "invalid_windows": 0,
            "estimated_llm_calls": 2,
        },
    }
    path.write_text(json.dumps(plan_payload, ensure_ascii=False), encoding="utf-8")
    return key_a, hash_a


def test_backfill_dry_run_does_not_call_llm_or_write(tmp_path):
    from backend.tools.m27_sentiment_cache_backfill import run_backfill

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE sentiment_cache (cache_key TEXT PRIMARY KEY)")

    def fail_runner(_titles, _symbol):
        raise AssertionError("dry-run must not call the sentiment runner")

    result = run_backfill(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=False,
        max_keys=1,
        max_llm_calls=1,
        batch_size=1,
        audit_output=None,
        rollback_output=None,
        sentiment_runner=fail_runner,
    )

    audit = result["audit"]
    assert audit["mode"] == "dry_run"
    assert audit["summary"]["selected_cache_keys"] == 1
    assert audit["summary"]["inserted_cache_keys"] == 0
    assert result["rollback"]["inserted_cache_keys"] == []
    with sqlite3.connect(db_path) as con:
        count = con.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0]
    assert count == 0


def test_backfill_execute_requires_explicit_db_url(tmp_path):
    from backend.tools.m27_sentiment_cache_backfill import run_backfill

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    _write_plan(plan_path, export_path)

    try:
        run_backfill(plan_path, execute=True, max_keys=1, max_llm_calls=1, audit_output=None, rollback_output=None)
    except ValueError as exc:
        assert "--db-url" in str(exc)
    else:
        raise AssertionError("execute should require an explicit DB URL")


def test_backfill_execute_inserts_and_writes_rollback_manifest(tmp_path):
    from backend.tools.m27_sentiment_cache_backfill import run_backfill

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE sentiment_cache ("
            "cache_key TEXT PRIMARY KEY, symbol TEXT, titles_hash TEXT, "
            "result_json TEXT, created_at DATETIME, updated_at DATETIME)"
        )

    calls = {"count": 0}

    def runner(_titles, _symbol):
        calls["count"] += 1
        return {"sentiment": 0.8, "summary": "偏正", "impact": "short", "key_events": ["合同"]}

    result = run_backfill(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=True,
        max_keys=1,
        max_llm_calls=1,
        batch_size=1,
        audit_output=None,
        rollback_output=None,
        sentiment_runner=runner,
    )

    assert calls["count"] == 1
    assert result["audit"]["summary"]["inserted_cache_keys"] == 1
    assert len(result["rollback"]["inserted_cache_keys"]) == 1
    with sqlite3.connect(db_path) as con:
        rows = con.execute("SELECT cache_key, result_json FROM sentiment_cache").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][1])["sentiment"] == 0.8


def test_backfill_execute_skips_existing_without_overwrite(tmp_path):
    from backend.tools.m27_sentiment_cache_backfill import run_backfill

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    key_a, hash_a = _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE sentiment_cache ("
            "cache_key TEXT PRIMARY KEY, symbol TEXT, titles_hash TEXT, "
            "result_json TEXT, created_at DATETIME, updated_at DATETIME)"
        )
        con.execute(
            "INSERT INTO sentiment_cache VALUES (?, ?, ?, ?, ?, ?)",
            (key_a, "300001", hash_a, '{"sentiment": -0.1}', "2026-01-01", "2026-01-01"),
        )

    calls = {"count": 0}

    def runner(_titles, _symbol):
        calls["count"] += 1
        return {"sentiment": 0.2, "summary": "中性", "impact": "short", "key_events": []}

    result = run_backfill(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=True,
        max_keys=2,
        max_llm_calls=2,
        batch_size=2,
        audit_output=None,
        rollback_output=None,
        sentiment_runner=runner,
    )

    assert calls["count"] == 1
    assert result["audit"]["summary"]["skipped_existing_cache_keys"] == 1
    assert result["audit"]["summary"]["inserted_cache_keys"] == 1
    with sqlite3.connect(db_path) as con:
        rows = con.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0]
        existing = con.execute("SELECT result_json FROM sentiment_cache WHERE cache_key = ?", (key_a,)).fetchone()[0]
    assert rows == 2
    assert json.loads(existing)["sentiment"] == -0.1
