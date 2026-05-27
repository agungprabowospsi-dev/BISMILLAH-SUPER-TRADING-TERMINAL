from app.ml.signal_quality import add_training_sample
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional
import asyncio
import json
from datetime import datetime, timezone
from app.core import invesgo
from app.engines.master_runner import run_all_engines, run_monitoring_engines
from app.engines.broker_behavior_engine import summarize_broker_behavior
from app.engines.orderbook_microstructure import build_orderbook_execution_overlay, normalize_orderbook
from app.core.official_enrichment import build_monitoring_enrichment
from app.core.money_maker import analyze_money_maker_context
from app.core.money_maker_store import get_latest_flow_snapshot_cloud, save_money_maker_cloud
from app.knowledge_base import kb_service
import logging

logger = logging.getLogger(__name__)

import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_): return bool(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)

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
    model_config = ConfigDict(extra="allow")

    ticker: str
    entry_price: float
    stop_loss: float
    take_profit: float
    take_profit_1: float = 0.0  # M-1: TP1
    take_profit_2: float = 0.0  # M-1: TP2
    take_profit_3: float = 0.0  # M-1: TP3
    mode: str = "swing"
    # ML Training fields — diisi otomatis dari Analytic
    engine_scores: Any = Field(default_factory=dict)
    market_regime: str = "SIDEWAYS"
    lq45_change: float = 0.0
    breadth_ratio: float = 50.0
    final_score: float = 50.0
    kb_context: str = ""
    analytic_context: dict = Field(default_factory=dict)

class MonitoringRemoveRequest(BaseModel):
    monitoring_id: Optional[str] = None
    ticker: Optional[str] = None

_active_monitors = {}
MONITORING_SET_KEY = "monitoring:active"
MONITORING_KEY_PREFIX = "monitoring:position:"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def _normalize_mode(mode: Any) -> str:
    value = str(mode or "swing").lower()
    if value == "daytrading":
        return "intraday"
    if value in ("swing", "intraday", "scalping"):
        return value
    return "swing"

def normalize_engine_scores(scores: Any) -> dict:
    if isinstance(scores, dict):
        return scores
    if isinstance(scores, list):
        normalized = {}
        for item in scores:
            if isinstance(item, dict):
                name = item.get("engine") or item.get("name")
                if name:
                    normalized[name] = float(item.get("score") or 0)
        return normalized
    return {}

def normalize_monitoring_payload(payload: Any) -> dict:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    elif hasattr(payload, "dict"):
        payload = payload.dict()
    payload = dict(payload or {})

    ticker = str(payload.get("ticker") or "").upper().strip()
    mode = _normalize_mode(payload.get("mode"))
    entry = _to_float(payload.get("entry_price"))
    stop = _to_float(payload.get("stop_loss"))
    tp1 = _to_float(payload.get("take_profit_1"), _to_float(payload.get("take_profit")))
    tp2 = _to_float(payload.get("take_profit_2"))
    tp3 = _to_float(payload.get("take_profit_3"))
    take_profit = _to_float(payload.get("take_profit"), tp1 or entry)
    monitoring_id = payload.get("monitoring_id") or f"{ticker}_{mode}_{int(entry or 0)}"
    created_at = payload.get("created_at") or _now_iso()

    normalized = {
        **payload,
        "monitoring_id": monitoring_id,
        "ticker": ticker,
        "mode": mode,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take_profit,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "current_price": _to_float(payload.get("current_price"), entry),
        "lot": _to_float(payload.get("lot"), 1.0),
        "entry_score": _to_float(payload.get("entry_score"), _to_float(payload.get("final_score"))),
        "final_score": _to_float(payload.get("final_score"), 50.0),
        "lq45_change": _to_float(payload.get("lq45_change"), 0.0),
        "breadth_ratio": _to_float(payload.get("breadth_ratio"), 50.0),
        "engine_scores": normalize_engine_scores(payload.get("engine_scores")),
        "market_regime": payload.get("market_regime") or "SIDEWAYS",
        "kb_context": payload.get("kb_context") or "",
        "analytic_context": payload.get("analytic_context") or {},
        "empirical_memory": payload.get("empirical_memory") or (payload.get("analytic_context") or {}).get("empirical_memory"),
        "broker": payload.get("broker") or "",
        "name": payload.get("name") or ticker,
        "status": payload.get("status") or "HOLD",
        "created_at": created_at,
        "updated_at": _now_iso(),
        "state_source": "backend",
    }
    return sanitize_for_json(normalized)

def _monitoring_key(monitoring_id: str) -> str:
    return f"{MONITORING_KEY_PREFIX}{monitoring_id}"

def _redis_client():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None

async def save_monitoring_position(position: dict) -> dict:
    position = normalize_monitoring_payload(position)
    monitoring_id = position["monitoring_id"]
    _active_monitors[monitoring_id] = position
    redis = _redis_client()
    if redis:
        try:
            await redis.sadd(MONITORING_SET_KEY, monitoring_id)
            await redis.set(_monitoring_key(monitoring_id), json.dumps(position, cls=NumpyEncoder))
        except Exception as exc:
            logger.warning(f"Redis monitoring save skipped [{monitoring_id}]: {exc}")
    return position

