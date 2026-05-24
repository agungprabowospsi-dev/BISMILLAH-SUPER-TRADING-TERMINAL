# ─── ANALYTIC ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _R, HTTPException
from fastapi.responses import JSONResponse
import json
import numpy as np
from sqlalchemy import text as sql_text
from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
from app.ml.signal_quality import predict_win_probability, get_model_status
from app.ml.dynamic_sltp import calculate_dynamic_sltp
from pydantic import BaseModel
from app.core import invesgo
from app.engines.master_runner import run_all_engines
from app.core.claude_client import ask_claude
from app.knowledge_base import kb_service
import logging

logger = logging.getLogger(__name__)

router = _R()

@router.get("/debug")
async def debug():
    import traceback
    results = {}
    try:
        from app.core import invesgo
        ohlcv = await invesgo.get_ohlcv_daily("BBCA")
        results["step1_ohlcv"] = f"OK {len(ohlcv)} candles"
    except Exception as e:
        return {"failed_at": "step1_ohlcv", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.engines.master_runner import run_all_engines
        all_eng = await run_all_engines("BBCA", ohlcv, "swing")
        results["step2_engines"] = f"OK score={all_eng['composite_score']} engines={all_eng['total_engines']}"
    except Exception as e:
        return {"failed_at": "step2_engines", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.api.analytic import _calc_atr
        atr = _calc_atr(ohlcv)
        results["step3_atr"] = f"OK atr={atr}"
    except Exception as e:
        return {"failed_at": "step3_atr", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.knowledge_base import kb_service
        ctx = await kb_service.get_kb_context_for_engine("PriceActionEngine", "BBCA")
        results["step4_rag"] = f"OK len={len(ctx)}"
    except Exception as e:
        return {"failed_at": "step4_rag", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.core.claude_client import ask_claude
        r = await ask_claude(system="test", prompt="say OK", max_tokens=10)
        results["step5_claude"] = f"OK: {r}"
    except Exception as e:
        return {"failed_at": "step5_claude", "error": str(e), "trace": traceback.format_exc()}
    # Test invesgo endpoints
    for name, coro in [
        ("price_table", invesgo.get_price_table("BBCA")),
        ("orderbook", invesgo.get_orderbook("BBCA")),
        ("broker", invesgo.get_broker_summary("BBCA")),
        ("company", invesgo.get_company_info("BBCA")),
    ]:
        try:
            data = await coro
            k = list(data.keys())[:5] if isinstance(data, dict) else f"list[{len(data)}]"
            results[f"step_{name}"] = f"OK keys={k}"
        except Exception as e:
            results[f"step_{name}"] = f"ERROR: {str(e)[:80]}"
    return {"all_ok": True, "results": results}

class ScreenerContext(BaseModel):
    grade: str = ""
    score: float = 0.0
    wyckoff_phase: str = ""
    weinstein_stage: int = 0
    vsa_signal: str = ""
    phase: str = ""
    akumulasi_score: float = 50.0
    foreign_signal: str = ""
    bandarmology_score: float = 0.0

class AnalyticRequest(BaseModel):
    ticker: str
    mode: str = "swing"
    screener_context: ScreenerContext = None  # SA-1: dari screener


def _round_price(value, fallback=0.0):
    try:
        value = float(value or fallback or 0)
    except Exception:
        value = float(fallback or 0)
    return float(round(value, 0))


def build_setup_action_plan(
    *,
    mode: str,
    verdict: str,
    setup_type: str,
    setup_reason: str,
    entry_method: str,
    current: float,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    atr: float,
    range_high_20: float,
    range_low_20: float,
    ma20: float,
    ma50: float,
    rvol: float,
    wyckoff_phase: str,
    weinstein_stage: int,
    vsa_signal: str,
    enrichment_verdict: str,
    foreign_signal: str,
    price_dist: dict,
    empirical_memory: dict,
) -> dict:
    """Turn a verdict into an executable setup contract for Swing/Intraday."""
    mode_l = (mode or "swing").lower()
    is_intraday = mode_l in ("intraday", "scalping")
    setup = (setup_type or "neutral").lower()
    verdict = verdict or "WAIT"
    wyckoff = (wyckoff_phase or "UNKNOWN").upper()
    vsa = (vsa_signal or "NONE").upper()
    foreign = (foreign_signal or "NEUTRAL").upper()
    poc = float((price_dist or {}).get("poc_price", 0) or 0)
    support = _round_price(range_low_20 or current)
    resistance = _round_price(range_high_20 or current)
    ma_level = _round_price(ma20 or current)
    trigger_buffer = 1.002 if is_intraday else 1.005
    trigger = _round_price((resistance or current) * trigger_buffer)
    retest_zone = _round_price(resistance or ma_level or current)
    accumulation_zone = _round_price(poc if poc > 0 else support)
    invalidation = _round_price(min(support, stop_loss or support))
    min_rvol = 1.2 if is_intraday else 1.3

    action = {
        "decision": verdict,
        "setup_type": (setup_type or "neutral").upper(),
        "order_type": entry_method or "MARKET_ORDER",
        "timeframe": "INTRADAY" if is_intraday else "SWING",
        "current_price": _round_price(current),
        "trigger_price": trigger,
        "entry_price": _round_price(entry or current),
        "entry_zone_low": _round_price(entry or current),
        "entry_zone_high": _round_price(entry or current),
        "stop_loss": _round_price(stop_loss or invalidation),
        "take_profit_1": _round_price(tp1),
        "take_profit_2": _round_price(tp2),
        "take_profit_3": _round_price(tp3),
        "support": support,
        "resistance": resistance,
        "invalidation_price": invalidation,
        "next_action": setup_reason or "Tunggu setup lebih jelas.",
        "confirmation_needed": [],
        "invalidation_rules": [],
        "aggressive_plan": "",
        "conservative_plan": "",
    }

    bearish_structure = wyckoff in ("MARKDOWN", "DISTRIBUTION") or setup.startswith("bearish") or setup == "distribution_warning"
    reversal_signal = vsa in ("STOPPING_VOLUME", "NO_SUPPLY", "TEST") or wyckoff == "ACCUMULATION"
    empirical_ok = bool(
        (empirical_memory or {}).get("available")
        and float((empirical_memory or {}).get("winrate", 0) or 0) >= 58
    )

    if verdict == "NO GO" or setup in ("bearish_breakdown", "bearish_continuation", "bearish_reversal", "distribution_warning"):
        action.update({
            "decision": "NO GO",
            "setup_type": "NO_LONG_ENTRY",
            "order_type": "NO_LONG_ENTRY",
            "entry_zone_low": 0,
            "entry_zone_high": 0,
            "next_action": "Tidak ada entry long valid sampai struktur bearish batal.",
            "confirmation_needed": [
                f"Reclaim di atas {trigger} dengan RVOL >= {min_rvol}",
                "Wyckoff tidak lagi MARKDOWN/DISTRIBUTION",
                "Tidak ada distribusi lanjutan atau foreign heavy sell",
            ],
            "invalidation_rules": [
                f"Close tetap di bawah support {support}",
                "Weinstein Stage 4 atau breakdown lanjutan",
            ],
            "aggressive_plan": "Tidak disarankan.",
            "conservative_plan": "Masukkan watchlist saja sampai reversal/reclaim terkonfirmasi.",
        })
        return action

    if bearish_structure and not (reversal_signal and empirical_ok):
        action.update({
            "decision": "WAIT",
            "setup_type": "WAIT_REVERSAL_CONFIRMATION",
            "order_type": "NO_MARKET_ENTRY",
            "trigger_price": trigger,
            "entry_price": trigger,
            "entry_zone_low": retest_zone,
            "entry_zone_high": trigger,
            "stop_loss": invalidation,
            "invalidation_price": invalidation,
            "next_action": "Tunggu perubahan struktur dari markdown/distribution menjadi reversal yang terkonfirmasi.",
            "confirmation_needed": [
                f"Reclaim dan close di atas {trigger}",
                f"RVOL >= {min_rvol}",
                "Wyckoff berubah ke ACCUMULATION/REACCUMULATION atau muncul SPRING/SOS/TEST",
                "Tidak ada UPTHRUST/NO_DEMAND setelah reclaim",
            ],
            "invalidation_rules": [
                f"Close breakdown di bawah {support}",
                "Foreign berubah NET SELL besar atau bandar score makin melemah",
            ],
            "aggressive_plan": f"Buy stop hanya setelah reclaim {trigger}.",
            "conservative_plan": f"Tunggu retest valid ke {retest_zone} setelah reclaim.",
        })
        return action

    if setup == "bullish_breakout" or entry_method in ("BUY_STOP_BREAKOUT", "BULKOWSKI_MEASURE_RULE"):
        action.update({
            "setup_type": "GO_BUY_STOP_BREAKOUT" if verdict in ("GO", "STRONG GO") else "WAIT_BREAKOUT_CONFIRMATION",
            "order_type": "BUY_STOP_BREAKOUT" if verdict in ("GO", "STRONG GO") else "WAIT_CLOSE_CONFIRMATION",
            "trigger_price": trigger,
            "entry_price": trigger,
            "entry_zone_low": trigger,
            "entry_zone_high": _round_price(trigger + atr * 0.3),
            "next_action": f"Tunggu breakout valid di atas {trigger}.",
            "confirmation_needed": [
                f"Close di atas resistance {resistance}",
                f"RVOL >= {min_rvol}",
                "Breakout tidak langsung kembali ke bawah resistance",
            ],
            "invalidation_rules": [f"Close kembali di bawah {resistance}", f"Breakdown support {support}"],
            "aggressive_plan": f"Buy stop di {trigger}.",
            "conservative_plan": f"Tunggu throwback/retest ke {resistance}.",
        })
    elif setup == "bullish_pullback":
        zone_low = _round_price(ma_level - atr * 0.25)
        zone_high = _round_price(ma_level + atr * 0.25)
        action.update({
            "setup_type": "GO_LIMIT_PULLBACK" if verdict in ("GO", "STRONG GO") else "WAIT_PULLBACK_ZONE",
            "order_type": "LIMIT_PULLBACK",
            "trigger_price": zone_high,
            "entry_price": ma_level,
            "entry_zone_low": zone_low,
            "entry_zone_high": zone_high,
            "next_action": f"Tunggu pullback sehat ke area {zone_low}-{zone_high}.",
            "confirmation_needed": [
                "Trend tetap di atas MA utama",
                "Volume koreksi lebih kecil dari volume naik",
                "Muncul bounce/rejection di area pullback",
            ],
            "invalidation_rules": [f"Close di bawah {invalidation}", "Pullback berubah jadi distribusi"],
            "aggressive_plan": f"Limit bertahap di area {zone_low}-{zone_high}.",
            "conservative_plan": f"Tunggu candle bounce dari area {zone_low}-{zone_high}.",
        })
    elif setup == "bullish_accumulation":
        zone = accumulation_zone or support
        action.update({
            "setup_type": "GO_LIMIT_ACCUMULATION" if verdict in ("GO", "STRONG GO") and wyckoff != "MARKDOWN" else "WAIT_ACCUMULATION_CONFIRMATION",
            "order_type": "LIMIT_ACCUMULATION" if verdict in ("GO", "STRONG GO") and wyckoff != "MARKDOWN" else "NO_MARKET_ENTRY",
            "trigger_price": trigger,
            "entry_price": zone,
            "entry_zone_low": _round_price(zone - atr * 0.25),
            "entry_zone_high": _round_price(zone + atr * 0.25),
            "next_action": f"Pantau akumulasi di area {zone}; jangan chase.",
            "confirmation_needed": [
                "Absorption/POC tetap bertahan",
                "Foreign/institusi tetap net buy",
                f"Reclaim resistance {resistance} untuk upgrade menjadi GO breakout",
            ],
            "invalidation_rules": [f"Close di bawah {support}", "POC gagal bertahan atau muncul distribusi"],
            "aggressive_plan": f"Akumulasi kecil dekat {zone} hanya jika risk terkendali.",
            "conservative_plan": f"Tunggu reclaim {trigger} atau retest valid setelah reclaim.",
        })
    elif setup == "bullish_reversal":
        action.update({
            "decision": "WAIT" if verdict == "GO" else verdict,
            "setup_type": "WAIT_REVERSAL_CONFIRMATION",
            "order_type": "NO_MARKET_ENTRY",
            "trigger_price": trigger,
            "entry_price": trigger,
            "entry_zone_low": support,
            "entry_zone_high": trigger,
            "next_action": "Tunggu reversal confirmation sebelum entry.",
            "confirmation_needed": [
                f"Reclaim {trigger}",
                "Spring/stopping volume/test terkonfirmasi",
                "Higher low terbentuk setelah reclaim",
            ],
            "invalidation_rules": [f"Close di bawah {support}", "Reversal gagal dan breakdown berlanjut"],
            "aggressive_plan": f"Buy stop di {trigger} setelah reclaim.",
            "conservative_plan": f"Tunggu retest higher low di atas {support}.",
        })
    elif setup == "bullish_continuation":
        action.update({
            "setup_type": "GO_MARKET_MOMENTUM" if is_intraday and verdict in ("GO", "STRONG GO") else "GO_CONTINUATION_CONFIRMATION",
            "order_type": "MARKET_MOMENTUM" if is_intraday and verdict in ("GO", "STRONG GO") else "WAIT_CLOSE_CONFIRMATION",
            "confirmation_needed": [
                "Momentum tetap di atas support intraday/MA",
                f"RVOL >= {min_rvol}",
                "Tidak ada exhaustion/upthrust",
            ],
            "invalidation_rules": [f"Close di bawah {ma_level}", f"Breakdown support {support}"],
            "aggressive_plan": "Market hanya jika momentum dan likuiditas masih aktif.",
            "conservative_plan": f"Tunggu pullback ke {ma_level}.",
        })
    else:
        action.update({
            "decision": "WAIT" if verdict in ("GO", "STRONG GO") else verdict,
            "setup_type": "WAIT_SETUP_CONFIRMATION",
            "order_type": "NO_MARKET_ENTRY",
            "next_action": "Belum ada entry dominan; tunggu trigger yang lebih bersih.",
            "confirmation_needed": [
                f"Breakout di atas {trigger} atau pullback valid ke {ma_level}",
                "Volume dan broker flow mendukung",
            ],
            "invalidation_rules": [f"Breakdown di bawah {support}"],
            "aggressive_plan": "Tidak disarankan sebelum setup jelas.",
            "conservative_plan": "Masuk watchlist sampai trigger muncul.",
        })

    if enrichment_verdict == "SKIP":
        action["decision"] = "NO GO"
        action["order_type"] = "NO_LONG_ENTRY"
        action["setup_type"] = "NO_LONG_ENTRY"
        action["next_action"] = "Enrichment SKIP; tunggu kondisi membaik."

    return action


@router.post("/analyze")
async def analyze(req: AnalyticRequest):
    try:
        ohlcv = await invesgo.get_ohlcv_daily(req.ticker)
        if not ohlcv or len(ohlcv) < 20:
            raise HTTPException(400, "Insufficient OHLCV data")

        # Inject harga realtime ke candle terakhir
        try:
            ctx = await invesgo.get_market_context(req.ticker)
            if ctx and ctx.get("price", {}).get("last"):
                realtime_price = float(ctx["price"]["last"])
                realtime_high = float(ctx["price"].get("high", ohlcv[-1].get("high", realtime_price)))
                realtime_low = float(ctx["price"].get("low", ohlcv[-1].get("low", realtime_price)))
                ohlcv[-1]["close"] = realtime_price
                ohlcv[-1]["high"] = max(realtime_high, realtime_price)
                ohlcv[-1]["low"] = min(realtime_low, realtime_price)
                logger.info(f"Injected realtime price {realtime_price} for {req.ticker}")
        except Exception as e:
            logger.warning(f"Could not inject realtime price: {e}")

        # Cast OHLCV ke float
        ohlcv = [{
            **c,
            "open":   float(c.get("open",   0) or 0),
            "high":   float(c.get("high",   0) or 0),
            "low":    float(c.get("low",    0) or 0),
            "close":  float(c.get("close",  0) or 0),
            "volume": float(c.get("volume", 0) or 0),
        } for c in ohlcv]

        broker_data_for_engines = []
        try:
            broker_data_for_engines = await invesgo.get_broker_summary(req.ticker)
        except Exception as broker_err:
            logger.debug(f"[BROKER] analytic prefetch skip: {broker_err}")

        # ALIGNMENT-FIX: Trust screener Grade A/B to avoid re-computation
        use_screener_score = False
        if req.screener_context and req.screener_context.grade.upper() in ("A", "B"):
            if req.screener_context.score >= 55:
                # Screener already validated — use its score
                use_screener_score = True
                score = float(req.screener_context.score)
                # Mock engines response untuk consistency
                all_engines = {
                    "composite_score": score,
                    "signal": "BULLISH" if score >= 65 else "BEARISH",
                    "bullish_count": int(score / 10),
                    "bearish_count": 3 if score < 65 else 1,
                    "total_engines": 10,
                    "engines": [{"engine": "screener_cached", "score": score, "signal": "BULLISH" if score >= 65 else "NEUTRAL"}]
                }
                logger.info(f"[ALIGN] Using screener Grade {req.screener_context.grade} score {score:.1f} for {req.ticker}")
        
        if not use_screener_score:
            # Fresh analysis — run all engines
            all_engines = await run_all_engines(
                req.ticker,
                ohlcv,
                req.mode,
                broker_summary_raw=broker_data_for_engines,
            )
            score = all_engines["composite_score"]

        current = ohlcv[-1]["close"]
        regime = "SIDEWAYS"
        regime_data = {}
        lq45_chg = 0.0
        breadth = 50.0
        entry_strat = {}
        price_dist = {}
        detected_pattern = {}
        pat_stats = {}
        bulkowski_context = ""
        price_dist_context = ""
        bandar_engines_context = ""
        foreign_flow_context = ""
        foreign_signal = "NEUTRAL"
        foreign_net_val = 0.0
        broker_conc = {}
        value_inflow = {}
        bid_offer = {}

        # ── Enrichment + Phase 2 Integration ──────────────────────
        enrichment_verdict  = "CAUTION"
        phase2_verdict      = "HOLD"
        wyckoff_phase       = "UNKNOWN"
        weinstein_stage     = 0
        vsa_signal          = "NONE"

        try:
            from app.api.enrichment.router import _run_phase2
            from app.api.enrichment.smart_mfi import SmartMFI
            from app.api.enrichment.kama_bands import KAMABands
            from app.api.enrichment.lele_exhaustion import LeleExhaustion
            from app.api.enrichment.divergence import DivergenceStateMachine

            mfi_r  = SmartMFI().compute(ohlcv)
            kama_r = KAMABands().compute(ohlcv)
            lele_r = LeleExhaustion().compute(ohlcv)
            redis  = None
            div_r  = await DivergenceStateMachine().compute(ohlcv, redis, req.ticker)

            warn = sum([
                mfi_r.get("signal") == "BEARISH",
                kama_r.get("entry_signal") in ("BELOW_LOWER3", "BELOW_LOWER2"),
                lele_r.get("detected", False),
                div_r.get("state") in ("BEARISH_WARN", "HIDDEN_BEAR"),
            ])
            enrichment_verdict = "SKIP" if warn >= 3 else "CAUTION" if warn == 2 else "PROCEED"

            p2 = _run_phase2(ohlcv)
            if p2:
                phase2_verdict  = p2.phase2_verdict
                wyckoff_phase   = p2.wyckoff.phase
                weinstein_stage = p2.weinstein.stage
                vsa_signal      = p2.vsa.signal

        except Exception as e:
            logger.warning(f"Enrichment/Phase2 in analytic failed: {e}")

        # ── GO / NO GO Logic ────────────────────────────────────────
        go_reasons    = []
        no_go_reasons = []

        if score >= 65:
            go_reasons.append(f"Bandar score {score:.0f} — TIER {'1' if score >= 80 else '2'}")
        else:
            no_go_reasons.append(f"Bandar score {score:.0f} terlalu rendah (min 65)")

        if enrichment_verdict == "PROCEED":
            go_reasons.append("Enrichment PROCEED — timing entry valid")
        elif enrichment_verdict == "SKIP":
            no_go_reasons.append("Enrichment SKIP — sinyal kontradiksi")

        if wyckoff_phase in ("ACCUMULATION", "MARKUP", "REACCUMULATION"):
            go_reasons.append(f"Wyckoff {wyckoff_phase} — fase bullish")
        elif wyckoff_phase in ("DISTRIBUTION", "MARKDOWN"):
            no_go_reasons.append(f"Wyckoff {wyckoff_phase} — fase bearish")

        if weinstein_stage == 2:
            go_reasons.append("Weinstein Stage 2 — ADVANCING")
        elif weinstein_stage == 4:
            no_go_reasons.append("Weinstein Stage 4 — DECLINING")

        if vsa_signal in ("STOPPING_VOLUME", "NO_SUPPLY", "TEST"):
            go_reasons.append(f"VSA {vsa_signal} — bullish microstructure")
        elif vsa_signal in ("UP_THRUST", "NO_DEMAND"):
            no_go_reasons.append(f"VSA {vsa_signal} — bearish microstructure")

        # INT-3: phase2_verdict masuk GO/NO GO
        if phase2_verdict in ("STRONG_BUY", "BUY"):
            go_reasons.append(f"Phase2 verdict {phase2_verdict} — konfirmasi bullish")
        elif phase2_verdict in ("SELL", "STRONG_SELL"):
            no_go_reasons.append(f"Phase2 verdict {phase2_verdict} — konfirmasi bearish")

        # SA-2: screener_grade masuk GO/NO GO sebagai sinyal
        if req.screener_context and req.screener_context.grade:
            sc_grade = req.screener_context.grade.upper()
            sc_score = req.screener_context.score
            if sc_grade == "A" and sc_score >= 75:
                go_reasons.append(f"Screener Grade A (score {sc_score:.1f}) — fully pre-validated")
            elif sc_grade == "B" and sc_score >= 55:
                go_reasons.append(f"Screener Grade B (score {sc_score:.1f}) — qualified candidate")
            elif sc_grade in ("C", "D"):
                no_go_reasons.append(f"Screener Grade {sc_grade} — kandidat lemah dari screener")
            # Phase 2 dari screener — pakai jika analytic Phase 2 tidak ada data
            if req.screener_context.wyckoff_phase and wyckoff_phase == "UNKNOWN":
                wyckoff_phase = req.screener_context.wyckoff_phase
            if req.screener_context.weinstein_stage and weinstein_stage == 0:
                weinstein_stage = req.screener_context.weinstein_stage
            if req.screener_context.vsa_signal and vsa_signal == "NONE":
                vsa_signal = req.screener_context.vsa_signal

        # Final GO/NO GO — ALIGNMENT-FIX: Respect screener Grade A/B override
        go_score = len(go_reasons)
        no_score = len(no_go_reasons)

        # Override: If screener Grade A/B, allow GO despite enrichment SKIP or low stage
        screener_grade_override = False
        if req.screener_context and req.screener_context.grade:
            sc_grade = req.screener_context.grade.upper()
            sc_score = req.screener_context.score
            # Grade A + score >= 75 → override score<55 dan no_score<=2
            if sc_grade == "A" and sc_score >= 75 and no_score <= 2:
                screener_grade_override = True
            # Grade B + score >= 55 -> override score<55 saja, no_score<=1
            elif sc_grade == "B" and sc_score >= 55 and no_score <= 1:
                screener_grade_override = True

        if (enrichment_verdict == "SKIP" or weinstein_stage == 4 or score < 55) and not screener_grade_override:
            go_no_go = "NO GO"
            go_confidence = max(0, 30 - (no_score * 10))
        elif go_score >= 3 and no_score == 0:
            go_no_go = "STRONG GO"
            go_confidence = min(95, 70 + go_score * 5)
        elif (go_score >= 2 and go_score > no_score) or screener_grade_override:
            go_no_go = "GO"
            go_confidence = min(95, 60 + go_score * 5) if screener_grade_override else min(85, 60 + go_score * 5)
        elif no_score >= 2:
            go_no_go = "WAIT"
            go_confidence = max(30, 60 - no_score * 10)
        else:
            go_no_go = "WAIT"
            go_confidence = 50

        # ── Setup Type Detector (additive) ─────────────────────────
        closes = [c["close"] for c in ohlcv]
        highs = [c["high"] for c in ohlcv]
        lows = [c["low"] for c in ohlcv]
        volumes = [c["volume"] for c in ohlcv]

        # FIX-2/3/4: Mode-aware setup metrics
        if req.mode == "intraday":
            # Intraday: lookback 3 hari, EMA9/EMA21, ATR dari range hari ini
            lookback = min(3, len(closes))
            ma20 = sum(closes[-9:]) / min(9, len(closes))   # EMA9 approx
            ma50 = sum(closes[-21:]) / min(21, len(closes)) # EMA21 approx
            range_high_20 = max(highs[-lookback:])
            range_low_20  = min(lows[-lookback:])
            # ATR intraday = rata2 (high-low) 3 hari terakhir
            intraday_ranges = [highs[i] - lows[i] for i in range(-lookback, 0)]
            atr_intraday = sum(intraday_ranges) / len(intraday_ranges) if intraday_ranges else atr
            atr = atr_intraday  # Override ATR dengan intraday ATR
        else:
            # Swing/scalping: lookback 20 hari seperti biasa
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current
            ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
            range_high_20 = max(highs[-20:]) if len(highs) >= 20 else current
            range_low_20  = min(lows[-20:]) if len(lows) >= 20 else current

        avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else max(volumes[-1], 1)
        rvol = volumes[-1] / avg_vol_20 if avg_vol_20 else 1

        trend_up = current >= ma20 >= ma50
        trend_down = current <= ma20 <= ma50
        near_low = current <= range_low_20 * 1.03
        near_high = current >= range_high_20 * 0.97
        breakout_up = current >= range_high_20 and rvol >= 1.3
        breakdown_down = current <= range_low_20 and rvol >= 1.3

        setup_type = "neutral"
        setup_reason = "Belum ada pola setup dominan."

        if breakout_up:
            setup_type = "bullish_breakout"
            setup_reason = "Harga menembus range high 20 hari dengan volume relatif kuat."
        elif breakdown_down:
            setup_type = "bearish_breakdown"
            setup_reason = "Harga menembus range low 20 hari dengan volume relatif kuat."
        elif trend_up and near_high:
            setup_type = "bullish_continuation"
            setup_reason = "Trend naik dan harga berada dekat area high, mengarah ke continuation."
        elif trend_up and current <= ma20 * 1.02:
            setup_type = "bullish_pullback"
            setup_reason = "Trend naik namun harga pullback dekat MA20."
        elif trend_down and near_low and score >= 55:
            setup_type = "bullish_reversal"
            setup_reason = "Harga berada dekat range low dalam downtrend, tetapi score mulai membaik."
        elif trend_down:
            setup_type = "bearish_continuation"
            setup_reason = "Trend turun masih dominan dan belum ada reversal kuat."
        elif near_low and score >= 55:
            setup_type = "bullish_reversal"
            setup_reason = "Harga dekat support/range low dengan score positif."
        elif near_high and score <= 45:
            setup_type = "bearish_reversal"
            setup_reason = "Harga dekat resistance/range high dengan score lemah."

        # ───────────────────────────────────────────────────────────

        # Hitung SL/TP sederhana
        atr = _calc_atr(ohlcv)
        sl_mult = {"swing": 2.0, "intraday": 1.5, "scalping": 1.0}.get(req.mode, 1.5)

        # Jika Bulkowski pattern entry tersedia dan lebih akurat, pakai itu
        # Jika tidak, hitung entry berdasarkan setup_type
        if entry_strat and entry_strat.get("entry_type") not in ("NO_ENTRY", "WAIT_CLOSE", ""):
            # Bulkowski Measure Rule entry
            entry = entry_strat.get("entry_price", current)
            sl    = entry_strat.get("stop_loss", round(entry - atr * sl_mult, 0))
            tp1   = entry_strat.get("take_profit_1", round(entry + atr * sl_mult * 1.5, 0))
            tp2   = entry_strat.get("take_profit_2", round(entry + atr * sl_mult * 2.5, 0))
            tp3   = entry_strat.get("take_profit_3", round(entry + atr * sl_mult * 4.0, 0))
            entry_method = "BULKOWSKI_MEASURE_RULE"
        elif setup_type == "bullish_accumulation":
            # Limit order di POC level — bukan market order
            poc = price_dist.get("poc_price", 0) if price_dist else 0
            entry = round(poc if poc > 0 else current * 0.99, 0)
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "LIMIT_AT_POC"
        elif setup_type == "bullish_pullback":
            # Limit order di MA20 atau EMA9
            ma20 = sum(c["close"] for c in ohlcv[-20:]) / 20 if len(ohlcv) >= 20 else current
            ema9 = sum(c["close"] for c in ohlcv[-9:]) / 9 if len(ohlcv) >= 9 else current
            ma_level = ema9 if req.mode.lower() == "intraday" else ma20
            entry = round(ma_level, 0)
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "LIMIT_AT_MA"
        elif setup_type == "bullish_breakout":
            # BUY STOP di atas resistance
            recent_high = max(c["high"] for c in ohlcv[-20:]) if len(ohlcv) >= 20 else current
            entry = round(recent_high * 1.005, 0)
            sl    = round(recent_high - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "BUY_STOP_BREAKOUT"
        elif setup_type in ("bearish_distribution", "bearish_continuation", "bearish_reversal", "bearish_breakdown"):
            # Bearish: NO ENTRY untuk long — set entry current tapi tandai
            entry = current
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "NO_LONG_ENTRY"
            no_go_reasons.append("Setup " + setup_type + " — tidak ada entry long yang valid")
        else:
            # Default: market order di current price
            entry = current
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "MARKET_ORDER"

        rr = round((tp1 - entry) / (entry - sl), 2) if entry != sl else 0

        # SW-2: RR < 1.0 → force NO GO — setup tidak layak
        if rr < 1.0 and rr > 0:
            no_go_reasons.append(f"RR={rr} < 1.0 — risk lebih besar dari reward, setup tidak layak")

        # ── RAG KB CONTEXT ──────────────────────────────────────────
        kb_context = ""
        try:
            from app.core.knowledge_base import query_bandarmologi_specific
            analytic_engines = [
                "PriceActionEngine", "VolumeIntelligenceEngine",
                "TrendStructureEngine", "RiskManagementEngine"
            ]
            kb_parts = []

            # Bandarmologi IDX — query khusus 3 buku murni IDX
            bandar_ctx = await query_bandarmologi_specific(
                ticker       = req.ticker,
                bandar_score = float(score),
                phase        = wyckoff_phase,
                signal       = all_engines.get('signal', 'NEUTRAL'),
            )
            if bandar_ctx:
                kb_parts.append(
                    f"=== BANDARMOLOGI IDX (3 Buku Khusus IDX) ===\n{bandar_ctx}"
                )

            # Buku teknikal spesifik per fungsi
            from app.core.knowledge_base import (
                query_trade_setup, query_murphy_ta,
                query_coulling_vpa, query_lopezdeprado
            )
            import asyncio as _asyncio

            setup_query = (
                f"Setup {setup_type} untuk {req.mode} trading, "
                f"score {score:.0f}, signal {all_engines.get('signal','NEUTRAL')}. "
                f"Apakah setup ini valid? Kriteria entry dan manajemen risiko?"
            )
            murphy_query = (
                f"Trend analysis {setup_type}, MA20={ma20:.0f}, MA50={ma50:.0f}, "
                f"harga {'di atas' if trend_up else 'di bawah'} MA. "
                f"Konfirmasi technical analysis?"
            )
            vpa_query = (
                f"Volume {rvol:.1f}x average, setup {setup_type}. "
                f"Apakah volume mengkonfirmasi price movement ini?"
            )
            ml_query = (
                f"Score {score:.0f}/100, win probability setup {setup_type}. "
                f"Statistical edge dan feature importance?"
            )

            setup_ctx, murphy_ctx, vpa_ctx, ml_ctx = await _asyncio.gather(
                query_trade_setup(setup_query, n=2),
                query_murphy_ta(murphy_query, n=2),
                query_coulling_vpa(vpa_query, n=2),
                query_lopezdeprado(ml_query, n=1),
            )

            for label, ctx in [
                ("Trade Setup Handbook", setup_ctx),
                ("Murphy TA", murphy_ctx),
                ("Coulling VPA", vpa_ctx),
                ("Lopez de Prado ML", ml_ctx),
            ]:
                if ctx:
                    kb_parts.append(f"=== {label} ===\n{ctx}")
            if kb_parts:
                kb_context = "\n\n=== REFERENSI KNOWLEDGE BASE ===\n" + "\n---\n".join(kb_parts[:5])  # FIX3
                logger.info(f"[RAG] Analytic {req.ticker}: {len(kb_parts)} KB contexts injected")
        except Exception as kb_err:
            logger.debug(f"[RAG] analytic skip: {kb_err}")
        # ────────────────────────────────────────────────────────────

        # Market Regime Context
        market_regime_context = ""
        lq45_chg = 0.0  # HOTFIX: default sebelum try block
        breadth = 50.0  # HOTFIX: default sebelum try block
        try:
            regime_data = await invesgo.get_market_regime()
            ihsg = regime_data.get("IHSG", {}) or {}
            lq45 = regime_data.get("LQ45", {}) or {}
            
            ihsg_close = ihsg.get("close")
            ihsg_prev = ihsg.get("prev")
            ihsg_change_pct = 0
            if ihsg_close and ihsg_prev and ihsg_prev != 0:
                ihsg_change_pct = ((ihsg_close - ihsg_prev) / ihsg_prev) * 100
            
            top_gainer = regime_data.get("top_gainer", [])
            top_loser = regime_data.get("top_loser", [])
            
            # Determine regime
            if ihsg_change_pct > 1:
                regime = "STRONG BULL"
            elif ihsg_change_pct > 0:
                regime = "BULL"
            elif ihsg_change_pct > -1:
                regime = "SIDEWAYS/BEAR"
            else:
                regime = "STRONG BEAR"
            
            lq45_close = lq45.get("close", 0)
            
            market_regime_context = f"""
=== MARKET REGIME ===
Regime: {regime}
IHSG: {ihsg_close or "N/A"} ({ihsg_change_pct:+.2f}%)
LQ45: {lq45_close}
Top Gainers: {", ".join([s.get("code","") for s in (top_gainer[:3] if top_gainer else [])])}
Top Losers: {", ".join([s.get("code","") for s in (top_loser[:3] if top_loser else [])])}
"""
        except Exception as regime_err:
            logger.debug(f"[REGIME] skip: {regime_err}")
            market_regime_context = ""

        # BUL-1: Bulkowski Pattern Detection
        bulkowski_context = ""
        detected_pattern = {}
        pat_stats = {}
        entry_strat = {}
        try:
            from app.engines.idx_pattern_detector import detect_patterns
            from app.engines.bulkowski_stats import get_pattern_stats, compute_entry_strategy
            from app.engines.idx_calibration import get_idx_calibration
            mode_pat = "intraday" if req.mode.lower() in ("intraday","scalping") else "swing"
            patterns_found = detect_patterns(ohlcv, mode=mode_pat) if ohlcv and len(ohlcv) >= 20 else []
            if patterns_found:
                pat = patterns_found[0]
                pname = pat.get("pattern", "")
                detected_pattern = pat
                idx_calib = get_idx_calibration(pname)
                pat_stats = get_pattern_stats(pname, regime, idx_calib)
                entry_strat = compute_entry_strategy(
                    pname,
                    current_price=float(ohlcv[-1].get("close", 0)) if ohlcv else 0,
                    formation_high=pat.get("formation_high", 0),
                    formation_low=pat.get("formation_low", 0),
                    breakout_price=pat.get("breakout_price", 0),
                )
                adj_fail = pat_stats.get("adj_failure_rate", 25)
                adj_rise = pat_stats.get("adj_avg_rise", 30)
                conf = pat.get("confidence", 0)
                if entry_strat.get("entry_type") not in ("NO_ENTRY", "WAIT_CLOSE"):
                    if adj_fail <= 15 and conf >= 75:
                        go_reasons.append("Pattern " + pname + " confidence " + str(conf) + " persen IDX failure rate " + str(adj_fail) + " persen RENDAH avg rise " + str(adj_rise) + " persen")
                    elif adj_fail >= 30:
                        no_go_reasons.append("Pattern " + pname + " IDX failure rate " + str(adj_fail) + " persen TINGGI konfirmasi volume dulu")
                if pat.get("bust_opportunity") and pat.get("status") == "BREAKDOWN_NEAR":
                    go_reasons.append("Busted " + pname + " opportunity 47 persen bust avg plus 65 persen rise")
                bulkowski_context = "Pattern " + pname + " status " + pat.get("status","") + " confidence " + str(conf) + " persen. " + pat.get("description","") + ". IDX failure rate " + str(adj_fail) + " persen avg rise " + str(adj_rise) + " persen. " + entry_strat.get("measure_rule_note","") + ". " + entry_strat.get("throwback_note","")
        except Exception as bul_err:
            logger.debug("BULKOWSKI skip " + str(bul_err))

        # BE-1/2/3: Bandar Engines — Broker Concentration + Value Inflow + Bid-Offer
        bandar_engines_context = ""
        try:
            from app.engines.broker_concentration_engine import analyze_broker_concentration
            from app.engines.value_inflow_engine import analyze_value_inflow
            from app.engines.bid_offer_depth_engine import analyze_bid_offer_depth

            broker_data = broker_data_for_engines or await invesgo.get_broker_summary(req.ticker)
            intraday    = await invesgo.get_ohlcv_intraday(req.ticker, market="RG")

            # BE-1: Broker Concentration
            broker_conc = analyze_broker_concentration(broker_data) if broker_data else {}
            # BE-2: Value Inflow
            value_inflow = analyze_value_inflow(broker_data) if broker_data else {}
            # BE-3: Bid-Offer Depth
            bid_offer = analyze_bid_offer_depth(intraday) if intraday else {}

            # Masuk GO/NO GO
            bc_signal = broker_conc.get("signal", "")
            vi_signal = value_inflow.get("signal", "")
            bo_signal = bid_offer.get("signal", "")

            if bc_signal in ("BANDAR_STRONG", "BANDAR_ACTIVE", "FOREIGN_BANDAR_STRONG", "FOREIGN_BANDAR_ACTIVE"):
                go_reasons.append(f"Broker Konsentrasi {bc_signal} (HHI {broker_conc.get('hhi',0):.2f}) — {broker_conc.get('dominant_broker','')} dominasi {broker_conc.get('dominant_share_pct',0):.0f}%")
            elif bc_signal == "RETAIL_MARKET":
                no_go_reasons.append("Broker tersebar merata — tidak ada bandar aktif")

            if vi_signal in ("SMART_MONEY_INFLOW", "INSTITUTIONAL_BUYING"):
                go_reasons.append(f"Value Inflow {vi_signal} — institusi net {value_inflow.get('institutional_net_bil',0):+.1f}B")
            elif vi_signal in ("SMART_MONEY_OUTFLOW", "RETAIL_CHASING_DISTRIBUTION"):
                no_go_reasons.append(f"Value Inflow {vi_signal} — smart money keluar")

            if bo_signal == "ABSORPTION":
                go_reasons.append(f"Bid-Offer ABSORPTION (ratio {bid_offer.get('depth_ratio',1):.1f}x) — bandar absorb supply")
            elif bo_signal == "DISTRIBUTION_PRESSURE":
                no_go_reasons.append(f"Bid-Offer DISTRIBUTION PRESSURE — tekanan jual dominan")

            if bid_offer.get("fake_bid_wall"):
                no_go_reasons.append("FAKE BID WALL terdeteksi — waspadai jebakan")

            bandar_engines_context = f"""
=== BANDAR ENGINES ===
Broker Concentration: {bc_signal} | HHI: {broker_conc.get('hhi',0):.3f} | Dominant: {broker_conc.get('dominant_broker','')} ({broker_conc.get('dominant_share_pct',0):.0f}%) | Type: {broker_conc.get('bandar_type','')}
Value Inflow: {vi_signal} | Inst Net: {value_inflow.get('institutional_net_bil',0):+.1f}B | Foreign Net: {value_inflow.get('foreign_net_bil',0):+.1f}B | SM Ratio: {value_inflow.get('smart_money_ratio',0):.0f}%
Bid-Offer: {bo_signal} | Depth Ratio: {bid_offer.get('depth_ratio',1):.2f}x | Spread: {bid_offer.get('spread_pct',0):.2f}% | Fake Wall: {bid_offer.get('fake_bid_wall',False)}
Divergence: {value_inflow.get('divergence','')}
"""
        except Exception as be_err:
            logger.debug(f"[BANDAR_ENGINES] skip: {be_err}")
            bandar_engines_context = ""

        # PT-3: Price Distribution Analysis
        price_dist = {}
        price_dist_context = ""
        try:
            from app.engines.price_distribution_engine import analyze_price_distribution
            from datetime import datetime as _dt_pd
            _today_pd = _dt_pd.now().strftime("%Y-%m-%d")
            pt_data = await invesgo.get_price_table(req.ticker, date=_today_pd)
            if pt_data and len(pt_data) >= 2:
                price_dist = analyze_price_distribution(pt_data)
                pd_signal = price_dist.get("signal", "NEUTRAL")
                pd_score  = price_dist.get("score", 50)
                poc       = price_dist.get("poc_price", 0)
                if pd_signal == "ACCUMULATION":
                    go_reasons.append(f"Price Distribution ACCUMULATION (score {pd_score:.0f}) — bandar absorb di {price_dist.get('accumulation_count',0)} level, POC {poc}")
                elif pd_signal == "DISTRIBUTION":
                    no_go_reasons.append(f"Price Distribution DISTRIBUTION (score {pd_score:.0f}) — distribusi di {price_dist.get('distribution_count',0)} level")
                price_dist_context = f"=== PRICE DISTRIBUTION {req.ticker} ===\nSignal: {pd_signal} | Score: {pd_score:.0f} | POC: {poc}\nNet Bias: {price_dist.get('net_bias')} | Ratio: {price_dist.get('net_ratio',0)*100:.1f}%\nAbsorption: {price_dist.get('accumulation_count',0)} level | Distribution: {price_dist.get('distribution_count',0)} level\n"
        except Exception as pd_err:
            logger.debug(f"[PRICE_DIST] skip: {pd_err}")

        # INT-4: Foreign flow ticker spesifik
        foreign_flow_context = ""
        foreign_signal = "NEUTRAL"
        foreign_net_val = 0.0
        try:
            broker_data = broker_data_for_engines or await invesgo.get_broker_summary(req.ticker)
            if broker_data:
                FOREIGN_BROKERS_SET = {"YP","BK","RX","ZP","AK","CC","DB","MS","CS","ML","DP","KI","OD","LG"}
                f_buy = 0.0; f_sell = 0.0; f_net = 0.0
                top_brokers = []
                for b in broker_data:
                    code = b.get("code", "")
                    if code in FOREIGN_BROKERS_SET:
                        net  = float(b.get("net_value", 0) or 0)
                        buy  = float(b.get("buy_value", 0) or 0)
                        sell = float(b.get("sell_value", 0) or 0)
                        f_buy += buy; f_sell += sell; f_net += net
                        top_brokers.append(f"{code}:{net/1e9:+.1f}B")
                foreign_net_val = f_net
                if f_net > 1e9:
                    foreign_signal = "NET BUY"
                    go_reasons.append(f"Foreign flow NET BUY {f_net/1e9:.1f}B — asing akumulasi")
                elif f_net < -1e9:
                    foreign_signal = "NET SELL"
                    no_go_reasons.append(f"Foreign flow NET SELL {f_net/1e9:.1f}B — asing distribusi")
                foreign_flow_context = f"""
=== FOREIGN FLOW {req.ticker} ===
Signal: {foreign_signal}
Net: {f_net/1e9:+.2f}B | Buy: {f_buy/1e9:.2f}B | Sell: {f_sell/1e9:.2f}B
Top Brokers: {", ".join(top_brokers[:5])}
"""
                if foreign_signal == "NET BUY" and setup_type in ("neutral", "bullish_pullback"):
                    setup_type = "bullish_accumulation"
                    setup_reason = f"Foreign broker akumulasi net {f_net/1e9:.1f}B — smart money masuk."
                elif foreign_signal == "NET SELL" and setup_type in ("neutral", "bullish_continuation"):
                    setup_type = "distribution_warning"
                    setup_reason = f"Foreign broker distribusi net {f_net/1e9:.1f}B — waspadai exit."
        except Exception as ff_err:
            logger.debug(f"[FOREIGN FLOW] skip: {ff_err}")

        # Final entry strategy: run after Bulkowski, price distribution,
        # broker engines, and foreign flow can refine setup_type.
        atr = _calc_atr(ohlcv)
        sl_mult = {"swing": 2.0, "intraday": 1.5, "scalping": 1.0}.get(req.mode, 1.5)

        if entry_strat and entry_strat.get("entry_type") not in ("NO_ENTRY", "WAIT_CLOSE", ""):
            entry = entry_strat.get("entry_price", current)
            sl    = entry_strat.get("stop_loss", round(entry - atr * sl_mult, 0))
            tp1   = entry_strat.get("take_profit_1", round(entry + atr * sl_mult * 1.5, 0))
            tp2   = entry_strat.get("take_profit_2", round(entry + atr * sl_mult * 2.5, 0))
            tp3   = entry_strat.get("take_profit_3", round(entry + atr * sl_mult * 4.0, 0))
            entry_method = "BULKOWSKI_MEASURE_RULE"
        elif setup_type == "bullish_accumulation":
            poc = price_dist.get("poc_price", 0) if price_dist else 0
            entry = round(poc if poc > 0 else current * 0.99, 0)
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "LIMIT_AT_POC"
        elif setup_type == "bullish_pullback":
            ma20 = sum(c["close"] for c in ohlcv[-20:]) / 20 if len(ohlcv) >= 20 else current
            ema9 = sum(c["close"] for c in ohlcv[-9:]) / 9 if len(ohlcv) >= 9 else current
            ma_level = ema9 if req.mode.lower() == "intraday" else ma20
            entry = round(ma_level, 0)
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "LIMIT_AT_MA"
        elif setup_type == "bullish_breakout":
            recent_high = max(c["high"] for c in ohlcv[-20:]) if len(ohlcv) >= 20 else current
            entry = round(recent_high * 1.005, 0)
            sl    = round(recent_high - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "BUY_STOP_BREAKOUT"
        elif setup_type in ("bearish_distribution", "bearish_continuation", "bearish_reversal", "bearish_breakdown", "distribution_warning"):
            entry = current
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "NO_LONG_ENTRY"
            msg = "Setup " + setup_type + " - tidak ada entry long yang valid"
            if msg not in no_go_reasons:
                no_go_reasons.append(msg)
        else:
            entry = current
            sl    = round(entry - atr * sl_mult, 0)
            tp1   = round(entry + atr * sl_mult * 1.5, 0)
            tp2   = round(entry + atr * sl_mult * 2.5, 0)
            tp3   = round(entry + atr * sl_mult * 4.0, 0)
            entry_method = "MARKET_ORDER"

        rr = round((tp1 - entry) / (entry - sl), 2) if entry != sl else 0
        rr_msg = f"RR={rr} < 1.0 - risk lebih besar dari reward, setup tidak layak"
        if rr < 1.0 and rr > 0 and rr_msg not in no_go_reasons:
            no_go_reasons.append(rr_msg)

        empirical_memory = {"available": False}
        empirical_context = ""
        try:
            from app.ml.historical_learning import get_empirical_context
            empirical_memory = await get_empirical_context(req.ticker, mode=req.mode, candles=ohlcv)
            if empirical_memory.get("available"):
                empirical_context = (
                    "Empirical IDX Memory: "
                    f"pattern {empirical_memory.get('pattern_key')} | "
                    f"sample {empirical_memory.get('sample_count')} | "
                    f"winrate {empirical_memory.get('winrate'):.1f}% | "
                    f"expectancy {empirical_memory.get('expectancy_pct'):.2f}%. "
                    f"{empirical_memory.get('literature', '')}"
                )
                if empirical_memory.get("winrate", 0) >= 58:
                    go_reasons.append(f"Empirical memory winrate {empirical_memory.get('winrate'):.1f}%")
                elif empirical_memory.get("winrate", 100) <= 45 and empirical_memory.get("sample_count", 0) >= 30:
                    no_go_reasons.append(f"Empirical memory lemah: winrate {empirical_memory.get('winrate'):.1f}%")
        except Exception:
            empirical_memory = {"available": False}

        go_score = len(go_reasons)
        no_score = len(no_go_reasons)
        screener_grade_override = False
        if req.screener_context and req.screener_context.grade:
            sc_grade = req.screener_context.grade.upper()
            sc_score = req.screener_context.score
            if sc_grade == "A" and sc_score >= 75 and no_score <= 2:
                screener_grade_override = True
            elif sc_grade == "B" and sc_score >= 55 and no_score <= 1:
                screener_grade_override = True

        if (enrichment_verdict == "SKIP" or weinstein_stage == 4 or score < 55) and not screener_grade_override:
            go_no_go = "NO GO"
            go_confidence = max(0, 30 - (no_score * 10))
        elif go_score >= 3 and no_score == 0:
            go_no_go = "STRONG GO"
            go_confidence = min(95, 70 + go_score * 5)
        elif (go_score >= 2 and go_score > no_score) or screener_grade_override:
            go_no_go = "GO"
            go_confidence = min(95, 60 + go_score * 5) if screener_grade_override else min(85, 60 + go_score * 5)
        elif no_score >= 2:
            go_no_go = "WAIT"
            go_confidence = max(30, 60 - no_score * 10)
        else:
            go_no_go = "WAIT"
            go_confidence = 50

        action_plan = build_setup_action_plan(
            mode=req.mode,
            verdict=go_no_go,
            setup_type=setup_type,
            setup_reason=setup_reason,
            entry_method=entry_method if 'entry_method' in locals() else "MARKET_ORDER",
            current=current,
            entry=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            atr=atr,
            range_high_20=range_high_20,
            range_low_20=range_low_20,
            ma20=ma20,
            ma50=ma50,
            rvol=rvol,
            wyckoff_phase=wyckoff_phase,
            weinstein_stage=weinstein_stage,
            vsa_signal=vsa_signal,
            enrichment_verdict=enrichment_verdict,
            foreign_signal=foreign_signal if 'foreign_signal' in locals() else "NEUTRAL",
            price_dist=price_dist if 'price_dist' in locals() else {},
            empirical_memory=empirical_memory,
        )
        if action_plan.get("decision") in ("WAIT", "NO GO"):
            go_no_go = action_plan["decision"]
            if go_no_go == "WAIT" and go_confidence < 45:
                go_confidence = 45
        setup_type = action_plan.get("setup_type", setup_type)
        entry_method = action_plan.get("order_type", entry_method if 'entry_method' in locals() else "MARKET_ORDER")

        rationale = await ask_claude(
            system="Kamu adalah analis saham IDX profesional. Berikan analisis trading yang jelas dan actionable dalam Bahasa Indonesia.",
            prompt=f"""
Ticker: {req.ticker} | Mode: {req.mode}
Score: {score:.1f}/100 | Signal: {all_engines['signal']}
Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
R:R = {rr}
Setup Type: {setup_type}
Setup Reason: {setup_reason}
Action Plan: {action_plan.get('decision')} | {action_plan.get('setup_type')} | {action_plan.get('order_type')}
Trigger: {action_plan.get('trigger_price')} | Entry Zone: {action_plan.get('entry_zone_low')} - {action_plan.get('entry_zone_high')} | Invalidation: {action_plan.get('invalidation_price')}
Engine: {all_engines.get('bullish_count', 0)} bullish, {all_engines.get('bearish_count', 0)} bearish dari 10 engines
{market_regime_context}
{foreign_flow_context}
{price_dist_context}
{bandar_engines_context}
{bulkowski_context}
{empirical_context}
Phase2: {wyckoff_phase} | Weinstein: {weinstein_stage} | VSA: {vsa_signal} | Verdict: {phase2_verdict}
Screener: {f"Grade {req.screener_context.grade} Score {req.screener_context.score:.1f} Phase {req.screener_context.phase}" if req.screener_context and req.screener_context.grade else "Direct analysis (no screener context)"}
LQ45 Change: {lq45_chg:+.2f}% | Market Breadth: {breadth:.0f}%
{kb_context}

Tulis analisis trading 3-4 kalimat dalam Bahasa Indonesia:
1. Kondisi market saat ini (sertakan regime market jika tersedia)
2. Jenis setup berdasarkan Setup Type, jangan otomatis menyebut continuation jika Setup Type bukan continuation
3. Alasan entry dan level kunci
4. Manajemen risiko (SL/TP)
Jika ada referensi Knowledge Base di atas, gunakan insight tersebut untuk memperkuat analisis.
""",
            max_tokens=400
        )

        import json as _json
        class NumpyEncoder(_json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer): return int(obj)
                if isinstance(obj, np.floating): return float(obj)
                if isinstance(obj, np.bool_): return bool(obj)
                if isinstance(obj, np.ndarray): return obj.tolist()
                return super().default(obj)

        result = {
            "ticker": req.ticker,
            "mode": req.mode,
            "entry": float(entry) if entry else 0,
            "stop_loss": float(sl) if sl else 0,
            "tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp3),
            "rr_ratio": float(rr),
            "score": float(score),
            "confidence": float(min(95, score)),
            "signal": all_engines['signal'],
            "market_regime": regime if 'regime' in dir() else "N/A",
            "setup_type": setup_type,
            "setup_reason": setup_reason,
            "action_plan": action_plan,
            "entry_order_type": action_plan.get("order_type"),
            "trigger_price": action_plan.get("trigger_price"),
            "entry_zone_low": action_plan.get("entry_zone_low"),
            "entry_zone_high": action_plan.get("entry_zone_high"),
            "invalidation_price": action_plan.get("invalidation_price"),
            "next_action": action_plan.get("next_action"),
            "confirmation_needed": action_plan.get("confirmation_needed", []),
            "invalidation_rules": action_plan.get("invalidation_rules", []),
            "setup_metrics": {
                "ma20": float(ma20),
                "ma50": float(ma50),
                "range_high_20": float(range_high_20),
                "range_low_20": float(range_low_20),
                "rvol": float(round(rvol, 2)),
                "trend_up": bool(trend_up),
                "trend_down": bool(trend_down),
                "near_low": bool(near_low),
                "near_high": bool(near_high),
            },
            "rationale": rationale,
            "engines": all_engines,

            # RAG / Knowledge Base validation metadata
            "rag_used": bool(kb_context),
            "rag_context_count": len(kb_parts) if "kb_parts" in locals() else 0,
            "rag_engines": analytic_engines if "analytic_engines" in locals() else [],
            # GO / NO GO
            "go_no_go":          go_no_go,
            "go_confidence":     go_confidence,
            "go_reasons":        go_reasons,
            "no_go_reasons":     no_go_reasons,
            # Enrichment + Phase 2
            "enrichment_verdict": enrichment_verdict,
            "phase2_verdict":    phase2_verdict,
            "wyckoff_phase":     wyckoff_phase,
            "weinstein_stage":   weinstein_stage,
            "vsa_signal":        vsa_signal,
            "foreign_signal":    foreign_signal if 'foreign_signal' in locals() else "N/A",
            "price_distribution": price_dist if 'price_dist' in locals() else {},
            "poc_price":         price_dist.get("poc_price", 0) if 'price_dist' in locals() and price_dist else 0,
            "broker_concentration": broker_conc if 'broker_conc' in locals() else {},
            "value_inflow":         value_inflow if 'value_inflow' in locals() else {},
            "bid_offer_depth":      bid_offer if 'bid_offer' in locals() else {},
            "detected_pattern": detected_pattern if detected_pattern else {},
            "bulkowski_stats": pat_stats if pat_stats else {},
            "pattern_entry": entry_strat if entry_strat else {},
            "entry_method": entry_method if 'entry_method' in locals() else "MARKET_ORDER",
            "foreign_net_bil":   round(foreign_net_val / 1e9, 2) if 'foreign_net_val' in locals() else 0,
            "lq45_change":       round(lq45_chg, 2) if 'lq45_chg' in locals() else 0,
            "market_breadth":    round(breadth, 1) if 'breadth' in locals() else 50,
            "empirical_memory": empirical_memory,
        }

        # ML — Win Probability
        try:
            regime_str = str(result.get("market_regime", "SIDEWAYS"))
            # INT-1: lq45_chg dari regime_data
            try:
                lq45_data = regime_data.get("LQ45", {}) or {}
                lq45_close_val = float(lq45_data.get("close", 0) or 0)
                lq45_prev_val  = float(lq45_data.get("prev", 0) or 0)
                if lq45_close_val > 0 and lq45_prev_val > 0:
                    lq45_chg = ((lq45_close_val - lq45_prev_val) / lq45_prev_val) * 100
                else:
                    lq45_chg = 0.0
            except Exception:
                lq45_chg = 0.0
            # INT-2: breadth dari top_gainer/loser ratio
            try:
                _gainers = len(regime_data.get("top_gainer", []) or [])
                _losers  = len(regime_data.get("top_loser", []) or [])
                _total   = _gainers + _losers
                breadth  = round((_gainers / _total) * 100, 1) if _total > 0 else 50.0
            except Exception:
                breadth = 50.0
            eng_list = all_engines.get('engines', [])
            eng_dict = {}
            if isinstance(eng_list, list):
                for e in eng_list:
                    eng_dict[e.get('engine','?')] = e.get('score', 0)
            elif isinstance(eng_list, dict):
                eng_dict = eng_list
            win_prob = predict_win_probability(
                engine_scores=eng_dict,
                market_regime=regime_str,
                lq45_change=lq45_chg,
                breadth_ratio=breadth,
                final_score=float(score),
                kb_context=kb_context if 'kb_context' in locals() else ""
            )
            result["win_probability"] = win_prob
            result["ml_status"] = get_model_status()
        except Exception as e:
            import traceback
            result["win_probability"] = {"probability": 50.0, "grade": "C", "grade_label": "Moderate", "color": "#fbbf24", "method": "fallback", "error": str(e), "trace": traceback.format_exc()[:200]}
        # Dynamic SL/TP
        try:
            dynamic = calculate_dynamic_sltp(
                entry_price=float(entry) if entry else float(result.get("entry", 0)),
                ohlcv=ohlcv,  # FIX1: was normalized_ohlcv (undefined)
                market_regime=str(result.get("market_regime", "SIDEWAYS")),
                final_score=float(score),
                mode=req.mode,
                akumulasi_score=float(
                    req.screener_context.akumulasi_score
                    if req.screener_context and req.screener_context.akumulasi_score > 50
                    else score
                )  # SA-3: pakai screener akumulasi_score jika tersedia
            )
            result["dynamic_sltp"] = dynamic
        except Exception as e:
            result["dynamic_sltp"] = {"method": "error", "error": str(e)}

        return JSONResponse(content=_json.loads(_json.dumps(result, cls=NumpyEncoder)))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Analytic error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, detail=f"{type(e).__name__}: {str(e)}")

@router.get("/market-context/{ticker}")
async def market_context(ticker: str):
    """4 box: price, volume, company, technical"""

    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.bool_): return bool(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    result = {}
    ohlcv = []

    # OHLCV untuk box 1, 2, 4
    try:
        raw = await invesgo.get_ohlcv_daily(ticker)
        ohlcv = [{**c,
            "open": float(c.get("open",0) or 0),
            "high": float(c.get("high",0) or 0),
            "low": float(c.get("low",0) or 0),
            "close": float(c.get("close",0) or 0),
            "volume": float(c.get("volume",0) or 0),
        } for c in raw]
    except Exception as e:
        ohlcv = []

    # Box 1: Price
    try:
        last = ohlcv[-1]; prev = ohlcv[-2]
        change = last["close"] - prev["close"]
        change_pct = round(change/prev["close"]*100, 2) if prev["close"] > 0 else 0
        result["price"] = {
            "last": last["close"], "change": round(change,0),
            "change_pct": change_pct, "high": last["high"],
            "low": last["low"], "open": last["open"],
        }
    except:
        result["price"] = {"error": "No data"}

    # Box 2: Volume
    try:
        vols = [c["volume"] for c in ohlcv[-20:]]
        avg_vol = sum(vols)/len(vols) if vols else 1
        last_vol = ohlcv[-1]["volume"]
        rvol = round(last_vol/avg_vol, 2) if avg_vol > 0 else 1
        vol_5 = sum(c["volume"] for c in ohlcv[-5:])/5
        result["volume"] = {
            "last_volume": int(last_vol),
            "avg_volume_20": int(avg_vol),
            "rvol": rvol,
            "vol_trend": "NAIK" if vol_5 > avg_vol*1.2 else "TURUN" if vol_5 < avg_vol*0.8 else "NORMAL",
            "signal": "HIGH" if rvol > 2 else "MEDIUM" if rvol > 1.3 else "NORMAL" if rvol > 0.7 else "LOW",
        }
    except:
        result["volume"] = {"error": "No data"}

    # Box 3: Company info
    try:
        info = await invesgo.get_company_info(ticker)
        result["company"] = {
            "name": info.get("company_name") or info.get("name") or ticker,
            "sector": info.get("sector") or info.get("industry") or "-",
            "subsector": info.get("subsindustry") or "-",
            "activity": info.get("activity") or "-",
            "code": info.get("code") or ticker,
        }
    except Exception as e:
        result["company"] = {"error": str(e)}

    # Box 4: Technical summary
    try:
        closes = [c["close"] for c in ohlcv]
        highs = [c["high"] for c in ohlcv]
        lows = [c["low"] for c in ohlcv]
        current = closes[-1]
        w52_high = max(highs[-252:]) if len(highs)>=252 else max(highs)
        w52_low = min(lows[-252:]) if len(lows)>=252 else min(lows)
        ma20 = sum(closes[-20:])/20
        ma50 = sum(closes[-50:])/50 if len(closes)>=50 else ma20
        result["technical"] = {
            "52w_high": w52_high,
            "52w_low": w52_low,
            "pct_from_high": round((current-w52_high)/w52_high*100, 2),
            "pct_from_low": round((current-w52_low)/w52_low*100, 2),
            "ma20": round(ma20, 0),
            "ma50": round(ma50, 0),
            "above_ma20": bool(current > ma20),
            "above_ma50": bool(current > ma50),
            "trend": "UPTREND" if current>ma20>ma50 else "DOWNTREND" if current<ma20<ma50 else "SIDEWAYS",
        }
    except:
        result["technical"] = {"error": "No data"}

    return JSONResponse(content=json.loads(json.dumps(result, cls=NumpyEncoder)))




# ─── SCHEDULED DATA ACCUMULATION ─────────────────────────────────────────────
@router.post("/data/accumulate-scheduled")
async def accumulate_scheduled():
    """
    RC-7: Jalankan setelah market tutup (16:00 WIB).
    Simpan OHLCV hari ini ke PostgreSQL + invalidate Redis cache.
    Panggil dari Railway cron atau manual setiap hari.
    """
    from datetime import datetime
    import pytz

    wib = pytz.timezone("Asia/Jakarta")
    now_wib = datetime.now(wib)
    hour = now_wib.hour

    # Hanya boleh jalan setelah jam 15:30 WIB
    if hour < 15:
        return {
            "status": "skipped",
            "reason": f"Market belum tutup — jam {now_wib.strftime('%H:%M')} WIB",
            "run_after": "15:30 WIB"
        }

    # Jalankan accumulation
    result = await accumulate_ohlcv()

    # Invalidate Redis cache untuk semua ticker yang berhasil
    if result.get("success"):
        try:
            from app.core.invesgo import invalidate_ticker_cache
            for ticker in result["details"]["success"]:
                await invalidate_ticker_cache(ticker)
        except Exception as e:
            pass

    return {
        "status": "ok",
        "message": f"Accumulation selesai jam {now_wib.strftime('%H:%M')} WIB",
        "accumulated": result.get("success", 0),
        "failed": result.get("failed", 0),
        "cache_invalidated": True,
    }


@router.get("/cache/status")
async def cache_status():
    """Cek berapa banyak key Redis yang aktif untuk invesgo cache."""
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if not r:
            return {"status": "redis_not_connected"}
        ohlcv_keys = await r.keys("ohlcv:*")
        broker_keys = await r.keys("broker:*")
        company_keys = await r.keys("company:*")
        regime_keys = await r.keys("market_regime:*")
        ksei_keys = await r.keys("ksei:*")
        return {
            "status": "ok",
            "cache_keys": {
                "ohlcv": len(ohlcv_keys),
                "broker": len(broker_keys),
                "company": len(company_keys),
                "market_regime": len(regime_keys),
                "ksei": len(ksei_keys),
                "total": len(ohlcv_keys) + len(broker_keys) + len(company_keys) + len(regime_keys) + len(ksei_keys)
            },
            "sample_ohlcv": ohlcv_keys[:5],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.delete("/cache/flush")
async def flush_cache():
    """Flush semua invesgo cache (emergency use only)."""
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        patterns = ["ohlcv:*", "broker:*", "company:*", "market_regime:*", "ksei:*"]
        total = 0
        for pattern in patterns:
            keys = await r.keys(pattern)
            if keys:
                await r.delete(*keys)
                total += len(keys)
        return {"status": "ok", "flushed": total}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── HISTORICAL BACKFILL ──────────────────────────────────────────────────────
@router.post("/data/backfill")
async def backfill_historical(years: int = 5):
    """
    Backfill historical OHLCV dari Invesgo ke PostgreSQL.
    Invesgo punya data 15 tahun — jalankan sekali untuk mengisi DB.
    Batching: 5 ticker per batch, delay 2 detik antar batch (anti rate-limit).
    
    Params:
      years: jumlah tahun ke belakang (default 5, max 15)
    """
    import asyncio as _asyncio
    from datetime import datetime as _dt, timedelta as _td
    import httpx as _httpx

    years = min(max(years, 1), 15)
    today = _dt.now().strftime("%Y-%m-%d")
    from_date = (_dt.now() - _td(days=years * 365)).strftime("%Y-%m-%d")

    INVESGO_TOKEN = invesgo.INVESGO_API_KEY if hasattr(invesgo, 'INVESGO_API_KEY') else ""
    try:
        import os
        INVESGO_TOKEN = os.environ.get("INVESGO_API_KEY", "")
    except Exception:
        pass

    results = {"success": [], "failed": [], "skipped": []}
    total_inserted = 0

    async def backfill_one(ticker: str):
        nonlocal total_inserted
        try:
            # Cek sudah ada berapa hari di DB
            async with _AsyncSessionLocal() as db:
                existing = await db.execute(sql_text(
                    "SELECT COUNT(*) FROM ohlcv_daily WHERE ticker = :t"
                ), {"t": ticker})
                count = existing.scalar()

            # Kalau sudah > years*200 hari, skip (sudah cukup)
            if count >= years * 200:
                results["skipped"].append({"ticker": ticker, "existing": count})
                return

            # Fetch dari Invesgo
            ohlcv = await _asyncio.wait_for(
                invesgo.get_ohlcv_daily(ticker, from_date=from_date, to_date=today),
                timeout=30
            )

            if not ohlcv:
                results["failed"].append({"ticker": ticker, "reason": "no data"})
                return

            # Batch insert ke PostgreSQL
            inserted = 0
            async with _AsyncSessionLocal() as db:
                for candle in ohlcv:
                    if not candle.get("close") or float(candle.get("close", 0)) <= 0:
                        continue
                    try:
                        date_str = str(candle.get("date", ""))[:10]
                        if not date_str or len(date_str) < 10:
                            continue
                        from datetime import datetime as _dtt
                        candle_date = _dtt.strptime(date_str, "%Y-%m-%d").date()
                        await db.execute(sql_text("""
                            INSERT INTO ohlcv_daily (ticker, date, open, high, low, close, volume, created_at)
                            VALUES (:ticker, :date, :open, :high, :low, :close, :volume, NOW())
                            ON CONFLICT (ticker, date) DO UPDATE SET
                            open=EXCLUDED.open, high=EXCLUDED.high,
                            low=EXCLUDED.low, close=EXCLUDED.close,
                            volume=EXCLUDED.volume
                        """), {
                            "ticker": ticker,
                            "date": candle_date,
                            "open": float(candle.get("open", 0) or 0),
                            "high": float(candle.get("high", 0) or 0),
                            "low": float(candle.get("low", 0) or 0),
                            "close": float(candle.get("close", 0) or 0),
                            "volume": int(float(candle.get("volume", 0) or 0)),
                        })
                        inserted += 1
                    except Exception:
                        continue
                await db.commit()

            total_inserted += inserted
            results["success"].append({"ticker": ticker, "inserted": inserted, "total_candles": len(ohlcv)})

        except Exception as e:
            results["failed"].append({"ticker": ticker, "reason": str(e)[:100]})

    # Batch 5 ticker per batch, delay 2 detik
    tickers = DATA_WATCHLIST
    for i in range(0, len(tickers), 5):
        batch = tickers[i:i+5]
        await _asyncio.gather(*[backfill_one(t) for t in batch])
        if i + 5 < len(tickers):
            await _asyncio.sleep(2)  # Anti rate-limit

    return {
        "status": "ok",
        "years": years,
        "from_date": from_date,
        "to_date": today,
        "total_inserted": total_inserted,
        "success": len(results["success"]),
        "failed": len(results["failed"]),
        "skipped": len(results["skipped"]),
        "details": results
    }

def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02

@router.get("/test-period/{ticker}/{period}")
async def test_period(ticker: str, period: str):
    try:
        data = await invesgo.get_ohlcv_daily(ticker, period=period)
        if isinstance(data, list):
            return {"period": period, "candles": len(data), "first": data[0] if data else None, "last": data[-1] if data else None}
        return {"period": period, "type": type(data).__name__, "keys": list(data.keys()) if isinstance(data, dict) else None}
    except Exception as e:
        return {"error": str(e)}

@router.get("/market-regime")
async def get_market_regime_endpoint():
    try:
        data = await invesgo.get_market_regime()
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/top-movers/{sort_type}")
async def get_top_movers_endpoint(sort_type: str = "gainer"):
    try:
        data = await invesgo.get_top_movers(sort=sort_type, limit=20)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/financial/{ticker}")
async def get_financial_endpoint(ticker: str):
    try:
        data = await invesgo.get_financial_statement(ticker)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── IDX PATTERN CALIBRATION ─────────────────────────────────────────────────
@router.post("/data/calibrate-patterns")
async def calibrate_patterns():
    """
    Sliding-window backtest over MSCI_LQ45_INTERSECTION OHLCV data.
    Recalculates IDX_CALIBRATION multipliers vs Bulkowski US baseline.
    Run after accumulating sufficient historical OHLCV in PostgreSQL.
    """
    try:
        from app.engines.idx_calibration import run_backtest_calibration
        result = await run_backtest_calibration()
        return result
    except Exception as e:
        import traceback
        logger.error(f"calibrate-patterns error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, detail=f"{type(e).__name__}: {str(e)}")

# ============ FOREIGN FLOW DASHBOARD ============
LQ45_STOCKS = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BYAN","GOTO","UNVR",
    "ICBP","INDF","ANTM","PTBA","ADRO","ESSA","SMGR","PGAS",
    "EXCL","KLBF","MAPI","SIDO"
]

# Broker asing yang dikenal di IDX
FOREIGN_BROKERS = {
    "YP":"Indo Premier","BK":"J.P Morgan","RX":"Macquarie",
    "ZP":"Kim Eng","AK":"UBS","CC":"Mandiri","DB":"Deutsche",
    "MS":"Morgan Stanley","CS":"Credit Suisse","ML":"Merrill Lynch",
    "DP":"DBS Vickers","KI":"Citi","OD":"Mirae","LG":"Trimegah"
}

@router.get("/foreign-flow")
async def get_foreign_flow_dashboard():
    import asyncio
    from app.core import invesgo

    async def fetch_broker(ticker):
        try:
            data = await invesgo.get_broker_summary(ticker)
            return ticker, data
        except:
            return ticker, []

    # Fetch 10 saham LQ45 terbesar secara parallel
    tasks = [fetch_broker(t) for t in LQ45_STOCKS[:10]]
    results = await asyncio.gather(*tasks)

    stocks = []
    total_foreign_buy = 0
    total_foreign_sell = 0

    for ticker, brokers in results:
        if not brokers:
            continue

        # Filter broker asing
        foreign_net = 0
        foreign_buy = 0
        foreign_sell = 0
        top_foreign = []

        for b in brokers:
            code = b.get("code","")
            if code in FOREIGN_BROKERS:
                net = float(b.get("net_value",0) or 0)
                buy = float(b.get("buy_value",0) or 0)
                sell = float(b.get("sell_value",0) or 0)
                foreign_net += net
                foreign_buy += buy
                foreign_sell += sell
                top_foreign.append({
                    "broker": code,
                    "name": FOREIGN_BROKERS[code],
                    "net_value": net,
                    "buy_value": buy,
                    "sell_value": sell
                })

        # Sort by abs net value
        top_foreign.sort(key=lambda x: abs(x["net_value"]), reverse=True)

        total_foreign_buy += foreign_buy
        total_foreign_sell += foreign_sell

        stocks.append({
            "ticker": ticker,
            "foreign_net": round(foreign_net/1e9, 2),
            "foreign_buy": round(foreign_buy/1e9, 2),
            "foreign_sell": round(foreign_sell/1e9, 2),
            "signal": "BUY" if foreign_net > 0 else "SELL" if foreign_net < 0 else "NEUTRAL",
            "top_brokers": top_foreign[:3]
        })

    # Sort by foreign net
    stocks.sort(key=lambda x: x["foreign_net"], reverse=True)

    return {
        "status": "ok",
        "data": {
            "summary": {
                "total_foreign_buy": round(total_foreign_buy/1e9, 2),
                "total_foreign_sell": round(total_foreign_sell/1e9, 2),
                "total_net": round((total_foreign_buy-total_foreign_sell)/1e9, 2),
                "signal": "NET BUY" if total_foreign_buy > total_foreign_sell else "NET SELL"
            },
            "stocks": stocks,
            "universe": "LQ45 Top 10",
            "period": "30 hari terakhir"
        }
    }


# ============ DATA ACCUMULATION ============

DATA_WATCHLIST = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BYAN","GOTO","UNVR",
    "ICBP","INDF","ANTM","PTBA","ADRO","ESSA","SMGR","PGAS",
    "EXCL","KLBF","MAPI","SIDO","MDKA","AMMN","EMTK","BUKA",
    "ACES","MNCN","SCMA","LSIP","AALI","HRUM"
]

@router.post("/data/create-table")
async def create_ohlcv_table():
    try:
        async with _AsyncSessionLocal() as db:
            await db.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS ohlcv_daily (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    date DATE NOT NULL,
                    open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                    volume BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(ticker, date)
                )
            """))
            await db.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_daily(ticker, date)"))
            await db.commit()
        return {"status": "ok", "message": "Table ohlcv_daily ready"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@router.post("/data/accumulate")
async def accumulate_ohlcv():
    import asyncio as _asyncio
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    results = {"success": [], "failed": []}

    # Cari hari bursa valid — cek hari ini dulu, mundur max 7 hari
    import httpx as _httpx
    INVESGO_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImNtbnVmb2s2bTAwMDcxa21wM25lODlqanEiLCJlbWFpbCI6ImFndW5ndHJhZGVyY3VhbkBnbWFpbC5jb20iLCJ1c2VybmFtZSI6InNhbWJlcmN1YW4iLCJuYW1lIjoiQUdVTkciLCJyb2xlIjoiUFJJTUUiLCJzY29wZSI6WyJwdWJsaWMiXSwidmVyaWZpZWQiOmZhbHNlLCJkZXZpY2UiOiJBUEkiLCJpYXQiOjE3Nzg2MzI2MjYsImV4cCI6MTc4MTMzNjAzNX0.XgcvzxL_Y-JIxYpH6DxtRnz1N-eWnSVddLfMoUeGmfA"
    trade_date = None
    for days_back in range(0, 8):
        candidate_dt = _dt.now() - _td(days=days_back)
        candidate = candidate_dt.strftime("%Y-%m-%d")
        if candidate_dt.weekday() in (5, 6):
            continue
        try:
            async with _httpx.AsyncClient(timeout=10) as _client:
                _r = await _client.get(
                    "https://api.invesgo.id/analysis/chart/stock/BBCA",
                    headers={"Authorization": f"Bearer {INVESGO_TOKEN}"},
                    params={"from": candidate, "to": candidate}
                )
                _data = _r.json()
                if _data and len(_data) > 0 and float(_data[-1].get("close", 0)) > 0:
                    trade_date = candidate
                    break
        except:
            continue
    if not trade_date:
        trade_date = (_dt.now() - _td(days=4)).strftime("%Y-%m-%d")

    async def save_one(ticker):
        try:
            ohlcv = await _asyncio.wait_for(
                invesgo.get_ohlcv_daily(ticker, from_date=trade_date, to_date=trade_date),
                timeout=15
            )
            if not ohlcv:
                results["failed"].append({"ticker": ticker, "reason": "no data from Invesgo"})
                return

            # Ambil candle valid terakhir
            last = None
            for candle in reversed(ohlcv):
                if candle.get("close") and float(candle.get("close", 0)) > 0:
                    last = candle
                    break

            if not last:
                results["failed"].append({"ticker": ticker, "reason": "no valid candle"})
                return

            async with _AsyncSessionLocal() as db:
                await db.execute(sql_text("""
                    INSERT INTO ohlcv_daily (ticker, date, open, high, low, close, volume, created_at)
                    VALUES (:ticker, :date, :open, :high, :low, :close, :volume, NOW())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high,
                    low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume
                """), {
                    "ticker": ticker, "date": _dt.strptime(last.get("date", trade_date)[:10], "%Y-%m-%d").date(),
                    "open": float(last.get("open", 0) or 0),
                    "high": float(last.get("high", 0) or 0),
                    "low": float(last.get("low", 0) or 0),
                    "close": float(last.get("close", 0) or 0),
                    "volume": int(float(last.get("volume", 0) or 0)),
                })
                await db.commit()
            results["success"].append(ticker)
        except Exception as e:
            results["failed"].append({"ticker": ticker, "reason": str(e)[:200]})

    for i in range(0, len(DATA_WATCHLIST), 10):
        await _asyncio.gather(*[save_one(t) for t in DATA_WATCHLIST[i:i+10]])
        await _asyncio.sleep(1)

    return {"status": "ok", "date": today, "trade_date": trade_date, "success": len(results["success"]), "failed": len(results["failed"]), "details": results}

@router.get("/data/status")
async def ohlcv_status():
    try:
        async with _AsyncSessionLocal() as db:
            result = await db.execute(sql_text("""
                SELECT ticker, COUNT(*) as days, MIN(date) as from_date, MAX(date) as to_date
                FROM ohlcv_daily GROUP BY ticker ORDER BY days DESC LIMIT 20
            """))
            rows = result.fetchall()
        return {"status": "ok", "tickers": [{"ticker": r[0], "days": r[1], "from": str(r[2]), "to": str(r[3])} for r in rows], "total": len(rows)}
    except Exception as e:
        return {"status": "error", "error": str(e)}
