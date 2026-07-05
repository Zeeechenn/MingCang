from __future__ import annotations

from datetime import datetime, timedelta


def _seed_gate_context(db, symbol: str = "601869", as_of: datetime | None = None) -> datetime:
    from backend.data.database import NewsItem, Price, Stock

    as_of = as_of or datetime(2026, 6, 28, 15, 0, 0)
    db.add(Stock(symbol=symbol, name="长飞光纤", market="CN", industry="通信", active=True))
    start = as_of - timedelta(days=20)
    for idx in range(20):
        day = start + timedelta(days=idx)
        close = 20 + idx
        db.add(
            Price(
                symbol=symbol,
                date=day.strftime("%Y-%m-%d"),
                open=close - 0.2,
                high=close + 0.3,
                low=close - 0.3,
                close=close,
                volume=10000 + idx,
                atr14=0.8,
            )
        )
    db.add(
        NewsItem(
            symbol=symbol,
            title="as_of前新闻可见",
            url="https://example.test/before",
            published_at=as_of - timedelta(hours=1),
            source="unit",
            provider="unit",
            content="as_of前正文可见",
        )
    )
    db.add(
        NewsItem(
            symbol=symbol,
            title="as_of之后新闻不得出现",
            url="https://example.test/after",
            published_at=as_of + timedelta(days=1),
            source="unit",
            provider="unit",
            content="未来正文不得出现",
        )
    )
    db.commit()
    return as_of


def _one_case() -> list[dict[str, str]]:
    return [
        {
            "id": "corning_glassbridge",
            "symbol": "601869",
            "name": "长飞光纤",
            "as_of": "2026-06-28",
            "question": "请判断这是逻辑破坏还是情绪错杀。",
            "outcome_note": "unit",
        }
    ]


def _raw_sqlite_connection(db):
    conn = db.connection().connection
    return getattr(conn, "driver_connection", conn)


def test_build_pit_context_excludes_post_as_of_news(test_db, tmp_path, monkeypatch):
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)

    report = gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705")
    case = report["cases"][0]

    for arm in ("starved", "full"):
        assert "as_of前新闻可见" in case["arms"][arm]["context"]
        assert "as_of之后新闻不得出现" not in case["arms"][arm]["context"]
        assert "未来正文不得出现" not in case["arms"][arm]["context"]


def test_build_starved_arm_is_deterministic(test_db, tmp_path, monkeypatch):
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)

    first = gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705a")
    second = gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705b")

    assert first["cases"][0]["arms"]["starved"] == second["cases"][0]["arms"]["starved"]


def test_build_output_is_blind_adjudication_packet_compatible(test_db, tmp_path, monkeypatch):
    from backend.tools import blind_adjudication
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)

    report = gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705")
    packet, key = blind_adjudication.build_packet(report["cases"][0], _raw_sqlite_connection(test_db))

    assert "盲裁案例包" in packet
    assert "回答甲" in packet
    assert "回答乙" in packet
    assert set(key.values()) == {"starved", "full"}


def test_generate_fills_full_arm_with_mock_provider(test_db, tmp_path, monkeypatch):
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)
    built = gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705")

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        def complete_structured(self, **kwargs):
            self.calls += 1
            if kwargs["tool"]["name"] == "m59_discretion_card":
                return {
                    "stance": "持有倾向",
                    "timing_note": "等待外部证据确认",
                    "rationale": "引用输入包内as_of前新闻与价格证据",
                    "confidence": "med",
                    "reevaluation_trigger": "出现新的公告或成交量异常",
                }
            return {
                "objections": [
                    {
                        "symbol": "601869",
                        "objection": "证据仍不足以排除技术替代风险",
                        "severity": "med",
                        "confidence_adjustment": "none",
                    }
                ]
            }

    provider = FakeProvider()
    generated = gate.generate_cases(
        tmp_path / "m59_discretion_gate_cases_20260705.json",
        db=test_db,
        provider_factory=lambda: provider,
    )

    full = generated["cases"][0]["arms"]["full"]
    assert provider.calls == 2
    assert full["status"] == "ok"
    assert "倾向" in full["response"]
    assert "反方" in full["response"]
    assert built["cases"][0]["arms"]["full"]["status"] == "pending_generate"


