"""
Router — Monitoring Enhancement REV22
Path: backend/app/api/monitoring_enhancement/router.py

Endpoint:
POST /api/monitoring/enhancement/{ticker}

Orchestrator semua engine:
1. data_adapter      — fetch + normalize data
2. price_feed        — harga + alert check
3. bandar_type       — Engine 3
4. bandarmologi      — Engine 4
5. momentum          — Engine 5
6. retest            — Engine 6
7. tp_probability    — Engine 7
8. enrichment        — Engine 8 (REV21 reuse)
9. rag_monitor       — Engine 9
10. recommendation   — final synthesis
"""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException

from .models import (
    MonitoringEnhancementRequest,
    MonitoringEnhancementResponse,
    PriceFeedResult,
    AlertResult, AlertType,
    FinalRecommendation, FinalAction,
    BandarType, MomentumLabel,
    RetestVerdict, EnrichmentVerdict,
    BandarPhase,
)
from .data_adapter import fetch_adapted_data
from .bandar_type_classifier import classify_bandar_type
from .bandarmologi_monitor import run_bandarmologi_monitor
from .momentum_strength import calculate_momentum_strength
from .retest_classifier import classify_retest
from .tp_probability import calculate_tp_probability
from .rag_monitor import run_rag_monitor

router = APIRouter()
logger = logging.getLogger(__name__)

def _normalize_trade_mode(mode: str) -> str:
    normalized = str(mode or "SWING").upper()
    if normalized == "INTRADAY":
        return "DAYTRADING"
    if normalized in ("SWING", "DAYTRADING", "SCALPING"):
        return normalized
    return "SWING"


# ─────────────────────────────────────────────
# HELPER — PRICE FEED + ALERT
# ─────────────────────────────────────────────

def _build_price_feed(data, req) -> PriceFeedResult:
    return PriceFeedResult(
        ticker       = req.ticker,
        last_price   = data.last_price,
        prev_close   = data.prev_close,
        change_pct   = round(data.change_pct, 2),
        volume_today = data.volume_today,
        timestamp    = datetime.now().isoformat(),
    )


def _check_alert(last_price: float, req) -> AlertResult:
    """Cek apakah SL atau TP sudah kena"""
    base = AlertResult(
        sl_price  = req.sl_price,
        tp1_price = req.tp1_price,
        tp2_price = req.tp2_price,
        tp3_price = req.tp3_price,
    )

    if last_price <= req.sl_price:
        base.alert_type    = AlertType.SL_HIT
        base.triggered     = True
        base.trigger_price = last_price
        base.message       = f"⛔ SL HIT di {last_price} — EXIT ALL"
    elif req.tp3_price > 0 and last_price >= req.tp3_price:
        base.alert_type    = AlertType.TP3_HIT
        base.triggered     = True
        base.trigger_price = last_price
        base.message       = f"🎯 TP3 HIT di {last_price} — PROFIT MAKSIMAL"
    elif req.tp2_price > 0 and last_price >= req.tp2_price:
        base.alert_type    = AlertType.TP2_HIT
        base.triggered     = True
        base.trigger_price = last_price
        base.message       = f"🎯 TP2 HIT di {last_price} — pertimbangkan partial exit"
    elif req.tp1_price > 0 and last_price >= req.tp1_price:
        base.alert_type    = AlertType.TP1_HIT
        base.triggered     = True
        base.trigger_price = last_price
        base.message       = f"✅ TP1 HIT di {last_price} — amankan sebagian profit"

    return base


# ─────────────────────────────────────────────
# HELPER — ENRICHMENT REUSE REV21
# ─────────────────────────────────────────────

