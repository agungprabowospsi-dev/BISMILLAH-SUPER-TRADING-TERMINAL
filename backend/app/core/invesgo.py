import os
import httpx
import json as _json
import asyncio
from datetime import datetime, timedelta

# RC-0: Redis cache layer
async def _cache_get(key: str):
    try:
        from app.core.redis_client import cache_get
        return await cache_get(key)
    except Exception:
        return None

async def _cache_set(key: str, value: str, ttl: int = 300):
    try:
        from app.core.redis_client import cache_set
        await cache_set(key, value, ttl)
    except Exception:
        pass

_INFLIGHT = {}

async def _cache_get_json(key: str):
    cached = await _cache_get(key)
    if cached:
        try:
            return _json.loads(cached)
        except Exception:
            return None
    return None

async def _cache_set_json(key: str, value, ttl: int):
    if value not in (None, "", []):
        await _cache_set(key, _json.dumps(value), ttl=ttl)

async def _cached_request(key: str, ttl: int, fetcher):
    cached = await _cache_get_json(key)
    if cached is not None:
        return cached

    if key in _INFLIGHT:
        return await _INFLIGHT[key]

    task = asyncio.create_task(fetcher())
    _INFLIGHT[key] = task
    try:
        data = await task
        await _cache_set_json(key, data, ttl)
        return data
    finally:
        _INFLIGHT.pop(key, None)
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

def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default

