"""
BISMILLAH SUPER TRADING TERMINAL
Super Screener 5-Phase Architecture

Replace:
    backend/app/api/screener.py

Design source:
- Phase 1 Universe Filter
- Phase 2 OHLCV Pre-filter with Semaphore(30)
- Phase 3 Super Scoring Engine with Semaphore(10)
- Phase 4 Disqualifier
- Phase 5 Final TOP 5 Ranking

Notes:
- This file is defensive against small differences in existing service method names.
- It prioritizes get_ohlcv_daily because price_table/orderbook/broker_summary/tick are known unstable.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, Field


# ===== Defensive imports for existing project structure =====

try:
    from app.core import invesgo
    from app.api.bandar_early_detection import get_bandar_early_score, apply_akumulasi_multiplier
except Exception:
    invesgo = None
    get_bandar_early_score = None
    apply_akumulasi_multiplier = None

try:
    from app.core.redis_client import cache_get, cache_set
except Exception:
    cache_get = None
    cache_set = None

try:
    from app.engines.master_runner import run_all_engines
except Exception:
    run_all_engines = None

try:
    from app.engines.master_runner import MasterRunner
except Exception:
    MasterRunner = None

try:
    from app.knowledge_base.kb_service import kb_service
except Exception:
    kb_service = None


router = APIRouter(tags=["screener"])


# ===== Request / config =====

Mode = Literal["scalping", "intraday", "swing"]


class ScreenerRequest(BaseModel):
    mode: Mode = Field(default="swing")
    limit: int = Field(default=5, ge=1, le=20)
    include_debug: bool = Field(default=True)
    filter_intensity: int = Field(default=75, ge=50, le=100)


MODE_CONFIG: Dict[str, Dict[str, Any]] = {
    "scalping": {
        "price_min": 100,
        "price_max": 5000,
        "rvol_min": 2.0,
        "change_min": 1.0,
        "candidate_max": 60,
        "min_score": 60,
        "engine_weights": {
            "execution": 0.25,
            "volume": 0.25,
            "market_structure": 0.20,
            "smart_money": 0.20,
            "decision": 0.10,
        },
        "final_weights": {
            "engine": 0.45,
            "bandarmology": 0.20,
            "foreign": 0.10,
            "pattern": 0.20,
            "rag": 0.10,
        },
    },
    "intraday": {
        "price_min": 100,
        "price_max": 10000,
        "rvol_min": 1.5,
        "change_min": 0.5,
        "candidate_max": 80,
        "min_score": 58,
        "engine_weights": {
            "volume": 0.25,
            "smart_money": 0.25,
            "execution": 0.20,
            "market_structure": 0.20,
            "decision": 0.10,
        },
        "final_weights": {
            "engine": 0.40,
            "bandarmology": 0.25,
            "foreign": 0.15,
            "pattern": 0.15,
            "rag": 0.05,
        },
    },
    "swing": {
        "price_min": 200,
        "price_max": 50000,
        "rvol_min": 1.2,
        "change_min": 0.0,
        "candidate_max": 100,
        "min_score": 55,
        "engine_weights": {
            "smart_money": 0.30,
            "market_structure": 0.25,
            "decision": 0.20,
            "volume": 0.15,
            "execution": 0.10,
        },
        "final_weights": {
            "engine": 0.35,
            "bandarmology": 0.30,
            "foreign": 0.15,
            "pattern": 0.15,
            "rag": 0.05,
        },
    },
}

SCALPING_SECTORS = {
    "finance",
    "financials",
    "keuangan",
    "energi",
    "energy",
    "barang baku",
    "basic materials",
    "properti",
    "property",
    "real estate",
    "infrastruktur",
    "infrastructure",
    "industri",
    "industrial",
    "industrials",
    "teknologi",
    "technology",
}


# ===== Generic helpers =====

def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if value == "":
                return default
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def normalize_ticker(raw: Any) -> str:
    ticker = str(raw or "").upper().strip()
    ticker = ticker.replace(".JK", "")
    return ticker


def pick(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(d, dict) and key in d and d[key] is not None:
            return d[key]
    return default


def normalize_ohlcv(raw: Any) -> List[Dict[str, Any]]:
    """
    Accepts common response forms:
    - list[candle]
    - {"data": list[candle]}
    - {"items": list[candle]}
    - {"ohlcv": list[candle]}
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        for key in ("data", "items", "ohlcv", "result", "prices"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        return []

    candles: List[Dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        candles.append({
            "date": pick(c, "date", "time", "timestamp", "datetime"),
            "open": to_float(pick(c, "open", "o"), 0),
            "high": to_float(pick(c, "high", "h"), 0),
            "low": to_float(pick(c, "low", "l"), 0),
            "close": to_float(pick(c, "close", "c", "last"), 0),
            "volume": to_float(pick(c, "volume", "v", "value"), 0),
        })

    # Preserve API order if already old -> new. If it appears new -> old, reverse.
    # This simple heuristic uses date strings where available.
    if len(candles) >= 2 and candles[0].get("date") and candles[-1].get("date"):
        if str(candles[0]["date"]) > str(candles[-1]["date"]):
            candles.reverse()

    return [c for c in candles if c["open"] > 0 and c["high"] > 0 and c["low"] > 0 and c["close"] > 0]


async def call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    if fn is None:
        return None
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def invesgo_call(method_name: str, *args: Any, **kwargs: Any) -> Any:
    if invesgo is None:
        return None
    method = getattr(invesgo, method_name, None)
    if method is None:
        return None
    return await call_maybe_async(method, *args, **kwargs)


# ===== Phase 1: Universe Filter =====


DEFAULT_UNIVERSE_TICKERS = [
    # Big banks / liquid blue chips
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BDMN", "BNGA", "BTPS", "NISP",
    # Telco / tech
    "TLKM", "EXCL", "ISAT", "MTEL", "TOWR", "GOTO", "BUKA", "WIFI",
    # Conglomerates / consumer / retail
    "ASII", "UNVR", "ICBP", "INDF", "MYOR", "SIDO", "MAPI", "ACES", "AMRT",
    # Energy / coal / oil gas
    "ADRO", "AADI", "PTBA", "ITMG", "HRUM", "UNTR", "MEDC", "AKRA", "PGAS", "ELSA",
    # Basic materials / metals
    "ANTM", "INCO", "MDKA", "BRMS", "TINS", "AMMN", "ESSA", "SMGR", "INTP",
    # Property / infra / construction
    "BSDE", "CTRA", "PWON", "SMRA", "WIKA", "WSKT", "PTPP", "JSMR",
    # Healthcare / pharma
    "KLBF", "MIKA", "HEAL", "SILO", "TSPC",
    # Popular liquid second liners
    "ARTO", "EMTK", "SCMA", "ERAA", "MDIY", "RAJA", "CUAN", "BREN", "PTRO", "TOBA",
]

def fallback_stock_universe() -> List[Dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "code": ticker,
            "name": ticker,
            "sector": "",
            "logo": None,
            "raw": {"source": "fallback_universe"},
        }
        for ticker in DEFAULT_UNIVERSE_TICKERS
    ]

async def get_stock_list_safe() -> List[Dict[str, Any]]:
    raw = await invesgo_call("get_stock_list")
    if raw is None:
        return []
    if isinstance(raw, dict):
        for key in ("data", "items", "stocks", "result"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        return []

    stocks: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(pick(item, "code", "ticker", "symbol"))
        if not ticker:
            continue
        stocks.append({
            "ticker": ticker,
            "code": ticker,
            "name": pick(item, "name", "company_name", default=ticker),
            "sector": pick(item, "sector", "industry", default=""),
            "logo": pick(item, "logo", default=None),
            "raw": item,
        })
    return stocks


def sector_allowed(mode: Mode, sector: str) -> bool:
    if mode == "swing":
        return True
    s = (sector or "").lower().strip()
    if mode == "intraday":
        return True
    return any(allowed in s for allowed in SCALPING_SECTORS)


async def build_universe(mode: Mode) -> List[Dict[str, Any]]:
    stocks = await get_stock_list_safe()
    if not stocks:
        stocks = fallback_stock_universe()
    filtered = [s for s in stocks if sector_allowed(mode, s.get("sector", ""))]
    return filtered[:200]


# ===== Phase 2: OHLCV Pre-filter =====

async def fetch_ohlcv_safe(ticker: str) -> List[Dict[str, Any]]:
    # Known working endpoint according to master doc.
    raw = await invesgo_call("get_ohlcv_daily", ticker)
    return normalize_ohlcv(raw)


def calc_prefilter_metrics(ohlcv: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(ohlcv) < 21:
        return None

    last = ohlcv[-1]
    prev = ohlcv[-2]
    close = to_float(last.get("close"))
    prev_close = to_float(prev.get("close"))
    if close <= 0 or prev_close <= 0:
        return None

    # Filter suspended: volume hari ini = 0 atau None
    last_vol_raw = last.get("volume")
    if last_vol_raw is None or to_float(last_vol_raw) <= 0:
        return None

    # Filter suspended: 3 hari terakhir semua volume = 0
    last3_vol = [to_float(c.get("volume")) for c in ohlcv[-3:]]
    if all(v <= 0 for v in last3_vol):
        return None

    volumes20 = [to_float(c.get("volume")) for c in ohlcv[-21:-1]]
    avg_volume20 = sum(volumes20) / len(volumes20) if volumes20 else 0
    last_volume = to_float(last.get("volume"))
    rvol = last_volume / avg_volume20 if avg_volume20 > 0 else 0

    change_pct = ((close - prev_close) / prev_close) * 100
    closes = [to_float(c.get("close")) for c in ohlcv if to_float(c.get("close")) > 0]
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else close
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
    downtrend_heavy = close < ma20 < ma50 and change_pct < -1.5

    # MA5
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else close

    # Value transaksi (price x volume)
    last_open = to_float(last.get("open"))
    value = close * last_volume

    # Candle bullish
    candle_bullish = last_open > 0 and close > last_open

    # Candle body size %
    candle_body_pct = abs(close - last_open) / last_open * 100 if last_open > 0 else 0

    return {
        "price": close,
        "open": last_open,
        "high": to_float(last.get("high")),
        "low": to_float(last.get("low")),
        "volume": last_volume,
        "avg_volume_20": avg_volume20,
        "rvol": round(rvol, 2),
        "change_pct": round(change_pct, 2),
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "value": value,
        "candle_bullish": candle_bullish,
        "candle_body_pct": round(candle_body_pct, 2),
        "downtrend_heavy": downtrend_heavy,
    }


async def prefilter_one(stock: Dict[str, Any], mode: Mode, semaphore: asyncio.Semaphore, filter_intensity: int = 75) -> Optional[Dict[str, Any]]:
    ticker = stock["ticker"]
    cfg = MODE_CONFIG[mode]

    async with semaphore:
        try:
            ohlcv = await asyncio.wait_for(fetch_ohlcv_safe(ticker), timeout=10)
            metrics = calc_prefilter_metrics(ohlcv)
            if not metrics:
                return None

            price = metrics["price"]
            if price < cfg["price_min"] or price > cfg["price_max"]:
                return None

            # Filter saham suspended — dari field Invesgo + OHLCV check
            if int(stock.get("suspend", 0) or 0) > 0:
                return None
            if metrics["volume"] <= 0:
                return None
            if metrics["avg_volume_20"] <= 0:
                return None
            if metrics["rvol"] <= 0:
                return None
            if (metrics.get("high", 0) == metrics.get("low", 0) == metrics["price"] and metrics["volume"] < 1000):
                return None

            # Filter ARA/ARB — saham yang kena auto reject atas/bawah (suspended risk)
            change_pct_now = metrics.get("change_pct", 0)
            if change_pct_now >= 24.0:
                return None  # ARA — potensi suspended/tidak bisa beli
            if change_pct_now <= -24.0:
                return None  # ARB — potensi suspended/tidak bisa jual

            if metrics["rvol"] < cfg["rvol_min"]:
                return None

            if metrics["change_pct"] < cfg["change_min"]:
                return None

            if mode == "scalping" and metrics["downtrend_heavy"]:
                return None

            # ===== FASE 1: Smart Pre-Filter per Mode =====
            price = metrics["price"]
            value = metrics.get("value", 0)
            ma5 = metrics.get("ma5", price)
            ma20 = metrics.get("ma20", price)
            candle_bullish = metrics.get("candle_bullish", False)
            candle_body_pct = metrics.get("candle_body_pct", 0)
            change_pct = metrics["change_pct"]

            # Intensity multiplier: 100%=ketat, 75%=sedang, 50%=longgar
            intensity = filter_intensity
            if intensity >= 100:
                val_swing, val_intraday, val_scalping = 10_000_000_000, 5_000_000_000, 2_000_000_000
                ma20_thr, ma5_thr = 0.98, 0.97
                chg_swing, chg_intraday, chg_scalping = -2.0, -0.5, 1.0
                body_min, price_min_scalping = 0.3, 200
            elif intensity >= 75:
                val_swing, val_intraday, val_scalping = 5_000_000_000, 2_000_000_000, 1_000_000_000
                ma20_thr, ma5_thr = 0.95, 0.95
                chg_swing, chg_intraday, chg_scalping = -3.0, -1.5, 0.5
                body_min, price_min_scalping = 0.1, 100
            else:  # 50%
                val_swing, val_intraday, val_scalping = 1_000_000_000, 500_000_000, 200_000_000
                ma20_thr, ma5_thr = 0.90, 0.90
                chg_swing, chg_intraday, chg_scalping = -5.0, -3.0, 0.0
                body_min, price_min_scalping = 0.0, 50

            if mode == "swing":
                if value < val_swing:
                    return None
                if price < ma20 * ma20_thr:
                    return None
                if change_pct < chg_swing:
                    return None

            elif mode == "intraday":
                if value < val_intraday:
                    return None
                if price < ma5 * ma5_thr:
                    return None
                if change_pct < chg_intraday:
                    return None

            elif mode == "scalping":
                if value < val_scalping:
                    return None
                if change_pct < chg_scalping:
                    return None
                if candle_body_pct < body_min:
                    return None
                if price < price_min_scalping:
                    return None

            return {
                **stock,
                **metrics,
                "ohlcv": ohlcv,
            }
        except Exception:
            return None


async def ohlcv_prefilter(universe: List[Dict[str, Any]], mode: Mode, filter_intensity: int = 75) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(30)
    tasks = [prefilter_one(stock, mode, sem, filter_intensity) for stock in universe]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates = [r for r in results if isinstance(r, dict)]
    candidates.sort(key=lambda x: (to_float(x.get("rvol")), to_float(x.get("change_pct"))), reverse=True)
    return candidates[: MODE_CONFIG[mode]["candidate_max"]]


# ===== Phase 3A: 34 Engines weighted score =====

def _extract_score_from_any(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("score", "final_score", "composite_score", "value"):
            if key in value:
                return to_float(value[key], default=-1)
    return None


def flatten_engine_scores(raw: Any) -> Dict[str, float]:
    """
    Tries to flatten arbitrary master_runner output into engine-name -> score.
    """
    scores: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return scores

    def walk(prefix: str, obj: Any) -> None:
        score = _extract_score_from_any(obj)
        if score is not None and score >= 0:
            scores[prefix.strip(".") or "engine"] = clamp(score)
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in {"ohlcv", "raw", "candles"}:
                    continue
                if isinstance(v, (dict, int, float)):
                    walk(f"{prefix}.{k}" if prefix else str(k), v)

    walk("", raw)
    return scores


def bucket_engine_scores(scores: Dict[str, float]) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = {
        "execution": [],
        "volume": [],
        "market_structure": [],
        "smart_money": [],
        "decision": [],
    }

    for name, score in scores.items():
        n = name.lower()
        if any(x in n for x in ("execution", "entry", "risk", "order", "liquidity", "setup")):
            buckets["execution"].append(score)
        elif any(x in n for x in ("volume", "rvol", "vpa", "frequency")):
            buckets["volume"].append(score)
        elif any(x in n for x in ("structure", "trend", "support", "resistance", "breakout", "wyckoff")):
            buckets["market_structure"].append(score)
        elif any(x in n for x in ("smart", "money", "bandar", "accum", "foreign", "institution")):
            buckets["smart_money"].append(score)
        elif any(x in n for x in ("decision", "control", "confidence", "signal")):
            buckets["decision"].append(score)

    # Fallback: spread global average if buckets are empty.
    all_scores = list(scores.values())
    global_avg = sum(all_scores) / len(all_scores) if all_scores else 50.0

    return {
        key: round(sum(vals) / len(vals), 2) if vals else round(global_avg, 2)
        for key, vals in buckets.items()
    }


async def run_master_engines_safe(ticker: str, mode: Mode, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Try most likely function first.
    if run_all_engines is not None:
        for args, kwargs in (
            ((ticker,), {"mode": mode, "ohlcv": ohlcv}),
            ((ticker, mode), {"ohlcv": ohlcv}),
            ((ticker, mode, ohlcv), {}),
            ((ticker,), {"mode": mode}),
        ):
            try:
                return await call_maybe_async(run_all_engines, *args, **kwargs) or {}
            except TypeError:
                continue
            except Exception as exc:
                return {"error": str(exc)}

    if MasterRunner is not None:
        try:
            runner = MasterRunner()
            for method_name in ("run", "analyze", "run_all", "analyze_ticker"):
                method = getattr(runner, method_name, None)
                if method is None:
                    continue
                for args, kwargs in (
                    ((ticker,), {"mode": mode, "ohlcv": ohlcv}),
                    ((ticker, mode), {"ohlcv": ohlcv}),
                    ((ticker, mode, ohlcv), {}),
                    ((ticker,), {"mode": mode}),
                ):
                    try:
                        return await call_maybe_async(method, *args, **kwargs) or {}
                    except TypeError:
                        continue
                    except Exception as exc:
                        return {"error": str(exc)}
        except Exception as exc:
            return {"error": str(exc)}

    return {"warning": "master_runner not available", "score": 50}


def weighted_engine_score(raw_engine_result: Dict[str, Any], mode: Mode) -> Tuple[float, Dict[str, Any]]:
    flat = flatten_engine_scores(raw_engine_result)
    buckets = bucket_engine_scores(flat)
    weights = MODE_CONFIG[mode]["engine_weights"]

    score = 0.0
    for bucket, weight in weights.items():
        score += buckets.get(bucket, 50.0) * weight

    return round(clamp(score), 2), {"flat_count": len(flat), "buckets": buckets}


# ===== Phase 3B: Bandarmology Composite =====

def estimate_bandarmology_score(ohlcv: List[Dict[str, Any]], rvol: float, change_pct: float) -> float:
    if len(ohlcv) < 20:
        return 50.0

    closes = [to_float(c.get("close")) for c in ohlcv[-20:]]
    volumes = [to_float(c.get("volume")) for c in ohlcv[-20:]]
    up_volume = 0.0
    down_volume = 0.0

    for i in range(1, len(ohlcv[-20:])):
        c = ohlcv[-20:][i]
        prev = ohlcv[-20:][i - 1]
        vol = to_float(c.get("volume"))
        if to_float(c.get("close")) >= to_float(prev.get("close")):
            up_volume += vol
        else:
            down_volume += vol

    vol_bias = 50.0
    total = up_volume + down_volume
    if total > 0:
        vol_bias = (up_volume / total) * 100

    price_range = ((max(closes) - min(closes)) / min(closes)) * 100 if min(closes) > 0 else 100
    quiet_accum_bonus = 10 if price_range < 12 and rvol > 1.2 else 0
    momentum_bonus = min(10, max(0, change_pct * 2))
    rvol_bonus = min(15, max(0, (rvol - 1) * 5))

    return round(clamp((vol_bias * 0.60) + 20 + quiet_accum_bonus + momentum_bonus + rvol_bonus), 2)


def big_accumulation_bonus(bandarm_score: float) -> int:
    if bandarm_score > 70:
        return 20
    if bandarm_score > 60:
        return 12
    if bandarm_score > 50:
        return 5
    if bandarm_score < 40:
        return -10
    return 0


async def save_bandar_score(ticker: str, score: float) -> None:
    if cache_set is None:
        return
    today = date.today().strftime("%Y-%m-%d")
    key = f"bandar_history:{ticker}:{today}"
    ttl = 4 * 3600  # 4 jam — realtime trading
    try:
        await call_maybe_async(cache_set, key, str(float(score)), ttl=ttl)
    except TypeError:
        try:
            await call_maybe_async(cache_set, key, str(float(score)), ttl)
        except Exception:
            pass
    except Exception:
        pass


async def get_bandar_history(ticker: str, days: int = 20) -> List[float]:
    if cache_get is None:
        return []
    scores: List[float] = []
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        key = f"bandar_history:{ticker}:{d}"
        try:
            val = await call_maybe_async(cache_get, key)
            if val is not None:
                scores.append(to_float(val))
        except Exception:
            continue
    return scores


def calc_bandar_macd_from_history(scores: List[float]) -> Optional[Dict[str, Any]]:
    if len(scores) < 10:
        return None

    today_score = scores[0]
    avg10 = sum(scores[:10]) / 10
    avg20 = sum(scores[:20]) / min(20, len(scores))

    if today_score > avg10 > avg20:
        return {"signal": "BULLISH_ACCELERATION", "bonus": 15, "disqualify": False, "avg10": avg10, "avg20": avg20}
    if today_score > avg10:
        return {"signal": "EARLY_RECOVERY", "bonus": 5, "disqualify": False, "avg10": avg10, "avg20": avg20}
    if today_score < avg10 * 0.8:
        return {"signal": "DISQUALIFY", "bonus": 0, "disqualify": True, "avg10": avg10, "avg20": avg20}
    return {"signal": "WARNING", "bonus": -10, "disqualify": False, "avg10": avg10, "avg20": avg20}


def estimate_bandar_macd_from_ohlcv(ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(ohlcv) < 20:
        return {"signal": "NEUTRAL", "bonus": 0, "disqualify": False, "source": "ohlcv_short"}
    volumes = [to_float(c.get("volume")) for c in ohlcv[-20:]]
    avg_vol = sum(volumes) / len(volumes)
    recent_avg = sum(volumes[-5:]) / 5
    older_avg = sum(volumes[:10]) / 10

    if recent_avg > avg_vol > older_avg:
        return {"signal": "BULLISH_ACCELERATION", "bonus": 10, "disqualify": False, "source": "ohlcv"}
    if recent_avg > avg_vol:
        return {"signal": "EARLY_RECOVERY", "bonus": 5, "disqualify": False, "source": "ohlcv"}
    if recent_avg < older_avg * 0.55:
        return {"signal": "DISQUALIFY", "bonus": 0, "disqualify": True, "source": "ohlcv"}
    return {"signal": "NEUTRAL", "bonus": 0, "disqualify": False, "source": "ohlcv"}


def detect_phase(ohlcv: List[Dict[str, Any]], bandarm_score: float, rvol: float, change_pct: float) -> Dict[str, Any]:
    if len(ohlcv) < 50:
        return {"phase": "neutral", "bonus": 0, "disqualify": False}

    closes = [to_float(c.get("close")) for c in ohlcv[-60:]]
    recent = closes[-20:]
    older = closes[:20] if len(closes) >= 40 else closes[:10]
    price = closes[-1]
    ma20 = sum(recent) / len(recent)
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20

    range60 = ((max(closes) - min(closes)) / min(closes)) * 100 if min(closes) > 0 else 100
    older_avg = sum(older) / len(older)
    recent_avg = sum(recent) / len(recent)

    if price < ma20 < ma50 and bandarm_score < 42:
        return {"phase": "decline", "bonus": 0, "disqualify": True}

    if change_pct < -3 and rvol > 1.8 and bandarm_score < 45:
        return {"phase": "distribution", "bonus": 0, "disqualify": True}

    if range60 < 15 and bandarm_score > 58 and rvol > 1.2:
        return {"phase": "early_accumulation", "bonus": 15, "disqualify": False}

    if recent_avg > older_avg * 1.02 and bandarm_score > 55:
        return {"phase": "accumulation", "bonus": 12, "disqualify": False}

    if price > ma20 > ma50 and change_pct > 1 and rvol > 1.5:
        return {"phase": "markup", "bonus": 15, "disqualify": False}

    if bandarm_score > 55:
        return {"phase": "accumulation_late", "bonus": 10, "disqualify": False}

    return {"phase": "neutral", "bonus": 0, "disqualify": False}


async def bandarmology_composite(ticker: str, mode: Mode, ohlcv: List[Dict[str, Any]], rvol: float, change_pct: float) -> Dict[str, Any]:
    bandarm_score = estimate_bandarmology_score(ohlcv, rvol, change_pct)
    await save_bandar_score(ticker, bandarm_score)

    history = await get_bandar_history(ticker)
    bandar_macd = calc_bandar_macd_from_history(history)
    if bandar_macd is None:
        bandar_macd = estimate_bandar_macd_from_ohlcv(ohlcv)

    phase = detect_phase(ohlcv, bandarm_score, rvol, change_pct)
    freq = frequency_spike_bonus(mode, ohlcv)

    raw_score = 50 + big_accumulation_bonus(bandarm_score) + bandar_macd["bonus"] + phase["bonus"] + freq["bonus"]
    composite = clamp(raw_score)

    # ── Phase 2 Integration ──────────────────────────────────
    wyckoff_phase   = "UNKNOWN"
    weinstein_stage = 0
    vsa_signal      = "NONE"
    phase2_bonus    = 0
    phase2_disqualify = False

    try:
        from app.api.enrichment.wyckoff_phase import classify_wyckoff
        from app.api.enrichment.weinstein_stage import classify_weinstein
        from app.api.enrichment.vsa_engine import analyze_vsa

        opens   = [float(c.get("open",   0) or 0) for c in ohlcv]
        highs   = [float(c.get("high",   0) or 0) for c in ohlcv]
        lows    = [float(c.get("low",    0) or 0) for c in ohlcv]
        closes  = [float(c.get("close",  0) or 0) for c in ohlcv]
        volumes = [int(float(c.get("volume", 0) or 0)) for c in ohlcv]

        p2_wyckoff   = classify_wyckoff(opens, highs, lows, closes, volumes)
        p2_weinstein = classify_weinstein(closes, volumes)
        p2_vsa       = analyze_vsa(opens, highs, lows, closes, volumes)

        wyckoff_phase   = p2_wyckoff.phase
        weinstein_stage = p2_weinstein.stage
        vsa_signal      = p2_vsa.signal

        # Bonus/penalty dari Phase 2
        if wyckoff_phase in ("ACCUMULATION", "MARKUP"):
            phase2_bonus += 10
        elif wyckoff_phase == "REACCUMULATION":
            phase2_bonus += 5
        elif wyckoff_phase == "DISTRIBUTION":
            phase2_bonus -= 15
            phase2_disqualify = True
        elif wyckoff_phase == "MARKDOWN":
            phase2_bonus -= 20
            phase2_disqualify = True

        if weinstein_stage == 2:
            phase2_bonus += 10
        elif weinstein_stage == 1:
            phase2_bonus += 3
        elif weinstein_stage == 3:
            phase2_bonus -= 10
        elif weinstein_stage == 4:
            phase2_bonus -= 20
            phase2_disqualify = True

        if vsa_signal in ("STOPPING_VOLUME", "NO_SUPPLY", "TEST"):
            phase2_bonus += 8
        elif vsa_signal in ("UP_THRUST", "NO_DEMAND"):
            phase2_bonus -= 8

        composite = clamp(composite + phase2_bonus)

    except Exception as e:
        pass

    return {
        "score": round(composite, 2),
        "base_bandarm_score": bandarm_score,
        "big_accumulation_bonus": big_accumulation_bonus(bandarm_score),
        "bandar_macd": bandar_macd,
        "frequency_spike": freq,
        "phase": phase["phase"],
        "phase_bonus": phase["bonus"],
        "disqualify": bool(phase["disqualify"] or bandar_macd.get("disqualify") or phase2_disqualify),
        "wyckoff_phase":   wyckoff_phase,
        "weinstein_stage": weinstein_stage,
        "vsa_signal":      vsa_signal,
        "phase2_bonus":    phase2_bonus,
    }


# ===== Phase 3C: Foreign Flow Proxy =====

def calculate_foreign_flow_proxy(ohlcv: List[Dict[str, Any]], bandarmology: Dict[str, Any]) -> Dict[str, Any]:
    if len(ohlcv) < 20:
        return {"score": 50, "signal": "NEUTRAL", "streak": 0, "heavy_sell": False}

    proxy_values: List[float] = []
    for i in range(1, len(ohlcv[-20:])):
        c = ohlcv[-20:][i]
        p = ohlcv[-20:][i - 1]
        change = to_float(c.get("close")) - to_float(p.get("close"))
        volume = to_float(c.get("volume"))
        # positive price change with volume is treated as foreign/smart flow proxy
        proxy_values.append(change * volume)

    today = proxy_values[-1] if proxy_values else 0
    ma20 = sum(proxy_values) / len(proxy_values) if proxy_values else 0
    ma10 = sum(proxy_values[-10:]) / min(10, len(proxy_values)) if proxy_values else 0

    streak = 0
    for val in reversed(proxy_values):
        if val > 0:
            streak += 1
        else:
            break

    signal = "NEUTRAL"
    score = 50
    if today > 0 and ma10 > 0 and streak >= 2 and today > ma20:
        signal = "BUY"
        score = 75
    elif today > 0 or ma10 > 0:
        signal = "NEUTRAL_BUY"
        score = 62
    elif today < 0 and ma10 < 0:
        signal = "SELL"
        score = 35
    elif today < 0:
        signal = "NEUTRAL_SELL"
        score = 45

    phase = bandarmology.get("phase")
    if bandarmology.get("base_bandarm_score", 50) > 55 and signal == "BUY":
        score += 15
    elif bandarmology.get("base_bandarm_score", 50) > 55 and signal == "NEUTRAL_BUY":
        score += 8
    elif bandarmology.get("base_bandarm_score", 50) < 45 and signal == "SELL":
        return {"score": 0, "signal": "HEAVY_SELL", "streak": streak, "heavy_sell": True, "proxy_today": today, "proxy_ma10": ma10, "proxy_ma20": ma20}

    heavy_sell = signal in {"SELL", "HEAVY_SELL"} and phase in {"distribution", "decline"}

    return {
        "score": round(clamp(score), 2),
        "signal": signal,
        "streak": streak,
        "heavy_sell": heavy_sell,
        "proxy_today": today,
        "proxy_ma10": ma10,
        "proxy_ma20": ma20,
    }


# ===== Phase 3D: Pattern Bonus =====

def check_flywins_pattern(ohlcv: List[Dict[str, Any]]) -> bool:
    if len(ohlcv) < 3:
        return False
    c1, c2, c3 = ohlcv[-3], ohlcv[-2], ohlcv[-1]
    day1_bullish = to_float(c1.get("close")) > to_float(c1.get("open")) * 1.01
    day2_bullish = to_float(c2.get("close")) > to_float(c2.get("open")) * 1.01
    gap_up = to_float(c3.get("open")) > to_float(c2.get("close")) * 1.008
    follow = to_float(c3.get("high")) > to_float(c3.get("open")) * 1.005
    return day1_bullish and day2_bullish and gap_up and follow


def check_3d1up_pattern(ohlcv: List[Dict[str, Any]]) -> bool:
    if len(ohlcv) < 4:
        return False
    c1, c2, c3, c4 = ohlcv[-4], ohlcv[-3], ohlcv[-2], ohlcv[-1]
    b1 = to_float(c1.get("open")) >= to_float(c1.get("close")) * 1.01
    b2 = to_float(c2.get("open")) >= to_float(c2.get("close")) * 1.01
    b3 = to_float(c3.get("open")) >= to_float(c3.get("close")) * 1.01
    lower = to_float(c2.get("close")) <= to_float(c1.get("close"))
    lower2 = to_float(c3.get("close")) <= to_float(c2.get("close"))
    reclaim = to_float(c4.get("close")) >= to_float(c1.get("open"))
    bullish = to_float(c4.get("close")) > to_float(c4.get("open"))
    return b1 and b2 and b3 and lower and lower2 and reclaim and bullish


def check_narrow_range_pattern(ohlcv: List[Dict[str, Any]], days: int = 4) -> bool:
    if len(ohlcv) < days + 1:
        return False
    current = ohlcv[-1]
    curr_range = to_float(current.get("high")) - to_float(current.get("low"))
    if curr_range <= 0:
        return False
    for i in range(2, days + 2):
        prev = ohlcv[-i]
        prev_range = to_float(prev.get("high")) - to_float(prev.get("low"))
        if prev_range <= curr_range:
            return False
    prev = ohlcv[-2]
    inside = to_float(current.get("high")) <= to_float(prev.get("high")) and to_float(current.get("low")) >= to_float(prev.get("low"))
    return inside


def check_sideways_accumulation(ohlcv: List[Dict[str, Any]], days: int = 60) -> bool:
    if len(ohlcv) < days:
        return False
    closes = [to_float(c.get("close")) for c in ohlcv[-days:]]
    if min(closes) <= 0:
        return False
    sma5 = sum(closes[-5:]) / 5
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else sma20
    return abs(sma5 - sma20) / sma20 < 0.03 and abs(sma5 - sma50) / sma50 < 0.03


def check_frequency_spike_scalping(ohlcv: List[Dict[str, Any]], days: int = 5) -> bool:
    if len(ohlcv) < 20:
        return False
    recent = ohlcv[-days:]
    closes = [to_float(c.get("close")) for c in recent]
    volumes = [to_float(c.get("volume")) for c in recent]
    if not closes or min(closes) <= 0:
        return False
    price_range = (max(closes) - min(closes)) / min(closes) * 100
    avg_vol = sum(to_float(c.get("volume")) for c in ohlcv[-20:-5]) / 15
    recent_vol = sum(volumes) / len(volumes)
    return price_range < 3.0 and avg_vol > 0 and recent_vol > avg_vol * 1.5


def check_frequency_spike_intraday(ohlcv: List[Dict[str, Any]], days: int = 10) -> bool:
    if len(ohlcv) < 25:
        return False
    recent = ohlcv[-days:]
    closes = [to_float(c.get("close")) for c in recent]
    if min(closes) <= 0:
        return False
    price_range = (max(closes) - min(closes)) / min(closes) * 100
    avg_vol_old = sum(to_float(c.get("volume")) for c in ohlcv[-25:-10]) / 15
    avg_vol_recent = sum(to_float(c.get("volume")) for c in recent) / days
    return price_range < 8.0 and avg_vol_old > 0 and avg_vol_recent > avg_vol_old * 1.35


def check_frequency_spike_swing(ohlcv: List[Dict[str, Any]], days: int = 60) -> bool:
    if len(ohlcv) < days:
        return False
    recent = ohlcv[-days:]
    closes = [to_float(c.get("close")) for c in recent]
    if min(closes) <= 0:
        return False
    price_range = (max(closes) - min(closes)) / min(closes) * 100
    recent_vol = sum(to_float(c.get("volume")) for c in ohlcv[-10:]) / 10
    base_vol = sum(to_float(c.get("volume")) for c in ohlcv[-60:-10]) / 50
    return price_range < 15.0 and base_vol > 0 and recent_vol > base_vol * 1.15


def check_candle_rebound(ohlcv: List[Dict[str, Any]]) -> bool:
    if len(ohlcv) < 4:
        return False
    c1, c2, c3, c4 = ohlcv[-4], ohlcv[-3], ohlcv[-2], ohlcv[-1]

    def weak_red(c: Dict[str, Any]) -> bool:
        o = to_float(c.get("open"))
        cl = to_float(c.get("close"))
        return o > cl and cl >= o * 0.995

    reclaim = to_float(c4.get("close")) > to_float(c3.get("open"))
    return weak_red(c1) and weak_red(c2) and weak_red(c3) and reclaim


def check_3insup_pattern(ohlcv: List[Dict[str, Any]]) -> bool:
    if len(ohlcv) < 3:
        return False
    c1, c2, c3 = ohlcv[-3], ohlcv[-2], ohlcv[-1]
    bearish_exhaust = to_float(c1.get("close")) < to_float(c1.get("open")) and (to_float(c1.get("open")) - to_float(c1.get("close"))) / to_float(c1.get("open"), 1) > 0.01
    inside_or_small = to_float(c2.get("high")) <= to_float(c1.get("high")) and to_float(c2.get("low")) >= to_float(c1.get("low"))
    engulf_reclaim = to_float(c3.get("close")) > to_float(c1.get("open")) and to_float(c3.get("close")) > to_float(c3.get("open"))
    return bearish_exhaust and inside_or_small and engulf_reclaim


def check_macd_golden_cross(ohlcv: List[Dict[str, Any]]) -> bool:
    if len(ohlcv) < 35:
        return False
    closes = [to_float(c.get("close")) for c in ohlcv]
    if any(c <= 0 for c in closes[-35:]):
        return False

    def ema(values: List[float], period: int) -> List[float]:
        k = 2 / (period + 1)
        out = [values[0]]
        for v in values[1:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    ema12 = ema(closes[-60:] if len(closes) >= 60 else closes, 12)
    ema26 = ema(closes[-60:] if len(closes) >= 60 else closes, 26)
    macd = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
    signal = ema(macd, 9)
    if len(macd) < 2 or len(signal) < 2:
        return False
    cross = macd[-2] <= signal[-2] and macd[-1] > signal[-1]

    gains, losses = [], []
    for i in range(-14, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 99
    rsi = 100 - (100 / (1 + rs))
    return cross and 50 <= rsi <= 70


def frequency_spike_bonus(mode: Mode, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
    if mode == "scalping" and check_frequency_spike_scalping(ohlcv):
        return {"matched": True, "name": "MICRO_FREQUENCY_SPIKE", "bonus": 8}
    if mode == "intraday" and check_frequency_spike_intraday(ohlcv):
        return {"matched": True, "name": "FREQUENCY_SPIKE_INTRADAY", "bonus": 8}
    if mode == "swing" and check_frequency_spike_swing(ohlcv):
        return {"matched": True, "name": "FREQUENCY_SPIKE_SWING", "bonus": 12}
    return {"matched": False, "name": None, "bonus": 0}


def calculate_pattern_bonus(mode: Mode, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
    patterns: List[Dict[str, Any]] = []

    def add(name: str, bonus: int, ok: bool) -> None:
        if ok:
            patterns.append({"name": name, "bonus": bonus})

    if mode == "scalping":
        add("FLYWINS", 8, check_flywins_pattern(ohlcv))
        add("CANDLE_REBOUND", 5, check_candle_rebound(ohlcv))
        add("MICRO_FREQUENCY_SPIKE", 7, check_frequency_spike_scalping(ohlcv))
    elif mode == "intraday":
        add("3D1UP", 8, check_3d1up_pattern(ohlcv))
        add("3INSUP", 10, check_3insup_pattern(ohlcv))
        add("GOLDEN_CROSS_MACD", 7, check_macd_golden_cross(ohlcv))
        add("FREQUENCY_SPIKE_INTRADAY", 8, check_frequency_spike_intraday(ohlcv))
    else:
        add("SIDEWAYS_ACCUMULATION", 10, check_sideways_accumulation(ohlcv))
        add("NR4", 7, check_narrow_range_pattern(ohlcv, days=4))
        add("NR7", 10, check_narrow_range_pattern(ohlcv, days=7))
        add("3INSUP", 8, check_3insup_pattern(ohlcv))
        add("FREQUENCY_SPIKE_SWING", 12, check_frequency_spike_swing(ohlcv))

    total_bonus = sum(p["bonus"] for p in patterns)
    return {
        "bonus": min(total_bonus, 25),
        "score": clamp(50 + min(total_bonus, 25) * 2),
        "patterns": patterns,
    }


# ===== Phase 3E: RAG KB Boost =====

async def calculate_rag_boost(ticker: str, mode: Mode, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced RAG boost — query spesifik per phase + pattern + mode
    Menggunakan insight dari 12 buku trading di Knowledge Base
    """
    if kb_service is None:
        return {"boost": 0, "reason": "kb_service unavailable"}

    # ── Bandarmologi IDX — query khusus 3 buku sebelum query umum ──
    bandarm_insight = ""
    try:
        from app.core.knowledge_base import query_bandarmologi_kb
        phase_val = context.get("phase", "neutral")
        rvol_val  = context.get("rvol", 1.0)
        bandarm_query = (
            f"Fase bandar IDX: {phase_val}, volume relatif {rvol_val:.1f}x. "
            f"Apakah ini tanda akumulasi atau distribusi bandar IDX? "
            f"Bagaimana ciri-ciri bandar IDX di fase ini?"
        )
        bandarm_insight = await query_bandarmologi_kb(bandarm_query, n_results=3)
    except Exception as e:
        pass

    # Build query spesifik berdasarkan konteks deteksi
    phase = context.get("phase", "neutral")
    rvol = context.get("rvol", 1.0)
    patterns = context.get("patterns", [])
    akumulasi_signals = context.get("akumulasi_signals", [])

    # Query berbeda per phase
    phase_queries = {
        "early_accumulation": "early accumulation phase quiet volume institutional buying bandar akumulasi awal",
        "accumulation": "accumulation phase bandar akumulasi volume naik harga sideways wyckoff phase B",
        "markup": "markup phase breakout volume konfirmasi trend naik institutional buying",
        "accumulation_late": "late accumulation bandar finishing position sebelum breakout",
        "distribution": "distribusi bandar jual institutional selling volume tinggi harga tidak naik",
        "decline": "downtrend bearish avoid tidak masuk posisi",
        "neutral": "volume price analysis setup trading IDX",
    }

    # Query spesifik per mode
    mode_context = {
        "swing": "swing trading 3-30 hari institutional accumulation trend following",
        "intraday": "intraday trading volume spike gap opening momentum hari ini",
        "scalping": "scalping momentum burst orderbook bid ask spread",
    }

    # Pattern context
    pattern_ctx = ""
    if patterns:
        pattern_names = [p.get("name", "") if isinstance(p, dict) else str(p) for p in patterns[:3]]
        pattern_ctx = f"chart pattern {' '.join(pattern_names)}"

    # Akumulasi signal context
    akum_ctx = " ".join(akumulasi_signals[:3]) if akumulasi_signals else ""

    # Build final query — gabungkan dengan insight bandarmologi IDX
    query = (
        f"{phase_queries.get(phase, phase_queries['neutral'])} "
        f"{mode_context.get(mode, '')} "
        f"rvol {rvol} {pattern_ctx} {akum_ctx} "
        f"IDX saham Indonesia trading setup"
    ).strip()

    # Inject bandarmologi insight ke query
    if bandarm_insight:
        query = f"{query} {bandarm_insight[:200]}" 

    # Keywords scoring — lebih komprehensif
    bullish_keywords = [
        "accumulation", "akumulasi", "institutional buying", "bandar beli",
        "volume naik", "breakout", "wyckoff", "markup", "bullish",
        "net buy", "foreign buy", "momentum", "uptrend", "support",
        "quiet accumulation", "demand zone", "absorption"
    ]
    bearish_keywords = [
        "distribution", "distribusi", "selling", "downtrend", "bearish",
        "decline", "avoid", "resistance", "overhead supply"
    ]

    try:
        for method_name in ("search_relevant", "search", "query", "get_context"):
            method = getattr(kb_service, method_name, None)
            if method is None:
                continue
            try:
                result = await call_maybe_async(method, query=query, limit=8)
            except TypeError:
                result = await call_maybe_async(method, query, 8)

            text = str(result or "").lower()
            if not text or len(text) < 50:
                continue

            bull_count = sum(1 for k in bullish_keywords if k in text)
            bear_count = sum(1 for k in bearish_keywords if k in text)

            # Net boost: bullish - bearish, max 8
            net_boost = bull_count - bear_count
            boost = max(0, min(8, net_boost))

            # Bonus kalau phase match dengan KB content
            if phase in ["early_accumulation", "accumulation"] and bull_count >= 3:
                boost = min(8, boost + 2)

            return {
                "boost": boost,
                "reason": f"KB: {bull_count} bullish / {bear_count} bearish signals",
                "source": method_name,
                "query_phase": phase,
                "bull_signals": bull_count,
                "bear_signals": bear_count
            }
    except Exception as exc:
        return {"boost": 0, "reason": f"KB error: {exc}"}

    return {"boost": 0, "reason": "compatible KB method not found"}


# ===== Phase 3 Combined Scoring =====

def final_score(mode: Mode, engine_score: float, bandarm_score: float, foreign_score: float, pattern_score: float, rag_boost: float, akumulasi_score: float = 50.0) -> float:
    w = MODE_CONFIG[mode]["final_weights"]
    score = (
        engine_score * w["engine"]
        + bandarm_score * w["bandarmology"]
        + foreign_score * w["foreign"]
        + pattern_score * w["pattern"]
        + (rag_boost * 12.5) * w["rag"]  # rag_boost 0-8 normalized to 0-100
    )
    # Fase 2B akumulasi multiplier — adaptive per mode
    score = apply_akumulasi_multiplier(score, akumulasi_score, mode)
    return round(clamp(score), 2)


def signal_from_score(score: float) -> str:
    if score >= 80:
        return "STRONG BUY"
    if score >= 70:
        return "BUY"
    if score >= 60:
        return "WATCHLIST"
    return "NEUTRAL"


def build_reason(item: Dict[str, Any]) -> str:
    patterns = [p["name"] for p in item.get("patterns", [])]
    bits = [
        f"Score {item['final_score']}",
        f"RVOL {item.get('rvol')}",
        f"change {item.get('change_pct')}%",
        f"phase {item.get('phase')}",
        f"Bandar MACD {item.get('bandar_macd', {}).get('signal')}",
        f"foreign {item.get('foreign_flow', {}).get('signal')}",
    ]
    if patterns:
        bits.append("pattern " + ", ".join(patterns[:3]))
    return "; ".join(bits)


async def score_one(candidate: Dict[str, Any], mode: Mode, semaphore: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
    async with semaphore:
        ticker = candidate["ticker"]
        ohlcv = candidate["ohlcv"]

        try:
            engine_raw = await asyncio.wait_for(run_master_engines_safe(ticker, mode, ohlcv), timeout=45)
        except Exception as exc:
            engine_raw = {"error": str(exc), "score": 50}

        engine_score, engine_meta = weighted_engine_score(engine_raw, mode)

        bandarm = await bandarmology_composite(
            ticker=ticker,
            mode=mode,
            ohlcv=ohlcv,
            rvol=to_float(candidate.get("rvol")),
            change_pct=to_float(candidate.get("change_pct")),
        )

        foreign = calculate_foreign_flow_proxy(ohlcv, bandarm)
        pattern = calculate_pattern_bonus(mode, ohlcv)

        # Fase 2B — Bandar Early Detection (harus sebelum rag)
        try:
            bandar_early = await asyncio.wait_for(
                get_bandar_early_score(ticker, mode, ohlcv), timeout=10
            )
            akumulasi_score = bandar_early.get("akumulasi_score", 50.0)
        except Exception:
            bandar_early = {"akumulasi_score": 50.0, "signals": [], "mode": mode}
            akumulasi_score = 50.0

        rag = await calculate_rag_boost(ticker, mode, {
            "phase": bandarm.get("phase"),
            "rvol": candidate.get("rvol"),
            "patterns": pattern.get("patterns"),
            "akumulasi_signals": bandar_early.get("signals", []),
        })

        fscore = final_score(
            mode=mode,
            engine_score=engine_score,
            bandarm_score=to_float(bandarm.get("score")),
            foreign_score=to_float(foreign.get("score")),
            pattern_score=to_float(pattern.get("score")),
            rag_boost=to_float(rag.get("boost")),
            akumulasi_score=akumulasi_score,
        )

        result = {
            "ticker": ticker,
            "code": ticker,
            "name": candidate.get("name"),
            "sector": candidate.get("sector"),
            "price": candidate.get("price"),
            "change_pct": candidate.get("change_pct"),
            "rvol": candidate.get("rvol"),
            "volume": candidate.get("volume"),
            "final_score": fscore,
            "signal": signal_from_score(fscore),
            "engine_score": engine_score,
            "engine_meta": engine_meta,
            "bandarmology_composite": bandarm.get("score"),
            "bandarmology": bandarm,
            "bandar_macd": bandarm.get("bandar_macd"),
            "phase": bandarm.get("phase"),
            "bandar_early": bandar_early,
            "akumulasi_score": akumulasi_score,
            "akumulasi_signals": bandar_early.get("signals", []),
            "foreign_flow_score": foreign.get("score"),
            "foreign_flow": foreign,
            "pattern_bonus": pattern.get("bonus"),
            "pattern_score": pattern.get("score"),
            "patterns": pattern.get("patterns"),
            "rag_boost": rag.get("boost"),
            "rag": rag,
            "disqualify": bool(bandarm.get("disqualify") or foreign.get("heavy_sell")),
            "disqualify_reason": None,
            "reason": "",
        }

        if bandarm.get("disqualify"):
            result["disqualify_reason"] = "Bandarmology phase/MACD disqualify"
        elif foreign.get("heavy_sell"):
            result["disqualify_reason"] = "Foreign heavy sell + weak/distribution condition"

        result["reason"] = build_reason(result)
        return result


async def score_candidates(candidates: List[Dict[str, Any]], mode: Mode) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(3)
    tasks = [score_one(c, mode, sem) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


# ===== Phase 4 and 5 =====

def apply_disqualifiers(scored: List[Dict[str, Any]], mode: Mode) -> List[Dict[str, Any]]:
    min_score = MODE_CONFIG[mode]["min_score"]
    qualified: List[Dict[str, Any]] = []

    for item in scored:
        phase = str(item.get("phase", "")).lower()
        if phase in {"distribution", "decline"}:
            item["disqualify"] = True
            item["disqualify_reason"] = f"Phase {phase} = DISQUALIFY TOTAL"
            continue

        if item.get("disqualify"):
            continue

        if to_float(item.get("final_score")) < min_score:
            item["disqualify"] = True
            item["disqualify_reason"] = f"Score below threshold {min_score}"
            continue

        qualified.append(item)

    return qualified


def rank_top(qualified: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    qualified.sort(
        key=lambda x: (
            to_float(x.get("final_score")),
            to_float(x.get("bandarmology_composite")),
            to_float(x.get("rvol")),
        ),
        reverse=True,
    )
    return qualified[:limit]


# ===== Optional endpoint testing market endpoints =====

@router.get("/test-endpoints")
async def test_endpoints() -> Dict[str, Any]:
    tests = {}
    for name in ("get_stock_list", "get_top_gainer", "get_top_loser", "get_foreign_net", "get_market_summary"):
        started = time.time()
        try:
            data = await invesgo_call(name)
            if isinstance(data, dict):
                preview = list(data.keys())[:10]
                count = len(data.get("data", [])) if isinstance(data.get("data"), list) else None
            elif isinstance(data, list):
                preview = list(data[0].keys())[:10] if data and isinstance(data[0], dict) else []
                count = len(data)
            else:
                preview = str(type(data))
                count = None
            tests[name.replace("get_", "")] = {
                "status": "OK",
                "count": count,
                "fields": preview,
                "duration_ms": round((time.time() - started) * 1000, 2),
            }
        except Exception as exc:
            tests[name.replace("get_", "")] = {
                "status": "ERROR",
                "error": str(exc),
                "duration_ms": round((time.time() - started) * 1000, 2),
            }
    # Extra OHLCV diagnostics for market holiday / fallback validation
    tests["ohlcv_bbca"] = {}
    started = time.time()
    try:
        raw = await invesgo_call("get_ohlcv_daily", "BBCA")
        normalized = normalize_ohlcv(raw)
        tests["ohlcv_bbca"] = {
            "status": "OK",
            "raw_type": str(type(raw)),
            "raw_keys": list(raw.keys())[:10] if isinstance(raw, dict) else None,
            "raw_count": len(raw) if isinstance(raw, list) else None,
            "normalized_count": len(normalized),
            "last_candle": normalized[-1] if normalized else None,
            "duration_ms": round((time.time() - started) * 1000, 2),
        }
    except Exception as exc:
        tests["ohlcv_bbca"] = {
            "status": "ERROR",
            "error": str(exc),
            "duration_ms": round((time.time() - started) * 1000, 2),
        }

    return tests


# ===== Main API =====

@router.post("/run")
async def run_screener(request: ScreenerRequest) -> Dict[str, Any]:
    started = time.time()
    mode: Mode = request.mode
    cfg = MODE_CONFIG[mode]

    universe = await build_universe(mode)
    candidates = await ohlcv_prefilter(universe, mode, request.filter_intensity)
    scored = await score_candidates(candidates, mode)
    qualified = apply_disqualifiers(scored, mode)
    top = rank_top(qualified, request.limit)

    response: Dict[str, Any] = {
        "status": "ok",
        "mode": mode,
        "duration_sec": round(time.time() - started, 2),
        "universe_count": len(universe),
        "candidate_count": len(candidates),
        "scored_count": len(scored),
        "qualified_count": len(qualified),
        "top_5": top,
        "results": top,
        "config": {
            "rvol_min": cfg["rvol_min"],
            "change_min": cfg["change_min"],
            "candidate_max": cfg["candidate_max"],
            "min_score": cfg["min_score"],
        },
    }

    if request.include_debug:
        disqualified = [x for x in scored if x.get("disqualify")]
        response["debug"] = {
            "disqualified_count": len(disqualified),
            "disqualified_sample": [
                {
                    "ticker": x.get("ticker"),
                    "score": x.get("final_score"),
                    "phase": x.get("phase"),
                    "reason": x.get("disqualify_reason"),
                }
                for x in disqualified[:20]
            ],
        }

    return response
