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

    logger.info(f"[{ticker}] verdict={summary['verdict']} bull={summary['bullish_count']} warn={summary['warning_count']}")

    return EnrichResponse(
        ticker=ticker,
        timestamp=datetime.now(timezone.utc).isoformat(),
        enabled=True,
        bandar_context=BandarCtx(**ctx),
        smart_mfi=SmartMFIResult(**mfi_r),
        kama_bands=KAMABandsResult(**kama_r),
        lele_exhaustion=LeleResult(**lele_r),
        divergence=DivResult(**div_r),
        summary=EnrichSummary(**summary),
    )