def _unwrap_list(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items", "stocks", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []

def _unwrap_first_list(data, keys: tuple = ()) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        rows = _unwrap_first_list(value, ())
        if rows:
            return rows
    for key in ("data", "result", "results", "items", "stocks", "rows"):
        value = data.get(key)
        rows = _unwrap_first_list(value, keys)
        if rows:
            return rows
    return []

def _normalize_mover(row: dict, source: str = "") -> dict:
    code = row.get("code") or row.get("ticker") or row.get("symbol") or row.get("stock_code")
    close = _to_float(row.get("close") or row.get("last") or row.get("last_price") or row.get("price"))
    prev = _to_float(row.get("prev") or row.get("previous") or row.get("previous_close") or row.get("prev_close"))
    change = row.get("change")
    if change is None and close and prev:
        change = close - prev
    change = _to_float(change)
    change_pct = (
        row.get("change_pct")
        or row.get("change_percent")
        or row.get("pct_change")
        or row.get("percent")
    )
    if change_pct is None and close and prev:
        change_pct = (close - prev) / prev * 100
    if change_pct is None and change and not prev:
        # Invezgo top-change responses use "change" as percentage in SDK docs.
        change_pct = change

    return {
        **row,
        "code": code,
        "ticker": code,
        "name": row.get("name") or row.get("company_name") or code,
        "close": close,
        "prev": prev,
        "change": round(change, 4),
        "change_pct": round(_to_float(change_pct), 4),
        "volume": _to_float(row.get("volume")),
        "value": _to_float(row.get("value") or row.get("value_idr")),
        "freq": _to_float(row.get("freq") or row.get("frequency")),
        "source": source or row.get("source", ""),
    }

async def _get_json_first_success(client: httpx.AsyncClient, candidates: list, fallback=None):
    last_error = None
    for path, params in candidates:
        try:
            r = await client.get(f"{INVESGO_BASE_URL}{path}", headers=_headers(), params=params or {})
            r.raise_for_status()
            data = r.json()
            if data not in (None, "", []):
                return data
        except Exception as exc:
            last_error = exc
            logger.debug(f"[INVESGO] endpoint fallback {path} failed: {exc}")
    if fallback is not None:
        return fallback
    if last_error:
        raise last_error
    return None

def _params_key(params: dict = None) -> str:
    if not params:
        return ""
    clean = {k: v for k, v in params.items() if v is not None}
    return _json.dumps(clean, sort_keys=True, separators=(",", ":"))

async def _official_get(path: str, params: dict = None, ttl: int = 300, cache_key: str = None):
    """Cached GET for official Invezgo endpoints. Keep this as the quota gate."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    key = cache_key or f"official:{path}:{_params_key(params)}"

    async def fetch():
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{INVESGO_BASE_URL}{path}", headers=_headers(), params=params)
            r.raise_for_status()
            return r.json()

    return await _cached_request(key, ttl, fetch)

def _today_id() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _range_dates(days: int = 30) -> tuple[str, str]:
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return from_date, to_date

async def get_stock_list() -> list:
    """Ambil semua saham IDX. Cache 24 jam."""
    async def fetch():
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/list/stock", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request("stock_list:all", 86400, fetch)
    return data if isinstance(data, list) else []

async def get_broker_list() -> list:
    """Daftar broker/sekuritas BEI. Cache 24 jam."""
    data = await _official_get("/analysis/list/broker", ttl=86400)
    return data if isinstance(data, list) else []

async def get_index_list() -> list:
    """Daftar index IDX yang didukung Invezgo. Cache 24 jam."""
    data = await _official_get("/analysis/list/index", ttl=86400)
    return data if isinstance(data, list) else []

async def get_ohlcv_from_db(ticker: str, days: int = 90) -> list:
    """Ambil OHLCV dari PostgreSQL — zero Invesgo request."""
    try:
        import os, sys
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _sql_text
        from datetime import datetime as _dt, timedelta as _td
        from_date = (_dt.now() - _td(days=days)).strftime("%Y-%m-%d")
        async with AsyncSessionLocal() as db:
            result = await db.execute(_sql_text("""
                SELECT date, open, high, low, close, volume
                FROM ohlcv_daily
                WHERE ticker = :ticker AND date >= :from_date
                ORDER BY date ASC
            """), {"ticker": ticker, "from_date": from_date})
            rows = result.fetchall()
        if not rows:
            return []
        return [{"date": str(r[0]), "open": float(r[1] or 0), "high": float(r[2] or 0),
                 "low": float(r[3] or 0), "close": float(r[4] or 0), "volume": float(r[5] or 0)}
                for r in rows]
    except Exception as e:
        return []


async def get_ohlcv_daily(ticker: str, period: str = "3mo", from_date: str = None, to_date: str = None) -> list:
    """OHLCV harian - support period atau from/to date. RC-1: Redis cache 4 jam."""
    from datetime import datetime, timedelta

    # RC-1: Cache — tidak cache kalau ada from/to custom
    use_cache = not (from_date and to_date)
    cache_key = f"ohlcv:{ticker}:{period}"
    if use_cache:
        # Tier 1: Redis cache
        cached = await _cache_get(cache_key)
        if cached:
            try:
                import json as _j
                return _j.loads(cached)
            except Exception:
                pass

        # Tier 2: PostgreSQL primary source
        _period_map = {"1mo":30,"3mo":90,"6mo":180,"1y":365,"2y":730,"3y":1095,"5y":1825,"10y":3650,"15y":5475}
        _days_needed = _period_map.get(period, 90)
        db_data = await get_ohlcv_from_db(ticker, days=_days_needed + 10)
        if len(db_data) >= max(20, _days_needed // 3):
            # DB cukup — inject harga hari ini dari get_tick (1 request ringan)
            try:
                from datetime import datetime as _dtnow
                _tick = await get_tick(ticker)
                if _tick and float(_tick.get("last_price", 0) or 0) > 0:
                    _rt = float(_tick["last_price"])
                    _today = _dtnow.now().strftime("%Y-%m-%d")
                    if db_data[-1]["date"] == _today:
                        db_data[-1]["close"] = _rt
                        db_data[-1]["high"] = max(db_data[-1]["high"], _rt)
                        db_data[-1]["low"] = min(db_data[-1]["low"] if db_data[-1]["low"] > 0 else _rt, _rt)
                    else:
                        db_data.append({"date": _today, "open": _rt, "high": _rt, "low": _rt, "close": _rt, "volume": 0})
            except Exception:
                pass
            import json as _j
            await _cache_set(cache_key, _j.dumps(db_data), ttl=300)
            return db_data

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
        data = r.json()
    if use_cache and data:
        import json as _j
        await _cache_set(cache_key, _j.dumps(data), ttl=14400)
    return data

async def get_ohlcv_intraday(ticker: str, market: str = "RG") -> dict:
    """OHLCV intraday + bid/ask real. Cache 2 menit."""
    cache_key = f"intraday:{ticker}:{market}"

    async def fetch():
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{INVESGO_BASE_URL}/analysis/intraday-data/{ticker}",
                headers=_headers(),
                params={"market": market}
            )
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return {}
        return {
            "code":        data.get("code", ticker),
            "open":        data.get("open", 0),
            "high":        data.get("high", 0),
            "low":         data.get("low", 0),
            "close":       data.get("close", 0),
            "avg":         data.get("avg", 0),
            "volume":      data.get("volume", 0),
            "freq":        data.get("freq", 0),
            "value":       data.get("value", 0),
            "prev":        data.get("prev", 0),
            "bid_price":   data.get("bid_price", 0),
            "bid_lot":     data.get("bid_lot", 0),
            "bid_freq":    data.get("bid_freq", 0),
            "offer_price": data.get("offer_price", 0),
            "offer_lot":   data.get("offer_lot", 0),
            "offer_freq":  data.get("offer_freq", 0),
            "iep":         data.get("iep", 0),
            "iev":         data.get("iev", 0),
        }

    result = await _cached_request(cache_key, 120, fetch)
    if market == "RG":
        await _cache_set_json(f"intraday:{ticker}", result, 120)
    return result if isinstance(result, dict) else {}

async def get_orderbook(ticker: str, market: str = "RG", date: str = None, time: str = None) -> dict:
    """Official /analysis/order-book/{code}; fallback to intraday top-of-book."""
    try:
        data = await _official_get(
            f"/analysis/order-book/{ticker}",
            params={"market": market, "date": date, "time": time},
            ttl=30 if not date else 1800,
            cache_key=f"orderbook:{ticker}:{market}:{date or 'live'}:{time or ''}",
        )
        if isinstance(data, dict) and data:
            data.setdefault("source", "official_order_book")
            return data
    except Exception as exc:
        logger.debug(f"[INVESGO] official orderbook fallback for {ticker}: {exc}")

    data = await get_ohlcv_intraday(ticker, market=market)
    if isinstance(data, dict):
        return {
            "bid_price":   data.get("bid_price", 0),
            "bid_lot":     data.get("bid_lot", 0),
            "bid_freq":    data.get("bid_freq", 0),
            "offer_price": data.get("offer_price", 0),
            "offer_lot":   data.get("offer_lot", 0),
            "offer_freq":  data.get("offer_freq", 0),
            "source":      "intraday_top_of_book_fallback",
        }
    return {}

async def get_broker_summary(ticker: str, investor: str = "all", market: str = "RG") -> list:
    # RC-2: Cache 30 menit (1800 detik)
    cache_key = f"broker:{ticker}:{investor}:{market}"

    async def fetch():
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

    data = await _cached_request(cache_key, 1800, fetch)
    return data if isinstance(data, list) else []

async def get_foreign_flow(ticker: str) -> dict:
    """Net foreign buy/sell - dari price table"""
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request(f"foreign_flow:{ticker}", 1800, fetch)
    return data

async def get_tick(ticker: str) -> dict:
    """Tick data — ambil dari OHLCV daily close terakhir (lebih stabil)"""
    try:
        ohlcv = await get_ohlcv_daily(ticker, period="5d")
        if ohlcv and len(ohlcv) > 0:
            last = ohlcv[-1]
            close = float(last.get("close") or last.get("c") or 0)
            if close > 0:
                return {"last_price": close, "source": "ohlcv_daily"}
    except Exception:
        pass
    # Fallback ke price-table
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/price-table/{ticker}", headers=_headers())
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            price = data.get("last_price") or data.get("close") or data.get("price") or 0
            return {"last_price": float(price), "source": "price_table"}
        return {"last_price": 0, "source": "unknown"}

async def get_company_info(ticker: str) -> dict:
    """Info perusahaan lengkap dari /analysis/information/. Cache 24 jam."""
    cache_key = f"info:{ticker}"
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return _json.loads(cached)
        except Exception:
            pass
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{INVESGO_BASE_URL}/analysis/information/{ticker}", headers=_headers())
        r.raise_for_status()
        data = r.json()
    if data:
        await _cache_set(cache_key, _json.dumps(data), ttl=86400)
    return data if isinstance(data, dict) else {}

async def get_price_table(ticker: str, date: str = None) -> list:
    """Price distribution table per level harga. RC: cache 30 menit."""
    from datetime import datetime as _dt
    _date = date or _dt.now().strftime("%Y-%m-%d")
    cache_key = f"price_table:{ticker}:{_date}"
    cached = await _cache_get(cache_key)
    if cached:
        try:
            import json as _j
            return _j.loads(cached)
        except Exception:
            pass
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
        data = r.json()
        if data:
            import json as _j
            await _cache_set(cache_key, _j.dumps(data), ttl=1800)
        return data if isinstance(data, list) else []


async def get_ksei_ownership(ticker: str, range_months: int = 3) -> list:
    # RC-5: Cache 1 jam (3600 detik)
    cache_key = f"ksei:{ticker}:{range_months}"
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return _json.loads(cached)
        except Exception:
            pass
    """KSEI ownership data - foreign vs retail"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{INVESGO_BASE_URL}/analysis/shareholder/ksei/{ticker}",
            headers=_headers(),
            params={"range": range_months}
        )
        r.raise_for_status()
        data = r.json()
        if data:
            await _cache_set(f"ksei:{ticker}:{range_months}", _json.dumps(data), ttl=3600)
        return data
