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
    """Fetch 4 box data: foreign flow, broker, company info, orderbook"""
    import traceback
    import json as _json

    class NumpyEncoder(_json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.bool_): return bool(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    result = {}

    # Box 1: Tick/realtime price
    try:
        tick = await invesgo.get_tick(ticker)
        result["tick"] = {
            "last_price": tick.get("last_price") or tick.get("close") or 0,
            "change": tick.get("change") or 0,
            "change_pct": tick.get("change_pct") or tick.get("pct") or 0,
            "volume": tick.get("volume") or 0,
            "value": tick.get("value") or 0,
            "freq": tick.get("freq") or 0,
        }
    except Exception as e:
        result["tick"] = {"error": str(e)}

    # Box 2: Foreign flow
    try:
        ff = await invesgo.get_foreign_flow(ticker)
        result["foreign_flow"] = {
            "foreign_buy": ff.get("foreign_buy") or ff.get("foreign") or 0,
            "foreign_sell": ff.get("foreign_sell") or 0,
            "foreign_net": ff.get("foreign_net") or ff.get("net_foreign") or 0,
            "bdm_buy": ff.get("bdm_buy") or ff.get("bdm") or 0,
            "bdm_sell": ff.get("bdm_sell") or 0,
            "ritel_buy": ff.get("ritel_buy") or ff.get("ritel") or 0,
        }
    except Exception as e:
        result["foreign_flow"] = {"error": str(e)}

    # Box 3: Company info
    try:
        info = await invesgo.get_company_info(ticker)
        result["company"] = {
            "name": info.get("company_name") or info.get("name") or ticker,
            "sector": info.get("sector") or "-",
            "market_cap": info.get("market_cap") or 0,
            "pe_ratio": info.get("pe_ratio") or info.get("per") or 0,
            "pbv": info.get("pbv") or 0,
            "dividend_yield": info.get("dividend_yield") or 0,
        }
    except Exception as e:
        result["company"] = {"error": str(e)}

    # Box 4: Orderbook
    try:
        ob = await invesgo.get_orderbook(ticker)
        bids = ob.get("bids") or ob.get("bid") or []
        asks = ob.get("asks") or ob.get("offer") or []
        best_bid = bids[0] if bids else {}
        best_ask = asks[0] if asks else {}
        result["orderbook"] = {
            "best_bid_price": best_bid.get("price") or best_bid.get("p") or 0,
            "best_bid_vol": best_bid.get("volume") or best_bid.get("v") or 0,
            "best_ask_price": best_ask.get("price") or best_ask.get("p") or 0,
            "best_ask_vol": best_ask.get("volume") or best_ask.get("v") or 0,
            "total_bid": sum(b.get("volume", b.get("v", 0)) for b in bids[:5]),
            "total_ask": sum(a.get("volume", a.get("v", 0)) for a in asks[:5]),
        }
    except Exception as e:
        result["orderbook"] = {"error": str(e)}

    return JSONResponse(content=_json.loads(_json.dumps(result, cls=NumpyEncoder)))


def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02
