# enrichment/router.py
import os, logging, asyncio, json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.enrichment.data_fetcher import get_enrichment_ohlcv, EnrichmentDataError
from app.api.enrichment.smart_mfi import SmartMFI
from app.api.enrichment.kama_bands import KAMABands
from app.api.enrichment.lele_exhaustion import LeleExhaustion
from app.api.enrichment.divergence import DivergenceStateMachine
from app.core.redis_client import get_redis
from app.api.enrichment.wyckoff_phase import classify_wyckoff
from app.api.enrichment.weinstein_stage import classify_weinstein
from app.api.enrichment.vsa_engine import analyze_vsa

logger = logging.getLogger(__name__)
router = APIRouter()

ENRICHMENT_ENABLED  = os.environ.get("ENABLE_ENRICHMENT","true").lower() != "false"
MIN_BANDAR_SCORE    = 55.0

# ── Pydantic models ──────────────────────────────────────────────────────────

class SmartMFIResult(BaseModel):
    value:float; signal:str; above_thresh:bool
    threshold_bull:float; threshold_bear:float
    mfi_history:list; interpretation:str

class KAMABandsResult(BaseModel):
    basis:float; lower1:float; lower2:float; lower3:float
    upper1:float; upper2:float; upper3:float; current_price:float
    price_zone:str; entry_signal:str; band_width_pct:float; interpretation:str

class LeleResult(BaseModel):
    detected:bool; severity:str; count:int; bars_ago:int
    bullish_exhaust:bool; bearish_exhaust:bool; tp_signal:str; interpretation:str

class DivResult(BaseModel):
    state:str; div_type:Optional[str]; bars_ago:int
    oscillator_val:float; sl_action:str; cached:bool; interpretation:str

class BandarCtx(BaseModel):
    bandar_score:float; signal_tier:Optional[str]; phase_2b_active:bool
    sl_price:Optional[float]; tp1_price:Optional[float]
    gate_passed:bool; gate_reason:str

class EnrichSummary(BaseModel):
    bullish_count:int; warning_count:int; verdict:str; confidence:str
    rag_insight:Optional[str]; sl_final:Optional[float]
    entry_zone:Optional[str]; tp_strategy:str

class EnrichResponse(BaseModel):
    ticker:str; timestamp:str; enabled:bool
    bandar_context:BandarCtx; smart_mfi:SmartMFIResult
    kama_bands:KAMABandsResult; lele_exhaustion:LeleResult
    divergence:DivResult; summary:EnrichSummary

# ── Phase 2 Models ──────────────────────────────────────────────────────────

class WyckoffResult(BaseModel):
    phase: str; sub_event: str; confidence: float; implication: str
    phase_label: str; is_spring: bool; is_sos: bool
    is_upthrust: bool; is_distribution: bool
    support_level: float; resistance_level: float

class WeinsteinResult(BaseModel):
    stage: int; stage_name: str; ma30: float
    price_vs_ma: str; ma_slope: str
    volume_confirmation: bool; implication: str
    confidence: float; breakout_detected: bool
    breakdown_detected: bool; weeks_in_stage: int

class VSAResult(BaseModel):
    signal: str; background: str; strength: str
    tradeable: bool; description: str
    vol_ratio: float; spread_ratio: float; close_position: float

class Phase2Result(BaseModel):
    wyckoff: WyckoffResult
    weinstein: WeinsteinResult
    vsa: VSAResult
    phase2_verdict: str          # STRONG_BUY / BUY / HOLD / REDUCE / AVOID
    phase2_confidence: float
    phase2_summary: str

class EnrichResponseV2(BaseModel):
    ticker: str; timestamp: str; enabled: bool
    bandar_context: BandarCtx; smart_mfi: SmartMFIResult
    kama_bands: KAMABandsResult; lele_exhaustion: LeleResult
    divergence: DivResult; summary: EnrichSummary
    phase2: Optional[Phase2Result] = None

