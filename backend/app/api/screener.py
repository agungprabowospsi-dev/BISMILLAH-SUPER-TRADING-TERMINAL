import uuid
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
from app.core import invesgo
from app.core.redis_client import cache_get, cache_set
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class ScreenerRequest(BaseModel):
    mode: str = "swing"
    filters: Optional[dict] = {}

@router.post("/run")
async def run_screener(req: ScreenerRequest):
    session_id = str(uuid.uuid4())[:8]
    cache_key = f"screener:{req.mode}:{session_id}"

    try:
        stocks = await invesgo.get_stock_list()
        if not stocks:
            raise HTTPException(500, "Failed to fetch stock list")

        tickers = []
        for s in stocks[:100]:
            code = s.get("code", "")
            if code and "-" not in code:
                tickers.append(code)

        tickers = tickers[:30]
        results = []

        for i in range(0, len(tickers), 10):
            batch = tickers[i:i+10]
            batch_tasks = [_analyze_stock(t, req.mode) for t in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, dict) and r.get("score", 0) > 0:
                    results.append(r)

        top5 = sorted(results, key=lambda x: x["score"], reverse=True)[:5]

        response = {
            "session_id": session_id,
            "mode": req.mode,
            "top5_stocks": top5,
            "total_scanned": len(results),
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

        closes = []
        for candle in ohlcv:
            if isinstance(candle, dict):
                c = candle.get("close") or candle.get("c") or candle.get("Close")
                if c:
                    closes.append(float(c))

        if len(closes) < 20:
            return {}

        score = _calculate_score(closes, mode)

        return {
            "ticker": ticker,
            "score": score,
            "signal": "BUY" if score > 60 else "NEUTRAL",
            "last_price": closes[-1],
        }
    except Exception as e:
        logger.debug(f"Skip {ticker}: {e}")
        return {}

def _calculate_score(closes: list, mode: str) -> float:
    score = 0.0
    try:
        ma20 = sum(closes[-20:]) / 20
        ma5 = sum(closes[-5:]) / 5
        last = closes[-1]

        if last > ma20:
            score += 30
        if ma5 > ma20:
            score += 20
        if last > closes[-2]:
            score += 10

        change = (last - closes[-20]) / closes[-20] * 100
        if mode == "swing" and 2 < change < 15:
            score += 20
        elif mode == "daytrading" and 0.5 < change < 5:
            score += 20
        elif mode == "scalping" and change > 0:
            score += 20

        if last > 0:
            score += 20
    except:
        pass

    return round(score, 2)