async def _run_enrichment(ticker: str, data):
    """Reuse enrichment engine dari REV21"""
    try:
        from app.api.enrichment.smart_mfi import SmartMFI
        from app.api.enrichment.kama_bands import KAMABands
        from app.api.enrichment.lele_exhaustion import LeleExhaustion
        from app.api.enrichment.divergence import DivergenceStateMachine
        from .models import EnrichmentRealtimeResult

        # Build ohlcv list of dict
        ohlcv = [
            {"open": o, "high": h, "low": l, "close": c, "volume": v}
            for o, h, l, c, v in zip(
                data.opens, data.highs, data.lows, data.closes, data.volumes
            )
        ]

        try:
            mfi_result = SmartMFI().compute(ohlcv)
            mfi_val    = float(mfi_result.get("mfi", 50.0))
            mfi_signal = "BULLISH" if mfi_val > 60 else "BEARISH" if mfi_val < 40 else "NEUTRAL"
        except Exception:
            mfi_val, mfi_signal = 50.0, "NEUTRAL"

        try:
            kama_result = KAMABands().compute(ohlcv)
            kama_val    = float(kama_result.get("basis", data.closes[-1] if data.closes else 0))
            last        = data.closes[-1] if data.closes else kama_val
            kama_dist   = ((last - kama_val) / kama_val * 100) if kama_val else 0
            kama_zone   = "ABOVE_BASIS" if kama_dist > 0.5 else "BELOW_BASIS" if kama_dist < -0.5 else "AT_BASIS"
        except Exception:
            kama_zone, kama_dist = "AT_BASIS", 0.0

        try:
            lele_result = LeleExhaustion().compute(ohlcv)
            lele_signal = lele_result.get("signal", "NONE")
        except Exception:
            lele_signal = "NONE"

        try:
            div_result = DivergenceStateMachine().compute(ohlcv)
            div_state  = div_result.get("state", "CLEAR")
        except Exception:
            div_state = "CLEAR"

        warnings = sum([
            mfi_signal == "BEARISH",
            kama_zone == "BELOW_BASIS",
            lele_signal != "NONE",
            div_state != "CLEAR",
        ])
        verdict = EnrichmentVerdict.PROCEED if warnings == 0 else \
                  EnrichmentVerdict.CAUTION if warnings <= 2 else \
                  EnrichmentVerdict.SKIP

        return EnrichmentRealtimeResult(
            mfi_signal        = mfi_signal,
            mfi_value         = mfi_val,
            kama_zone         = kama_zone,
            kama_distance_pct = kama_dist,
            lele_signal       = lele_signal,
            divergence_state  = div_state,
            verdict           = verdict,
            warning_count     = warnings,
        )
    except Exception as e:
        logger.warning(f"Enrichment failed [{ticker}]: {e}")
        from .models import EnrichmentRealtimeResult
        return EnrichmentRealtimeResult(mfi_signal="NEUTRAL", mfi_value=50.0, kama_zone="AT_BASIS", kama_distance_pct=0.0, lele_signal="NONE", divergence_state="CLEAR", verdict=EnrichmentVerdict.CAUTION)


# ─────────────────────────────────────────────
# HELPER — FINAL RECOMMENDATION
# ─────────────────────────────────────────────

def _build_recommendation(
    tp_result,
    alert,
    bandarmologi,
    rag,
) -> FinalRecommendation:
    reasons = []
    action  = tp_result.recommendation

    # Override jika SL hit
    if alert.triggered and alert.alert_type == AlertType.SL_HIT:
        action = FinalAction.EXIT_ALL
        reasons.append("SL HIT — exit semua posisi")

    # Reasons dari engine
    if bandarmologi.distribution_detected:
        reasons.append(f"Distribusi terdeteksi ({bandarmologi.distribution_signals.count} sinyal)")
    if bandarmologi.phase_changed:
        reasons.append(f"Fase berubah ke {bandarmologi.current_phase.value}")
    if rag.triggered and rag.kb_insight:
        reasons.append(f"RAG insight: {rag.kb_insight[:100]}...")

    reasons.append(f"TP1 probability: {tp_result.prob_tp1}%")
    reasons.append(f"Multiplier total: {tp_result.multiplier_stack.get('total', 1.0):.3f}x")

    confidence = tp_result.prob_tp1
    if rag.confidence_boost > 0:
        confidence = min(99.0, confidence + rag.confidence_boost)

    return FinalRecommendation(
        action     = action,
        reason     = reasons,
        confidence = round(confidence, 1),
        sl_hit     = alert.triggered and alert.alert_type == AlertType.SL_HIT,
        tp_hit     = alert.alert_type if alert.triggered else None,
    )