def test_generate_retries_with_schema_reminder_then_degrades(test_db, tmp_path, monkeypatch):
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)
    gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705")
    cases_path = tmp_path / "m59_discretion_gate_cases_20260705.json"

    class SemanticFailThenValidProvider:
        """超长已走软截断首跑即过;语义失败(非法stance)仍触发带提醒的重试。"""

        def __init__(self):
            self.card_calls = 0
            self.saw_reminder = False

        def complete_structured(self, **kwargs):
            if kwargs["tool"]["name"] == "m59_discretion_card":
                self.card_calls += 1
                if self.card_calls == 1:
                    return {
                        "stance": "非法立场",
                        "timing_note": "等待外部证据确认",
                        "rationale": "首轮语义失败",
                        "confidence": "med",
                        "reevaluation_trigger": "出现新的公告或成交量异常",
                    }
                self.saw_reminder = gate.SCHEMA_REMINDER.strip() in kwargs["prompt"]
                return {
                    "stance": "持有倾向",
                    "timing_note": "等待外部证据确认",
                    "rationale": "重试后合规的理由",
                    "confidence": "med",
                    "reevaluation_trigger": "出现新的公告或成交量异常",
                }
            return {"objections": []}

    provider = SemanticFailThenValidProvider()
    generated = gate.generate_cases(cases_path, db=test_db, provider_factory=lambda: provider)
    assert generated["cases"][0]["arms"]["full"]["status"] == "ok"
    assert provider.card_calls == 2
    assert provider.saw_reminder

    # 已 ok 的案例幂等跳过
    class BoomProvider:
        def complete_structured(self, **kwargs):
            raise AssertionError("should not be called for ok cases")

    gate.generate_cases(cases_path, db=test_db, provider_factory=lambda: BoomProvider())


def test_generate_marks_failed_and_continues(test_db, tmp_path, monkeypatch):
    from backend.tools import m59_discretion_gate as gate

    _seed_gate_context(test_db)
    monkeypatch.setattr(gate, "selected_cases", _one_case)
    gate.build_gate_cases(db=test_db, out_dir=tmp_path, date_token="20260705")
    cases_path = tmp_path / "m59_discretion_gate_cases_20260705.json"

    class AlwaysInvalidProvider:
        def complete_structured(self, **kwargs):
            if kwargs["tool"]["name"] == "m59_discretion_card":
                return {"stance": "持有倾向", "timing_note": "", "rationale": "",
                        "confidence": "med", "reevaluation_trigger": "外部证据变化"}
            return {"objections": []}

    generated = gate.generate_cases(
        cases_path, db=test_db, provider_factory=lambda: AlwaysInvalidProvider()
    )
    full = generated["cases"][0]["arms"]["full"]
    assert full["status"] == "failed"
    assert "rationale" in str(full["error"])


def test_validate_card_soft_length_truncates_with_flag():
    from backend.tools import m59_discretion as d

    data = {
        "stance": "持有倾向",
        "timing_note": "等待确认",
        "rationale": "证据一。证据二。" + "长" * 130,
        "confidence": "med",
        "reevaluation_trigger": "外部公告或成交量变化",
    }
    card = d._validate_card(data, slot="holding_decision", soft_length=True)
    assert card["length_truncated"] == "true"
    assert len(card["rationale"]) <= 120
    # 硬模式行为不变
    import pytest as _pytest

    with _pytest.raises(ValueError):
        d._validate_card(data, slot="holding_decision")


def test_validate_objections_soft_length_truncates_with_flag():
    from backend.tools import m59_discretion as d

    data = {
        "objections": [
            {
                "symbol": "601869",
                "objection": "反面事实一。" + "长" * 100,
                "severity": "med",
                "confidence_adjustment": "none",
            }
        ]
    }
    out = d._validate_objections(data, {"601869"}, soft_length=True)
    assert out["601869"]["length_truncated"] == "true"
    assert len(out["601869"]["objection"]) <= 80
