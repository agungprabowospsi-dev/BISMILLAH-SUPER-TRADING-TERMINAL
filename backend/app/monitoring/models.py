from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


PositionSide = Literal["long", "short"]
PositionStatus = Literal["open", "closed"]
MonitoringDecision = Literal["HOLD", "EXIT", "WATCH"]


class PositionCreate(BaseModel):
    ticker: str = Field(..., min_length=3, max_length=10)
    side: PositionSide = "long"
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float = 1
    setup_type: Optional[str] = None
    source: Optional[str] = "analytic_tool"
    notes: Optional[str] = None


class PositionState(PositionCreate):
    id: str
    status: PositionStatus = "open"
    created_at: datetime
    closed_at: Optional[datetime] = None
    last_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    rr_current: Optional[float] = None
    rr_target: Optional[float] = None
    decision: MonitoringDecision = "HOLD"


class MonitoringSnapshot(BaseModel):
    position_id: str
    ticker: str
    last_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    pnl: float
    rr_current: float
    rr_target: float
    decision: MonitoringDecision
    sl_hit: bool
    tp_hit: bool
    volume_warning: Literal["HIGH", "MEDIUM", "LOW"]
    volatility_warning: Literal["HIGH", "MEDIUM", "LOW"]
    bandar_warning: Literal["HIGH", "MEDIUM", "LOW"]
    message: str
    checked_at: datetime
