from __future__ import annotations

import json

from backend.research.watchlist import (
    REQUIRED_FIELDS,
    all_watchlist_symbols,
    load_watchlists,
    symbols_by_theme,
    thesis_view,
    themes_by_symbol,
    validate_watchlist_entry,
)

_VALID_ENTRY = {
    "theme_key": "innovative_drug",
    "title": "创新药",
    "thesis": "owner 前期板块研究,细节待 owner 补充",
    "symbols": ["603259", "300759", "002821"],
    "validation_conditions": ["清单内成员触发价量异动/板块共振/新闻L1"],
    "invalidation_conditions": ["owner 前期板块研究判断被证伪(细节待 owner 补充)"],
    "created_at": "2026-07-03",
    "source_ref": "pending",
}


def test_validate_watchlist_entry_accepts_valid_entry():
    assert validate_watchlist_entry(_VALID_ENTRY) == []


def test_validate_watchlist_entry_reports_all_missing_fields():
    errors = validate_watchlist_entry({})
    assert len(errors) == len(REQUIRED_FIELDS)
    for field in REQUIRED_FIELDS:
        assert any(field in error for error in errors)


def test_validate_watchlist_entry_reports_type_errors():
    bad_entry = dict(_VALID_ENTRY)
    bad_entry["symbols"] = "603259"  # should be a list
    bad_entry["created_at"] = "not-a-date"
    bad_entry["validation_conditions"] = "not-a-list"
    errors = validate_watchlist_entry(bad_entry)
    assert any("symbols must be" in e for e in errors)
    assert any("created_at must be" in e for e in errors)
    assert any("validation_conditions must be" in e for e in errors)


def test_validate_watchlist_entry_rejects_non_dict():
    assert validate_watchlist_entry(["not", "a", "dict"]) == ["entry is not a JSON object"]


def test_load_watchlists_loads_valid_files(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY), encoding="utf-8")
    entries, errors = load_watchlists(tmp_path)
    assert errors == []
    assert len(entries) == 1
    assert entries[0]["theme_key"] == "innovative_drug"


def test_load_watchlists_reports_invalid_json_without_dropping_valid_entries(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY), encoding="utf-8")
    (tmp_path / "b.json").write_text("{not valid json", encoding="utf-8")
    entries, errors = load_watchlists(tmp_path)
    assert len(entries) == 1
    assert any("invalid JSON" in e for e in errors)


def test_load_watchlists_reports_schema_violation_without_dropping_valid_entries(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY), encoding="utf-8")
    bad_entry = dict(_VALID_ENTRY, theme_key="broken", symbols=[])
    (tmp_path / "b.json").write_text(json.dumps(bad_entry), encoding="utf-8")
    entries, errors = load_watchlists(tmp_path)
    assert len(entries) == 1
    assert any("symbols must be" in e for e in errors)


def test_load_watchlists_reports_duplicate_theme_key(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_VALID_ENTRY), encoding="utf-8")
    entries, errors = load_watchlists(tmp_path)
    assert len(entries) == 1
    assert any("duplicate theme_key" in e for e in errors)


def test_load_watchlists_missing_directory_reports_explicit_error(tmp_path):
    entries, errors = load_watchlists(tmp_path / "does_not_exist")
    assert entries == []
    assert errors == [f"missing:directory:{tmp_path / 'does_not_exist'}"]


def test_load_watchlists_accepts_json_array_of_entries(tmp_path):
    second = dict(_VALID_ENTRY, theme_key="other_theme", title="其他主题", symbols=["000001"])
    (tmp_path / "combined.json").write_text(json.dumps([_VALID_ENTRY, second]), encoding="utf-8")
    entries, errors = load_watchlists(tmp_path)
    assert errors == []
    assert {e["theme_key"] for e in entries} == {"innovative_drug", "other_theme"}


