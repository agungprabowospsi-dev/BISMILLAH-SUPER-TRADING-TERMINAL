from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
from app.core import invesgo
import logging

logger = logging.getLogger(__name__)

# ─── MONITORING ───────────────────────────────────────────────────────────────
router = APIRouter()

class MonitoringRequest(BaseModel):
    ticker: str
    entry_price: float
    stop_loss: float
    take_profit: float
    mode: str = "swing"

_active_monitors = {}

@router.post("/start")
async def start_monitoring(req: MonitoringRequest):
    monitoring_id = f"{req.ticker}_{req.mode}_{int(req.entry_price)}"
    _active_monitors[monitoring_id] = req.dict()
    return {"monitoring_id": monitoring_id, "status": "active"}

@router.get("/status/{monitoring_id}")
async def get_status(monitoring_id: str):
    if monitoring_id not in _active_monitors:
        raise HTTPException(404, "Monitor not found")
    pos = _active_monitors[monitoring_id]
    try:
        tick = await invesgo.get_tick(pos["ticker"])
        current = tick.get("last_price", pos["entry_price"])
    except:
        current = pos["entry_price"]

    warnings = []
    position_status = "hold"

    if current <= pos["stop_loss"]:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"STOP LOSS HIT at {current}"})
    elif current >= pos["take_profit"]:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"TAKE PROFIT HIT at {current}"})
    elif current <= pos["entry_price"] * 0.97:
        warnings.append({"level": "medium", "msg": "Price down 3% from entry — monitor closely"})

    return {
        "monitoring_id": monitoring_id,
        "ticker": pos["ticker"],
        "current_price": current,
        "entry_price": pos["entry_price"],
        "stop_loss": pos["stop_loss"],
        "take_profit": pos["take_profit"],
        "position": position_status,
        "pnl_pct": round((current - pos["entry_price"]) / pos["entry_price"] * 100, 2),
        "warnings": warnings,
    }
