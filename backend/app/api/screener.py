import uuid
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
from app.core import invesgo
from app.core.redis_client import cache_get, cache_set
from app.engines.group1_runner import run_group1
from app.engines.smart_money_engines import BandarmologyEngine
from app.knowledge_base import kb_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

_bandarmology = BandarmologyEngine()

class ScreenerRequest(BaseModel):
    mode: str = "swing"
    filters: Optional[dict] = {}

@router.get("/market-overview")
async def market_overview():
    """IHSG proxy + sector rotation"""
    result = {}

    # Sector rotation
    try:
        sectors = await invesgo.get_sector_rotation()
        if isinstance(sectors, list) and sectors:
            sorted_s = sorted(sectors, key=lambda x: float(x.get("change_pct") or x.get("pct") or 0), reverse=True)
            result["sectors"] = [{"name": s.get("sector") or s.get("name") or "-",
                "change_pct": round(float(s.get("change_pct") or s.get("pct") or 0), 2),
                "signal": "UP" if float(s.get("change_pct") or s.get("pct") or 0) > 0 else "DOWN"
            } for s in sorted_s[:10]]
            result["strongest"] = result["sectors"][0] if result["sectors"] else {}
            result["weakest"] = result["sectors"][-1] if result["sectors"] else {}
        else:
            result["sectors"] = []
            result["sectors_raw"] = str(sectors)[:200]
    except Exception as e:
        result["sectors"] = []
        result["sector_error"] = str(e)[:100]

    # Market proxy dari blue chip
    try:
        changes = []
        for ticker in ["BBCA","BBRI","TLKM","ASII","BMRI"]:
            try:
                ohlcv = await invesgo.get_ohlcv_daily(ticker)
                if ohlcv and len(ohlcv) >= 2:
                    last = float(ohlcv[-1].get("close",0) or 0)
                    prev = float(ohlcv[-2].get("close",0) or 0)
                    if prev > 0: changes.append((last-prev)/prev*100)
            except: pass
        avg = round(sum(changes)/len(changes), 2) if changes else 0
        result["market"] = {
            "proxy": "Blue Chip IDX",
            "avg_change_pct": avg,
            "sentiment": "BULLISH" if avg > 0.3 else "BEARISH" if avg < -0.3 else "SIDEWAYS",
        }
    except Exception as e:
        result["market"] = {"error": str(e)[:100]}

    return result


@router.post("/run")
async def run_screener(req: ScreenerRequest):
    session_id = str(uuid.uuid4())[:8]
    cache_key = f"screener:{req.mode}:{session_id}"

    try:
        stocks = await invesgo.get_stock_list()
        if not stocks:
            raise HTTPException(500, "Failed to fetch stock list")

        tickers = []
        for s in stocks:
            code = s.get("code", "")
            if code and "-" not in code and len(code) <= 6:
                tickers.append(code)

        logger.info(f"Screener: {len(tickers)} tickers akan di-scan")

        results = []
        # Batch 20 paralel untuk lebih cepat
        for i in range(0, len(tickers), 20):
            batch = tickers[i:i+20]
            batch_tasks = [
                asyncio.wait_for(_analyze_stock(t, req.mode), timeout=15.0)
                for t in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, dict) and r.get("score", 0) > 0:
                    results.append(r)
            logger.info(f"Progress: {min(i+20, len(tickers))}/{len(tickers)} scanned, {len(results)} valid")

        filtered = [r for r in results if r["score"] > 55]
        top5 = sorted(filtered, key=lambda x: x["score"], reverse=True)[:5]

        response = {
            "session_id": session_id,
            "mode": req.mode,
            "top5_stocks": top5,
            "total_scanned": len(results),
            "total_tickers": len(tickers),
        }

        await cache_set(cache_key, json.dumps(response), ttl=300)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Screener error: {e}")
        raise HTTPException(500, str(e))

@router.get("/results/{session_id}")
async def get_results(session_id: str):
    for mode in ["swing", "daytrading", "scalping"]:
        data = await cache_get(f"screener:{mode}:{session_id}")
        if data:
            return json.loads(data)
    raise HTTPException(404, "Session not found")

async def _analyze_stock(ticker: str, mode: str) -> dict:
    try:
        ohlcv = await invesgo.get_ohlcv_daily(ticker)
        if not ohlcv or len(ohlcv) < 20:
            return {}

        ohlcv_fixed = [{**c, "volume": float(c.get("volume", 0))} for c in ohlcv]
        group1_task = run_group1(ticker, ohlcv_fixed, mode)
        bandarm_task = _bandarmology.analyze(ticker, ohlcv_fixed, mode)
        group1, bandarm = await asyncio.gather(group1_task, bandarm_task, return_exceptions=True)

        group1_score = group1.get("group_score", 0) if isinstance(group1, dict) else 0
        bandarm_score = bandarm.score if hasattr(bandarm, "score") else 40.0
        bandarm_phase = bandarm.data.get("phase", "unknown") if hasattr(bandarm, "data") else "unknown"

        kb_boost = 0.0
        kb_context_summary = ""
        try:
            screener_engines = ["VolumeIntelligenceEngine","BandarmologyEngine","TrendStructureEngine","FibonacciEngine","LiquidityQualityEngine"]
            kb_contexts = []
            for eng in screener_engines:
                ctx = await kb_service.get_kb_context_for_engine(eng, ticker)
                if ctx:
                    kb_contexts.append(ctx)
            if kb_contexts:
                kb_boost = min(4.5, len(kb_contexts) * 1.5)
                kb_context_summary = f"{len(kb_contexts)} KB refs"
        except Exception as kb_err:
            logger.debug(f"[RAG] KB skip {ticker}: {kb_err}")

        base_score = min(100.0, (group1_score * 0.70) + (bandarm_score * 0.30))
        final_score = round(min(100.0, base_score + kb_boost), 2)
        consensus = group1.get("consensus", "neutral") if isinstance(group1, dict) else "neutral"

        if final_score > 65 and consensus == "bullish" and bandarm_phase in ["accumulation", "early_accumulation"]:
            signal = "BUY"
        elif final_score < 35 or bandarm_phase == "distribution":
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        closes = []
        for candle in ohlcv:
            if isinstance(candle, dict):
                c = candle.get("close") or candle.get("c") or candle.get("Close")
                if c:
                    closes.append(float(c))
        last_price = closes[-1] if closes else 0

        return {
            "ticker": ticker,
            "score": final_score,
            "signal": signal,
            "last_price": last_price,
            "consensus": consensus,
            "bandarm_phase": bandarm_phase,
            "bandarm_score": round(bandarm_score, 2),
            "group1_score": round(group1_score, 2),
            "kb_boost": kb_boost,
            "kb_context": kb_context_summary,
            "bullish_engines": group1.get("bullish_count", 0) if isinstance(group1, dict) else 0,
            "bearish_engines": group1.get("bearish_count", 0) if isinstance(group1, dict) else 0,
        }
    except asyncio.TimeoutError:
        logger.debug(f"Timeout: {ticker}")
        return {}
    except Exception as e:
        logger.debug(f"Skip {ticker}: {e}")
        return {}