# ── Helper: Phase 2 ─────────────────────────────────────────────────────────

def _run_phase2(ohlcv: list) -> Phase2Result:
    """Jalankan 3 engine Phase 2 dari ohlcv list of dict"""
    try:
        opens   = [float(c.get("open",   0) or 0) for c in ohlcv]
        highs   = [float(c.get("high",   0) or 0) for c in ohlcv]
        lows    = [float(c.get("low",    0) or 0) for c in ohlcv]
        closes  = [float(c.get("close",  0) or 0) for c in ohlcv]
        volumes = [int(float(c.get("volume", 0) or 0)) for c in ohlcv]

        wyckoff  = classify_wyckoff(opens, highs, lows, closes, volumes)
        weinstein = classify_weinstein(closes, volumes)
        vsa      = analyze_vsa(opens, highs, lows, closes, volumes)

        # Phase 2 verdict synthesis
        buy_signals  = 0
        sell_signals = 0

        if wyckoff.implication in ("BUY",):         buy_signals  += 2
        if wyckoff.implication in ("EXIT","REDUCE"): sell_signals += 2
        if weinstein.implication in ("BUY",):        buy_signals  += 2
        if weinstein.implication in ("AVOID","EXIT"): sell_signals += 2
        if vsa.background == "BULLISH":              buy_signals  += 1
        if vsa.background == "BEARISH":              sell_signals += 1
        if vsa.signal in ("STOPPING_VOLUME","NO_SUPPLY","TEST"): buy_signals += 1
        if vsa.signal in ("UP_THRUST","NO_DEMAND"):  sell_signals += 1

        if buy_signals >= 4:
            verdict    = "STRONG_BUY"
            confidence = min(90.0, 60 + buy_signals * 5)
        elif buy_signals >= 2 and buy_signals > sell_signals:
            verdict    = "BUY"
            confidence = min(80.0, 50 + buy_signals * 5)
        elif sell_signals >= 4:
            verdict    = "AVOID"
            confidence = min(90.0, 60 + sell_signals * 5)
        elif sell_signals >= 2 and sell_signals > buy_signals:
            verdict    = "REDUCE"
            confidence = min(75.0, 50 + sell_signals * 5)
        else:
            verdict    = "HOLD"
            confidence = 50.0

        summary = (
            f"Wyckoff:{wyckoff.phase}({wyckoff.sub_event}) "
            f"Weinstein:Stage{weinstein.stage}({weinstein.stage_name}) "
            f"VSA:{vsa.signal}({vsa.background})"
        )

        return Phase2Result(
            wyckoff  = WyckoffResult(
                phase            = wyckoff.phase,
                sub_event        = wyckoff.sub_event,
                confidence       = wyckoff.confidence,
                implication      = wyckoff.implication,
                phase_label      = wyckoff.phase_label,
                is_spring        = wyckoff.is_spring,
                is_sos           = wyckoff.is_sos,
                is_upthrust      = wyckoff.is_upthrust,
                is_distribution  = wyckoff.is_distribution,
                support_level    = wyckoff.support_level,
                resistance_level = wyckoff.resistance_level,
            ),
            weinstein = WeinsteinResult(
                stage               = weinstein.stage,
                stage_name          = weinstein.stage_name,
                ma30                = weinstein.ma30,
                price_vs_ma         = weinstein.price_vs_ma,
                ma_slope            = weinstein.ma_slope,
                volume_confirmation = weinstein.volume_confirmation,
                implication         = weinstein.implication,
                confidence          = weinstein.confidence,
                breakout_detected   = weinstein.breakout_detected,
                breakdown_detected  = weinstein.breakdown_detected,
                weeks_in_stage      = weinstein.weeks_in_stage,
            ),
            vsa = VSAResult(
                signal        = vsa.signal,
                background    = vsa.background,
                strength      = vsa.strength,
                tradeable     = vsa.tradeable,
                description   = vsa.description,
                vol_ratio     = vsa.vol_ratio,
                spread_ratio  = vsa.spread_ratio,
                close_position = vsa.close_position,
            ),
            phase2_verdict    = verdict,
            phase2_confidence = confidence,
            phase2_summary    = summary,
        )
    except Exception as e:
        logger.error(f"Phase2 error: {e}")
        return None


