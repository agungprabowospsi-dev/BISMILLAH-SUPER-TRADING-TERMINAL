# ─── ANALYTIC ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _R, HTTPException
from fastapi.responses import JSONResponse
import numpy as np
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
        all_engines = await run_all_engines(req.ticker, ohlcv, req.mode)
        current = ohlcv[-1]["close"]
        score   = all_engines["composite_score"]

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
Score: {score:.1f}/100 | Signal: {all_engines['signal']}
Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
R:R = {rr}
Engine: {all_engines.get('bullish_count', 0)} bullish, {all_engines.get('bearish_count', 0)} bearish dari 10 engines
{kb_context}

Tulis analisis trading 3-4 kalimat dalam Bahasa Indonesia:
1. Kondisi market saat ini
2. Alasan entry dan level kunci
3. Manajemen risiko (SL/TP)
Jika ada referensi Knowledge Base di atas, gunakan insight tersebut untuk memperkuat analisis.
""",
            max_tokens=350
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
            "rationale": rationale,
            "engines": all_engines,
        }
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
    import json as _json

    class NumpyEncoder(_json.JSONEncoder):
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

    return JSONResponse(content=_json.loads(_json.dumps(result, cls=NumpyEncoder)))


def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02
