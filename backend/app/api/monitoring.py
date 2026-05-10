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
        "rr": calculate_rr(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "smart_trailing_stop": calculate_smart_trailing_stop(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "warnings": warnings,
    }


# ─── ADDITIVE MONITORING HELPERS — RR TRACKING ────────────────────────────────
def calculate_rr(entry_price: float, stop_loss: float, take_profit: float, current_price: float):
    risk = abs(entry_price - stop_loss)

    if risk == 0:
        return {
            "rr_current": 0,
            "rr_target": 0,
            "risk_per_share": 0,
            "reward_per_share": 0,
        }

    rr_current = round((current_price - entry_price) / risk, 2)
    rr_target = round((take_profit - entry_price) / risk, 2)

    return {
        "rr_current": rr_current,
        "rr_target": rr_target,
        "risk_per_share": risk,
        "reward_per_share": abs(take_profit - entry_price),
    }


# ─── ADDITIVE MULTI-POSITION MONITORING ENDPOINTS ─────────────────────────────

@router.get("/active")
async def list_active_monitors():
    return {
        "count": len(_active_monitors),
        "monitors": [
            {
                "monitoring_id": monitoring_id,
                "ticker": data.get("ticker"),
                "entry_price": data.get("entry_price"),
                "stop_loss": data.get("stop_loss"),
                "take_profit": data.get("take_profit"),
                "mode": data.get("mode"),
            }
            for monitoring_id, data in _active_monitors.items()
        ],
    }


@router.get("/portfolio-risk")
async def portfolio_risk_summary():
    total_positions = len(_active_monitors)
    total_risk_value = 0
    total_reward_value = 0
    positions = []

    for monitoring_id, pos in _active_monitors.items():
        risk = abs(pos["entry_price"] - pos["stop_loss"])
        reward = abs(pos["take_profit"] - pos["entry_price"])
        rr_target = round(reward / risk, 2) if risk else 0

        total_risk_value += risk
        total_reward_value += reward

        positions.append({
            "monitoring_id": monitoring_id,
            "ticker": pos["ticker"],
            "mode": pos.get("mode", "swing"),
            "risk_per_share": risk,
            "reward_per_share": reward,
            "rr_target": rr_target,
        })

    portfolio_rr = round(total_reward_value / total_risk_value, 2) if total_risk_value else 0

    return {
        "total_positions": total_positions,
        "total_risk_value": total_risk_value,
        "total_reward_value": total_reward_value,
        "portfolio_rr": portfolio_rr,
        "positions": positions,
    }


# ─── ADDITIVE SMART TRAILING STOP ENGINE ──────────────────────────────────────

def calculate_smart_trailing_stop(entry_price: float, stop_loss: float, take_profit: float, current_price: float):
    risk = abs(entry_price - stop_loss)

    if risk == 0:
        return {
            "active": False,
            "suggested_stop_loss": stop_loss,
            "lock_profit": 0,
            "trailing_stage": "invalid_risk",
        }

    rr_current = round((current_price - entry_price) / risk, 2)

    if rr_current < 1:
        return {
            "active": False,
            "suggested_stop_loss": stop_loss,
            "lock_profit": 0,
            "trailing_stage": "not_activated",
        }

    if rr_current >= 1 and rr_current < 1.5:
        suggested_sl = entry_price
        stage = "breakeven_lock"
    elif rr_current >= 1.5 and rr_current < 2:
        suggested_sl = entry_price + (risk * 0.5)
        stage = "half_risk_profit_lock"
    else:
        suggested_sl = entry_price + risk
        stage = "one_risk_profit_lock"

    return {
        "active": True,
        "suggested_stop_loss": round(suggested_sl, 2),
        "lock_profit": round(suggested_sl - entry_price, 2),
        "trailing_stage": stage,
    }
