from fastapi import APIRouter, HTTPException
from datetime import datetime
from uuid import uuid4
from typing import Dict, List

from app.monitoring.models import PositionCreate, PositionState, MonitoringSnapshot


router = APIRouter(prefix="/api/monitoring", tags=["Sector Monitoring Tool"])

POSITIONS: Dict[str, PositionState] = {}


def calculate_rr_current(side: str, entry: float, stop_loss: float, last_price: float) -> float:
    risk = abs(entry - stop_loss)
    if risk == 0:
        return 0.0
    reward = last_price - entry if side == "long" else entry - last_price
    return round(reward / risk, 2)


def calculate_rr_target(side: str, entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(entry - stop_loss)
    if risk == 0:
        return 0.0
    reward = take_profit - entry if side == "long" else entry - take_profit
    return round(reward / risk, 2)


def calculate_pnl(side: str, entry: float, last_price: float, quantity: float) -> float:
    pnl = (last_price - entry) * quantity if side == "long" else (entry - last_price) * quantity
    return round(pnl, 2)


def detect_decision(side: str, last_price: float, stop_loss: float, take_profit: float) -> str:
    if side == "long":
        if last_price <= stop_loss or last_price >= take_profit:
            return "EXIT"
        return "HOLD"

    if last_price >= stop_loss or last_price <= take_profit:
        return "EXIT"
    return "HOLD"


@router.post("/positions", response_model=PositionState)
def create_position(payload: PositionCreate):
    rr_target = calculate_rr_target(
        payload.side,
        payload.entry_price,
        payload.stop_loss,
        payload.take_profit,
    )

    position = PositionState(
        id=str(uuid4()),
        **payload.model_dump(),
        created_at=datetime.utcnow(),
        rr_target=rr_target,
    )

    POSITIONS[position.id] = position
    return position


@router.get("/positions", response_model=List[PositionState])
def list_positions():
    return list(POSITIONS.values())


@router.get("/positions/open", response_model=List[PositionState])
def list_open_positions():
    return [p for p in POSITIONS.values() if p.status == "open"]


@router.get("/positions/{position_id}", response_model=PositionState)
def get_position(position_id: str):
    position = POSITIONS.get(position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return position


@router.post("/positions/{position_id}/snapshot", response_model=MonitoringSnapshot)
def create_monitoring_snapshot(position_id: str, last_price: float):
    position = POSITIONS.get(position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    pnl = calculate_pnl(position.side, position.entry_price, last_price, position.quantity)
    rr_current = calculate_rr_current(position.side, position.entry_price, position.stop_loss, last_price)
    rr_target = calculate_rr_target(position.side, position.entry_price, position.stop_loss, position.take_profit)
    decision = detect_decision(position.side, last_price, position.stop_loss, position.take_profit)

    if position.side == "long":
        sl_hit = last_price <= position.stop_loss
        tp_hit = last_price >= position.take_profit
    else:
        sl_hit = last_price >= position.stop_loss
        tp_hit = last_price <= position.take_profit

    position.last_price = last_price
    position.pnl = pnl
    position.rr_current = rr_current
    position.rr_target = rr_target
    position.decision = decision

    if decision == "EXIT":
        position.status = "closed"
        position.closed_at = datetime.utcnow()
        position.exit_price = last_price

    message = "Position masih valid untuk HOLD."
    if sl_hit:
        message = "STOP LOSS HIT. Exit position."
    elif tp_hit:
        message = "TAKE PROFIT HIT. Exit position."

    return MonitoringSnapshot(
        position_id=position.id,
        ticker=position.ticker,
        last_price=last_price,
        entry_price=position.entry_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        pnl=pnl,
        rr_current=rr_current,
        rr_target=rr_target,
        decision=decision,
        sl_hit=sl_hit,
        tp_hit=tp_hit,
        volume_warning="LOW",
        volatility_warning="LOW",
        bandar_warning="LOW",
        message=message,
        checked_at=datetime.utcnow(),
    )
