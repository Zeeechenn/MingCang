from __future__ import annotations

from datetime import datetime, timedelta


def _seed_case_context(db, symbol: str = "601869", as_of: datetime | None = None) -> datetime:
    from backend.data.database import Announcement, NewsItem, Price, ResearchReport, Stock

    as_of = as_of or datetime(2026, 6, 28, 15, 0, 0)
    db.add(Stock(symbol=symbol, name="长飞光纤", market="CN", industry="通信", active=True))

    start = as_of - timedelta(days=70)
    for idx in range(70):
        day = start + timedelta(days=idx)
        close = 30 + idx * 0.1
        db.add(
            Price(
                symbol=symbol,
                date=day.strftime("%Y-%m-%d"),
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=10000 + idx,
                atr14=0.8,
            )
        )

    db.add(
        NewsItem(
            symbol=symbol,
            title="玻璃桥传言引发板块大跌",
            url="https://example.test/news-before",
            published_at=as_of - timedelta(hours=2),
            source="unit",
            provider="unit",
            content="正文不应出现在饥饿臂",
        )
    )
    db.add(
        NewsItem(
            symbol=symbol,
            title="未来新闻不得出现",
            url="https://example.test/news-after",
            published_at=as_of + timedelta(days=1),
            source="unit",
            provider="unit",
            content="未来正文不得出现",
        )
    )
    db.add(
        Announcement(
            symbol=symbol,
            title="公告证据",
            ann_type="经营",
            published_at=as_of - timedelta(days=1),
            provider="unit",
        )
    )
    db.add(
        ResearchReport(
            symbol=symbol,
            title="研报证据",
            org_name="券商",
            rating="买入",
            eps_forecast_y1=1.2,
            eps_forecast_y2=1.4,
            publish_date=as_of - timedelta(days=2),
            provider="unit",
        )
    )
    db.commit()
    return as_of


def test_dry_run_builds_starved_and_full_scopes_with_as_of_filter(test_db, tmp_path):
    from backend.tools import m61_judgment_gate as gate

    _seed_case_context(test_db)

    result = gate.run_gate(
        case_ids=["corning_glassbridge"],
        dry_run=True,
        db=test_db,
        out_dir=tmp_path,
        timestamp="20260704_1200",
    )
    case = result["cases"][0]
    arm_a = case["arms"]["starved"]
    arm_b = case["arms"]["full"]

    assert "【价格】" in arm_a["context"]
    assert "新闻标题" in arm_a["context"]
    assert "玻璃桥传言引发板块大跌" in arm_a["context"]
    assert "正文不应出现在饥饿臂" not in arm_a["context"]
    assert "【公告】" not in arm_a["context"]
    assert "【研报】" not in arm_a["context"]
    assert "未来新闻不得出现" not in arm_a["context"]

    assert "【公告】" in arm_b["context"]
    assert "【研报】" in arm_b["context"]
    assert "未来新闻不得出现" not in arm_b["context"]


def test_output_files_written_with_all_four_case_sections(test_db, tmp_path):
    from backend.tools import m61_judgment_gate as gate

    _seed_case_context(test_db)

    result = gate.run_gate(dry_run=True, db=test_db, out_dir=tmp_path, timestamp="20260704_1201")
    md_path = tmp_path / "judgment_gate_20260704_1201.md"
    json_path = tmp_path / "judgment_gate_20260704_1201.json"

    assert result["markdown_path"] == str(md_path)
    assert result["json_path"] == str(json_path)
    assert md_path.exists()
    assert json_path.exists()
    text = md_path.read_text(encoding="utf-8")
    for case in gate.CASES:
        assert f"## {case['id']} - {case['name']}({case['symbol']})" in text
        assert "## 裁决(leader/owner填写)" in text


def test_llm_failure_marks_case_failed_and_continues(test_db, tmp_path):
    from backend.tools import m61_judgment_gate as gate

    _seed_case_context(test_db)

    class EmptyProvider:
        def __init__(self):
            self.calls = 0

        def complete_structured(self, **kwargs):
            self.calls += 1
            return {}

    provider = EmptyProvider()
    result = gate.run_gate(
        case_ids=["corning_glassbridge", "gigadevice_divergence"],
        dry_run=False,
        db=test_db,
        out_dir=tmp_path,
        timestamp="20260704_1202",
        provider_factory=lambda: provider,
    )

    assert len(result["cases"]) == 2
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][1]["status"] == "failed"
    assert provider.calls == 8
    assert "LLM_FAILED" in (tmp_path / "judgment_gate_20260704_1202.md").read_text(encoding="utf-8")
