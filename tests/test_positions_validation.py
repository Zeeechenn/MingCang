from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "600519", "quantity": 0, "avg_cost": 100},
        {"symbol": "600519", "quantity": -1, "avg_cost": 100},
        {"symbol": "600519", "quantity": 1, "avg_cost": 0},
        {"symbol": "600519", "quantity": 1, "avg_cost": -100},
        {"symbol": "600519", "market": "XX", "quantity": 1, "avg_cost": 100},
        {"symbol": "600519", "quantity": 1, "avg_cost": 100, "stop_loss": 0},
        {"symbol": "600519", "quantity": 1, "avg_cost": 100, "take_profit": -1},
    ],
)
def test_position_create_rejects_invalid_trading_inputs(payload):
    from backend.api.schemas import PositionCreate

    with pytest.raises(ValidationError):
        PositionCreate(**payload)


def test_position_create_accepts_valid_payload_and_adds_stock(test_db):
    from backend.api.routes.positions import create_position
    from backend.api.schemas import PositionCreate
    from backend.data.database import Stock

    created = create_position(
        PositionCreate(
            symbol="600519",
            name="贵州茅台",
            market="CN",
            quantity=2,
            avg_cost=100,
            stop_loss=90,
            take_profit=130,
            note="initial",
        ),
        db=test_db,
    )

    assert created.symbol == "600519"
    assert created.quantity == 2
    assert created.avg_cost == 100
    assert test_db.query(Stock).filter(Stock.symbol == "600519", Stock.active).count() == 1


def test_position_update_rejects_invalid_values():
    from backend.api.schemas import PositionClose, PositionUpdate

    with pytest.raises(ValidationError):
        PositionUpdate(quantity=-1)
    with pytest.raises(ValidationError):
        PositionUpdate(avg_cost=0)
    with pytest.raises(ValidationError):
        PositionClose(close_price=0)
    with pytest.raises(ValidationError):
        PositionUpdate(status="archived")


def test_close_rejects_non_positive_close_price(test_db):
    from fastapi import HTTPException

    from backend.api.routes.positions import close_position, create_position
    from backend.api.schemas import PositionCreate

    created = create_position(PositionCreate(symbol="600519", quantity=1, avg_cost=100), db=test_db)

    with pytest.raises(HTTPException) as exc:
        close_position(created.id, close_price=0, db=test_db)

    assert exc.value.status_code in {400, 422}


def test_close_rejects_second_close_without_rewriting_realized_pnl(test_db):
    from fastapi import HTTPException

    from backend.api.routes.positions import close_position, create_position
    from backend.api.schemas import PositionClose, PositionCreate
    from backend.data.database import Position

    created = create_position(PositionCreate(symbol="600519", quantity=2, avg_cost=100), db=test_db)
    first = close_position(
        created.id,
        payload=PositionClose(close_price=110, closed_at="2026-05-20"),
        db=test_db,
    )

    with pytest.raises(HTTPException) as exc:
        close_position(
            created.id,
            payload=PositionClose(close_price=90, closed_at="2026-05-21"),
            db=test_db,
        )

    assert exc.value.status_code == 409
    stored = test_db.query(Position).filter(Position.id == created.id).one()
    assert stored.realized_pnl == first.realized_pnl
    assert stored.realized_pnl_pct == first.realized_pnl_pct
    assert stored.closed_at == first.closed_at
    assert stored.close_price == first.close_price


def test_delete_position_keeps_closed_delete_idempotent(test_db):
    from backend.api.routes.positions import close_position, create_position, delete_position
    from backend.api.schemas import PositionClose, PositionCreate

    created = create_position(PositionCreate(symbol="600519", quantity=1, avg_cost=100), db=test_db)
    close_position(created.id, payload=PositionClose(close_price=110), db=test_db)

    assert delete_position(created.id, db=test_db) == {"status": "already_closed"}
