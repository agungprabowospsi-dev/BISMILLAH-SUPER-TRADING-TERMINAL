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

async def get_financial_statement(ticker: str) -> dict:
    """Laporan keuangan quarterly - Balance Sheet, Cash Flow, Income Statement"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/financial-statement/{ticker}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_intraday_index(index: str = "IHSG") -> dict:
    """IHSG & index live - IHSG, LQ45, IDX30, sektoral (15+ indices)"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/intraday-index/{index}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def get_top_movers(sort: str = "gainer", limit: int = 20) -> list:
    """Top Gainers, Losers, Most Active - sort: gainer/loser/active/value/freq/foreign"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/top-change",
            headers=_headers(),
            params={"sort": sort, "limit": limit}
        )
        r.raise_for_status()
        return r.json()

async def get_market_regime() -> dict:
    """Market Regime lengkap dari semua index Invesgo"""
    import asyncio
    
    ALL_INDICES = [
        "IHSG", "LQ45", "IDX30", "IDXSMC", "IDXBUMN",
        "IDXG30", "IDXESGL", "IDXHIDIV", "IDXVESTA",
        "IDXBASIC", "IDXCYC", "IDXNONCYC", "IDXENERGY",
        "IDXFINANCE", "IDXHEALTH", "IDXINDUST", "IDXINFRA",
        "IDXPROPERT", "IDXTECHNO", "IDXTRANS"
    ]
    
    results = {}
    
    async def fetch_index(idx):
        try:
            data = await get_intraday_index(idx)
            results[idx] = data
        except:
            results[idx] = None
    
    # Fetch semua index secara parallel
    await asyncio.gather(*[fetch_index(idx) for idx in ALL_INDICES])
    
    # Hitung market breadth dari IHSG (semua saham IDX) - fallback ke LQ45
    ihsg = results.get("IHSG") or {}
    lq45 = results.get("LQ45") or {}
    idxsmc = results.get("IDXSMC") or {}

    # Gunakan IHSG kalau ada data, otherwise aggregate semua index
    ihsg_pos = ihsg.get("positive", 0) or 0
    ihsg_neg = ihsg.get("negative", 0) or 0
    ihsg_neu = ihsg.get("neutral", 0) or 0

    if ihsg_pos + ihsg_neg + ihsg_neu > 0:
        # IHSG punya data lengkap (900+ saham)
        positive = ihsg_pos
        negative = ihsg_neg
        neutral = ihsg_neu
        breadth_source = "IDX (All Stocks)"
    else:
        # Fallback: aggregate LQ45 + IDXSMC
        positive = (lq45.get("positive", 0) or 0) + (idxsmc.get("positive", 0) or 0)
        negative = (lq45.get("negative", 0) or 0) + (idxsmc.get("negative", 0) or 0)
        neutral = (lq45.get("neutral", 0) or 0) + (idxsmc.get("neutral", 0) or 0)
        if positive + negative + neutral == 0:
            positive = lq45.get("positive", 0) or 0
            negative = lq45.get("negative", 0) or 0
            neutral = lq45.get("neutral", 0) or 0
            breadth_source = "LQ45"
        else:
            breadth_source = "LQ45 + SMC"
    total = positive + negative + neutral
    
    # Hitung change% dari index yang ada data
    def calc_change(d):
        if not d: return 0
        close = d.get("close") or 0
        prev = d.get("prev") or 0
        if close and prev and prev != 0:
            return ((close - prev) / prev) * 100
        return 0
    
    # Gunakan IHSG change sebagai main market indicator
    ihsg_change = calc_change(ihsg)
    lq45_change = ihsg_change if ihsg_change != 0 else calc_change(lq45)
    
    # Determine regime
    if lq45_change > 1 and positive > negative:
        regime = "STRONG BULL"
    elif lq45_change > 0 or positive > negative:
        regime = "BULL"
    elif lq45_change > -1 and abs(positive - negative) < 10:
        regime = "SIDEWAYS"
    elif lq45_change < -1 and negative > positive:
        regime = "STRONG BEAR"
    else:
        regime = "BEAR"
    
    results["_regime"] = regime
    results["_breadth"] = {
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "total": total,
        "breadth_ratio": round(positive / total * 100, 1) if total > 0 else 0,
        "source": breadth_source
    }
    results["_lq45_change"] = round(lq45_change, 2)
    
    # Sektoral summary
    sektoral = {}
    sektor_keys = ["IDXBASIC","IDXCYC","IDXNONCYC","IDXENERGY","IDXFINANCE",
                   "IDXHEALTH","IDXINDUST","IDXINFRA","IDXPROPERT","IDXTECHNO","IDXTRANS"]
    for sk in sektor_keys:
        d = results.get(sk)
        if d:
            chg = calc_change(d)
            sektoral[sk] = {
                "close": d.get("close"),
                "change_pct": round(chg, 2),
                "status": "UP" if chg > 0 else "DOWN" if chg < 0 else "FLAT"
            }
    results["_sektoral"] = sektoral
    
    return results
