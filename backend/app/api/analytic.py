# ─── ANALYTIC ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _R, HTTPException
from pydantic import BaseModel
from app.core import invesgo
from app.engines.group1_runner import run_group1
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
        from app.engines.group1_runner import run_group1
        group1 = await run_group1("BBCA", ohlcv, "swing")
        results["step2_group1"] = f"OK score={group1['group_score']}"
    except Exception as e:
        return {"failed_at": "step2_group1", "error": str(e), "trace": traceback.format_exc()}
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
    return {"all_ok": True, "results": results}

class AnalyticRequest(BaseModel):
    ticker: str
    mode: str = "swing"

@router.post("/analyze")
async def analyze(req: AnalyticRequest):
    try:
        ohlcv = await invesgo.get_ohlcv_daily(req.ticker)
        if not ohlcv or len(ohlcv) < 20:
            raise HTTPException(400, "Insufficient OHLCV data")

        # Cast OHLCV ke float
        ohlcv = [{
            **c,
            "open":   float(c.get("open",   0) or 0),
            "high":   float(c.get("high",   0) or 0),
            "low":    float(c.get("low",    0) or 0),
            "close":  float(c.get("close",  0) or 0),
            "volume": float(c.get("volume", 0) or 0),
        } for c in ohlcv]
        group1 = await run_group1(req.ticker, ohlcv, req.mode)
        current = ohlcv[-1]["close"]
        score   = group1["group_score"]

        # Hitung SL/TP sederhana
        atr = _calc_atr(ohlcv)
        sl_mult = {"swing": 2.0, "daytrading": 1.5, "scalping": 1.0}.get(req.mode, 1.5)

        entry = current
        sl    = round(entry - atr * sl_mult, 0)
        tp1   = round(entry + atr * sl_mult * 1.5, 0)
        tp2   = round(entry + atr * sl_mult * 2.5, 0)
        tp3   = round(entry + atr * sl_mult * 4.0, 0)
        rr    = round((tp1 - entry) / (entry - sl), 2) if entry != sl else 0

        # ── RAG KB CONTEXT ──────────────────────────────────────────
        kb_context = ""
        try:
            analytic_engines = [
                "PriceActionEngine", "VolumeIntelligenceEngine",
                "BandarmologyEngine", "TrendStructureEngine",
                "RiskManagementEngine"
            ]
            kb_parts = []
            for eng in analytic_engines:
                ctx = await kb_service.get_kb_context_for_engine(eng, req.ticker)
                if ctx:
                    kb_parts.append(ctx)
            if kb_parts:
                kb_context = "\n\n=== REFERENSI KNOWLEDGE BASE ===\n" + "\n---\n".join(kb_parts[:4])
                logger.info(f"[RAG] Analytic {req.ticker}: {len(kb_parts)} KB contexts injected")
        except Exception as kb_err:
            logger.debug(f"[RAG] analytic skip: {kb_err}")
        # ────────────────────────────────────────────────────────────

        rationale = await ask_claude(
            system="Kamu adalah analis saham IDX profesional. Berikan analisis trading yang jelas dan actionable dalam Bahasa Indonesia.",
            prompt=f"""
Ticker: {req.ticker} | Mode: {req.mode}
Score: {score:.1f}/100 | Signal: {group1['consensus']}
Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
R:R = {rr}
Engine: {group1['bullish_count']} bullish, {group1['bearish_count']} bearish dari 10 engines
{kb_context}

Tulis analisis trading 3-4 kalimat dalam Bahasa Indonesia:
1. Kondisi market saat ini
2. Alasan entry dan level kunci
3. Manajemen risiko (SL/TP)
Jika ada referensi Knowledge Base di atas, gunakan insight tersebut untuk memperkuat analisis.
""",
            max_tokens=350
        )

        return {
            "ticker": req.ticker,
            "mode": req.mode,
            "entry": entry,
            "stop_loss": sl,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "rr_ratio": rr,
            "score": score,
            "confidence": min(95, score),
            "signal": group1["consensus"],
            "rationale": rationale,
            "engines": group1,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Analytic error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, detail=f"{type(e).__name__}: {str(e)}")

def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02