async def get_sector_rotation() -> dict:
    """Sector rotation"""
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/sector/rotation", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request("sector_rotation:global", 300, fetch)
    return data if isinstance(data, dict) else {}

async def get_market_summary() -> dict:
    """Market summary / IHSG.

    REV28: /analysis/market/summary is currently dead on Invesgo. Try known
    market-summary variants first, then fall back to intraday-index IHSG/LQ45.
    """
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            return await _get_json_first_success(client, [
                ("/analysis/market/summary", None),
                ("/analysis/market-summary", None),
                ("/analysis/summary/market", None),
                ("/analysis/intraday-index/IHSG", None),
            ], fallback={})

    data = await _cached_request("market_summary:global", 120, fetch)

    if not isinstance(data, dict):
        return {"source": "unavailable", "data": data}

    if data.get("code") or data.get("index") or data.get("close"):
        close = _to_float(data.get("close"))
        prev = _to_float(data.get("prev") or data.get("previous_close"))
        change = close - prev if close and prev else _to_float(data.get("change"))
        change_pct = (change / prev * 100) if prev else _to_float(data.get("change_pct"))
        return {
            **data,
            "source": data.get("source") or "intraday-index",
            "index": data.get("index") or data.get("code") or "IHSG",
            "close": close,
            "prev": prev,
            "change": round(change, 4),
            "change_pct": round(change_pct, 4),
            "positive": int(_to_float(data.get("positive"))),
            "negative": int(_to_float(data.get("negative"))),
            "neutral": int(_to_float(data.get("neutral"))),
        }

    data.setdefault("source", "market-summary")
    return data