async def load_monitoring_positions() -> list:
    redis = _redis_client()
    if redis:
        try:
            ids = await redis.smembers(MONITORING_SET_KEY)
            positions = []
            for monitoring_id in sorted(ids):
                raw = await redis.get(_monitoring_key(monitoring_id))
                if not raw:
                    continue
                position = normalize_monitoring_payload(json.loads(raw))
                _active_monitors[position["monitoring_id"]] = position
                positions.append(position)
            if positions:
                return positions
        except Exception as exc:
            logger.warning(f"Redis monitoring load skipped: {exc}")
    return list(_active_monitors.values())

async def delete_monitoring_position(monitoring_id: str) -> bool:
    existed = monitoring_id in _active_monitors
    _active_monitors.pop(monitoring_id, None)
    redis = _redis_client()
    if redis:
        try:
            await redis.srem(MONITORING_SET_KEY, monitoring_id)
            await redis.delete(_monitoring_key(monitoring_id))
            existed = True
        except Exception as exc:
            logger.warning(f"Redis monitoring delete skipped [{monitoring_id}]: {exc}")
    return existed

async def clear_monitoring_positions() -> int:
    positions = await load_monitoring_positions()
    for pos in positions:
        await delete_monitoring_position(pos["monitoring_id"])
    _active_monitors.clear()
    return len(positions)

def analytic_alignment_warnings(analytic_context: dict, current: float) -> list:
    warnings = []
    if not analytic_context:
        return warnings

    verdict = str(analytic_context.get("go_no_go") or "").upper()
    if verdict in ("NO GO", "WAIT"):
        warnings.append({
            "level": "MEDIUM",
            "type": "ANALYTIC_DECISION_CONTEXT",
            "message": f"Analytic decision awal adalah {verdict}; posisi wajib dimonitor lebih ketat terhadap invalidation.",
        })

    action_plan = analytic_context.get("action_plan") or {}
    if action_plan:
        invalidation = float(action_plan.get("invalidation_price") or 0)
        trigger = float(action_plan.get("trigger_price") or 0)
        order_type = str(action_plan.get("order_type") or "").upper()
        opportunity_execution = (
            action_plan.get("opportunity_execution")
            or analytic_context.get("opportunity_execution")
            or {}
        )
        watchlist_alignment = (
            action_plan.get("watchlist_alignment")
            or analytic_context.get("watchlist_alignment")
            or {}
        )
        screener_alignment = (
            action_plan.get("screener_alignment")
            or analytic_context.get("screener_alignment")
            or {}
        )
        if opportunity_execution.get("active"):
            warnings.append({
                "level": "MEDIUM",
                "type": "OPPORTUNITY_WATCH_ACTIVE",
                "message": (
                    "Top gainer opportunity mode aktif; ini bukan entry normal. "
                    "Pantau trigger, base/VWAP, orderbook bid refill, dan Money Maker flow."
                ),
            })
            if trigger > 0 and current < trigger:
                warnings.append({
                    "level": "LOW",
                    "type": "OPPORTUNITY_TRIGGER_PENDING",
                    "message": f"Trigger opportunity {trigger} belum ditembus; jangan chase sebelum konfirmasi.",
                })
            elif trigger > 0 and current >= trigger:
                warnings.append({
                    "level": "MEDIUM",
                    "type": "OPPORTUNITY_TRIGGER_TOUCHED",
                    "message": "Trigger opportunity tersentuh; validasi time table, momentum chart, dan broker flow sebelum eksekusi/tambah posisi.",
                })
        elif watchlist_alignment.get("active"):
            warnings.append({
                "level": "LOW",
                "type": "WATCHLIST_RADAR_OBSERVATION",
                "message": (
                    "Adaptive watchlist radar aktif, tetapi belum execution lane. "
                    "Execution lane hanya untuk mover awal 5%-10%; di atas itu tunggu reset/base."
                ),
            })
        elif screener_alignment.get("active"):
            warnings.append({
                "level": "LOW",
                "type": "SCREENER_QUALIFIED_ANALYTIC_WAIT",
                "message": (
                    "Screener qualified tetapi Analytic masih WAIT confirmation; monitor trigger dan flow, bukan entry otomatis."
                ),
            })
        if invalidation > 0 and current <= invalidation:
            warnings.append({
                "level": "HIGH",
                "type": "ACTION_PLAN_INVALIDATION",
                "message": f"Current price {current} sudah menyentuh/bawah invalidation {invalidation}.",
            })
        if order_type in ("NO_MARKET_ENTRY", "WAIT_CLOSE_CONFIRMATION") and trigger > 0 and current < trigger:
            warnings.append({
                "level": "LOW",
                "type": "TRIGGER_NOT_CONFIRMED",
                "message": f"Trigger analytic {trigger} belum terkonfirmasi; jangan tambah posisi sebelum reclaim.",
            })
    money_maker = analytic_context.get("money_maker") or (action_plan.get("money_maker") if isinstance(action_plan, dict) else {}) or {}
    if money_maker:
        mm_verdict = str(money_maker.get("verdict") or "").upper()
        if mm_verdict == "FLOW_OUT_AVOID":
            warnings.append({
                "level": "HIGH",
                "type": "ANALYTIC_MONEY_MAKER_FLOW_OUT",
                "message": "Analytic awal sudah membaca money maker flow out; posisi wajib defensif.",
            })
        if (money_maker.get("flow_memory") or {}).get("flow_reversal_alert"):
            warnings.append({
                "level": "HIGH",
                "type": "ANALYTIC_BFD_REVERSAL",
                "message": "Analytic context membawa BFD reversal; jangan tambah posisi sebelum flow pulih.",
            })
    return warnings

