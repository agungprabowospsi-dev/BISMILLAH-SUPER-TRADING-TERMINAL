import uuid
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
from app.core import invesgo
from app.core.redis_client import cache_get, cache_set
from app.engines.group1_runner import run_group1
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class ScreenerRequest(BaseModel):
    mode: str = "swing"  # swing | daytrading | scalping
    filters: Optional[dict] = {}

@router.post("/run")
async def run_screener(req: ScreenerRequest):
    session_id = str(uuid.uuid4())[:8]
    cache_key = f"screener:{req.mode}:{session_id}"

    try:
        # Ambil daftar saham
        stocks = await invesgo.get_stock_list()
        if not stocks:
            raise HTTPException(500, "Failed to fetch stock list")

        # Pre-filter: ambil 50 saham terlikuid saja dulu
        tickers = [s.get("code", s.get("ticker","")) for s in stocks[:50]]

        # Analisis paralel (batch 10)
        results = []
        for i in range(0, min(len(tickers), 30), 10):
            batch = tickers[i:i+10]
            batch_tasks = [_analyze_stock(t, req.mode) for t in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, dict) and "score" in r:
                    results.append(r)

        # Sort by score, ambil top 5
        top5 = sorted(results, key=lambda x: x["score"], reverse=True)[:5]

        response = {
            "session_id": session_id,
            "mode": req.mode,
            "top5_stocks": top5,
            "total_scanned": len(results),
        }

        await cache_set(cache_key, json.dumps(response), ttl=300)
        return response

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
        group1 = await run_group1(ticker, ohlcv, mode)
        return {
            "ticker": ticker,
            "score": group1["group_score"],
            "signal": group1["consensus"],
            "market_structure": group1,
        }
    except:
        return {}