async def get_top_gainer() -> list:
    """Top gainer saham IDX"""
    return await get_top_movers(sort="gainer", limit=20)

async def get_top_loser() -> list:
    """Top loser saham IDX"""
    return await get_top_movers(sort="loser", limit=20)

async def get_chart_composite() -> list:
    """IHSG composite chart"""
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/chart/composite", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request("chart_composite:global", 300, fetch)
    return data if isinstance(data, list) else []

async def get_foreign_net() -> list:
    """Net foreign buy/sell list"""
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/market/foreign-net", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request("foreign_net:global", 300, fetch)
    return data if isinstance(data, list) else []

async def get_top_flow(kind: str = "change", date: str = None, **filters) -> dict:
    """Official top flow endpoints: change, foreign, accumulation, ritel."""
    kind = (kind or "change").lower()
    endpoint = {
        "change": "/analysis/top/change",
        "foreign": "/analysis/top/foreign",
        "accumulation": "/analysis/top/accumulation",
        "ritel": "/analysis/top/ritel",
        "retail": "/analysis/top/ritel",
    }.get(kind, "/analysis/top/change")
    params = {"date": date or _today_id(), **{k: v for k, v in filters.items() if v is not None}}
    data = await _official_get(endpoint, params=params, ttl=300, cache_key=f"top_flow:{kind}:{_params_key(params)}")
    if isinstance(data, dict) and not _unwrap_first_list(data, ("gain", "loss", "accum", "dist", "data", "results", "items", "rows")):
        fallback_params = {k: v for k, v in filters.items() if v is not None}
        data_no_date = await _official_get(endpoint, params=fallback_params, ttl=180, cache_key=f"top_flow:{kind}:live:{_params_key(fallback_params)}")
        if isinstance(data_no_date, dict) and _unwrap_first_list(data_no_date, ("gain", "loss", "accum", "dist", "data", "results", "items", "rows")):
            data = data_no_date
    return data if isinstance(data, dict) else {}

