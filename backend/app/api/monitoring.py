from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
import json
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
from app.core import invesgo
from app.engines.master_runner import run_all_engines
from app.knowledge_base import kb_service
import logging

logger = logging.getLogger(__name__)

import numpy as np

def sanitize_for_json(obj):
    """Recursively convert numpy types to Python native types."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(i) for i in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

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

    engine_context = await get_monitoring_engine_context(pos["ticker"], pos.get("mode", "swing"))

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
        "institutional_alerts": generate_institutional_alerts(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "engine_context": engine_context,
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


# ─── ADDITIVE INSTITUTIONAL ALERT ENGINE ──────────────────────────────────────

def generate_institutional_alerts(entry_price: float, stop_loss: float, take_profit: float, current_price: float):
    alerts = []
    risk = abs(entry_price - stop_loss)

    if risk == 0:
        return [{
            "level": "HIGH",
            "type": "INVALID_RISK",
            "message": "Invalid risk structure: entry and stop loss are equal.",
        }]

    rr_current = round((current_price - entry_price) / risk, 2)

    if current_price <= stop_loss:
        alerts.append({
            "level": "HIGH",
            "type": "STOP_LOSS_HIT",
            "message": "Stop loss hit. Exit position immediately.",
        })

    if current_price >= take_profit:
        alerts.append({
            "level": "HIGH",
            "type": "TAKE_PROFIT_HIT",
            "message": "Take profit hit. Secure realized profit.",
        })

    if rr_current < -0.5:
        alerts.append({
            "level": "MEDIUM",
            "type": "RR_DETERIORATION",
            "message": "RR deteriorating. Price is moving against the setup.",
        })

    if rr_current >= 1:
        alerts.append({
            "level": "MEDIUM",
            "type": "PROFIT_PROTECTION",
            "message": "Position has reached at least 1R. Consider trailing stop protection.",
        })

    if rr_current >= 2:
        alerts.append({
            "level": "HIGH",
            "type": "STRONG_PROFIT_ZONE",
            "message": "Position is in strong profit zone. Protect gains aggressively.",
        })

    if not alerts:
        alerts.append({
            "level": "LOW",
            "type": "NORMAL_MONITORING",
            "message": "Position condition normal. Continue monitoring.",
        })

    return alerts


# ─── ADDITIVE MONITORING ENGINE BRIDGE — 34 ENGINES + RAG ─────────────────────

async def get_monitoring_engine_context(ticker: str, mode: str = "swing"):
    try:
        ohlcv = await invesgo.get_ohlcv_daily(ticker)

        if not ohlcv or len(ohlcv) < 20:
            return {
                "engines_used": False,
                "rag_used": False,
                "reason": "Insufficient OHLCV data for monitoring engine context.",
            }

        normalized_ohlcv = [{
            **c,
            "open": float(c.get("open", 0) or 0),
            "high": float(c.get("high", 0) or 0),
            "low": float(c.get("low", 0) or 0),
            "close": float(c.get("close", 0) or 0),
            "volume": float(c.get("volume", 0) or 0),
        } for c in ohlcv]

        engine_result = await run_all_engines(ticker, normalized_ohlcv, mode)
        logger.warning(f"[DEBUG] engine_result keys: {list(engine_result.keys()) if engine_result else None}")
        logger.warning(f"[DEBUG] engines count: {len(engine_result.get('engines', []))}")

        rag_engines = [
            "PriceActionEngine",
            "VolumeIntelligenceEngine",
            "BandarmologyEngine",
            "TrendStructureEngine",
            "RiskManagementEngine",
        ]

        rag_count = 0
        for engine_name in rag_engines:
            try:
                ctx = await kb_service.get_kb_context_for_engine(engine_name, ticker)
                if ctx:
                    rag_count += 1
            except Exception:
                continue

        return {
            "engines_used": True,
            "engine_scope": "monitoring_bridge",
            "total_engines": engine_result.get("total_engines"),
            "composite_score": engine_result.get("composite_score"),
            "signal": engine_result.get("signal"),
            "bullish_count": engine_result.get("bullish_count"),
            "bearish_count": engine_result.get("bearish_count"),
            "rag_used": rag_count > 0,
            "rag_context_count": rag_count,
            "rag_engines": rag_engines,
            "bandarmology_included": "BandarmologyEngine" in rag_engines,
            "engine_details": sanitize_for_json({e["engine"]: e for e in engine_result.get("engines", [])}),
            "debug_keys": list(engine_result.keys()),
        }

    except Exception as e:
        logger.warning(f"[MONITORING_ENGINE_BRIDGE] skipped for {ticker}: {e}")
        return {
            "engines_used": False,
            "rag_used": False,
            "reason": str(e),
        }


# ─── ADDITIVE STATELESS MONITORING CHECK ──────────────────────────────────────

@router.post("/check")
async def stateless_monitoring_check(req: MonitoringRequest):
    try:
        tick = await invesgo.get_tick(req.ticker)
        current = tick.get("last_price", req.entry_price)
    except Exception:
        current = req.entry_price

    warnings = []
    position_status = "hold"

    if current <= req.stop_loss:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"STOP LOSS HIT at {current}"})
    elif current >= req.take_profit:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"TAKE PROFIT HIT at {current}"})
    elif current <= req.entry_price * 0.97:
        warnings.append({"level": "medium", "msg": "Price down 3% from entry — monitor closely"})

    engine_context = await get_monitoring_engine_context(req.ticker, req.mode)
    early_warnings = extract_early_warnings(engine_context)
    warnings = warnings + early_warnings

    return JSONResponse(content=json.loads(json.dumps(sanitize_for_json({
        "ticker": req.ticker,
        "mode": req.mode,
        "current_price": current,
        "entry_price": req.entry_price,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "position": position_status,
        "pnl_pct": round((current - req.entry_price) / req.entry_price * 100, 2),
        "rr": calculate_rr(req.entry_price, req.stop_loss, req.take_profit, current),
        "smart_trailing_stop": calculate_smart_trailing_stop(req.entry_price, req.stop_loss, req.take_profit, current),
        "institutional_alerts": generate_institutional_alerts(req.entry_price, req.stop_loss, req.take_profit, current),
        "engine_context": engine_context,
        "warnings": warnings,
    })))


# ─── ADDITIVE EARLY WARNING SYSTEM ────────────────────────────────────────────

def extract_early_warnings(engine_context: dict) -> list:
    warnings = []
    if not engine_context or not engine_context.get("engines_used"):
        return warnings

    engine_details = engine_context.get("engine_details") or {}

    # ── Volume Warning ──────────────────────────────────────────────────────
    vol = engine_details.get("VolumeIntelligenceEngine", {})
    vol_data = vol.get("data", {})
    vol_ratio = vol_data.get("volume_ratio", 1.0)
    obv_trend = vol_data.get("obv_trend", "")
    ad_trend  = vol_data.get("ad_trend", "")

    if vol_ratio >= 3.0:
        warnings.append({"level": "HIGH", "type": "VOLUME_SPIKE", "message": f"Volume spike ekstrem: {vol_ratio:.1f}x rata-rata 20 hari. Waspadai pergerakan besar."})
    elif vol_ratio >= 2.0:
        warnings.append({"level": "HIGH", "type": "VOLUME_SURGE", "message": f"Volume surge: {vol_ratio:.1f}x rata-rata. Konfirmasi arah sebelum tambah posisi."})
    elif vol_ratio >= 1.5:
        warnings.append({"level": "MEDIUM", "type": "VOLUME_ELEVATED", "message": f"Volume di atas normal: {vol_ratio:.1f}x. Perhatikan price action."})
    elif vol_ratio < 0.5:
        warnings.append({"level": "LOW", "type": "VOLUME_DRY", "message": f"Volume sangat rendah: {vol_ratio:.1f}x. Likuiditas tipis."})
    elif vol_ratio < 0.7:
        warnings.append({"level": "LOW", "type": "VOLUME_LOW", "message": f"Volume di bawah normal: {vol_ratio:.1f}x. Sinyal lemah."})

    if obv_trend == "falling" and ad_trend == "distribution":
        warnings.append({"level": "MEDIUM", "type": "VOLUME_DISTRIBUTION", "message": "OBV turun + A/D distribution — tekanan jual institusi terdeteksi."})

    # ── Bandarmology Warning ────────────────────────────────────────────────
    bandar = engine_details.get("BandarmologyEngine", {})
    bandar_data = bandar.get("data", {})
    phase     = bandar_data.get("phase", "")
    big_up    = bandar_data.get("big_vol_up_days", 0)
    big_down  = bandar_data.get("big_vol_down_days", 0)
    bandar_score = bandar.get("score", 50)

    if phase == "distribution":
        warnings.append({"level": "HIGH", "type": "BANDAR_DISTRIBUSI", "message": f"⚠️ GUYURAN BANDAR terdeteksi! Big vol down {big_down} hari vs up {big_up} hari. Waspadai exit paksa."})
    elif phase == "accumulation" and bandar_score >= 75:
        warnings.append({"level": "MEDIUM", "type": "BANDAR_AKUMULASI", "message": f"Bandar akumulasi aktif ({big_up} hari big vol naik). Posisi aligned dengan smart money."})
    elif phase == "early_accumulation":
        warnings.append({"level": "LOW", "type": "BANDAR_EARLY_AKUMULASI", "message": "Sinyal awal akumulasi bandar. Monitor volume besar hari berikutnya."})

    return warnings