# ── Helper: bandar context ───────────────────────────────────────────────────

async def _get_bandar_ctx(ticker: str) -> dict:
    try:
        redis = get_redis()
        # Coba ambil dari cache screener
        raw = await redis.get(f"analytic:{ticker}")
        if not raw:
            raw = await redis.get(f"screener:result:{ticker}")
        data = json.loads(raw) if raw else {}

        score = float(data.get("bandar_score") or data.get("score") or 0)
        tier  = "TIER_1" if score>=80 else "TIER_2" if score>=60 else "TIER_3"
        p2b   = bool(data.get("fase_2b_active") or data.get("early_detection_active"))
        gate  = score >= MIN_BANDAR_SCORE

        return {
            "bandar_score": round(score,1), "signal_tier": tier,
            "phase_2b_active": p2b,
            "sl_price":  data.get("sl_price"),
            "tp1_price": data.get("tp1_price"),
            "gate_passed": gate,
            "gate_reason": "OK" if gate else f"Score {score:.0f} < minimum {MIN_BANDAR_SCORE}",
        }
    except Exception as e:
        logger.warning(f"[{ticker}] bandar_ctx fallback: {e}")
        # Fallback: gate pass dengan score default supaya enrichment tetap jalan
        return {
            "bandar_score":70.0,"signal_tier":"TIER_2","phase_2b_active":False,
            "sl_price":None,"tp1_price":None,
            "gate_passed":True,"gate_reason":"Cache miss — gate bypass",
        }

# ── Helper: RAG query (hanya saat ada kontradiksi) ───────────────────────────

async def _rag_query(ticker, mfi_signal, kama_signal, div_state, lele_sev, score, p2b) -> Optional[str]:
    contradiction = (
        (mfi_signal=="BULLISH" and div_state in ["BEARISH_WARN","HIDDEN_BEAR"]) or
        (kama_signal=="IDEAL"  and lele_sev=="MAJOR") or
        (p2b and div_state=="BEARISH_WARN")
    )
    if not contradiction:
        return None
    try:
        from app.core.knowledge_base import query_knowledge_base
        q = (f"Saham {ticker} score {score:.0f}. MFI:{mfi_signal} KAMA:{kama_signal} "
             f"Div:{div_state} Lele:{lele_sev}. Apakah valid entry menurut Larry Harris dan Tom Williams?")
        result = await query_knowledge_base(q, top_k=2)
        ans = (result or {}).get("answer","")
        return ans[:280] if ans else None
    except Exception as e:
        logger.debug(f"RAG skip: {e}")
        return None

# ── Helper: verdict ──────────────────────────────────────────────────────────