async def get_market_context(ticker: str) -> dict:
    """Harga realtime + company info dari market-context endpoint"""
    cached = await _cache_get_json(f"market_context:{ticker}")
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{INVESGO_BASE_URL}/analysis/market-context/{ticker}",
                headers=_headers()
            )
            if r.status_code == 200:
                data = r.json()
                await _cache_set_json(f"market_context:{ticker}", data, 120)
                return data
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
                    result = {"price": {"last": last.get("close"), "high": last.get("high"), "low": last.get("low")}}
                    await _cache_set_json(f"market_context:{ticker}", result, 120)
                    return result
    except:
        pass
    return {}

async def get_multi_timeframe_chart(ticker: str, timeframe: str = "5", from_date: str = None, to_date: str = None) -> list:
    from_date, to_date = (from_date, to_date) if from_date and to_date else _range_dates(10)
    data = await _official_get(
        f"/analysis/chart/multi-time/{ticker}",
        params={"from": from_date, "to": to_date, "timeframe": timeframe},
        ttl=900,
    )
    return data if isinstance(data, list) else []

async def get_financial_statement(ticker: str) -> dict:
    """Laporan keuangan quarterly - Balance Sheet, Cash Flow, Income Statement"""
    async def fetch():
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/financial-statement/{ticker}", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request(f"financial:{ticker}", 21600, fetch)
    return data if isinstance(data, dict) else {}

async def get_key_stat(ticker: str, type_period: str = "Q", limit: int = 8) -> dict:
    data = await _official_get(
        f"/analysis/keystat/{ticker}",
        params={"type": type_period, "limit": min(int(limit or 8), 20)},
        ttl=21600,
        cache_key=f"keystat:{ticker}:{type_period}:{limit}",
    )
    return data if isinstance(data, dict) else {}

async def get_corporate_actions(ticker: str = None, action_type: str = None, page: int = 1, limit: int = 10) -> dict:
    data = await _official_get(
        "/analysis/calendar",
        params={"code": ticker, "type": action_type, "page": page, "limit": limit},
        ttl=21600,
    )
    return data if isinstance(data, dict) else {}

async def get_intraday_index(index: str = "IHSG") -> dict:
    """IHSG & index live - IHSG, LQ45, IDX30, sektoral (15+ indices)"""
    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{INVESGO_BASE_URL}/analysis/intraday-index/{index}", headers=_headers())
            r.raise_for_status()
            return r.json()

    data = await _cached_request(f"intraday_index:{index}", 120, fetch)
    return data if isinstance(data, dict) else {}

async def get_time_table(ticker: str, date: str = None, range_minutes: int = 5) -> list:
    date = date or _today_id()
    data = await _official_get(
        f"/analysis/time-table/{ticker}",
        params={"date": date, "range": range_minutes},
        ttl=120,
        cache_key=f"time_table:{ticker}:{date}:{range_minutes}",
    )
    return data if isinstance(data, list) else []

async def get_momentum_chart(ticker: str, date: str = None, range_minutes: int = 5, scope: str = "vol") -> list:
    date = date or _today_id()
    data = await _official_get(
        f"/analysis/momentum-chart/{ticker}",
        params={"date": date, "range": range_minutes, "scope": scope},
        ttl=120,
        cache_key=f"momentum:{ticker}:{date}:{range_minutes}:{scope}",
    )
    return data if isinstance(data, list) else []

