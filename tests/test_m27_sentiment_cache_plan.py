import json
import sqlite3


def _write_export(path):
    from backend.analysis.sentiment import _cache_key

    title_a = ["公司公告获得重大合同"]
    title_b = ["公司公告收到监管处罚", "公司公告警示函"]
    key_a, hash_a = _cache_key(title_a, "300001")
    key_b, hash_b = _cache_key(title_b, "600001")
    payload = {
        "generated_at": "2026-05-31T00:00:00+00:00",
        "cache_miss_windows": 4,
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
            {
                "symbol": "600002",
                "date": "2026-01-01",
                "titles": ["公司普通经营动态"],
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_m27_sentiment_cache_plan_dedupes_windows_without_default_db(tmp_path, monkeypatch):
    from backend.tools.m27_sentiment_cache_plan import build_plan

    export_path = tmp_path / "cache_missing.json"
    _write_export(export_path)

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("default DB should not be opened without explicit db_url")

    monkeypatch.setattr("backend.tools.m27_sentiment_cache_plan.sqlite3.connect", fail_connect)
    plan = build_plan(export_path, batch_size=2)

    assert plan["summary"] == {
        "total_windows": 4,
        "unique_symbols": 3,
        "deduped_cache_keys": 3,
        "duplicate_windows": 1,
        "invalid_windows": 0,
        "estimated_llm_calls": 3,
    }
    assert plan["batch_recommendation"]["estimated_batches"] == 2
    assert plan["db_check"]["mode"] == "not_connected"
    assert "db_not_checked_by_design_pass_explicit_db_url_for_readonly_recheck" in plan["risks"]


def test_m27_sentiment_cache_plan_uses_explicit_sqlite_db_readonly(tmp_path):
    from backend.tools.m27_sentiment_cache_plan import build_plan

    export_path = tmp_path / "cache_missing.json"
    _write_export(export_path)
    db_path = tmp_path / "mingcang.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE sentiment_cache (cache_key TEXT PRIMARY KEY)")
        cache_key = build_plan(export_path)["deduped_cache_keys_sample"][0]["cache_key"]
        con.execute("INSERT INTO sentiment_cache (cache_key) VALUES (?)", (cache_key,))
        con.commit()
    finally:
        con.close()

    plan = build_plan(export_path, batch_size=2, db_url=f"sqlite:///{db_path}")

    assert plan["db_check"] == {
        "enabled": True,
        "mode": "sqlite_readonly",
        "existing_cache_keys": 1,
    }
    assert plan["summary"]["deduped_cache_keys"] == 3
    assert plan["summary"]["estimated_llm_calls"] == 2
    assert plan["batch_recommendation"]["estimated_batches"] == 1


def test_m27_sentiment_cache_plan_rejects_mismatched_export_keys(tmp_path):
    from backend.tools.m27_sentiment_cache_plan import build_plan

    export_path = tmp_path / "cache_missing.json"
    payload = {
        "windows": [
            {
                "symbol": "300001",
                "date": "2026-01-01",
                "titles": ["公司公告获得重大合同"],
                "cache_key": "300001:not-the-real-key",
                "titles_hash": "not-the-real-hash",
            }
        ]
    }
    export_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    plan = build_plan(export_path)

    assert plan["summary"]["total_windows"] == 0
    assert plan["summary"]["deduped_cache_keys"] == 0
    assert plan["summary"]["invalid_windows"] == 1
    assert plan["invalid_windows_sample"][0]["reason"] == "cache_key_mismatch"
    assert "invalid_windows_require_review_before_any_backfill_writer" in plan["risks"]


def test_m27_sentiment_cache_plan_markdown_contains_required_sections(tmp_path):
    from backend.tools.m27_sentiment_cache_plan import build_plan, plan_to_markdown

    export_path = tmp_path / "cache_missing.json"
    _write_export(export_path)
    markdown = plan_to_markdown(build_plan(export_path, batch_size=25))

    assert "M27.3 Sentiment Cache Backfill Dry-Run Plan" in markdown
    assert "total_windows: 4" in markdown
    assert "deduped_cache_keys: 3" in markdown
    assert "duplicate_windows: 1" in markdown
    assert "invalid_windows: 0" in markdown
    assert "estimated_llm_calls: 3" in markdown
    assert "## Batch Recommendation" in markdown
    assert "## Risks" in markdown
    assert "## Next Steps" in markdown


def test_m27_sentiment_cache_plan_rejects_non_sqlite_db_url(tmp_path):
    from backend.tools.m27_sentiment_cache_plan import build_plan

    export_path = tmp_path / "cache_missing.json"
    _write_export(export_path)

    try:
        build_plan(export_path, db_url="postgresql://localhost/mingcang")
    except ValueError as exc:
        assert "only sqlite" in str(exc)
    else:
        raise AssertionError("non-sqlite DB URLs should be rejected")
