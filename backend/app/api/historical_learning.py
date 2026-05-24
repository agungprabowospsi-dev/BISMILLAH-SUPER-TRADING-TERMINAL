import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.ml.historical_learning import (
    build_ticker_memory,
    ensure_historical_tables,
    get_empirical_context,
    get_learning_status,
    mine_empirical_patterns,
    sync_many,
    sync_ticker_history,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/historical-learning", tags=["historical_learning"])


class HistoricalSyncRequest(BaseModel):
    tickers: List[str] = Field(default_factory=list)
    years: int = Field(default=15, ge=1, le=15)
    force: bool = False
    concurrency: int = Field(default=3, ge=1, le=6)
    learn_after_sync: bool = True
    mode: str = "swing"


class LearnRequest(BaseModel):
    ticker: str
    mode: str = "swing"
    years: int = Field(default=15, ge=1, le=15)


def _redis():
    from app.core.redis_client import get_redis
    return get_redis()


async def _save_job(job_id: str, data: dict):
    try:
        await _redis().setex(f"historical_learning:{job_id}", 86400, json.dumps(data))
    except Exception as exc:
        logger.warning(f"historical learning job save failed: {exc}")


async def _get_job(job_id: str):
    try:
        raw = await _redis().get(f"historical_learning:{job_id}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _run_sync_job(job_id: str, req: HistoricalSyncRequest):
    tickers = [t.upper().strip() for t in req.tickers if t.strip()]
    await _save_job(job_id, {
        "status": "running",
        "progress": 5,
        "message": f"Starting 15-year historical sync for {len(tickers)} tickers",
        "started_at": datetime.now().isoformat(),
    })
    try:
        await ensure_historical_tables()
        results = await sync_many(tickers, years=req.years, force=req.force, concurrency=req.concurrency)
        learned = []
        if req.learn_after_sync:
            for idx, item in enumerate(results):
                ticker = item.get("ticker")
                await _save_job(job_id, {
                    "status": "running",
                    "progress": 60 + int((idx / max(len(results), 1)) * 30),
                    "message": f"Building empirical memory for {ticker}",
                    "sync_results": results,
                    "learned": learned,
                })
                if item.get("status") in ("synced", "cached") and ticker:
                    learned.append(await build_ticker_memory(ticker, mode=req.mode, years=req.years))
        mined = await mine_empirical_patterns(req.mode)
        await _save_job(job_id, {
            "status": "done",
            "progress": 100,
            "message": "Historical learning job complete",
            "sync_results": results,
            "learned": learned,
            "mined": mined,
            "finished_at": datetime.now().isoformat(),
        })
    except Exception as exc:
        await _save_job(job_id, {
            "status": "error",
            "progress": 100,
            "message": str(exc),
            "finished_at": datetime.now().isoformat(),
        })


@router.post("/ensure")
async def ensure_tables():
    await ensure_historical_tables()
    return {"status": "ok", "message": "historical learning tables ready"}


@router.get("/status")
async def status(limit: int = 25):
    return {"status": "ok", **await get_learning_status(limit=limit)}


@router.post("/sync")
async def sync_history(req: HistoricalSyncRequest, background_tasks: BackgroundTasks):
    if not req.tickers:
        return {"status": "error", "message": "tickers is required"}
    job_id = str(uuid.uuid4())[:8]
    await _save_job(job_id, {"status": "queued", "progress": 0, "message": "queued"})
    background_tasks.add_task(_run_sync_job, job_id, req)
    return {
        "status": "queued",
        "job_id": job_id,
        "status_url": f"/api/historical-learning/jobs/{job_id}",
    }


@router.get("/jobs/{job_id}")
async def job_status(job_id: str):
    data = await _get_job(job_id)
    return data or {"status": "not_found", "job_id": job_id}


@router.post("/sync/{ticker}")
async def sync_one(ticker: str, years: int = 15, force: bool = False):
    await ensure_historical_tables()
    return await sync_ticker_history(ticker.upper(), years=years, force=force)


@router.post("/learn")
async def learn(req: LearnRequest):
    return await build_ticker_memory(req.ticker.upper(), mode=req.mode, years=req.years)


@router.post("/mine")
async def mine(mode: str = "swing", min_samples: int = 30):
    return await mine_empirical_patterns(mode=mode, min_samples=min_samples)


@router.get("/context/{ticker}")
async def context(ticker: str, mode: str = "swing"):
    return await get_empirical_context(ticker.upper(), mode=mode)