async def get_intraday_inventory_chart(
    ticker: str,
    date: str = None,
    range_minutes: int = 5,
    type_: str = "value",
    total: int = 10,
    buyer: str = "all",
    seller: str = "all",
    market: str = "RG",
    broker: str = None,
) -> dict:
    data = await _official_get(
        f"/analysis/intraday-inventory-chart/{ticker}",
        params={
            "date": date or _today_id(),
            "range": range_minutes,
            "type": type_,
            "total": total,
            "buyer": buyer,
            "seller": seller,
            "market": market,
            "broker": broker,
        },
        ttl=180,
    )
    return data if isinstance(data, dict) else {}

async def get_sankey_chart(
    ticker: str,
    date: str = None,
    type_: str = "broker",
    buyer: str = "all",
    seller: str = "all",
    market: str = "RG",
) -> dict:
    data = await _official_get(
        f"/analysis/sankey-chart/{ticker}",
        params={"date": date or _today_id(), "type": type_, "buyer": buyer, "seller": seller, "market": market},
        ttl=300,
    )
    return data if isinstance(data, dict) else {}

async def get_broker_stalker(
    broker: str,
    stock: str,
    from_date: str = None,
    to_date: str = None,
    investor: str = "all",
    market: str = "RG",
) -> dict:
    from_date, to_date = (from_date, to_date) if from_date and to_date else _range_dates(30)
    data = await _official_get(
        f"/analysis/stalker/broker/{broker}/{stock}",
        params={"from": from_date, "to": to_date, "investor": investor, "market": market},
        ttl=1800,
    )
    return data if isinstance(data, dict) else {}

async def get_broker_stalker_list(
    broker: str,
    from_date: str = None,
    to_date: str = None,
    investor: str = "all",
    market: str = "RG",
) -> dict:
    from_date, to_date = (from_date, to_date) if from_date and to_date else _range_dates(30)
    data = await _official_get(
        f"/analysis/stalker/list/{broker}",
        params={"from": from_date, "to": to_date, "investor": investor, "market": market},
        ttl=1800,
    )
    return data if isinstance(data, dict) else {}

async def get_sector_stalker(from_date: str = None, to_date: str = None, base: str = "COMPOSITE", limit: int = 20) -> dict:
    from_date, to_date = (from_date, to_date) if from_date and to_date else _range_dates(30)
    data = await _official_get(
        "/analysis/stalker/sector",
        params={"from": from_date, "to": to_date, "base": base, "limit": limit},
        ttl=1800,
    )
    return data if isinstance(data, dict) else {}

