"""Signal.date 可能是纯日期，也可能是批次时间戳(YYYY-MM-DDTHH:MM+08:00)。
下游用 Price.date（永远是纯日期）做等值/范围比较时必须先取信号日前缀，
否则时间戳信号永远匹配不到日线（见 backend/api/routes/signals.py、system.py）。"""
from __future__ import annotations


def test_eval_signals_matches_timestamp_signal_to_plain_date_price(test_db, sample_stocks):
    from backend.api.routes.signals import eval_signals
    from backend.data.database import Price, Signal

    test_db.add_all([
        Price(symbol="300308", date="2026-07-14", open=100, high=101, low=99, close=100, volume=1000),
        Price(symbol="300308", date="2026-07-15", open=100, high=110, low=99, close=110, volume=1000),
    ])
    test_db.add(Signal(
        symbol="300308",
        date="2026-07-14T16:25+08:00",  # test2/live 批次时间戳，非纯日期
        composite_score=35.0,
        recommendation="买入",
        confidence="中",
    ))
    test_db.commit()

    result = eval_signals("300308", days=60, db=test_db)

    assert result.total_signals == 1
    assert result.evaluated == 1
    assert result.records[0].next_day_return == 10.0
    assert result.records[0].correct is True


def test_eval_signals_records_unevaluated_when_no_price_match(test_db, sample_stocks):
    """无对应日线时（含时间戳但当日无价、或跨市场）应仍然优雅返回未评估记录，而非误报。"""
    from backend.api.routes.signals import eval_signals
    from backend.data.database import Signal

    test_db.add(Signal(
        symbol="300308",
        date="2026-07-14T16:25+08:00",
        composite_score=35.0,
        recommendation="买入",
        confidence="中",
    ))
    test_db.commit()

    result = eval_signals("300308", days=60, db=test_db)

    assert result.total_signals == 1
    assert result.evaluated == 0
    assert result.records[0].next_day_return is None


def test_system_health_counts_losses_from_timestamp_signals(test_db, sample_stocks):
    from backend.api.routes.system import system_health
    from backend.data.database import Price, Signal

    test_db.add_all([
        Price(symbol="300308", date="2026-07-14", open=100, high=101, low=99, close=100, volume=1000),
        Price(symbol="300308", date="2026-07-15", open=95, high=99, low=94, close=95, volume=1000),
    ])
    test_db.add(Signal(
        symbol="300308",
        date="2026-07-14T16:25+08:00",
        composite_score=35.0,
        recommendation="买入",
        confidence="中",
    ))
    test_db.commit()

    health = system_health(db=test_db)

    assert health["consecutive_losses"] == 1
