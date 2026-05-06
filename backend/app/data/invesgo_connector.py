import os
import httpx
import logging

logger = logging.getLogger(__name__)

INVESGO_BASE_URL = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
INVESGO_API_KEY = os.environ.get("INVESGO_API_KEY", "")

def _headers():
    return {
        "Authorization": f"Bearer {INVESGO_API_KEY}",
        "Content-Type": "application/json"
    }

async def _get(path: str, params: dict = None):
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{INVESGO_BASE_URL}{path}"
        logger.info(f"InvesGo GET: {url}")
        r = await client.get(url, headers=_headers(), params=params)
        if r.status_code != 200:
            logger.error(f"InvesGo API error {r.status_code}: {path}")
            raise Exception(f"InvesGo API error {r.status_code}: {path}")
        return r.json()

async def get_stock_list() -> list:
    data = await _get("/analysis/list/stock")
    if isinstance(data, list):
        return data
    return data.get("data", [])

async def get_ohlcv_daily(ticker: str, period: str = "1y") -> list:
    data = await _get(f"/analysis/chart/stock/{ticker}", {"period": period})
    if isinstance(data, list):
        return data
    return data.get("data", [])

async def get_ohlcv_intraday(ticker: str, interval: str = "5m") -> list:
    data = await _get(f"/analysis/intraday-data/{ticker}", {"interval": interval})
    if isinstance(data, list):
        return data
    return data.get("data", [])

async def get_orderbook(ticker: str) -> dict:
    try:
        return await _get(f"/analysis/order-book/{ticker}")
    except:
        return {}

async def get_broker_summary(ticker: str) -> dict:
    try:
        return await _get(f"/analysis/inventory-chart/stock/{ticker}")
    except:
        return {}

async def get_foreign_flow(ticker: str) -> dict:
    try:
        return await _get(f"/analysis/intraday/{ticker}")
    except:
        return {}
