"""Smoke tests for /api/export CSV endpoints (M25.4)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_export_signals_csv_returns_csv_headers(test_db):
    client = TestClient(app)
    resp = client.get("/api/export/signals.csv?limit=5")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "signals.csv" in resp.headers["content-disposition"]
    body = resp.text
    assert body.startswith("﻿")
    first_line = body.splitlines()[0].lstrip("﻿")
    assert "代码" in first_line


def test_export_positions_csv_returns_csv_headers(test_db):
    client = TestClient(app)
    resp = client.get("/api/export/positions.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "positions.csv" in resp.headers["content-disposition"]


def test_export_reviews_csv_returns_csv_headers(test_db):
    client = TestClient(app)
    resp = client.get("/api/export/reviews.csv?limit=5")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "reviews.csv" in resp.headers["content-disposition"]


def test_export_coverage_csv_returns_csv_headers(test_db):
    client = TestClient(app)
    resp = client.get("/api/export/coverage.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "coverage.csv" in resp.headers["content-disposition"]
    body = resp.text.lstrip("﻿")
    assert "snapshot_at" in body