def _clamp_pct(value: float, low: float = 1.0, high: float = 99.0) -> float:
    return round(max(low, min(high, float(value or 0))), 1)

def _warning_counts(warnings: list) -> dict:
    counts = {"high": 0, "medium": 0, "low": 0}
    for warning in warnings or []:
        level = str(warning.get("level") or warning.get("severity") or "low").lower()
        if level.startswith("high"):
            counts["high"] += 1
        elif level.startswith("med"):
            counts["medium"] += 1
        else:
            counts["low"] += 1
    return counts

def _extract_win_probability(value: Any) -> float:
    if isinstance(value, dict):
        return _to_float(value.get("probability"), 50.0)
    return _to_float(value, 50.0)

def _regime_adjustment(regime: Any) -> tuple[float, str]:
    text = str(regime or "SIDEWAYS").upper()
    if any(key in text for key in ("BULL", "STRONG", "RISK_ON", "RECOVERY")):
        return 7.0, "Market regime supportive; TP ladder diberi ruang lebih besar."
    if any(key in text for key in ("BEAR", "BAD", "RED", "RISK_OFF", "WEAK")):
        return -12.0, "Market regime defensif; confidence TP ditahan dan SL risk dinaikkan."
    if any(key in text for key in ("SIDEWAYS", "CHOP", "MIXED")):
        return -3.0, "Market regime sideways; monitoring memakai bias konservatif."
    return 0.0, "Market regime netral."

def _target_confidence(base: float, entry: float, current: float, target: float, level: str) -> float:
    if not target or target <= entry:
        return 0.0
    if current >= target:
        return 98.0
    distance = target - entry
    progress = (current - entry) / distance if distance else 0.0
    progress_bonus = max(-18.0, min(18.0, progress * 24.0))
    decay = {"tp1": 0.0, "tp2": -16.0, "tp3": -30.0}.get(level, 0.0)
    return _clamp_pct(base + progress_bonus + decay, 1.0, 98.0)

def _build_position_guard_state(pos: dict, current: float, warnings: list) -> dict:
    entry = _to_float(pos.get("entry_price"))
    stop = _to_float(pos.get("stop_loss"))
    tp1 = _to_float(pos.get("take_profit_1"), _to_float(pos.get("take_profit")))
    tp2 = _to_float(pos.get("take_profit_2"))
    tp3 = _to_float(pos.get("take_profit_3"))
    counts = _warning_counts(warnings)

    if stop and current <= stop:
        state = "SL_HIT"
        action = "EXIT_REQUIRED"
        message = "SL tersentuh. Monitoring berubah menjadi exit-required sesuai plan."
    elif tp3 and current >= tp3:
        state = "TP3_REACHED"
        action = "TARGET_COMPLETE"
        message = "TP3 tercapai. Posisi sudah menyelesaikan full target; user boleh stop monitoring."
    elif tp2 and current >= tp2:
        state = "TP2_REACHED"
        action = "TRAILING_PROTECT"
        message = "TP2 tercapai. Proteksi profit lebih ketat dan pantau distribusi."
    elif tp1 and current >= tp1:
        state = "TP1_REACHED"
        action = "PROTECT_PARTIAL_PROFIT"
        message = "TP1 tercapai. Monitoring masuk protect mode sampai TP2/TP3 atau user stop."
    elif counts["high"] >= 2:
        state = "ACTIVE_DANGER"
        action = "RISK_REVIEW"
        message = "Beberapa warning high aktif. Evaluasi exit/kurangi posisi sesuai risk plan."
    elif counts["high"] >= 1 or counts["medium"] >= 3:
        state = "ACTIVE_CAUTION"
        action = "HOLD_TIGHT"
        message = "Posisi masih aktif tetapi warning meningkat. Jangan tambah posisi tanpa konfirmasi baru."
    else:
        state = "POSITION_ACTIVE"
        action = "HOLD_MONITOR"
        message = "Posisi aktif; monitoring menjaga tesis analytic sampai TP/SL/stop manual."

    pnl_pct = round((current - entry) / entry * 100, 2) if entry else 0
    return {
        "state": state,
        "recommended_action": action,
        "message": message,
        "post_buy_only": True,
        "user_has_bought_assumption": True,
        "pnl_pct": pnl_pct,
        "tp_reached": {
            "tp1": bool(tp1 and current >= tp1),
            "tp2": bool(tp2 and current >= tp2),
            "tp3": bool(tp3 and current >= tp3),
        },
        "stop_monitoring_allowed": state in ("TP1_REACHED", "TP2_REACHED", "TP3_REACHED", "SL_HIT"),
    }