async def get_top_movers(sort: str = "gainer", limit: int = 20) -> list:
    """Top Gainers, Losers, Most Active - sort: gainer/loser/active/value/freq/foreign.

    REV28: /analysis/top-change and /analysis/market/top-* may return 404.
    Keep the public function stable by trying endpoint variants and falling
    back to stock-list sorting when the list payload already contains change,
    value, volume, or frequency fields.
    """
    sort_key = (sort or "gainer").lower()
    cache_key = f"top_movers:{sort_key}:{limit}"
    cached = await _cache_get_json(cache_key)
    if cached is not None:
        return cached if isinstance(cached, list) else []

    try:
        official_rows = []
        if sort_key in ("gainer", "loser"):
            top_change = await get_top_flow("change")
            if sort_key == "gainer":
                official_rows = _unwrap_first_list(top_change, ("gain", "gainer", "gainers", "top_gainer", "top_gainers", "topGain", "topGainers", "up"))
            else:
                official_rows = _unwrap_first_list(top_change, ("loss", "loser", "losers", "top_loser", "top_losers", "topLoss", "topLosers", "down"))
        elif sort_key == "foreign":
            top_foreign = await get_top_flow("foreign")
            official_rows = _unwrap_first_list(top_foreign, ("accum", "dist", "accumulation", "distribution"))
        rows = [_normalize_mover(row, source=f"official-top-{sort_key}") for row in official_rows if isinstance(row, dict)]
        if rows:
            result = rows[:limit]
            await _cache_set_json(cache_key, result, 120)
            return result
    except Exception as exc:
        logger.debug(f"[INVESGO] official top movers fallback for {sort_key}: {exc}")

    endpoint_by_sort = {
        "gainer": [
            ("/analysis/top-change", {"sort": "gainer", "limit": limit}),
            ("/analysis/top-change", {"type": "gainer", "limit": limit}),
            ("/analysis/top-change", {"filter": "gainer", "limit": limit}),
            ("/analysis/top-change/gainer", {"limit": limit}),
            ("/analysis/market/top-gainer", None),
            ("/analysis/top-gainer", None),
        ],
        "loser": [
            ("/analysis/top-change", {"sort": "loser", "limit": limit}),
            ("/analysis/top-change", {"type": "loser", "limit": limit}),
            ("/analysis/top-change", {"filter": "loser", "limit": limit}),
            ("/analysis/top-change/loser", {"limit": limit}),
            ("/analysis/market/top-loser", None),
            ("/analysis/top-loser", None),
        ],
        "active": [
            ("/analysis/top-change", {"sort": "active", "limit": limit}),
            ("/analysis/top-active", None),
            ("/analysis/market/top-active", None),
        ],
        "value": [
            ("/analysis/top-change", {"sort": "value", "limit": limit}),
            ("/analysis/top-value", None),
            ("/analysis/market/top-value", None),
        ],
        "freq": [
            ("/analysis/top-change", {"sort": "freq", "limit": limit}),
            ("/analysis/top-frequency", None),
            ("/analysis/market/top-frequency", None),
        ],
        "foreign": [
            ("/analysis/top-change", {"sort": "foreign", "limit": limit}),
            ("/analysis/market/foreign-net", None),
        ],
    }
    candidates = endpoint_by_sort.get(sort_key, endpoint_by_sort["gainer"])

    async with httpx.AsyncClient(timeout=15) as client:
        data = await _get_json_first_success(client, candidates, fallback=[])

    rows = [_normalize_mover(row, source="top-movers") for row in _unwrap_list(data) if isinstance(row, dict)]
    if rows:
        result = rows[:limit]
        await _cache_set_json(cache_key, result, 120)
        return result

    try:
        stock_rows = [_normalize_mover(row, source="stock-list-fallback") for row in await get_stock_list() if isinstance(row, dict)]
    except Exception as exc:
        logger.warning(f"[INVESGO] top movers fallback stock list failed: {exc}")
        return []

    if sort_key == "loser":
        stock_rows = [row for row in stock_rows if row.get("change_pct", 0) < 0]
        stock_rows.sort(key=lambda row: row.get("change_pct", 0))
    elif sort_key in ("active", "volume"):
        stock_rows.sort(key=lambda row: row.get("volume", 0), reverse=True)
    elif sort_key == "value":
        stock_rows.sort(key=lambda row: row.get("value", 0), reverse=True)
    elif sort_key in ("freq", "frequency"):
        stock_rows.sort(key=lambda row: row.get("freq", 0), reverse=True)
    elif sort_key == "foreign":
        stock_rows.sort(key=lambda row: abs(row.get("foreign_net", 0) or 0), reverse=True)
    else:
        stock_rows = [row for row in stock_rows if row.get("change_pct", 0) > 0]
        stock_rows.sort(key=lambda row: row.get("change_pct", 0), reverse=True)

    result = stock_rows[:limit]
    await _cache_set_json(cache_key, result, 120)
    return result

async def get_market_regime() -> dict:
    # RC-3: Cache 10 menit (600 detik)
    cache_key = "market_regime:global"
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return _json.loads(cached)
        except Exception:
            pass
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

    await _cache_set_json(cache_key, results, 600)
    return results


async def invalidate_ticker_cache(ticker: str):
    """RC-6: Invalidate semua cache untuk ticker tertentu"""
    keys = [
        f"ohlcv:{ticker}:3mo",
        f"ohlcv:{ticker}:1mo",
        f"ohlcv:{ticker}:6mo",
        f"broker:{ticker}:all:RG",
        f"info:{ticker}",
        f"intraday:{ticker}",
        f"intraday:{ticker}:RG",
        f"ksei:{ticker}:3",
        f"market_context:{ticker}",
        f"financial:{ticker}",
        f"foreign_flow:{ticker}",
    ]
    for key in keys:
        await _cache_delete(key)

async def _cache_delete(key: str):
    try:
        from app.core.redis_client import cache_delete
        await cache_delete(key)
    except Exception:
        pass
