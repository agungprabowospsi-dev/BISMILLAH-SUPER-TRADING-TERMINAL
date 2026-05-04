# ─── ANALYTIC ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _R, HTTPException
from pydantic import BaseModel
from app.core import invesgo
from app.engines.group1_runner import run_group1
from app.core.claude_client import ask_claude
import logging

logger = logging.getLogger(__name__)

router = _R()

class AnalyticRequest(BaseModel):
    ticker: str
    mode: str = "swing"

@router.post("/analyze")
async def analyze(req: AnalyticRequest):
    try:
        ohlcv = await invesgo.get_ohlcv_daily(req.ticker)
        if not ohlcv or len(ohlcv) < 20:
            raise HTTPException(400, "Insufficient OHLCV data")

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

        rationale = await ask_claude(
            system="You are a professional IDX stock analyst. Give clear, actionable trading analysis.",
            prompt=f"""
Ticker: {req.ticker} | Mode: {req.mode}
Score: {score:.1f}/100 | Signal: {group1['consensus']}
Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
R:R = {rr}
Engine summary: {group1['bullish_count']} bullish, {group1['bearish_count']} bearish of 10 engines

Write a 3-sentence trading analysis: market condition, entry rationale, risk management advice.
""",
            max_tokens=250
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
        logger.error(f"Analytic error: {e}")
        raise HTTPException(500, str(e))

def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02