def build_tp_sl_confidence(pos: dict, current: float, engine_context: dict, empirical_memory: dict, warnings: list) -> dict:
    analytic_context = pos.get("analytic_context") or {}
    entry = _to_float(pos.get("entry_price"))
    stop = _to_float(pos.get("stop_loss"))
    tp1 = _to_float(pos.get("take_profit_1"), _to_float(pos.get("take_profit")))
    tp2 = _to_float(pos.get("take_profit_2"))
    tp3 = _to_float(pos.get("take_profit_3"))
    market_regime = (
        pos.get("market_regime")
        or analytic_context.get("market_regime")
        or (analytic_context.get("action_plan") or {}).get("market_regime")
        or "SIDEWAYS"
    )

    analytic_conf = _to_float(analytic_context.get("go_confidence"), _to_float(pos.get("final_score"), 50.0))
    win_prob = _extract_win_probability(analytic_context.get("win_probability"))
    engine_score = _to_float((engine_context or {}).get("composite_score"), 50.0)
    bullish = _to_float((engine_context or {}).get("bullish_count"), 0.0)
    bearish = _to_float((engine_context or {}).get("bearish_count"), 0.0)
    money_maker = (engine_context or {}).get("money_maker") or analytic_context.get("money_maker") or {}
    mm_score = _to_float(money_maker.get("score"), 50.0)
    mm_verdict = str(money_maker.get("verdict") or "").upper()
    empirical_wr = _to_float((empirical_memory or {}).get("winrate"), 50.0) if (empirical_memory or {}).get("available") else 50.0
    counts = _warning_counts(warnings)
    regime_adj, regime_note = _regime_adjustment(market_regime)

    support_score = (
        50.0
        + (analytic_conf - 50.0) * 0.25
        + (win_prob - 50.0) * 0.20
        + (engine_score - 50.0) * 0.35
        + (mm_score - 50.0) * 0.20
        + (empirical_wr - 50.0) * 0.25
        + (bullish - bearish) * 2.0
        + regime_adj
        - counts["high"] * 9.0
        - counts["medium"] * 4.0
    )
    if mm_verdict in ("FLOW_OUT_AVOID", "DISTRIBUTION_TRAP", "BFD_REVERSAL"):
        support_score -= 14.0
    elif mm_verdict in ("ACCUMULATION", "FLOW_IN_FOLLOW", "SMART_MONEY_IN"):
        support_score += 8.0

    sl_distance = entry - stop if entry and stop else 0.0
    sl_progress = ((entry - current) / sl_distance * 35.0) if sl_distance > 0 else 0.0
    sl_risk = 100.0 - support_score + sl_progress + counts["high"] * 11.0 + counts["medium"] * 4.0
    if stop and current <= stop:
        sl_risk = 99.0

    drivers = [
        f"Analytic confidence {analytic_conf:.1f} dan win probability {win_prob:.1f}.",
        f"Monitoring engines score {engine_score:.1f} dengan bull/bear {int(bullish)}/{int(bearish)}.",
        f"Money Maker score {mm_score:.1f} verdict {mm_verdict or 'NEUTRAL'}.",
        regime_note,
    ]
    if (empirical_memory or {}).get("available"):
        drivers.append(f"15Y memory winrate {empirical_wr:.1f}% ikut menimbang TP/SL.")
    if counts["high"] or counts["medium"]:
        drivers.append(f"Warning aktif: high {counts['high']}, medium {counts['medium']}.")

    tp1_conf = _target_confidence(support_score, entry, current, tp1, "tp1")
    tp2_conf = _target_confidence(support_score, entry, current, tp2, "tp2")
    tp3_conf = _target_confidence(support_score, entry, current, tp3, "tp3")

    return sanitize_for_json({
        "scope": "post_buy_position_guardian",
        "market_regime": market_regime,
        "base_support_score": _clamp_pct(support_score),
        "tp1_confidence": tp1_conf,
        "tp2_confidence": tp2_conf,
        "tp3_confidence": tp3_conf,
        "sl_risk_confidence": _clamp_pct(sl_risk),
        "confidence_drivers": drivers,
        "source_weights": {
            "analytic": "go_confidence + win_probability",
            "engines": "monitoring composite + bull/bear + 35-engine lineage",
            "money_maker": "score + flow verdict + broker/orderbook/foreign context",
            "market_regime": "inherited from screener/analytic",
            "historical_memory": "15Y empirical context when available",
        },
        "token_policy": {
            "extra_invezgo_calls": 0,
            "reason": "Confidence dihitung dari snapshot Monitoring yang sudah diambil, tanpa polling baru.",
        },
    })

@router.post("/start")
async def start_monitoring(req: MonitoringRequest):
    position = await save_monitoring_position(req)
    return {"monitoring_id": position["monitoring_id"], "status": "active", "position": position}

