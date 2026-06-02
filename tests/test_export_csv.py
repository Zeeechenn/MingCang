"""Smoke tests for /api/export CSV endpoints (M25.4)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.data.database import get_db
from backend.main import app


def _client_for_db(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _clear_client_override():
    app.dependency_overrides.pop(get_db, None)


def test_export_signals_csv_returns_csv_headers(test_db):
    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/signals.csv?limit=5")
    finally:
        _clear_client_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "signals.csv" in resp.headers["content-disposition"]
    body = resp.text
    assert body.startswith("﻿")
    first_line = body.splitlines()[0].lstrip("﻿")
    assert "代码" in first_line


def test_export_positions_csv_returns_csv_headers(test_db):
    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/positions.csv")
    finally:
        _clear_client_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "positions.csv" in resp.headers["content-disposition"]


def test_export_reviews_csv_returns_csv_headers(test_db):
    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/reviews.csv?limit=5")
    finally:
        _clear_client_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "reviews.csv" in resp.headers["content-disposition"]


def test_export_coverage_csv_returns_csv_headers(test_db):
    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/coverage.csv")
    finally:
        _clear_client_override()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "coverage.csv" in resp.headers["content-disposition"]
    body = resp.text.lstrip("﻿")
    assert "snapshot_at" in body


def test_export_postmarket_review_html_includes_versions_and_disclaimer(test_db):
    from backend.data.database import ReviewRun, Signal, Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", active=True))
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-21",
        technical_score=20,
        sentiment_score=35,
        composite_score=36,
        recommendation="可小仓试错",
        confidence="中",
        limit_status="normal",
        rule_version="multi_agent_v2:new_framework",
    ))
    test_db.add(ReviewRun(
        kind="daily",
        as_of="2026-05-21",
        summary="盘后复盘已生成。",
        status="created",
    ))
    test_db.commit()

    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/postmarket-review.html?as_of=2026-05-21")
    finally:
        _clear_client_override()

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "postmarket-review-2026-05-21.html" in resp.headers["content-disposition"]
    assert "研究复盘，非投资建议、非价格预测" in resp.text
    assert "rule/profile version" in resp.text
    assert "multi_agent_v2:new_framework" in resp.text
    assert "profile_version" in resp.text
    assert "new_framework" in resp.text
    assert "盘后复盘已生成。" in resp.text


def test_export_postmarket_review_word_compatible_response(test_db):
    client = _client_for_db(test_db)
    try:
        resp = client.get("/api/export/postmarket-review.html?as_of=2026-05-21&format=word")
    finally:
        _clear_client_override()

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/msword")
    assert "postmarket-review-2026-05-21.doc" in resp.headers["content-disposition"]
    assert "<html>" in resp.text
    assert "研究复盘，非投资建议、非价格预测" in resp.text
    assert "rule_version" in resp.text
