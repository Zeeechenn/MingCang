from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.research.watchlist import REQUIRED_FIELDS
from backend.tools import m63_opinion, m63_research


def _watchlist_entry(theme_key: str = "optical", title: str = "光通信") -> dict:
    return {
        "theme_key": theme_key,
        "title": title,
        "thesis": "unit thesis",
        "symbols": ["300308", "300394"],
        "validation_conditions": [],
        "invalidation_conditions": [],
        "created_at": "2026-07-05",
        "source_ref": "unit",
    }


def _write_watchlist(directory: Path, entry: dict | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = entry or _watchlist_entry()
    (directory / f"{payload['theme_key']}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_universe(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "601869", "name": "长飞光纤", "sector": "光纤/DCI"},
                    {"symbol": "600487", "name": "亨通光电", "sector": "光纤/DCI"},
                    {"symbol": "603259", "name": "药明康德", "sector": "CXO / 医药"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _tmp_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            CREATE TABLE long_term_labels(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                label TEXT
            )
            """
        )
        con.commit()
    finally:
        con.close()
    return path


def test_symbol_target_resolution():
    resolved = m63_research.resolve_target("300604")

    assert resolved["target_type"] == "symbol"
    assert resolved["symbols"] == ["300604"]


def test_theme_from_watchlist_resolution(tmp_path):
    watchlists = tmp_path / "watchlists"
    _write_watchlist(watchlists)

    resolved = m63_research.resolve_target("光通信", watchlist_dir=watchlists, universe_paths=())

    assert resolved["source"] == "watchlist"
    assert resolved["theme_key"] == "optical"
    assert resolved["symbols"] == ["300308", "300394"]


def test_theme_from_universe_sector_resolution(tmp_path):
    universe = tmp_path / "universe.json"
    _write_universe(universe)

    resolved = m63_research.resolve_target("光纤", watchlist_dir=tmp_path / "empty", universe_paths=(universe,))

    assert resolved["source"] == "universe_sector"
    assert resolved["symbols"] == ["601869", "600487"]


def test_unresolvable_theme_fails_with_human_message(tmp_path, capsys):
    code = m63_research.main(["--target", "不存在主题", "--no-llm"])

    captured = capsys.readouterr()
    assert code == 2
    assert "请显式提供 --symbols" in captured.err


def test_pipeline_continues_past_failing_stage(tmp_path, monkeypatch):
    _tmp_db(tmp_path / "m63.db")
    monkeypatch.setattr(m63_research, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(m63_research, "_latest_labels", lambda symbols: {})
    monkeypatch.setattr(
        m63_research,
        "_run_backfill",
        lambda symbols, as_of: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(m63_research, "_run_label_builder", lambda symbols, no_llm: {"skipped": True})
    monkeypatch.setattr(
        m63_research,
        "_run_deep_research_stage",
        lambda target, as_of, auto, no_llm: {"summary": "deep ok"},
    )
    monkeypatch.setattr(m63_research, "_run_copilot_stage", lambda symbols, no_llm: {"cards": []})
    monkeypatch.setattr(
        m63_research,
        "_upsert_watchlist",
        lambda target, as_of, deep_research: {"path": str(tmp_path / "watch.json"), "updated": False},
    )

    result = m63_research.run_research(target="300604", no_llm=True, as_of="2026-07-05")

    assert "⚠️ 数据补齐 失败:RuntimeError: boom" in result["text"]
    assert "标签:OK" in result["text"]


def test_research_final_text_uses_sanitize_language_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(m63_research, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(m63_research, "_latest_labels", lambda symbols: {})
    monkeypatch.setattr(m63_research, "_run_backfill", lambda symbols, as_of: {"news": {"skipped": True}})
    monkeypatch.setattr(m63_research, "_run_label_builder", lambda symbols, no_llm: {"skipped": True})
    monkeypatch.setattr(
        m63_research,
        "_run_deep_research_stage",
        lambda target, as_of, auto, no_llm: {"summary": "强烈推荐"},
    )
    monkeypatch.setattr(m63_research, "_run_copilot_stage", lambda symbols, no_llm: {"cards": []})
    monkeypatch.setattr(
        m63_research,
        "_upsert_watchlist",
        lambda target, as_of, deep_research: {"path": str(tmp_path / "watch.json"), "updated": False},
    )

    result = m63_research.run_research(target="300604", no_llm=True, as_of="2026-07-05")

    assert "强烈推荐" not in result["text"]
    assert "[操作词已屏蔽]" in result["text"]
    assert "语言守卫" in result["text"]


def test_from_queue_marks_done_on_success(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            [
                {
                    "id": "2026-07-05:R4_opinion_change:optical",
                    "created_at": "2026-07-05",
                    "target": "300604",
                    "reason": "unit",
                    "trigger_rule": "R4_opinion_change",
                    "status": "pending",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m63_research, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(m63_research, "_latest_labels", lambda symbols: {})
    monkeypatch.setattr(m63_research, "_run_backfill", lambda symbols, as_of: {"news": {"skipped": True}})
    monkeypatch.setattr(m63_research, "_run_label_builder", lambda symbols, no_llm: {"skipped": True})
    monkeypatch.setattr(
        m63_research,
        "_run_deep_research_stage",
        lambda target, as_of, auto, no_llm: {"summary": "deep ok"},
    )
    monkeypatch.setattr(m63_research, "_run_copilot_stage", lambda symbols, no_llm: {"cards": []})
    monkeypatch.setattr(
        m63_research,
        "_upsert_watchlist",
        lambda target, as_of, deep_research: {"path": str(tmp_path / "watch.json"), "updated": False},
    )

    m63_research.run_research(
        target="ignored",
        no_llm=True,
        from_queue="2026-07-05:R4_opinion_change:optical",
        queue_path=queue_path,
        as_of="2026-07-05",
    )

    updated = json.loads(queue_path.read_text(encoding="utf-8"))
    assert updated[0]["status"] == "done"


def test_watchlist_file_created_with_schema_keys(tmp_path):
    target = {
        "target": "光通信",
        "theme_key": "optical",
        "title": "光通信",
        "symbols": ["300308", "300394"],
    }

    result = m63_research._upsert_watchlist(
        target,
        as_of="2026-07-05",
        deep_research={"summary": "景气持续"},
        watchlist_dir=tmp_path,
    )

    entry = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert set(entry) == set(REQUIRED_FIELDS)
    assert entry["source_ref"] == "m63_research_20260705"


def test_opinion_stores_jsonl_and_reversed_enqueues_with_dedup(tmp_path, monkeypatch):
    opinions_path = tmp_path / "opinions.jsonl"
    queue_path = tmp_path / "queue.json"
    analysis = {
        "affected_themes": [
            {"theme_key": "optical", "stance_change": "reversed", "summary": "景气反转"},
        ]
    }
    monkeypatch.setattr(m63_opinion, "analyze_opinion", lambda opinion: analysis)

    m63_opinion.run_opinion(
        text="光纤景气反转",
        source="unit",
        as_of="2026-07-05",
        opinions_path=opinions_path,
        queue_path=queue_path,
    )
    m63_opinion.run_opinion(
        text="光纤景气反转",
        source="unit",
        as_of="2026-07-05",
        opinions_path=opinions_path,
        queue_path=queue_path,
    )

    line = json.loads(opinions_path.read_text(encoding="utf-8").splitlines()[0])
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert line["text"] == "光纤景气反转"
    assert len(queue) == 1
    assert queue[0]["trigger_rule"] == "R4_opinion_change"
    assert queue[0]["reason"] == "观点变化(unit): 景气反转"


def test_opinion_none_does_not_enqueue(tmp_path, monkeypatch):
    opinions_path = tmp_path / "opinions.jsonl"
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(
        m63_opinion,
        "analyze_opinion",
        lambda opinion: {"affected_themes": [{"theme_key": "optical", "stance_change": "none", "summary": "无变化"}]},
    )

    result = m63_opinion.run_opinion(
        text="普通观点",
        source="unit",
        as_of="2026-07-05",
        opinions_path=opinions_path,
        queue_path=queue_path,
    )

    assert result["enqueued"] == []
    assert json.loads(opinions_path.read_text(encoding="utf-8").splitlines()[0])["source"] == "unit"
    assert json.loads(queue_path.read_text(encoding="utf-8")) == []


def test_opinion_no_llm_archive_path(tmp_path, capsys):
    opinions_path = tmp_path / "opinions.jsonl"

    result = m63_opinion.run_opinion(
        text="仅归档",
        source="unit",
        as_of="2026-07-05",
        no_llm=True,
        opinions_path=opinions_path,
        queue_path=tmp_path / "queue.json",
    )

    captured = capsys.readouterr()
    assert "已存档,未分析(无LLM)" in captured.out
    assert result["analysis"] is None
    assert json.loads(opinions_path.read_text(encoding="utf-8").splitlines()[0])["text"] == "仅归档"


def test_opinion_enqueue_sanitizes_trade_words(tmp_path, monkeypatch):
    opinions_path = tmp_path / "opinions.jsonl"
    queue_path = tmp_path / "queue.json"
    analysis = {
        "affected_themes": [
            {"theme_key": "optical", "stance_change": "reversed", "summary": "建议立即买入光模块龙头"},
        ]
    }
    monkeypatch.setattr(m63_opinion, "analyze_opinion", lambda opinion: analysis)

    result = m63_opinion.run_opinion(
        text="我觉得可以买入",
        source="unit",
        as_of="2026-07-05",
        opinions_path=opinions_path,
        queue_path=queue_path,
    )

    assert result["enqueued"], "观点变化应入队"
    reason = result["enqueued"][0]["reason"]
    assert "买入" not in reason
    assert "[操作词已屏蔽]" in reason