@router.get("/status/{monitoring_id}")
async def get_status(monitoring_id: str):
    positions = {pos["monitoring_id"]: pos for pos in await load_monitoring_positions()}
    if monitoring_id not in positions:
        raise HTTPException(404, "Monitor not found")
    pos = positions[monitoring_id]
    snapshot = await build_monitoring_result(pos)
    await save_monitoring_position(snapshot)
    return sanitize_for_json(snapshot)

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
        # ML Training — outcome = 0 (loss)
        try:
            add_training_sample(
                engine_scores=normalize_engine_scores(pos.get("engine_scores", {})),
                market_regime=pos.get("market_regime", "SIDEWAYS"),
                lq45_change=pos.get("lq45_change", 0.0),
                breadth_ratio=pos.get("breadth_ratio", 50.0),
                final_score=pos.get("final_score", 50.0),
                outcome=0,
                kb_context=pos.get("kb_context", "")
            )
        except Exception as ml_err:
            pass
    elif current >= pos["take_profit"]:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"TAKE PROFIT HIT at {current}"})
        # ML Training — outcome = 1 (win)
        try:
            add_training_sample(
                engine_scores=normalize_engine_scores(pos.get("engine_scores", {})),
                market_regime=pos.get("market_regime", "SIDEWAYS"),
                lq45_change=pos.get("lq45_change", 0.0),
                breadth_ratio=pos.get("breadth_ratio", 50.0),
                final_score=pos.get("final_score", 50.0),
                outcome=1,
                kb_context=pos.get("kb_context", "")
            )
        except Exception as ml_err:
            pass
    elif current <= pos["entry_price"] * 0.97:
        warnings.append({"level": "medium", "msg": "Price down 3% from entry — monitor closely"})

    engine_context = await get_monitoring_engine_context(pos["ticker"], pos.get("mode", "swing"))

    snapshot = {
        **pos,
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
        "analytic_context": pos.get("analytic_context", {}),
        "warnings": warnings,
    }
    snapshot["status"] = "EXIT" if position_status == "exit" else pos.get("status", "HOLD")
    await save_monitoring_position(snapshot)
    return sanitize_for_json(snapshot)


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
    positions = await load_monitoring_positions()
    return {
        "count": len(positions),
        "monitors": sanitize_for_json(positions),
    }

@router.post("/remove")
async def remove_monitoring(req: MonitoringRemoveRequest):
    positions = await load_monitoring_positions()
    ids = []
    if req.monitoring_id:
        ids = [req.monitoring_id]
    elif req.ticker:
        ticker = req.ticker.upper()
        ids = [pos["monitoring_id"] for pos in positions if pos.get("ticker") == ticker]
    if not ids:
        raise HTTPException(404, "Monitor not found")
    removed = 0
    for monitoring_id in ids:
        if await delete_monitoring_position(monitoring_id):
            removed += 1
    return {"status": "removed", "removed": removed, "monitoring_ids": ids}

@router.post("/clear")
async def clear_monitoring():
    removed = await clear_monitoring_positions()
    return {"status": "cleared", "removed": removed}


