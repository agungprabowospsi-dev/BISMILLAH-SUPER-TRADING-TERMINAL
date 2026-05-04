import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

INVESGO_BASE_URL = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
INVESGO_API_KEY = os.environ["INVESGO_API_KEY"]

def _headers():
    return {
        "Authorization": f"Bearer {INVESGO_API_KEY}",
        "Content-Type": "application/json"
    }

async def get_stock_list() -> list:
    """Ambil semua saham IDX"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/stocks", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_ohlcv_daily(ticker: str, period: str = "1y") -> list:
    """OHLCV harian"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/stocks/{ticker}/ohlcv",
            headers=_headers(),
            params={"period": period, "interval": "1d"}
        )
        r.raise_for_status()
        return r.json()

async def get_ohlcv_intraday(ticker: str, interval: str = "5m") -> list:
    """OHLCV intraday"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/stocks/{ticker}/ohlcv",
            headers=_headers(),
            params={"interval": interval, "period": "5d"}
        )
        r.raise_for_status()
        return r.json()

async def get_orderbook(ticker: str) -> dict:
    """Orderbook bid/ask"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/stocks/{ticker}/orderbook", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_broker_summary(ticker: str) -> dict:
    """Broker summary untuk bandarmology"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/stocks/{ticker}/broker-summary", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_foreign_flow(ticker: str) -> dict:
    """Net foreign buy/sell"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/stocks/{ticker}/foreign-flow", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_tick(ticker: str) -> dict:
    """Tick data realtime"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/stocks/{ticker}/tick", headers=_headers())
        r.raise_for_status()
        return r.json()
