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

async def get_ohlcv_daily(ticker: str, period: str = "3mo", from_date: str = None, to_date: str = None) -> list:
    """OHLCV harian - support period atau from/to date"""
    from datetime import datetime, timedelta
    if from_date and to_date:
        params = {"from": from_date, "to": to_date}
    else:
        # Convert period ke from/to date
        today = datetime.now().strftime("%Y-%m-%d")
        period_map = {
            "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "3y": 1095,
            "5y": 1825, "10y": 3650, "15y": 5475
        }
        days = period_map.get(period, 90)
        from_dt = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        params = {"from": from_dt, "to": today}
    
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/chart/stock/{ticker}",
            headers=_headers(),
            params=params
        )
        r.raise_for_status()
        return r.json()

async def get_ohlcv_intraday(ticker: str, market: str = "RG") -> dict:
    """OHLCV intraday + bid/ask real"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/intraday-data/{ticker}",
            headers=_headers(),
            params={"market": market}
        )
        r.raise_for_status()
        return r.json()

async def get_orderbook(ticker: str) -> dict:
    """Orderbook bid/ask"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/order-book/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_broker_summary(ticker: str, investor: str = "all", market: str = "RG") -> list:
    """Broker net buy/sell real dari BEI"""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/summary/stock/{ticker}",
            headers=_headers(),
            params={"from": from_date, "to": today, "investor": investor, "market": market}
        )
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
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}",
            headers=_headers(),
            params={"date": today}
        )
        r.raise_for_status()
        return r.json()


async def get_ksei_ownership(ticker: str, range_months: int = 3) -> list:
    """KSEI ownership data - foreign vs retail"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/shareholder/ksei/{ticker}",
            headers=_headers(),
            params={"range": range_months}
        )
        r.raise_for_status()
        return r.json()
async def get_sector_rotation() -> dict:
    """Sector rotation"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/sector/rotation", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_market_summary() -> dict:
    """Market summary / IHSG"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/market/summary", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_top_gainer() -> list:
    """Top gainer saham IDX"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/market/top-gainer", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_top_loser() -> list:
    """Top loser saham IDX"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/market/top-loser", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_chart_composite() -> list:
    """IHSG composite chart"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/chart/composite", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_foreign_net() -> list:
    """Net foreign buy/sell list"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/market/foreign-net", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_market_context(ticker: str) -> dict:
    """Harga realtime + company info dari market-context endpoint"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{INVESGO_BASE_URL}/analysis/market-context/{ticker}",
                headers=_headers()
            )
            if r.status_code == 200:
                return r.json()
    except:
        pass
    # Fallback: pakai price-table
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{INVESGO_BASE_URL}/analysis/chart/stock/{ticker}",
                headers=_headers(),
                params={"period": "1d"}
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    last = data[-1]
                    return {"price": {"last": last.get("close"), "high": last.get("high"), "low": last.get("low")}}
    except:
        pass
    return {}