@router.get("/portfolio-risk")
async def portfolio_risk_summary():
    active_positions = await load_monitoring_positions()
    total_positions = len(active_positions)
    total_risk_value = 0
    total_reward_value = 0
    positions = []

    for pos in active_positions:
        risk = abs(pos["entry_price"] - pos["stop_loss"])
        reward = abs(pos["take_profit"] - pos["entry_price"])
        rr_target = round(reward / risk, 2) if risk else 0

        total_risk_value += risk
        total_reward_value += reward

        positions.append({
            "monitoring_id": pos["monitoring_id"],
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

        # Ambil data real dari Invesgo untuk Orderbook + Bandarmology + Foreign
        intraday_data = {}
        orderbook_raw = {}
        broker_data_raw = []
        ksei_data_raw = []
        try:
            intraday_data = await invesgo.get_ohlcv_intraday(ticker, market="RG")
        except Exception as e:
            logger.warning(f"[INTRADAY] skip for {ticker}: {e}")
        try:
            orderbook_raw = await invesgo.get_orderbook(ticker)
        except Exception as e:
            logger.warning(f"[ORDERBOOK] skip for {ticker}: {e}")
        try:
            broker_data_raw = await invesgo.get_broker_summary(ticker, investor="all", market="RG")
        except Exception as e:
            logger.warning(f"[BROKER] skip for {ticker}: {e}")
        try:
            ksei_data_raw = await invesgo.get_ksei_ownership(ticker)
        except Exception as e:
            logger.warning(f"[KSEI] skip for {ticker}: {e}")
        official_enrichment = {"available": False}
        try:
            official_enrichment = await build_monitoring_enrichment(ticker, mode=mode, broker_summary=broker_data_raw)
        except Exception as e:
            logger.warning(f"[OFFICIAL_ENRICHMENT] monitoring skip for {ticker}: {e}")
            official_enrichment = {"available": False, "reason": str(e)[:160]}

        # Format orderbook dari Invesgo; fallback ke top-of-book intraday.
        orderbook = normalize_orderbook(orderbook_raw)
        if not orderbook.get("available") and intraday_data:
            orderbook = normalize_orderbook(intraday_data)
        orderbook_execution = build_orderbook_execution_overlay(orderbook, mode=mode)

        # Format broker data
        broker_data = {}
        if broker_data_raw:
            behavior = summarize_broker_behavior(broker_data_raw, top_n=5)
            sorted_brokers = sorted(broker_data_raw, key=lambda x: float(x.get("net_value", 0) or 0), reverse=True)
            top_buy = sorted_brokers[:5] if sorted_brokers else []
            top_sell = sorted(broker_data_raw, key=lambda x: float(x.get("net_value", 0) or 0))[:5]
            total_net = sum(float(b.get("net_value", 0) or 0) for b in broker_data_raw)
            broker_data = {
                "top_broker_net_buy": total_net,
                "top_buyers": behavior.get("top_buyers") or [{"name": b.get("name"), "net_value": float(b.get("net_value", 0) or 0)} for b in top_buy],
                "top_sellers": behavior.get("top_sellers") or [{"name": b.get("name"), "net_value": float(b.get("net_value", 0) or 0)} for b in top_sell],
                "total_net_value": total_net,
                "behavior": behavior,
            }

        # Format KSEI/Foreign data
        foreign_data = {}
        if ksei_data_raw and len(ksei_data_raw) > 0:
            latest = ksei_data_raw[0]
            prev = ksei_data_raw[1] if len(ksei_data_raw) > 1 else {}
            foreign_now = float(latest.get("foreign_cp", 0) or 0)
            foreign_prev = float(prev.get("foreign_cp", 0) or 0)
            net_foreign = foreign_now - foreign_prev
            foreign_data = {
                "net_foreign_buy": net_foreign,
                "foreign_buy": foreign_now,
                "foreign_sell": foreign_prev,
                "foreign_ownership_pct": float(latest.get("foreign_pf", 0) or 0),
            }

        engine_result = await run_monitoring_engines(
            ticker,
            normalized_ohlcv,
            mode,
            orderbook=orderbook,
            broker_data=broker_data,
            broker_summary_raw=broker_data_raw,
            foreign_data=foreign_data,
            official_enrichment=official_enrichment,
        )
        money_maker_previous = await get_latest_flow_snapshot_cloud(ticker, mode)
        money_maker = analyze_money_maker_context(
            ticker=ticker,
            mode=mode,
            ohlcv=normalized_ohlcv,
            engine_result=engine_result,
            broker_summary=broker_data_raw,
            orderbook=orderbook,
            official_enrichment=official_enrichment,
            foreign_flow=foreign_data,
            previous_snapshot=money_maker_previous,
        )
        money_maker_persist = await save_money_maker_cloud(money_maker)
        money_maker.setdefault("flow_memory", {})["cloud_saved"] = bool(money_maker_persist.get("saved"))
        money_maker["flow_memory"]["persistent_backend"] = money_maker_persist.get("persistent_backend", "sqlite")
        logger.warning(f"[DEBUG] engine_result keys: {list(engine_result.keys()) if engine_result else None}")
        logger.warning(f"[DEBUG] engines count: {len(engine_result.get('engines', []))}")

        rag_engines = [
            "PriceActionEngine",
            "VolumeIntelligenceEngine",
            "BandarmologyEngine",
            "BrokerBehaviorEngine",
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

        engine_details = sanitize_for_json({e["engine"]: e for e in engine_result.get("engines", [])})
        engine_names = set(engine_details.keys())

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
            "monitoring_engine_names": sorted(engine_names),
            "bandarmology_included": "BandarmologyEngine" in engine_names,
            "broker_behavior_included": "BrokerBehaviorEngine" in engine_names,
            "orderbook_included": "OrderbookEngine" in engine_names,
            "orderbook_execution": orderbook_execution,
            "official_enrichment": official_enrichment,
            "money_maker": money_maker,
            "engine_details": engine_details,
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

async def build_monitoring_result(payload: Any) -> dict:
    pos = normalize_monitoring_payload(payload)
    try:
        tick = await invesgo.get_tick(pos["ticker"])
        current = tick.get("last_price", pos["entry_price"])
    except Exception:
        current = pos["entry_price"]

    warnings = []
    position_status = "hold"

    if current <= pos["stop_loss"]:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"STOP LOSS HIT at {current}"})
    elif pos["take_profit_3"] and current >= pos["take_profit_3"]:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"TP3 HIT at {current} - full target tercapai!"})
    elif pos["take_profit_2"] and current >= pos["take_profit_2"]:
        warnings.append({"level": "high", "msg": f"TP2 HIT at {current} - partial exit, trail SL ke entry"})
    elif current >= pos["take_profit"] or (pos["take_profit_1"] and current >= pos["take_profit_1"]):
        warnings.append({"level": "high", "msg": f"TP1 HIT at {current} - partial exit 50%, trail SL ke breakeven"})
    elif current <= pos["entry_price"] * 0.97:
        warnings.append({"level": "medium", "msg": "Price down 3% from entry - monitor closely"})

    engine_context = await get_monitoring_engine_context(pos["ticker"], pos["mode"])
    warnings = warnings + extract_early_warnings(engine_context)
    warnings = warnings + analytic_alignment_warnings(pos.get("analytic_context", {}), current)

    empirical_memory = {"available": False}
    try:
        from app.ml.historical_learning import get_empirical_context
        empirical_memory = await get_empirical_context(pos["ticker"], mode=pos["mode"])
        if empirical_memory.get("available") and empirical_memory.get("sample_count", 0) >= 30:
            wr = float(empirical_memory.get("winrate", 0) or 0)
            if wr <= 45:
                warnings.append({
                    "level": "medium",
                    "msg": f"Empirical memory warning: setup historis mirip hanya winrate {wr:.1f}%",
                    "type": "EMPIRICAL_LOW_EDGE",
                })
            elif wr >= 60:
                warnings.append({
                    "level": "low",
                    "msg": f"Empirical memory support: setup historis mirip winrate {wr:.1f}%",
                    "type": "EMPIRICAL_EDGE",
                })
    except Exception:
        empirical_memory = pos.get("empirical_memory") or {"available": False}

    position_guard = _build_position_guard_state(pos, current, warnings)
    tp_sl_confidence = build_tp_sl_confidence(pos, current, engine_context, empirical_memory, warnings)

    result = {
        **pos,
        "current_price": current,
        "position": position_status,
        "status": "EXIT" if position_status == "exit" else pos.get("status", "HOLD"),
        "pnl_pct": round((current - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0,
        "rr": calculate_rr(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "smart_trailing_stop": calculate_smart_trailing_stop(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "institutional_alerts": generate_institutional_alerts(pos["entry_price"], pos["stop_loss"], pos["take_profit"], current),
        "engine_context": engine_context,
        "empirical_memory": empirical_memory,
        "analytic_context": pos.get("analytic_context", {}),
        "position_guard": position_guard,
        "tp_sl_confidence": tp_sl_confidence,
        "warnings": warnings,
    }
    return sanitize_for_json(result)

@router.post("/check")
async def stateless_monitoring_check(req: MonitoringRequest):
    result = await build_monitoring_result(req)
    return JSONResponse(content=json.loads(json.dumps(result, cls=NumpyEncoder)))

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
    elif req.take_profit_3 and current >= req.take_profit_3:
        position_status = "exit"
        warnings.append({"level": "high", "msg": f"✅ TP3 HIT at {current} — full target tercapai!"})
    elif req.take_profit_2 and current >= req.take_profit_2:
        warnings.append({"level": "high", "msg": f"✅ TP2 HIT at {current} — partial exit, trail SL ke entry"})
    elif current >= req.take_profit or (req.take_profit_1 and current >= req.take_profit_1):
        warnings.append({"level": "high", "msg": f"✅ TP1 HIT at {current} — partial exit 50%, trail SL ke breakeven"})
    elif current <= req.entry_price * 0.97:
        warnings.append({"level": "medium", "msg": "Price down 3% from entry — monitor closely"})

    engine_context = await get_monitoring_engine_context(req.ticker, req.mode)
    early_warnings = extract_early_warnings(engine_context)
    warnings = warnings + early_warnings
    warnings = warnings + analytic_alignment_warnings(req.analytic_context, current)
    empirical_memory = {"available": False}
    try:
        from app.ml.historical_learning import get_empirical_context
        empirical_memory = await get_empirical_context(req.ticker, mode=req.mode)
        if empirical_memory.get("available") and empirical_memory.get("sample_count", 0) >= 30:
            wr = float(empirical_memory.get("winrate", 0) or 0)
            if wr <= 45:
                warnings.append({
                    "level": "medium",
                    "msg": f"Empirical memory warning: setup historis mirip hanya winrate {wr:.1f}%",
                    "type": "EMPIRICAL_LOW_EDGE",
                })
            elif wr >= 60:
                warnings.append({
                    "level": "low",
                    "msg": f"Empirical memory support: setup historis mirip winrate {wr:.1f}%",
                    "type": "EMPIRICAL_EDGE",
                })
    except Exception:
        empirical_memory = {"available": False}

    result = sanitize_for_json({
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
        "empirical_memory": empirical_memory,
        "analytic_context": req.analytic_context,
        "warnings": warnings,
    })
    return JSONResponse(content=json.loads(json.dumps(result, cls=NumpyEncoder)))


# ─── ADDITIVE EARLY WARNING SYSTEM ────────────────────────────────────────────

def extract_early_warnings(engine_context: dict) -> list:
    warnings = []
    if not engine_context or not engine_context.get("engines_used"):
        return warnings

    official_enrichment = engine_context.get("official_enrichment") or {}
    for warning in official_enrichment.get("warnings") or []:
        warnings.append({
            "level": warning.get("level", "LOW"),
            "type": warning.get("type", "OFFICIAL_ENRICHMENT"),
            "message": warning.get("message", "Official Invezgo enrichment warning."),
        })
    money_maker = engine_context.get("money_maker") or {}
    for warning in money_maker.get("warnings") or []:
        warnings.append({
            "level": warning.get("level", "MEDIUM"),
            "type": warning.get("type", "MONEY_MAKER_CORE"),
            "message": warning.get("message", "Money Maker Core warning."),
        })
    if money_maker.get("verdict") == "FLOW_OUT_AVOID":
        warnings.append({
            "level": "HIGH",
            "type": "MONEY_MAKER_FLOW_OUT",
            "message": "Money Maker Core membaca flow out/distribution trap; kurangi risiko atau exit sesuai plan.",
        })

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

    # M-2: Phase 2 warnings dari engine details
    try:
        phase2_data = engine_details.get("Phase2Engine", {}) or engine_details.get("WyckoffEngine", {})
        wyckoff = phase2_data.get("data", {}).get("wyckoff_phase", "") or phase2_data.get("wyckoff_phase", "")
        weinstein = phase2_data.get("data", {}).get("weinstein_stage", 0) or phase2_data.get("weinstein_stage", 0)
        vsa = phase2_data.get("data", {}).get("vsa_signal", "") or phase2_data.get("vsa_signal", "")

        if wyckoff in ("DISTRIBUTION", "MARKDOWN"):
            warnings.append({"level": "HIGH", "type": "PHASE2_EXIT",
                "message": f"⚠️ Wyckoff {wyckoff} terdeteksi — pertimbangkan exit posisi!"})
        elif wyckoff in ("ACCUMULATION", "MARKUP", "REACCUMULATION"):
            warnings.append({"level": "LOW", "type": "PHASE2_HOLD",
                "message": f"Wyckoff {wyckoff} — posisi aligned dengan fase market"})
        if weinstein == 4:
            warnings.append({"level": "HIGH", "type": "WEINSTEIN_DECLINE",
                "message": "Weinstein Stage 4 DECLINING — pertimbangkan exit segera!"})
        if vsa in ("UP_THRUST", "NO_DEMAND"):
            warnings.append({"level": "MEDIUM", "type": "VSA_BEARISH",
                "message": f"VSA {vsa} — tekanan jual microstructure terdeteksi"})
    except Exception:
        pass

    # M-3: TrendStructure warnings
    try:
        trend = engine_details.get("TrendStructureEngine", {})
        trend_data = trend.get("data", {})
        trend_dir = trend_data.get("trend", "") or trend_data.get("direction", "")
        ma_cross = trend_data.get("ma_cross", "")
        if trend_dir in ("DOWNTREND", "BEARISH"):
            warnings.append({"level": "MEDIUM", "type": "TREND_REVERSAL",
                "message": "TrendStructure: trend berubah BEARISH — waspadai reversal"})
        if ma_cross in ("DEATH_CROSS", "bearish_cross"):
            warnings.append({"level": "HIGH", "type": "DEATH_CROSS",
                "message": "Death cross terdeteksi — sinyal bearish kuat"})
    except Exception:
        pass

    # M-3: PriceAction warnings
    try:
        pa = engine_details.get("PriceActionEngine", {})
        pa_data = pa.get("data", {})
        pa_signal = pa_data.get("signal", "") or pa_data.get("pattern", "")
        if pa_signal in ("BEARISH_ENGULFING", "SHOOTING_STAR", "EVENING_STAR"):
            warnings.append({"level": "MEDIUM", "type": "PRICE_ACTION_BEARISH",
                "message": f"Price Action: pola {pa_signal} — potensi reversal bearish"})
    except Exception:
        pass

    # M-3: RiskManagement warnings
    try:
        rm = engine_details.get("RiskManagementEngine", {})
        rm_score = rm.get("score", 50)
        if rm_score < 35:
            warnings.append({"level": "HIGH", "type": "RISK_DETERIORATED",
                "message": f"Risk Management score {rm_score:.0f} — kondisi risk memburuk"})
    except Exception:
        pass

    # M-4: Foreign flow warning dari broker data
    try:
        foreign = engine_details.get("ForeignFlowEngine", {}) or engine_details.get("foreign_data", {})
        net_foreign = foreign.get("net_foreign_buy", 0) or foreign.get("data", {}).get("net_foreign_buy", 0)
        if net_foreign < -5e9:
            warnings.append({"level": "HIGH", "type": "FOREIGN_EXIT",
                "message": f"Foreign flow NET SELL {net_foreign/1e9:.1f}B — asing keluar posisi"})
        elif net_foreign > 5e9:
            warnings.append({"level": "LOW", "type": "FOREIGN_HOLD",
                "message": f"Foreign flow NET BUY {net_foreign/1e9:.1f}B — asing masih akumulasi"})
    except Exception:
        pass

    # REV28: BrokerBehaviorEngine warning dari top 5 buyer/seller
    try:
        broker_behavior = engine_details.get("BrokerBehaviorEngine", {})
        behavior_data = broker_behavior.get("data", {})
        pressure = behavior_data.get("pressure", "")
        smart_net = float(behavior_data.get("smart_money_net_bil", 0) or 0)
        dominant_buyer = (behavior_data.get("dominant_buyer") or {}).get("code", "")
        dominant_seller = (behavior_data.get("dominant_seller") or {}).get("code", "")
        if pressure in ("distribution", "retail_exit_liquidity") and smart_net < -1:
            warnings.append({"level": "HIGH", "type": "BROKER_DISTRIBUTION",
                "message": f"BrokerBehavior: smart money net sell {smart_net:.1f}B, top seller {dominant_seller}. Waspadai distribusi."})
        elif pressure in ("accumulation", "smart_accumulation") and smart_net > 1:
            warnings.append({"level": "LOW", "type": "BROKER_ACCUMULATION",
                "message": f"BrokerBehavior: smart money net buy {smart_net:.1f}B, top buyer {dominant_buyer}. Akumulasi broker mendukung posisi."})
    except Exception:
        pass

    return warnings
