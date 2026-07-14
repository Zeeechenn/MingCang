"""Manual position management routes."""
from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.api.schemas import PositionClose, PositionCreate, PositionOut, PositionUpdate
from backend.data.database import Position, Price, Stock, get_db

router = APIRouter()


def _latest_price(db: Session, symbol: str) -> Price | None:
    return (
        db.query(Price)
        .filter(Price.symbol == symbol)
        .order_by(Price.date.desc())
        .first()
    )


def position_to_schema(pos: Position, db: Session) -> PositionOut:
    """Serialize a position with latest mark-to-market fields."""
    stock = db.query(Stock).filter(Stock.symbol == pos.symbol).first()
    px = _latest_price(db, pos.symbol)
    latest = float(px.close) if px else None
    cost_value = round(float(pos.quantity or 0) * float(pos.avg_cost or 0), 2)
    market_value = round(float(pos.quantity or 0) * latest, 2) if latest is not None else None
    pnl = round(market_value - cost_value, 2) if market_value is not None else None
    pnl_pct = round(pnl / cost_value * 100, 2) if pnl is not None and cost_value else None
    return PositionOut(
        id=pos.id,
        symbol=pos.symbol,
        name=pos.name or (stock.name if stock else pos.symbol),
        market=pos.market or (stock.market if stock else "CN"),
        quantity=pos.quantity,
        avg_cost=pos.avg_cost,
        opened_at=pos.opened_at,
        stop_loss=pos.stop_loss,
        take_profit=pos.take_profit,
        closed_at=pos.closed_at,
        close_price=pos.close_price,
        realized_pnl=pos.realized_pnl,
        realized_pnl_pct=pos.realized_pnl_pct,
        note=pos.note,
        status=pos.status or "open",
        latest_price=latest,
        latest_price_date=px.date if px else None,
        market_value=market_value,
        cost_value=cost_value,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


@router.get("/positions", response_model=list[PositionOut])
def list_positions(status: str = "open", db: Session = Depends(get_db)):
    """Return manual positions, defaulting to open holdings."""
    query = db.query(Position)
    if status != "all":
        query = query.filter(Position.status == status)
    rows = query.order_by(Position.opened_at.desc(), Position.id.desc()).all()
    return [position_to_schema(row, db) for row in rows]


@router.post(
    "/positions",
    response_model=PositionOut,
    dependencies=[Depends(agent_write_guard("position.add"))],
)
def create_position(payload: PositionCreate, db: Session = Depends(get_db)):
    """Create a manual position and ensure the stock exists in the watch universe."""
    symbol = payload.symbol.strip().upper()
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    name = (payload.name or (stock.name if stock else symbol)).strip()
    market = payload.market or (stock.market if stock else "CN")
    if stock is None:
        db.add(Stock(symbol=symbol, name=name, market=market, active=True))
    else:
        stock.active = True
        if payload.name:
            stock.name = payload.name
    pos = Position(
        symbol=symbol,
        name=name,
        market=market,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
        opened_at=payload.opened_at or date.today().isoformat(),
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        note=payload.note,
        status="open",
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return position_to_schema(pos, db)


@router.patch(
    "/positions/{position_id}/close",
    response_model=PositionOut,
    dependencies=[Depends(agent_write_guard("position.close"))],
)
@router.post(
    "/positions/{position_id}/close",
    response_model=PositionOut,
    dependencies=[Depends(agent_write_guard("position.close"))],
)
def close_position(
    position_id: int,
    payload: PositionClose | None = None,
    close_price: float | None = None,
    closed_at: str | None = None,
    db: Session = Depends(get_db),
):
    """Close a position and persist realized PnL."""
    pos = db.query(Position).filter(Position.id == position_id).first()
    if pos is None:
        raise HTTPException(404, "position not found")
    if pos.status == "closed":
        raise HTTPException(409, "position already closed")
    px = _latest_price(db, pos.symbol)
    final_price = close_price
    if final_price is None and payload and payload.close_price is not None:
        final_price = payload.close_price
    if final_price is None and px:
        final_price = float(px.close)
    if final_price is None:
        raise HTTPException(400, "close_price required when no latest price exists")
    if final_price <= 0:
        raise HTTPException(400, "close_price must be > 0")

    cost_value = float(pos.quantity or 0) * float(pos.avg_cost or 0)
    exit_value = float(pos.quantity or 0) * float(final_price)
    realized = round(exit_value - cost_value, 2)

    if payload:
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key in {"status", "closed_at", "close_price"}:
                continue
            setattr(pos, key, value)
    pos.status = "closed"
    pos.closed_at = closed_at or (payload.closed_at if payload and payload.closed_at else date.today().isoformat())
    pos.close_price = float(final_price)
    pos.realized_pnl = realized
    pos.realized_pnl_pct = round(realized / cost_value * 100, 2) if cost_value else None
    pos.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(pos)
    return position_to_schema(pos, db)


@router.delete(
    "/positions/{position_id}/closed",
    dependencies=[Depends(agent_write_guard("position.delete_closed"))],
)
def delete_closed_position(position_id: int, db: Session = Depends(get_db)):
    """Permanently delete a closed position record."""
    pos = db.query(Position).filter(Position.id == position_id).first()
    if pos is None:
        raise HTTPException(404, "position not found")
    if pos.status != "closed":
        raise HTTPException(400, "only closed positions can be permanently deleted")
    db.delete(pos)
    db.commit()
    return {"status": "deleted"}


@router.patch(
    "/positions/{position_id}",
    response_model=PositionOut,
    dependencies=[Depends(agent_write_guard("position.update"))],
)
def update_position(
    position_id: int,
    payload: PositionUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing manual position."""
    pos = db.query(Position).filter(Position.id == position_id).first()
    if pos is None:
        raise HTTPException(404, "position not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(pos, key, value)
    pos.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(pos)
    return position_to_schema(pos, db)


@router.delete(
    "/positions/{position_id}",
    dependencies=[Depends(agent_write_guard("position.close"))],
)
def delete_position(position_id: int, db: Session = Depends(get_db)):
    """Close a position without deleting its history."""
    pos = db.query(Position).filter(Position.id == position_id).first()
    if pos is None:
        raise HTTPException(404, "position not found")
    if pos.status == "closed":
        return {"status": "already_closed"}
    close_position(position_id, db=db)
    return {"status": "closed"}
