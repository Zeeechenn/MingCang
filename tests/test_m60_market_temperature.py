from __future__ import annotations

import json
from datetime import datetime


def test_market_temperature_snapshot_uses_fixture_and_is_idempotent(monkeypatch, test_db):
    from backend.data.database import MarketTemperatureSnapshot
    from backend.tools import m60_market_temperature as tool

    fixtures = {
        tool.EASTMONEY_ZT_POOL_URL: {
            "data": {
                "pool": [
                    {"c": "300001", "n": "测试涨停", "p": 12340, "zdp": 20.0, "fbt": "09:31:00"}
                ]
            }
        },
        tool.EASTMONEY_ZB_POOL_URL: {
            "data": {
                "pool": [
                    {"c": "300002", "n": "测试炸板", "p": 5670, "zdp": 10.0, "fbt": "10:01:00"}
                ]
            }
        },
        tool.EASTMONEY_YZT_POOL_URL: {
            "data": {
                "pool": [
                    {"c": "300003", "n": "昨涨今强", "p": 8910, "zdp": 5.0, "zs": 1.2},
                    {"c": "300004", "n": "昨涨今弱", "p": 4320, "zdp": -1.0, "zs": 0.8},
                ]
            }
        },
    }
    captured = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, headers, timeout):
        captured.append((url, params, headers, timeout))
        return FakeResponse(fixtures[url])

    monkeypatch.setattr(tool.requests, "get", fake_get)
    monkeypatch.setattr(tool, "_utcnow", lambda: datetime(2026, 7, 5, 18, 0))
    monkeypatch.setattr(tool._EASTMONEY_THROTTLE, "wait", lambda: None)

    first = tool.capture_market_temperature_snapshot("2026-07-03", db=test_db)
    second = tool.capture_market_temperature_snapshot("2026-07-03", db=test_db)

    assert first["inserted"] == 4
    assert second["inserted"] == 0
    assert first["summary"] == {
        "snap_date": "2026-07-03",
        "limit_up_count": 1,
        "failed_limit_up_count": 1,
        "failed_limit_up_rate": 0.5,
        "yesterday_limit_up_avg_chg_pct": 2.0,
        "consecutive_limit_height": None,
    }
    assert [call[1]["date"] for call in captured[:3]] == ["20260703", "20260703", "20260703"]
    assert captured[0][1]["sort"] == "fbt:asc"
    assert captured[2][1]["sort"] == "zs:desc"

    rows = test_db.query(MarketTemperatureSnapshot).order_by(MarketTemperatureSnapshot.code).all()
    assert [(row.pool_type, row.code, row.name, row.price) for row in rows] == [
        ("zt", "300001", "测试涨停", 12.34),
        ("zb", "300002", "测试炸板", 5.67),
        ("yzt", "300003", "昨涨今强", 8.91),
        ("yzt", "300004", "昨涨今弱", 4.32),
    ]
    assert json.loads(rows[0].fields_json)["zdp"] == 20.0