def _verdict(mfi, kama, lele, div, ctx, rag) -> dict:
    bull = warn = 0

    if mfi["signal"]=="BULLISH" and mfi["above_thresh"]: bull+=1
    elif mfi["signal"]=="BEARISH": warn+=1

    if kama["entry_signal"] in ("IDEAL","CONSERVATIVE"): bull+=1
    elif kama["entry_signal"] in ("INVALIDATED","OVERBOUGHT"): warn+=1

    if not lele["detected"]: bull+=1
    elif lele["severity"]=="MAJOR": warn+=2
    elif lele["severity"]=="MINOR": warn+=1

    ds = div["state"]
    if ds in ("CLEAR","BULLISH_DIV","HIDDEN_BULL"): bull+=1
    elif ds=="BEARISH_WARN": warn+=2
    elif ds=="HIDDEN_BEAR":  warn+=1

    # VETO: divergence bearish segar
    if ds=="BEARISH_WARN" and div["bars_ago"]<=3:
        verdict = "SKIP"; confidence = "HIGH"
    elif warn>=3: verdict="SKIP"; confidence="HIGH"
    elif warn==2: verdict="CAUTION"; confidence="LOW"
    elif warn<=1: verdict="PROCEED"; confidence="MEDIUM"
    else: verdict="CAUTION"; confidence="LOW"

    # Confidence upgrade
    p2b  = ctx.get("phase_2b_active",False)
    tier = ctx.get("signal_tier","TIER_2")
    if verdict=="PROCEED" and bull==4 and tier=="TIER_1": confidence="VERY_HIGH"
    elif verdict=="PROCEED" and bull>=3 and p2b: confidence="HIGH"

    # Entry zone
    entry_zone = None
    if verdict!="SKIP":
        sig = kama.get("entry_signal","")
        if sig=="IDEAL":        entry_zone=f"{kama['lower1']:,.0f} – {kama['lower2']:,.0f}"
        elif sig=="CONSERVATIVE": entry_zone=f"{kama['lower2']:,.0f} – {kama['lower3']:,.0f}"

    # SL final
    sl_base = ctx.get("sl_price")
    sl_final = (round(float(sl_base)*1.01,0) if sl_base and div["sl_action"]=="TIGHTEN"
                else sl_base)

    return {
        "bullish_count":bull,"warning_count":warn,"verdict":verdict,
        "confidence":confidence,"rag_insight":rag,"sl_final":sl_final,
        "entry_zone":entry_zone,"tp_strategy":lele.get("tp_signal","NO_ACTION"),
    }

# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/{ticker}", response_model=EnrichResponse)
async def get_enrichment(ticker: str):
    ticker = ticker.upper().strip()

    if not ENRICHMENT_ENABLED:
        raise HTTPException(503, "Enrichment disabled")

    logger.info(f"[{ticker}] Enrichment request")

    ctx = await _get_bandar_ctx(ticker)

    # Ambil OHLCV
    try:
        ohlcv = await get_enrichment_ohlcv(ticker)
    except EnrichmentDataError as e:
        raise HTTPException(422, str(e))

    # 4 engine paralel
    mfi_e  = SmartMFI()
    kama_e = KAMABands()
    lele_e = LeleExhaustion()
    div_e  = DivergenceStateMachine()
    redis  = get_redis()

    mfi_r, kama_r, lele_r, div_r = await asyncio.gather(
        asyncio.to_thread(mfi_e.compute,  ohlcv),
        asyncio.to_thread(kama_e.compute, ohlcv),
        asyncio.to_thread(lele_e.compute, ohlcv),
        div_e.compute(ohlcv, redis, ticker),
    )

    # RAG hanya saat kontradiksi
    rag = await _rag_query(
        ticker, mfi_r["signal"], kama_r["entry_signal"],
        div_r["state"], lele_r["severity"],
        ctx["bandar_score"], ctx["phase_2b_active"],
    )

    summary = _verdict(mfi_r, kama_r, lele_r, div_r, ctx, rag)

    # Phase 2 — Wyckoff + Weinstein + VSA
    phase2 = await asyncio.to_thread(_run_phase2, ohlcv)

    logger.info(f"[{ticker}] verdict={summary['verdict']} bull={summary['bullish_count']} warn={summary['warning_count']} phase2={phase2.phase2_verdict if phase2 else 'N/A'}")

    return EnrichResponseV2(
        ticker=ticker,
        timestamp=datetime.now(timezone.utc).isoformat(),
        enabled=True,
        bandar_context=BandarCtx(**ctx),
        smart_mfi=SmartMFIResult(**mfi_r),
        kama_bands=KAMABandsResult(**kama_r),
        lele_exhaustion=LeleResult(**lele_r),
        divergence=DivResult(**div_r),
        summary=EnrichSummary(**summary),
        phase2=phase2,
    )