def test_symbols_by_theme_and_themes_by_symbol_and_all_symbols():
    entries = [
        _VALID_ENTRY,
        dict(_VALID_ENTRY, theme_key="semiconductor", title="半导体", symbols=["603259", "000725"]),
    ]
    by_theme = symbols_by_theme(entries)
    assert by_theme["innovative_drug"] == ["603259", "300759", "002821"]
    assert by_theme["semiconductor"] == ["603259", "000725"]

    by_symbol = themes_by_symbol(entries)
    assert sorted(by_symbol["603259"]) == ["innovative_drug", "semiconductor"]
    assert by_symbol["300759"] == ["innovative_drug"]

    all_symbols = all_watchlist_symbols(entries)
    assert all_symbols == ["603259", "300759", "002821", "000725"]


def test_thesis_view_reads_authoritative_forward_thesis(test_db, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.config.settings.forward_thesis_enabled", True, raising=False)
    from backend.research.forward_thesis import create_forward_thesis

    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY, ensure_ascii=False), encoding="utf-8")
    create_forward_thesis(
        test_db,
        statement="[theme:innovative_drug] 权威论点",
        status="active",
        invalidation_conditions=["失效条件A", "失效条件B"],
        follow_up_metrics=["验证条件A"],
    )

    view = thesis_view("innovative_drug", db=test_db, fallback_entry=_VALID_ENTRY)
    assert view["theme_key"] == "innovative_drug"
    assert view["title"] == "创新药"
    assert view["symbols"] == ["603259", "300759", "002821"]
    assert view["thesis"] == "权威论点"
    assert view["validation_conditions"] == ["验证条件A"]
    assert view["invalidation_conditions"] == ["失效条件A", "失效条件B"]
    assert view["source_ref"] == "pending"

    entries, errors = load_watchlists(tmp_path, db=test_db)
    assert errors == []
    assert entries[0]["thesis"] == "权威论点"
    assert entries[0]["validation_conditions"] == ["验证条件A"]
    assert entries[0]["invalidation_conditions"] == ["失效条件A", "失效条件B"]


def test_m60_thesis_sync_is_idempotent_and_preserves_conditions(test_db, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.config.settings.forward_thesis_enabled", True, raising=False)
    from backend.data.database import ForwardThesis
    from backend.tools.m60_thesis_sync import sync_watchlists_to_forward_thesis

    (tmp_path / "a.json").write_text(json.dumps(_VALID_ENTRY, ensure_ascii=False), encoding="utf-8")

    first = sync_watchlists_to_forward_thesis(db=test_db, watchlist_dir=tmp_path)
    assert first["summary"]["created"] == 1
    assert first["summary"]["updated"] == 0
    assert test_db.query(ForwardThesis).count() == 1

    second = sync_watchlists_to_forward_thesis(db=test_db, watchlist_dir=tmp_path)
    assert second["summary"]["created"] == 0
    assert second["summary"]["unchanged"] == 1
    assert test_db.query(ForwardThesis).count() == 1

    row = test_db.query(ForwardThesis).one()
    assert row.symbol is None
    assert row.status == "active"
    assert row.statement == "[theme:innovative_drug] owner 前期板块研究,细节待 owner 补充"
    assert json.loads(row.follow_up_metrics_json) == _VALID_ENTRY["validation_conditions"]
    assert json.loads(row.invalidation_conditions_json) == _VALID_ENTRY["invalidation_conditions"]


def test_seed_innovative_drug_file_is_valid():
    """Guard the shipped Phase 0 seed entry against schema drift."""
    entries, errors = load_watchlists()
    assert errors == []
    innovative_drug = next(e for e in entries if e["theme_key"] == "innovative_drug")
    assert innovative_drug["title"] == "创新药/CXO"
    assert set(innovative_drug["symbols"]) == {"603259", "300759", "002821"}
    # 2026-07-04 论点已回填(m61_p4 盲裁 PIT 重建):source_ref 不再是占位符,
    # thesis 为真实论点——守护"已回填"状态,不许倒退回 pending。
    assert innovative_drug["source_ref"] != "pending"
    assert innovative_drug["source_ref"].strip()
    assert "待 owner 补充" not in innovative_drug["thesis"]
    assert innovative_drug["thesis"].strip()
