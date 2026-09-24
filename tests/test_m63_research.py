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


def test_latest_labels_as_of_excludes_created_after_cutoff(tmp_path):
    path = tmp_path / "labels.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE long_term_labels(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, label TEXT, expires_at TEXT, created_at TEXT)")
    con.executemany(
        "INSERT INTO long_term_labels(symbol,date,label,expires_at,created_at) VALUES(?,?,?,?,?)",
        [
            ("000858", "2026-09-20", "旧标签", "2026-10-01", "2026-09-20 08:00:00"),
            ("000858", "2026-09-20", "未来重算", "2026-10-01", "2026-09-25 08:00:00"),
        ],
    )
    con.commit()
    con.close()
    assert m63_research._latest_labels(["000858"], db_path=path, as_of="2026-09-24") == {"000858": "旧标签(2026-09-20)"}


def test_run_target_local_industry_fallback_is_tracked_subset(tmp_path, monkeypatch):
    path = tmp_path / "industry.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE stocks(asset_key TEXT, symbol TEXT, name TEXT, industry TEXT, market TEXT, active BOOLEAN)")
    con.executemany(
        "INSERT INTO stocks VALUES(?,?,?,?,?,?)",
        [(f"CN:{symbol}", symbol, name, "白酒Ⅱ", "CN", 1) for symbol, name in [("000596", "古井贡酒"), ("000858", "五粮液")]]
        + [("US:WINE", "WINE", "Wine Co", "白酒", "US", 1), ("CN:INACTIVE", "600000", "Inactive", "白酒", "CN", 0)],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(m63_research, "default_sqlite_path", lambda: path)
    resolved = m63_research._resolve_from_local_stock_industry("白酒")
    assert resolved["symbols"] == ["000596", "000858"]
    assert resolved["source"] == "local_stock_industry_unversioned"
    assert resolved["coverage"]["full_market"] is False


def test_stage_payload_failure_blocks_queue_completion():
    assert m63_research._stage_payload_has_failure({"failed": [{"symbol": "000858"}]})
    assert m63_research._stage_payload_has_failure({"deep": {"gate_status": "blocked"}})
    assert not m63_research._stage_payload_has_failure({"failed": [], "cards": []})


def test_stage_health_does_not_confuse_skipped_or_partial_with_ok():
    assert "跳过" in m63_research._stage_health_line({"name": "标签", "ok": True, "result": {"skipped": True, "reason": "offline"}})
    assert "partial" in m63_research._stage_health_line({"name": "深研", "ok": True, "result": {"quality_status": "partial"}})
    assert "跳过" in m63_research._stage_health_line({"name": "数据", "ok": True, "result": {"news": {"skipped": True}, "quotes": {"skipped": True}}})


def test_offline_orchestration_closes_network_models_and_queue_writes(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    queue = [{"id": "q1", "target": "300308", "status": "pending", "created_at": "2026-09-20"}]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    calls = []
    monkeypatch.setattr(m63_research, "_latest_labels", lambda symbols, as_of=None: {})

    def backfill(symbols, *, as_of, offline=False):
        assert offline is True
        calls.append("no-data-fetch")
        return {"skipped": True}

    def labels(symbols, *, no_llm, as_of=None):
        assert no_llm is True and as_of == "2026-09-24"
        calls.append("no-label-model")
        return {"skipped": True}

    def deep(target, *, as_of, auto, no_llm, offline=False, output_dir=None):
        assert no_llm and offline and output_dir == tmp_path / "out"
        calls.append("offline-local-deep")
        return {"quality_status": "partial", "model_calls": 0, "offline": True}

    def copilot(symbols, *, no_llm):
        assert no_llm
        calls.append("no-copilot")
        return {"skipped": True}

    monkeypatch.setattr(m63_research, "_run_backfill", backfill)
    monkeypatch.setattr(m63_research, "_run_label_builder", labels)
    monkeypatch.setattr(m63_research, "_run_deep_research_stage", deep)
    monkeypatch.setattr(m63_research, "_run_copilot_stage", copilot)
    monkeypatch.setattr(m63_research, "_upsert_watchlist", lambda *a, **k: (_ for _ in ()).throw(AssertionError("watchlist write")))
    result = m63_research.run_research(
        target="300308", from_queue="q1", queue_path=queue_path, as_of="2026-09-24",
        offline=True, output_dir=tmp_path / "out",
    )
    assert set(calls) == {"no-data-fetch", "no-label-model", "offline-local-deep", "no-copilot"}
    assert json.loads(queue_path.read_text(encoding="utf-8")) == queue
    assert Path(result["report_path"]).is_relative_to(tmp_path / "out")


def test_symbol_target_resolution():
    resolved = m63_research.resolve_target("300604")

    assert resolved["target_type"] == "symbol"
    assert resolved["symbols"] == ["300604"]


def test_preflight_exposes_duplicate_work_and_uncapped_provider_cost():
    submitted = ["300308", "300308", "300394", "601869", "600487", "603259", "600036", "600900", "000858"]
    resolved = m63_research.resolve_target("光通信", symbols=submitted)
    report = m63_research.build_research_preflight(resolved)

    assert report["status"] == "preflight_only_no_execution"
    assert report["submitted_count"] == 9
    assert report["unique_count"] == 8
    assert report["normalized_unique_symbols"] == list(dict.fromkeys(submitted))
    assert report["duplicate_symbols"] == ["300308"]
    assert report["default_run_behavior_changed"] is False
    assert report["stages_on_default_run"]["backfill"]["submitted_symbol_occurrences"] == 9
    assert report["stages_on_default_run"]["labels"]["per_symbol_attempts_at_most"] == 9
    assert report["stages_on_default_run"]["copilot"]["per_symbol_attempts_at_most"] == 8
    assert report["stages_on_default_run"]["copilot"]["omitted_occurrences"] == 1
    assert report["stages_on_default_run"]["copilot"]["first_eight_occurrences"].count("300308") == 2
    assert report["budget"]["model_call_upper_bound"] is None
    assert report["budget"]["billed_cost_upper_bound"] is None
    assert "duplicate_symbols_default_run_repeats_stage_work" in report["warnings"]


def test_preflight_cli_has_no_stage_db_or_network_execution(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not execute a research stage or DB query")

    monkeypatch.setattr(m63_research, "run_research", forbidden)
    monkeypatch.setattr(m63_research, "_connect", forbidden)
    monkeypatch.setattr(m63_research, "_run_backfill", forbidden)
    monkeypatch.setattr(m63_research, "_run_label_builder", forbidden)
    monkeypatch.setattr(m63_research, "_run_deep_research_stage", forbidden)
    monkeypatch.setattr(m63_research, "_run_copilot_stage", forbidden)
    monkeypatch.setattr(m63_research, "_upsert_watchlist", forbidden)
    monkeypatch.setattr(m63_research, "OUTPUT_DIR", tmp_path / "never-written")

    code = m63_research.main([
        "--target", "光通信", "--symbols", "300308,300308,300394",
        "--no-llm", "--preflight",
    ])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["normalized_unique_symbols"] == ["300308", "300394"]
    assert report["stages_on_default_run"]["labels"]["model_call_upper_bound"] == 0
    assert report["budget"]["model_call_upper_bound"] == 0
    assert report["budget"]["external_request_upper_bound"] is None
    assert not (tmp_path / "never-written").exists()


def test_theme_from_watchlist_resolution(tmp_path):
    watchlists = tmp_path / "watchlists"
    _write_watchlist(watchlists)

    resolved = m63_research.resolve_target("光通信", watchlist_dir=watchlists, universe_paths=())

    assert resolved["source"] == "watchlist"
    assert resolved["theme_key"] == "optical"
    assert resolved["symbols"] == ["300308", "300394"]
    assert resolved["coverage"]["listed_count"] == 2
    assert resolved["coverage"]["full_market"] is False


def test_theme_uses_runtime_watchlist_dir_default(monkeypatch, tmp_path):
    watchlists = tmp_path / "runtime-watchlists"
    _write_watchlist(watchlists)
    monkeypatch.setattr(m63_research, "WATCHLIST_DIR", watchlists)

    resolved = m63_research.resolve_target("光通信", universe_paths=())

    assert resolved["source"] == "watchlist"
    assert resolved["coverage"]["watchlist_file"].startswith(str(watchlists))


def test_long_term_role_summary_displays_saved_findings_and_absence():
    lines = m63_research._format_long_term_role_lines(
        ["000858", "600519"],
        {
            "000858": {
                "date": "2026-09-24",
                "label": "观望",
                "quality": "degraded",
                "quality_notes": ["财务项缺失"],
                "votes": {"track": "观望", "quality": "规避"},
                "findings": ["[赛道] 供应链议价稳定", "[质量] 财务覆盖不足"],
                "expires_at": "2026-10-04",
            }
        },
    )

    rendered = "\n".join(lines)
    assert "赛道/供应链: 投票=观望" in rendered
    assert "Piotroski质量: 投票=规避" in rendered
    assert "没有保存该角色的发现" in rendered
    assert "600519: 当前没有有效的已存长期标签" in rendered


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
    assert "标签:跳过" in result["text"]


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
        lambda target, as_of, auto, no_llm: {"summary": "deep ok", "quality_status": "sufficient"},
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
