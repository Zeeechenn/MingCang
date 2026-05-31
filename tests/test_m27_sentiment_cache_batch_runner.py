import json
import sqlite3


def _write_plan(path, export_path):
    from backend.analysis.sentiment import _cache_key

    rows = []
    for idx, symbol in enumerate(["300001", "300002", "300003"], start=1):
        titles = [f"公司公告获得重大合同 {idx}"]
        cache_key, titles_hash = _cache_key(titles, symbol)
        rows.append({
            "symbol": symbol,
            "date": "2026-01-01",
            "titles": titles,
            "cache_key": cache_key,
            "titles_hash": titles_hash,
            "news_count": 1,
        })
    export_path.write_text(
        json.dumps({"generated_at": "2026-05-31T00:00:00+00:00", "windows": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    plan = {
        "input": {"path": str(export_path)},
        "summary": {
            "total_windows": 3,
            "unique_symbols": 3,
            "deduped_cache_keys": 3,
            "duplicate_windows": 0,
            "invalid_windows": 0,
            "estimated_llm_calls": 3,
        },
    }
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return rows


def _create_cache_db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE sentiment_cache ("
        "cache_key TEXT PRIMARY KEY, symbol TEXT, titles_hash TEXT, "
        "result_json TEXT, created_at DATETIME, updated_at DATETIME)"
    )
    con.commit()
    con.close()


def test_batch_runner_dry_run_writes_state_without_llm_or_db(tmp_path):
    from backend.tools.m27_sentiment_cache_batch_runner import run_batch_runner

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    _create_cache_db(db_path)

    def fail_runner(_titles, _symbol):
        raise AssertionError("dry-run must not call LLM")

    report = run_batch_runner(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=False,
        batch_size=2,
        max_batches=3,
        max_llm_calls_total=6,
        audit_dir=tmp_path / "audit",
        summary_output=tmp_path / "summary.json",
        run_id="dry",
        sentiment_runner=fail_runner,
    )

    assert report["summary"]["stop_reason"] == "dry_run_only"
    assert report["summary"]["batches_attempted"] == 1
    assert report["summary"]["inserted_cache_keys"] == 0
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "audit" / "dry_batch_001_audit.json").exists()
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 0


def test_batch_runner_execute_limits_batches(tmp_path):
    from backend.tools.m27_sentiment_cache_batch_runner import run_batch_runner

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    _create_cache_db(db_path)
    calls = {"count": 0}

    def runner(_titles, _symbol):
        calls["count"] += 1
        return {"sentiment": 0.5, "summary": "偏正", "impact": "short", "key_events": []}

    report = run_batch_runner(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=True,
        batch_size=1,
        max_batches=2,
        max_llm_calls_total=2,
        audit_dir=tmp_path / "audit",
        summary_output=tmp_path / "summary.json",
        run_id="exec",
        sentiment_runner=runner,
    )

    assert calls["count"] == 2
    assert report["summary"]["batches_attempted"] == 2
    assert report["summary"]["inserted_cache_keys"] == 2
    assert report["summary"]["stop_reason"] == "max_llm_calls_total_reached"
    assert (tmp_path / "audit" / "exec_batch_001_rollback.json").exists()
    assert (tmp_path / "audit" / "exec_batch_002_rollback.json").exists()
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 2


def test_batch_runner_resume_skips_existing_without_overwrite(tmp_path):
    from backend.tools.m27_sentiment_cache_batch_runner import run_batch_runner

    plan_path = tmp_path / "plan.json"
    export_path = tmp_path / "missing.json"
    rows = _write_plan(plan_path, export_path)
    db_path = tmp_path / "stocksage.sqlite"
    _create_cache_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO sentiment_cache VALUES (?, ?, ?, ?, ?, ?)",
            (
                rows[0]["cache_key"],
                rows[0]["symbol"],
                rows[0]["titles_hash"],
                '{"sentiment": -0.1}',
                "2026-01-01",
                "2026-01-01",
            ),
        )

    calls = {"count": 0}

    def runner(_titles, _symbol):
        calls["count"] += 1
        return {"sentiment": 0.7, "summary": "偏正", "impact": "short", "key_events": []}

    report = run_batch_runner(
        plan_path,
        db_url=f"sqlite:///{db_path}",
        execute=True,
        batch_size=1,
        max_batches=1,
        max_llm_calls_total=1,
        audit_dir=tmp_path / "audit",
        summary_output=None,
        run_id="resume",
        sentiment_runner=runner,
    )

    assert calls["count"] == 1
    assert report["batches"][0]["existing_cache_keys"] == 1
    assert report["summary"]["inserted_cache_keys"] == 1
    with sqlite3.connect(db_path) as con:
        existing = con.execute(
            "SELECT result_json FROM sentiment_cache WHERE cache_key = ?",
            (rows[0]["cache_key"],),
        ).fetchone()[0]
        assert json.loads(existing)["sentiment"] == -0.1
        assert con.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 2
