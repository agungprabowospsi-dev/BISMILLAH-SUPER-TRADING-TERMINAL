"""
Data Adapter — Monitoring Enhancement REV22
Path: backend/app/api/monitoring_enhancement/data_adapter.py
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Literal

from app.core import invesgo

logger = logging.getLogger(__name__)

TradeMode = Literal["SWING", "DAYTRADING", "SCALPING"]

@dataclass
class NormalizedCandle:
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int

@dataclass
class OrderbookData:
    bid_price:   float = 0.0
    offer_price: float = 0.0
    bid_lot:     float = 0.0
    offer_lot:   float = 0.0
    bid_freq:    float = 0.0
    offer_freq:  float = 0.0
    spread:      float = 0.0
    spread_pct:  float = 0.0
    imbalance:   float = 1.0

@dataclass
class AdaptedData:
    trade_mode:      TradeMode
    ticker:          str
    candles:         list = field(default_factory=list)
    opens:           list = field(default_factory=list)
    highs:           list = field(default_factory=list)
    lows:            list = field(default_factory=list)
    closes:          list = field(default_factory=list)
    volumes:         list = field(default_factory=list)
    last_price:      float = 0.0
    prev_close:      float = 0.0
    change_pct:      float = 0.0
    volume_today:    int   = 0
    vwap:            float = 0.0
    avg_volume:      float = 0.0
    avg_volume_days: int   = 20
    orderbook:       Optional[OrderbookData] = None
    net_foreign_lot: int   = 0
    broker_summary_raw: list = field(default_factory=list)
    intraday_raw:    Optional[dict] = None
    daily_candles:   list = field(default_factory=list)
    daily_closes:    list = field(default_factory=list)
    daily_volumes:   list = field(default_factory=list)
    roc_period:      int  = 5
    fib_lookback:    int  = 20
    error:           Optional[str] = None
    data_source:     str  = ""

MODE_PARAMS = {
    "SWING":      {"roc_period": 5,  "fib_lookback": 20, "vol_avg_days": 20},
    "DAYTRADING": {"roc_period": 14, "fib_lookback": 20, "vol_avg_days": 20},
    "SCALPING":   {"roc_period": 10, "fib_lookback": 15, "vol_avg_days": 15},
}

def _normalize_daily(raw_list: list) -> list:
    result = []
    for c in raw_list:
        try:
            result.append(NormalizedCandle(
                open   = float(c.get("open",   0) or 0),
                high   = float(c.get("high",   0) or 0),
                low    = float(c.get("low",    0) or 0),
                close  = float(c.get("close",  0) or 0),
                volume = int(float(c.get("volume", 0) or 0)),
            ))
        except Exception:
            continue
    return result

def _normalize_intraday(raw: dict) -> NormalizedCandle:
    close = float(raw.get("close", 0) or raw.get("last_price", 0) or 0)
    return NormalizedCandle(
        open   = float(raw.get("open",   close) or close),
        high   = float(raw.get("high",   close) or close),
        low    = float(raw.get("low",    close) or close),
        close  = close,
        volume = int(float(raw.get("volume", 0) or 0)),
    )

def _normalize_orderbook(raw: dict) -> OrderbookData:
    bid_price   = float(raw.get("bid_price",   0) or 0)
    offer_price = float(raw.get("offer_price", 0) or 0)
    bid_lot     = float(raw.get("bid_lot",     0) or 0)
    offer_lot   = float(raw.get("offer_lot",   0) or 0)
    bid_freq    = float(raw.get("bid_freq",    0) or 0)
    offer_freq  = float(raw.get("offer_freq",  0) or 0)
    spread      = offer_price - bid_price if bid_price and offer_price else 0
    spread_pct  = (spread / bid_price * 100) if bid_price else 0
    imbalance   = bid_lot / offer_lot if offer_lot > 0 else 1.0
    return OrderbookData(
        bid_price=bid_price, offer_price=offer_price,
        bid_lot=bid_lot, offer_lot=offer_lot,
        bid_freq=bid_freq, offer_freq=offer_freq,
        spread=spread, spread_pct=spread_pct, imbalance=imbalance,
    )

def _calc_net_foreign(broker_summary: list) -> int:
    FOREIGN_BROKERS = {
        "DB","CS","ML","UBS","MS","JP","CG","RX",
        "YP","BK","AK","KZ","KI","DP","LG","OD"
    }
    net = 0
    for b in broker_summary:
        try:
            code = str(b.get("broker_code", "") or "").upper()
            if code in FOREIGN_BROKERS:
                buy  = int(float(b.get("buy_lot",  0) or 0))
                sell = int(float(b.get("sell_lot", 0) or 0))
                net += (buy - sell)
        except Exception:
            continue
    return net

def _build_series(candles: list) -> tuple:
    opens   = [c.open   for c in candles]
    highs   = [c.high   for c in candles]
    lows    = [c.low    for c in candles]
    closes  = [c.close  for c in candles]
    volumes = [c.volume for c in candles]
    return opens, highs, lows, closes, volumes

def _calc_avg_volume(volumes: list, days: int) -> float:
    if not volumes:
        return 1.0
    subset = volumes[-days:]
    return sum(subset) / len(subset)

async def _fetch_all(ticker: str) -> tuple:
    async def safe(coro):
        try:
            return await coro
        except Exception as e:
            logger.warning(f"Fetch failed: {e}")
            return None
    results = await asyncio.gather(
        safe(invesgo.get_ohlcv_intraday(ticker)),
        safe(invesgo.get_ohlcv_daily(ticker, period="3mo")),
        safe(invesgo.get_orderbook(ticker)),
        safe(invesgo.get_broker_summary(ticker)),
    )
    return (results[0] or {}, results[1] or [], results[2] or {}, results[3] or [])

async def _fetch_swing(ticker: str) -> AdaptedData:
    p    = MODE_PARAMS["SWING"]
    data = AdaptedData(trade_mode="SWING", ticker=ticker,
                       roc_period=p["roc_period"], fib_lookback=p["fib_lookback"])
    try:
        raw_daily    = await invesgo.get_ohlcv_daily(ticker, period="3mo")
        data.candles = _normalize_daily(raw_daily)
        if not data.candles:
            data.error = "No daily OHLCV data"
            return data
        data.opens, data.highs, data.lows, data.closes, data.volumes = \
            _build_series(data.candles)
        last = data.candles[-1]
        prev = data.candles[-2] if len(data.candles) >= 2 else last
        data.last_price   = last.close
        data.prev_close   = prev.close
        data.change_pct   = ((last.close - prev.close) / prev.close * 100) if prev.close else 0
        data.volume_today = last.volume
        data.vwap         = last.close
        data.avg_volume   = _calc_avg_volume(data.volumes, p["vol_avg_days"])
        try:
            raw_broker          = await invesgo.get_broker_summary(ticker)
            data.broker_summary_raw = raw_broker
            data.net_foreign_lot    = _calc_net_foreign(raw_broker)
        except Exception as e:
            logger.warning(f"Broker summary failed [{ticker}]: {e}")
        data.data_source = "daily_ohlcv+broker_summary"
    except Exception as e:
        data.error = str(e)
        logger.error(f"DataAdapter SWING error [{ticker}]: {e}")
    return data

async def _fetch_daytrading(ticker: str) -> AdaptedData:
    p    = MODE_PARAMS["DAYTRADING"]
    data = AdaptedData(trade_mode="DAYTRADING", ticker=ticker,
                       roc_period=p["roc_period"], fib_lookback=p["fib_lookback"])
    try:
        raw_intraday, raw_daily, raw_orderbook, raw_broker = await _fetch_all(ticker)
        intraday_candle    = _normalize_intraday(raw_intraday)
        data.intraday_raw  = raw_intraday
        data.daily_candles = _normalize_daily(raw_daily)
        _, _, _, data.daily_closes, data.daily_volumes = _build_series(data.daily_candles)
        data.candles = data.daily_candles[-19:] + [intraday_candle]
        data.opens, data.highs, data.lows, data.closes, data.volumes = \
            _build_series(data.candles)
        prev_close        = data.daily_closes[-1] if data.daily_closes else intraday_candle.close
        data.last_price   = intraday_candle.close
        data.prev_close   = prev_close
        data.change_pct   = ((intraday_candle.close - prev_close) / prev_close * 100) if prev_close else 0
        data.volume_today = intraday_candle.volume
        data.vwap         = float(raw_intraday.get("avg", intraday_candle.close) or intraday_candle.close)
        data.avg_volume   = _calc_avg_volume(data.daily_volumes, p["vol_avg_days"])
        if raw_orderbook:
            data.orderbook = _normalize_orderbook(raw_orderbook)
        if raw_broker:
            data.broker_summary_raw = raw_broker
            data.net_foreign_lot    = _calc_net_foreign(raw_broker)
        data.data_source = "intraday+daily+orderbook+broker"
    except Exception as e:
        data.error = str(e)
        logger.error(f"DataAdapter DAYTRADING error [{ticker}]: {e}")
    return data

async def _fetch_scalping(ticker: str) -> AdaptedData:
    p    = MODE_PARAMS["SCALPING"]
    data = AdaptedData(trade_mode="SCALPING", ticker=ticker,
                       roc_period=p["roc_period"], fib_lookback=p["fib_lookback"])
    try:
        raw_intraday      = await invesgo.get_ohlcv_intraday(ticker)
        raw_daily         = await invesgo.get_ohlcv_daily(ticker, period="1mo")
        data.intraday_raw = raw_intraday
        intraday_candle   = _normalize_intraday(raw_intraday)
        data.daily_candles = _normalize_daily(raw_daily)
        _, _, _, data.daily_closes, data.daily_volumes = _build_series(data.daily_candles)
        data.candles = data.daily_candles[-14:] + [intraday_candle]
        data.opens, data.highs, data.lows, data.closes, data.volumes = \
            _build_series(data.candles)
        prev_close        = data.daily_closes[-1] if data.daily_closes else intraday_candle.close
        data.last_price   = intraday_candle.close
        data.prev_close   = prev_close
        data.change_pct   = ((intraday_candle.close - prev_close) / prev_close * 100) if prev_close else 0
        data.volume_today = intraday_candle.volume
        data.vwap         = float(raw_intraday.get("avg", intraday_candle.close) or intraday_candle.close)
        data.avg_volume   = _calc_avg_volume(data.daily_volumes, p["vol_avg_days"])
        try:
            raw_orderbook  = await invesgo.get_orderbook(ticker)
            data.orderbook = _normalize_orderbook(raw_orderbook)
        except Exception as e:
            logger.warning(f"Orderbook failed [{ticker}]: {e}")
        data.data_source = "intraday+daily+orderbook"
    except Exception as e:
        data.error = str(e)
        logger.error(f"DataAdapter SCALPING error [{ticker}]: {e}")
    return data

async def fetch_adapted_data(ticker: str, trade_mode: TradeMode) -> AdaptedData:
    ticker = ticker.upper()
    if trade_mode == "SWING":
        return await _fetch_swing(ticker)
    elif trade_mode == "DAYTRADING":
        return await _fetch_daytrading(ticker)
    elif trade_mode == "SCALPING":
        return await _fetch_scalping(ticker)
    else:
        data = AdaptedData(trade_mode=trade_mode, ticker=ticker)
        data.error = f"Unknown trade_mode: {trade_mode}"
        return data
