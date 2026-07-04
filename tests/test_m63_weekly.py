from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.tools import m63_daily


def _db(path: Path) -> Path:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE positions(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                quantity REAL,
                avg_cost REAL,
                sector TEXT,
                status TEXT
            );
            CREATE TABLE prices(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                close REAL
            );
            CREATE TABLE long_term_labels(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                label TEXT,
                expires_at TEXT,
                created_at TEXT
            );
            CREATE TABLE degradation_events(
                id INTEGER PRIMARY KEY,
                ts TEXT,
                component TEXT,
                category TEXT,
                provider TEXT,
                error TEXT,
                context_json TEXT
            );
            """
        )
        con.executemany(
            "INSERT INTO prices(symbol, date, close) VALUES (?, ?, ?)",
            [
                ("300308", "2026-06-29", 100),
                ("300308", "2026-07-05", 112),
                ("300394", "2026-06-29", 50),
                ("300394", "2026-07-05", 51),
            ],
        )
        con.execute(
            """
            INSERT INTO long_term_labels(symbol, date, label, expires_at, created_at)
            VALUES ('300308', '2026-07-04', '可关注', '2026-07-07', '2026-07-04')
            """
        )
        con.execute(
            """
            INSERT INTO positions(symbol, name, quantity, avg_cost, sector, status)
            VALUES ('300394', '天孚通信', 10, 40, '光通信', 'open')
            """
        )
        con.execute(
            """
            INSERT INTO degradation_events(ts, component, category, provider, error, context_json)
            VALUES ('2026-07-04T10:00:00', 'category_registry', 'fund_flow', 'unit', 'empty', '{}')
            """
        )
        con.commit()
    finally:
        con.close()
    return path


def _write_universe(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "300308", "name": "中际旭创", "sector": "光通信"},
                    {"symbol": "300394", "name": "天孚通信", "sector": "光通信"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_watchlist(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stale.json").write_text(
        json.dumps(
            {
                "theme_key": "stale",
                "title": "陈旧主题",
                "thesis": "旧论点",
                "symbols": ["300394"],
                "validation_conditions": [],
                "invalidation_conditions": [],
                "created_at": "2026-05-20",
                "source_ref": "m63_research_20260520",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_weekly_no_llm_detects_miss_stale_expiring_and_writes_report(tmp_path, monkeypatch):
    from backend.tools import m63_weekly

    db_path = _db(tmp_path / "m63.db")
    universe = tmp_path / "universe.json"
    _write_universe(universe)
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe,))
    queue_path = tmp_path / "queue.json"
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [{"date": "2026-07-04", "target": "300394", "trigger_type": "price_move"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_watchlist(tmp_path / "watchlists")

    result = m63_weekly.run_weekly(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=queue_path,
        history_path=history_path,
        watchlist_dir=tmp_path / "watchlists",
        output_dir=tmp_path / "out",
        exit_shadow_builder=lambda **_: {"trade_differences": []},
    )

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert result["attribution"]["skipped"] is True
    assert "300308" in result["text"]
    assert "漏网清单" in result["text"]
    assert any(item["target"] == "300308" and item["trigger_rule"] == "R5_weekly_sweep" for item in queue)
    assert any(item["target"] == "stale" and item["trigger_rule"] == "R5_weekly_sweep" for item in queue)
    assert sum(item["target"] == "300308" and item["trigger_rule"] == "R5_weekly_sweep" for item in queue) == 1
    assert "长期标签临期" in result["text"]
    assert "陈旧主题" in result["text"]
    assert "category_registry" in result["text"]
    assert Path(result["output_path"]).exists()

    second = m63_weekly.run_weekly(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=queue_path,
        history_path=history_path,
        watchlist_dir=tmp_path / "watchlists",
        output_dir=tmp_path / "out",
        exit_shadow_builder=lambda **_: {"trade_differences": []},
    )
    second_queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(second_queue) == len(queue)
    assert second["output_path"] == str(tmp_path / "out" / "weekly_2026-07-05.md")


def test_weekly_llm_attribution_uses_one_structured_call(tmp_path, monkeypatch):
    from backend.tools import m63_weekly

    db_path = _db(tmp_path / "m63.db")
    universe = tmp_path / "universe.json"
    _write_universe(universe)
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe,))
    calls: list[dict] = []

    def fake_llm(facts):
        calls.append(facts)
        return {"lessons": ["只追踪覆盖过的急涨"], "validated": ["300308"], "falsified": []}

    result = m63_weekly.run_weekly(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=False,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        watchlist_dir=tmp_path / "empty-watchlists",
        output_dir=tmp_path / "out",
        exit_shadow_builder=lambda **_: {"trade_differences": [{"symbol": "300308"}]},
        attribution_runner=fake_llm,
    )

    assert len(calls) == 1
    assert calls[0]["week_price_changes"]
    assert result["attribution"]["lessons"] == ["只追踪覆盖过的急涨"]
    assert "只追踪覆盖过的急涨" in result["text"]


def test_weekly_final_text_uses_sanitize_language_guard(tmp_path, monkeypatch):
    from backend.tools import m63_weekly

    db_path = _db(tmp_path / "m63.db")
    universe = tmp_path / "universe.json"
    _write_universe(universe)
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe,))

    result = m63_weekly.run_weekly(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=False,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        watchlist_dir=tmp_path / "empty-watchlists",
        output_dir=tmp_path / "out",
        exit_shadow_builder=lambda **_: {"trade_differences": []},
        attribution_runner=lambda facts: {"lessons": ["强烈推荐"], "validated": [], "falsified": []},
    )

    assert "强烈推荐" not in result["text"]
    assert "[操作词已屏蔽]" in result["text"]
    assert "语言守卫" in result["text"]