# ─────────────────────────────────────────────
# MAIN ENDPOINT
# ─────────────────────────────────────────────

@router.post(
    "/monitoring/enhancement/{ticker}",
    response_model=MonitoringEnhancementResponse,
    summary="Monitoring Enhancement REV22",
    tags=["Monitoring Enhancement"],
)
async def monitoring_enhancement(
    ticker: str,
    req:    MonitoringEnhancementRequest,
):
    """
    Endpoint utama Monitoring Enhancement REV22.
    Orchestrate 9 engine dan return rekomendasi final.
    """
    start_time = time.time()
    ticker     = ticker.upper()
    trade_mode = _normalize_trade_mode(req.trade_mode)

    try:
        # ── Step 1: Fetch + normalize data ──
        data = await fetch_adapted_data(ticker, trade_mode)
        if data.error and not data.closes:
            raise HTTPException(status_code=503, detail=f"Data fetch failed: {data.error}")

        # ── Step 2: Price feed + Alert ──
        price_feed = _build_price_feed(data, req)
        alert      = _check_alert(data.last_price, req)
        sl_hit     = alert.triggered and alert.alert_type.value == "SL_HIT"

        # ── Step 3: Bandar Type (Engine 3) ──
        avg_lot_size = data.avg_volume / max(len(data.volumes), 1)
        bandar_type_result = classify_bandar_type(
            ticker              = ticker,
            net_foreign_lot     = data.net_foreign_lot,
            usd_idr_correlation = None,
            avg_lot_size        = avg_lot_size,
            lot_count           = len(data.volumes),
            total_volume        = data.volume_today,
            price_change_pct    = data.change_pct,
            market_cap_billion  = None,
            spread_pct          = data.orderbook.spread_pct if data.orderbook else 0.5,
            price_changes_3d    = [((data.closes[i] - data.closes[i-1]) / data.closes[i-1] * 100)
                                   for i in range(-3, 0) if len(data.closes) > 3],
            volume_changes_3d   = data.volumes[-3:] if len(data.volumes) >= 3 else data.volumes,
        )

        # ── Step 4: Bandarmologi Monitor (Engine 4) ──
        bandarmologi_result = run_bandarmologi_monitor(
            ticker           = ticker,
            current_score    = req.entry_score,
            entry_score      = req.entry_score,
            net_foreign_lot  = data.net_foreign_lot,
            closes           = data.closes,
            highs            = data.highs,
            lows             = data.lows,
            volumes          = data.volumes,
            avg_volume       = data.avg_volume,
            price_change_pct = data.change_pct,
        )

        # ── Step 5: Momentum (Engine 5) ──
        momentum_result = calculate_momentum_strength(
            ticker  = ticker,
            opens   = data.opens,
            highs   = data.highs,
            lows    = data.lows,
            closes  = data.closes,
            volumes = data.volumes,
        )

        # ── Step 6: Retest Classifier (Engine 6) ──
        retest_result = await classify_retest(
            ticker          = ticker,
            highs           = data.highs,
            lows            = data.lows,
            closes          = data.closes,
            volumes         = data.volumes,
            avg_volume      = data.avg_volume,
            bandar_phase    = bandarmologi_result.current_phase.value,
            net_foreign_lot = data.net_foreign_lot,
            swing_lookback  = trade_mode == "SWING" and 20 or 15,
        )

        # ── Phase 2 dari retest_result ──
        wyckoff_phase   = getattr(retest_result, 'wyckoff_phase',   'UNKNOWN')
        weinstein_stage = getattr(retest_result, 'weinstein_stage', 0)
        vsa_background  = getattr(retest_result, 'vsa_background',  'NEUTRAL')

        # ── Step 7: TP Probability (Engine 7) ──
        tp_result = calculate_tp_probability(
            ticker                 = ticker,
            trade_mode             = trade_mode,
            entry_price            = req.entry_price,
            sl_price               = req.sl_price,
            tp1_price              = req.tp1_price,
            tp2_price              = req.tp2_price,
            tp3_price              = req.tp3_price,
            last_price             = data.last_price,
            bandar_type            = bandar_type_result.bandar_type,
            momentum_label         = momentum_result.label,
            retest_verdict         = retest_result.retest_verdict,
            enrichment_verdict     = EnrichmentVerdict.CAUTION,
            distribution_detected  = bandarmologi_result.distribution_detected,
            sl_hit                 = sl_hit,
            vwap                   = data.vwap,
            orderbook_imbalance    = data.orderbook.imbalance if data.orderbook else 1.0,
            lots                   = req.lots,
            wyckoff_phase          = wyckoff_phase,
            weinstein_stage        = weinstein_stage,
            vsa_background         = vsa_background,
        )

        # ── Step 8: Enrichment REV21 ──
        enrichment_result = await _run_enrichment(ticker, data)

        # Update tp_result enrichment verdict
        tp_result = calculate_tp_probability(
            ticker                 = ticker,
            trade_mode             = trade_mode,
            entry_price            = req.entry_price,
            sl_price               = req.sl_price,
            tp1_price              = req.tp1_price,
            tp2_price              = req.tp2_price,
            tp3_price              = req.tp3_price,
            last_price             = data.last_price,
            bandar_type            = bandar_type_result.bandar_type,
            momentum_label         = momentum_result.label,
            retest_verdict         = retest_result.retest_verdict,
            enrichment_verdict     = enrichment_result.verdict,
            distribution_detected  = bandarmologi_result.distribution_detected,
            sl_hit                 = sl_hit,
            vwap                   = data.vwap,
            orderbook_imbalance    = data.orderbook.imbalance if data.orderbook else 1.0,
            lots                   = req.lots,
            wyckoff_phase          = wyckoff_phase,
            weinstein_stage        = weinstein_stage,
            vsa_background         = vsa_background,
        )

        # ── Step 9: RAG Monitor (Engine 9) ──
        rag_result = await run_rag_monitor(
            ticker                 = ticker,
            bandar_confidence      = bandar_type_result.confidence,
            distribution_detected  = bandarmologi_result.distribution_detected,
            distribution_signals   = [k for k, v in {
                "upthrust":         bandarmologi_result.distribution_signals.upthrust,
                "no_demand":        bandarmologi_result.distribution_signals.no_demand,
                "effort_vs_result": bandarmologi_result.distribution_signals.effort_vs_result,
                "top_volume":       bandarmologi_result.distribution_signals.top_volume,
            }.items() if v],
            bandar_retest_type     = retest_result.bandar_retest_type.value,
            fib_pct                = retest_result.fib_level_pct,
            momentum_score         = momentum_result.score,
            momentum_prev_score    = momentum_result.prev_score or momentum_result.score,
            momentum_score_drop    = momentum_result.score_drop,
            prob_tp1               = tp_result.prob_tp1,
            prob_tp1_drop          = tp_result.prob_tp1_drop,
        )

        # ── Step 10: Final Recommendation ──
        recommendation = _build_recommendation(
            tp_result, alert, bandarmologi_result, rag_result
        )

        processing_ms = round((time.time() - start_time) * 1000, 1)

        return MonitoringEnhancementResponse(
            ticker             = ticker,
            trade_mode         = trade_mode,
            poll_timestamp     = datetime.now().isoformat(),
            price_feed         = price_feed,
            alert              = alert,
            bandar_type        = bandar_type_result,
            bandarmologi       = bandarmologi_result,
            momentum           = momentum_result,
            retest             = retest_result,
            tp_probability     = tp_result,
            enrichment         = enrichment_result,
            rag_monitor        = rag_result,
            recommendation     = recommendation,
            processing_time_ms = processing_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MonitoringEnhancement error [{ticker}]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
