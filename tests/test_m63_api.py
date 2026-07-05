from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.data.database import Base, get_db
from backend.main import app


@pytest.fixture
def http_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(http_db):
    def override_get_db():
        yield http_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_m63_reports_list_and_latest_are_sorted(client, tmp_path, monkeypatch):
    from backend.api.routes import m63

    out = tmp_path / "m63_out"
    out.mkdir()
    (out / "postmarket_2026-07-03.md").write_text("old", encoding="utf-8")
    (out / "postmarket_2026-07-05.md").write_text("new", encoding="utf-8")
    (out / "research_300308_20260704.md").write_text("research", encoding="utf-8")
    (out / "postmarket_2026-07-06.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(m63, "OUTPUT_DIR", out)

    listed = client.get("/api/m63/reports?mode=postmarket")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"mode": "postmarket", "as_of": "2026-07-05", "filename": "postmarket_2026-07-05.md"},
        {"mode": "postmarket", "as_of": "2026-07-03", "filename": "postmarket_2026-07-03.md"},
    ]

    latest = client.get("/api/m63/reports/postmarket/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json() == {"mode": "postmarket", "as_of": "2026-07-05", "text": "new"}


def test_m63_report_file_rejects_path_traversal(client, tmp_path, monkeypatch):
    from backend.api.routes import m63

    out = tmp_path / "m63_out"
    out.mkdir()
    (out / "weekly_2026-07-05.md").write_text("weekly", encoding="utf-8")
    monkeypatch.setattr(m63, "OUTPUT_DIR", out)

    ok = client.get("/api/m63/reports/file/weekly_2026-07-05.md")
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"mode": "weekly", "as_of": "2026-07-05", "text": "weekly"}

    bad = client.get("/api/m63/reports/file/..%2Fsecret.md")
    assert bad.status_code in {400, 404}


def test_m63_queue_empty_and_ordered(client, tmp_path, monkeypatch):
    from backend.api.routes import m63

    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(m63, "DEFAULT_QUEUE_PATH", queue_path)
    assert client.get("/api/m63/queue").json() == {"pending": [], "done": []}

    queue_path.write_text(
        json.dumps(
            [
                {"id": "done-old", "target": "A", "status": "done", "done_at": "2026-07-01"},
                {"id": "pending", "target": "B", "status": "pending", "created_at": "2026-07-02"},
                {"id": "done-new", "target": "C", "status": "done", "done_at": "2026-07-03"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    body = client.get("/api/m63/queue").json()
    assert [item["id"] for item in body["pending"]] == ["pending"]
    assert [item["id"] for item in body["done"]] == ["done-new", "done-old"]


def test_m59_discretion_latest_empty_without_table(client):
    resp = client.get("/api/m59/discretion/latest")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_m59_discretion_latest_returns_latest_as_of_cards(client, http_db):
    http_db.execute(
        text(
            """
            CREATE TABLE m59_discretion_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                symbol TEXT NOT NULL,
                slot TEXT NOT NULL,
                card_json TEXT NOT NULL,
                inputs_digest TEXT NOT NULL,
                provider TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    )
    http_db.execute(
        text(
            """
            INSERT INTO m59_discretion_cards(as_of, symbol, slot, card_json, inputs_digest, provider, created_at)
            VALUES (:as_of, :symbol, :slot, :card_json, :inputs_digest, :provider, :created_at)
            """
        ),
        {
            "as_of": "2026-07-04",
            "symbol": "300308",
            "slot": "candidate",
            "card_json": json.dumps({"stance": "observe"}),
            "inputs_digest": "d1",
            "provider": "fake",
            "created_at": "t1",
        },
    )
    http_db.execute(
        text(
            """
            INSERT INTO m59_discretion_cards(as_of, symbol, slot, card_json, inputs_digest, provider, created_at)
            VALUES (:as_of, :symbol, :slot, :card_json, :inputs_digest, :provider, :created_at)
            """
        ),
        {
            "as_of": "2026-07-05",
            "symbol": "300604",
            "slot": "holding",
            "card_json": json.dumps({"stance": "wait"}),
            "inputs_digest": "d2",
            "provider": "fake",
            "created_at": "t2",
        },
    )
    http_db.commit()

    resp = client.get("/api/m59/discretion/latest")
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "as_of": "2026-07-05",
            "symbol": "300604",
            "slot": "holding",
            "provider": "fake",
            "created_at": "t2",
            "card": {"stance": "wait"},
        }
    ]
