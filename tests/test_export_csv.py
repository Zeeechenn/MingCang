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
