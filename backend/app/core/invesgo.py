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
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/list/stock", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_ohlcv_daily(ticker: str, period: str = "1y") -> list:
    """OHLCV harian"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/chart/stock/{ticker}",
            headers=_headers(),
            params={"period": period}
        )
        r.raise_for_status()
        return r.json()

async def get_ohlcv_intraday(ticker: str, interval: str = "5m") -> list:
    """OHLCV intraday"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/intraday-data/{ticker}",
            headers=_headers()
        )
        r.raise_for_status()
        return r.json()

async def get_orderbook(ticker: str) -> dict:
    """Orderbook bid/ask"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/order-book/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_broker_summary(ticker: str) -> dict:
    """Broker summary"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/inventory-chart/stock/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_foreign_flow(ticker: str) -> dict:
    """Net foreign buy/sell - dari price table"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_tick(ticker: str) -> dict:
    """Tick data realtime - dari price table"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_company_info(ticker: str) -> dict:
    """Info perusahaan"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/information/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_price_table(ticker: str) -> dict:
    """Price table"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_sector_rotation() -> dict:
    """Sector rotation"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/sector/rotation", headers=_headers())
        r.raise_for_status()
        return r.json()
