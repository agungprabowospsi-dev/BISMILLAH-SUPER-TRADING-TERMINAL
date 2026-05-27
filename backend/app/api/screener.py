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
import logging
import math
import re
import time
import zipfile
from datetime import date, timedelta
from io import BytesIO
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ===== Defensive imports for existing project structure =====

try:
    from app.core import invesgo
    from app.core.official_enrichment import enrich_screener_results
    from app.core.money_maker import analyze_money_maker_context
    from app.core.money_maker_store import get_latest_flow_snapshot_cloud, save_money_maker_cloud
    from app.api.bandar_early_detection import get_bandar_early_score, apply_akumulasi_multiplier
except Exception:
    invesgo = None
    enrich_screener_results = None
    analyze_money_maker_context = None
    get_latest_flow_snapshot_cloud = None
    save_money_maker_cloud = None
    get_bandar_early_score = None
    apply_akumulasi_multiplier = None

# SC-1: Fallback apply_akumulasi_multiplier — cegah crash jika import gagal
def _safe_akumulasi_multiplier(score: float, akumulasi_score: float, mode: str) -> float:
    """Fallback jika apply_akumulasi_multiplier tidak tersedia"""
    if apply_akumulasi_multiplier is not None:
        try:
            return apply_akumulasi_multiplier(score, akumulasi_score, mode)
        except Exception:
            pass
    # Fallback manual: akumulasi_score > 65 → bonus kecil
    if akumulasi_score >= 70:
        return min(100.0, score * 1.05)
    elif akumulasi_score >= 60:
        return min(100.0, score * 1.02)
    elif akumulasi_score < 35:
        return score * 0.95
    return score

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
    try:
        return await call_maybe_async(method, *args, **kwargs)
    except Exception as exc:
        logger.warning("[SCREENER] Invesgo call %s failed: %s", method_name, exc)
        return None


def _pct_change(close: Any, prev: Any) -> float:
    close_f = to_float(close)
    prev_f = to_float(prev)
    if close_f <= 0 or prev_f <= 0:
        return 0.0
    return ((close_f - prev_f) / prev_f) * 100


async def build_market_execution_regime() -> Dict[str, Any]:
    """Classify whether Screener should run normal execution or bad-market opportunity lanes."""
    data = await invesgo_call("get_market_regime") or {}
    ihsg = data.get("IHSG", {}) if isinstance(data, dict) else {}
    lq45 = data.get("LQ45", {}) if isinstance(data, dict) else {}
    top_gainer = data.get("top_gainer", []) if isinstance(data, dict) else []
    top_loser = data.get("top_loser", []) if isinstance(data, dict) else []
    ihsg_change = _pct_change(ihsg.get("close"), ihsg.get("prev"))
    lq45_change = _pct_change(lq45.get("close"), lq45.get("prev"))
    total_movers = len(top_gainer or []) + len(top_loser or [])
    breadth = round((len(top_gainer or []) / total_movers) * 100, 1) if total_movers else 50.0
    has_top_gainer = bool(top_gainer)

    if ihsg_change <= -0.75 or lq45_change <= -0.75 or breadth < 40:
        key = "BAD_MARKET_OPPORTUNITY_ONLY" if has_top_gainer else "DEFENSIVE_NO_CHASE"
        label = "Bad Market Opportunity Only" if has_top_gainer else "Defensive No-Chase"
        policy = "Full screener tetap dihitung, tetapi execution lane diprioritaskan hanya untuk mover kuat yang lolos guardrail."
    elif ihsg_change >= 0.35 and lq45_change >= 0 and breadth >= 50:
        key = "NORMAL_GREEN_MARKET"
        label = "Normal Green Market"
        policy = "Full-variable screener boleh menjadi execution candidate setelah Analytical validasi."
    else:
        key = "MIXED_MARKET"
        label = "Mixed Market"
        policy = "Full-variable screener berjalan, tetapi entry tetap butuh konfirmasi struktur dan flow."

    return {
        "key": key,
        "label": label,
        "policy": policy,
        "ihsg_change_pct": round(ihsg_change, 2),
        "lq45_change_pct": round(lq45_change, 2),
        "breadth_pct": breadth,
        "top_gainer_count": len(top_gainer or []),
        "top_loser_count": len(top_loser or []),
        "sample_top_gainers": [
            str((x or {}).get("code") or (x or {}).get("ticker") or "").upper()
            for x in (top_gainer or [])[:5]
            if isinstance(x, dict)
        ],
    }


def annotate_screener_lanes(items: List[Dict[str, Any]], market_regime: Dict[str, Any], watchlist_fallback_used: bool = False) -> List[Dict[str, Any]]:
    """Attach user-facing lane labels that Analytical can consume without guessing."""
    regime_key = (market_regime or {}).get("key", "MIXED_MARKET")
    annotated: List[Dict[str, Any]] = []
    for raw in items or []:
        item = dict(raw)
        top_opp = item.get("top_gainer_opportunity") if isinstance(item.get("top_gainer_opportunity"), dict) else {}
        if item.get("no_chase_radar") or top_opp.get("radar_only"):
            lane = "NO_CHASE_RADAR"
            expectation = "RADAR_ONLY_WAIT_RESET_BASE"
        elif top_opp.get("available"):
            lane = "TOP_GAINER_OPPORTUNITY"
            expectation = "ANALYTIC_CONDITIONAL_BUY_STOP_REVIEW"
        elif item.get("watchlist_only") or watchlist_fallback_used:
            lane = "WATCHLIST_ONLY"
            expectation = "ANALYTIC_WAIT_CONFIRMATION_REVIEW"
        elif regime_key in ("BAD_MARKET_OPPORTUNITY_ONLY", "DEFENSIVE_NO_CHASE"):
            lane = "DEFENSIVE_QUALIFIED_CANDIDATE"
            expectation = "ANALYTIC_STRICT_CONFIRMATION_REQUIRED"
        else:
            lane = "EXECUTION_CANDIDATE"
            expectation = "ANALYTIC_FULL_VARIABLE_REVIEW"
        item["market_execution_regime"] = regime_key
        item["screener_lane"] = lane
        item["analytic_expectation"] = expectation
        item["execution_candidate"] = lane in ("EXECUTION_CANDIDATE", "TOP_GAINER_OPPORTUNITY")
        annotated.append(item)
    return annotated


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
    # Opening momentum/top-gainer radar names often outside IDX80 coverage
    "TPIA", "NZIA", "SIPD", "FILM", "BUMI", "BIPI", "BUVA", "BRPT", "MBMA", "NCKL",
]

OPENING_MOMENTUM_RADAR_TICKERS = [
    "TPIA", "NZIA", "CUAN", "SIPD", "AMMN", "FILM", "BREN", "BRPT", "BUMI", "BIPI", "BUVA", "MBMA", "NCKL",
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
            "_default_universe_seed": True,
        }
        for ticker in DEFAULT_UNIVERSE_TICKERS
    ]


def merge_default_universe(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_code = {str(s.get("ticker") or s.get("code") or "").upper(): s for s in stocks}
    for seed in DEFAULT_UNIVERSE_TICKERS:
        code = seed.upper()
        if code in by_code:
            by_code[code]["_default_universe_seed"] = True
            continue
        stocks.append({
            "ticker": code,
            "code": code,
            "name": code,
            "sector": "",
            "logo": None,
            "raw": {"source": "default_universe_seed"},
            "_default_universe_seed": True,
        })
    return stocks


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


async def build_universe(mode: str) -> list:
    """
    Phase 1 Universe Filter — berbasis kriteria likuiditas + index membership.
    Gate 1: active status
    Gate 2: bukan warrant/right
    Gate 3: sector filter per mode
    Gate 4: LQ45/MSCI priority + liquidity filter (value IDR + freq)
    """
    import asyncio
    import json as _j

    # Tier 0: LQ45 + MSCI Indonesia intersection (~48 ticker)
    TIER0_TICKERS = {
        "BBCA","BBRI","BMRI","TLKM","ASII","ADRO","ANTM","BYAN",
        "ICBP","INDF","KLBF","MAPI","MDKA","PTBA","SMGR","UNVR",
        "AMMN","PGAS","GOTO","EXCL","INCO","MEDC","TOWR","BUKA",
        "BBNI","BSDE","CPIN","GGRM","HMSP","INTP","ITMG","JPFA",
        "JSMR","MYOR","INKP","TKIM","TBIG","ISAT","AKRA","AMRT",
        "BRPT","CTRA","HEAL","PGEO","SMRA","ULTJ","WIFI","HRTA",
    }

    # Tier 1: IDX80 diluar LQ45/MSCI (~32 ticker)
    TIER1_TICKERS = {
        "ACES","AALI","LSIP","SCMA","MNCN","EMTK","SIDO","HRUM",
        "ESSA","ERAA","FILM","BJBR","NIKEL","TBIG","WSKT","WIKA",
        "ADHI","PTPP","NCKL","DOID","ADMR","MBMA","MAPA","MIDI",
        "MIKA","SILO","TSPC","DVLA","KAEF","PEHA","PYFA","SOHO",
    }

    stocks = await get_stock_list_safe()
    if not stocks:
        stocks = fallback_stock_universe()
    else:
        stocks = merge_default_universe(stocks)

    mover_map: Dict[str, Dict[str, Any]] = {}
    try:
        top_gainers = await invesgo_call("get_top_gainer") or []
        for idx, row in enumerate(top_gainers[:30], start=1):
            if not isinstance(row, dict):
                continue
            code = str(row.get("ticker") or row.get("code") or "").upper()
            change_pct = to_float(row.get("change_pct") or row.get("change"))
            if not code or change_pct < 5:
                continue
            mover_map[code] = {
                "rank": idx,
                "change_pct": change_pct,
                "source": row.get("source") or "top_gainer",
                "name": row.get("name") or code,
                "price": row.get("close") or row.get("price") or row.get("last_price"),
            }
    except Exception as exc:
        logger.debug("[UNIVERSE] top gainer lane unavailable: %s", exc)

    if not mover_map:
        for row in stocks:
            raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
            code = str(row.get("ticker") or row.get("code") or raw.get("code") or raw.get("ticker") or "").upper()
            change_pct = to_float(
                row.get("change_pct")
                or row.get("change_percent")
                or raw.get("change_pct")
                or raw.get("change_percent")
                or raw.get("pct_change")
                or raw.get("percent")
            )
            if not code or change_pct < 5:
                continue
            mover_map[code] = {
                "rank": len(mover_map) + 1,
                "change_pct": change_pct,
                "source": "stock_list_change_fallback",
                "name": row.get("name") or raw.get("name") or code,
                "price": row.get("price") or row.get("last_price") or raw.get("close") or raw.get("price") or raw.get("last_price"),
            }

    if mover_map:
        by_code = {str(s.get("ticker") or s.get("code") or "").upper(): s for s in stocks}
        for code, meta in mover_map.items():
            stock = by_code.get(code)
            if stock is None:
                stock = {"ticker": code, "code": code, "name": meta.get("name"), "sector": "", "raw": {"source": "top_gainer_lane"}}
                stocks.append(stock)
                by_code[code] = stock
            stock["_opportunity_lane"] = "top_gainer"
            stock["_mover_rank"] = meta.get("rank")
            stock["_mover_change_pct"] = meta.get("change_pct")
            stock["_mover_price"] = meta.get("price")
            stock["_mover_source"] = meta.get("source")

    # Gate 1: drop suspended/delisted
    stocks = [s for s in stocks if s.get("active", True) is not False]

    # Gate 2: drop warrant/right/serial
    stocks = [s for s in stocks
              if "-" not in str(s.get("ticker",""))
              and not str(s.get("ticker","")).endswith(("W","R","S"))]

    # Gate 3: sector filter
    stocks = [s for s in stocks if sector_allowed(mode, s.get("sector",""))]

    # Pre-assign tier dari hardcoded list (tidak tergantung cache)
    for s in stocks:
        t = s.get("ticker","").upper()
        if t in TIER0_TICKERS:
            s["_idx_tier"] = 0
        elif t in TIER1_TICKERS:
            s["_idx_tier"] = 1
        else:
            s["_idx_tier"] = 2

    # Gate 4: liquidity scoring — semua ticker, bukan hanya 200 pertama
    # Tapi batasi API call: tier0+tier1 semua, tier2 maksimal 150
    tier0 = [s for s in stocks if s["_idx_tier"] == 0]
    tier1 = [s for s in stocks if s["_idx_tier"] == 1]
    tier2 = [s for s in stocks if s["_idx_tier"] == 2][:150]
    movers = [s for s in stocks if s.get("_opportunity_lane") == "top_gainer"]
    to_score_map = {s.get("ticker"): s for s in (tier0 + tier1 + tier2 + movers)}
    to_score = list(to_score_map.values())

    async def score_liquidity(stock):
        ticker = stock.get("ticker","")
        try:
            intraday = await invesgo_call("get_ohlcv_intraday", ticker, market="RG")
            if not intraday:
                return {**stock, "_liq_value": 0, "_liq_freq": 0}
            value = float(intraday.get("value", 0) or 0)
            freq  = float(intraday.get("freq",  0) or 0)
            # Enrich tier dari category jika ada di cache
            info_cached = await invesgo_call("_cache_get", f"info:{ticker}")
            if info_cached and stock["_idx_tier"] == 2:
                try:
                    info = _j.loads(info_cached)
                    cats = info.get("category", []) or []
                    if any(c in cats for c in ["LQ45","IDX30","IDXBUMN30","MSCI"]):
                        stock["_idx_tier"] = 0
                    elif any(c in cats for c in ["IDX80","IDXFINANCE","IDXENERGY"]):
                        stock["_idx_tier"] = 1
                except Exception:
                    pass
            return {**stock, "_liq_value": value, "_liq_freq": freq}
        except Exception:
            return {**stock, "_liq_value": 0, "_liq_freq": 0}

    sem = asyncio.Semaphore(10)
    async def score_with_sem(stock):
        async with sem:
            return await score_liquidity(stock)

    scored = await asyncio.gather(*[score_with_sem(s) for s in to_score])

    VALUE_TIER = {0: 1e9, 1: 2e9}
    FREQ_TIER  = {0: 200, 1: 500}
    VALUE_MIN  = {"swing": 5e9,  "intraday": 10e9, "scalping": 20e9}
    FREQ_MIN   = {"swing": 1000, "intraday": 3000,  "scalping": 5000}

    passed = []
    soft   = []
    dropped_tickers = set()

    for s in scored:
        tier   = s.get("_idx_tier", 2)
        value  = s.get("_liq_value", 0)
        freq   = s.get("_liq_freq", 0)
        ticker = s.get("ticker", "")
        raw_source = ""
        if isinstance(s.get("raw"), dict):
            raw_source = str(s["raw"].get("source") or "")

        if value == 0 and freq == 0 and s.get("_opportunity_lane") == "top_gainer":
            s["_liquidity_fallback"] = True
            soft.append(s)
            continue
        if value == 0 and freq == 0 and (raw_source == "default_universe_seed" or s.get("_default_universe_seed")):
            s["_liquidity_fallback"] = True
            soft.append(s)
            continue
        if value == 0 and freq == 0:
            dropped_tickers.add(ticker)
            continue

        if tier <= 1:
            v_min = VALUE_TIER.get(tier, 1e9)
            f_min = FREQ_TIER.get(tier, 200)
        else:
            v_min = VALUE_MIN.get(mode, 5e9)
            f_min = FREQ_MIN.get(mode, 1000)

        if value >= v_min and freq >= f_min:
            passed.append(s)
        elif value > 0 and freq > 100:
            soft.append(s)
        else:
            dropped_tickers.add(ticker)

    # Sort: tier dulu, lalu value DESC
    passed.sort(key=lambda x: (x.get("_idx_tier",2), -x.get("_liq_value",0)))
    soft.sort(key=lambda x: (x.get("_idx_tier",2), -x.get("_liq_value",0)))

    final = passed + soft
    if not final and to_score:
        logger.warning(
            "[UNIVERSE] liquidity gate returned no stocks; using tiered fallback universe"
        )
        final = sorted(to_score, key=lambda x: x.get("_idx_tier", 2))[:80]
        for s in final:
            s.setdefault("_liq_value", 0)
            s.setdefault("_liq_freq", 0)
            s["_liquidity_fallback"] = True

    logger.info(
        f"[UNIVERSE] mode={mode} total_input={len(stocks)} "
        f"scored={len(scored)} passed={len(passed)} soft={len(soft)} "
        f"dropped={len(dropped_tickers)} "
        f"tier0={len([s for s in passed if s.get('_idx_tier')==0])} "
        f"tier1={len([s for s in passed if s.get('_idx_tier')==1])}"
    )

    return final


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
    vpa = analyze_vpa_variables(ohlcv, rvol, change_pct)

    return {
        "date": last.get("date"),
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
        "vpa": vpa,
        "vpa_score": vpa["score"],
        "vpa_state": vpa["state"],
        "vpa_signals": vpa["signals"],
        "vpa_distribution_risk": vpa["distribution_risk"],
        "downtrend_heavy": downtrend_heavy,
    }


def analyze_vpa_variables(ohlcv: List[Dict[str, Any]], rvol: float, change_pct: float) -> Dict[str, Any]:
    """
    Internal Volume Price Analysis variables.
    This is not a separate Screener gate; it enriches scoring, disqualifier,
    lane explanation, and Analytical context.
    """
    if len(ohlcv) < 21:
        return {
            "score": 50.0,
            "state": "VPA_NEUTRAL",
            "signals": [],
            "distribution_risk": False,
            "confirmation": False,
        }

    last = ohlcv[-1]
    prev = ohlcv[-2]
    open_f = to_float(last.get("open"))
    high = to_float(last.get("high"))
    low = to_float(last.get("low"))
    close = to_float(last.get("close"))
    prev_close = to_float(prev.get("close"))
    prev_high = to_float(prev.get("high"))
    if min(open_f, high, low, close, prev_close) <= 0 or high <= low:
        return {
            "score": 50.0,
            "state": "VPA_NEUTRAL",
            "signals": [],
            "distribution_risk": False,
            "confirmation": False,
        }

    ranges = [
        max(0.0, to_float(c.get("high")) - to_float(c.get("low")))
        for c in ohlcv[-21:-1]
        if to_float(c.get("high")) > to_float(c.get("low"))
    ]
    avg_range = sum(ranges) / len(ranges) if ranges else (high - low)
    candle_range = high - low
    body = abs(close - open_f)
    upper_wick = max(0.0, high - max(open_f, close))
    lower_wick = max(0.0, min(open_f, close) - low)

    close_position = (close - low) / candle_range
    body_ratio = body / candle_range
    upper_wick_pct = upper_wick / candle_range
    lower_wick_pct = lower_wick / candle_range
    spread_ratio = candle_range / avg_range if avg_range > 0 else 1.0
    price_up = close > prev_close
    candle_bullish = close > open_f

    signals: List[str] = []
    score = 50.0

    bullish_effort = (
        price_up
        and candle_bullish
        and rvol >= 1.2
        and close_position >= 0.65
        and body_ratio >= 0.35
        and upper_wick_pct <= 0.35
    )
    healthy_advance = (
        price_up
        and close_position >= 0.55
        and 0.75 <= rvol <= 1.8
        and upper_wick_pct <= 0.35
    )
    absorption = rvol >= 1.5 and lower_wick_pct >= 0.35 and close_position >= 0.55
    stopping_volume = (not price_up) and rvol >= 2.0 and lower_wick_pct >= 0.35 and close_position >= 0.45
    no_demand = price_up and rvol < 0.7 and spread_ratio <= 0.95 and upper_wick_pct >= 0.20
    upthrust = high > prev_high and close_position <= 0.45 and upper_wick_pct >= 0.35 and rvol >= 1.3
    effort_no_result = rvol >= 1.8 and body_ratio <= 0.35 and 0.30 <= close_position <= 0.70
    climax_extension = change_pct > 15 and rvol > 2.0 and (close_position < 0.65 or upper_wick_pct >= 0.30)

    if bullish_effort:
        signals.append("BULLISH_EFFORT_CONFIRMED")
        score += 18
    elif healthy_advance:
        signals.append("HEALTHY_ADVANCE")
        score += 8

    if absorption:
        signals.append("ABSORPTION")
        score += 12
    if stopping_volume:
        signals.append("STOPPING_VOLUME")
        score += 8
    if close_position >= 0.70:
        score += 8
    elif close_position <= 0.35:
        score -= 10
    if spread_ratio >= 1.25 and close_position >= 0.60:
        score += 6
    elif spread_ratio >= 1.6 and close_position <= 0.45:
        score -= 8
    if upper_wick_pct >= 0.45:
        signals.append("UPPER_WICK_REJECTION")
        score -= 12
    if rvol >= 1.5 and not price_up:
        signals.append("HIGH_VOLUME_PRICE_DOWN")
        score -= 15
    if no_demand:
        signals.append("NO_DEMAND")
        score -= 12
    if effort_no_result:
        signals.append("EFFORT_NO_RESULT")
        score -= 12
    if upthrust:
        signals.append("UPTHRUST")
        score -= 25
    if climax_extension:
        signals.append("CLIMAX_EXTENSION_RISK")
        score -= 30

    distribution_risk = any(
        sig in signals
        for sig in ("UPTHRUST", "CLIMAX_EXTENSION_RISK", "HIGH_VOLUME_PRICE_DOWN")
    ) or sum(sig in signals for sig in ("NO_DEMAND", "EFFORT_NO_RESULT", "UPPER_WICK_REJECTION")) >= 2
    confirmation = any(sig in signals for sig in ("BULLISH_EFFORT_CONFIRMED", "HEALTHY_ADVANCE", "ABSORPTION", "STOPPING_VOLUME"))
    score = round(clamp(score), 2)
    if distribution_risk:
        state = "VPA_DISTRIBUTION_RISK"
    elif score >= 68:
        state = "VPA_CONFIRMED"
    elif score <= 42:
        state = "VPA_WARNING"
    else:
        state = "VPA_NEUTRAL"

    return {
        "score": score,
        "state": state,
        "signals": list(dict.fromkeys(signals)),
        "distribution_risk": bool(distribution_risk),
        "confirmation": bool(confirmation),
        "close_position": round(close_position, 2),
        "body_ratio": round(body_ratio, 2),
        "upper_wick_pct": round(upper_wick_pct, 2),
        "lower_wick_pct": round(lower_wick_pct, 2),
        "spread_ratio": round(spread_ratio, 2),
        "rvol": round(float(rvol or 0), 2),
        "change_pct": round(float(change_pct or 0), 2),
    }


def _adaptive_gate(mode: Mode, filter_intensity: int, adaptive: bool = False) -> Dict[str, float]:
    cfg = MODE_CONFIG[mode]
    if adaptive:
        return {
            "rvol_min": {"swing": 0.45, "intraday": 0.45, "scalping": 1.0}.get(mode, 0.5),
            "change_min": {"swing": -1.5, "intraday": -1.0, "scalping": 0.5}.get(mode, 0.0),
        }
    if filter_intensity <= 50:
        multiplier = 0.55
    elif filter_intensity <= 75:
        multiplier = 0.75
    else:
        multiplier = 1.0
    return {
        "rvol_min": cfg["rvol_min"] * multiplier,
        "change_min": cfg["change_min"],
    }


def _allow_live_metrics_with_stale_date(metrics: Dict[str, Any], gate: Dict[str, float]) -> bool:
    """
    Invezgo opening feed can update price/volume while leaving the OHLCV date
    on the previous trading day. Keep the row only when live-like metrics are
    already moving, then let the normal rvol/change gates decide.
    """
    volume = to_float(metrics.get("volume"))
    avg_volume = to_float(metrics.get("avg_volume_20"))
    rvol = to_float(metrics.get("rvol"))
    change_pct = to_float(metrics.get("change_pct"))
    price = to_float(metrics.get("price"))
    high = to_float(metrics.get("high"))
    low = to_float(metrics.get("low"))
    min_change = max(0.5, min(to_float(gate.get("change_min")), 1.0))
    min_rvol = max(0.25, min(to_float(gate.get("rvol_min")), 0.75))
    has_active_range = high > 0 and low > 0 and high != low
    return (
        price > 0
        and volume > 0
        and avg_volume > 0
        and rvol >= min_rvol
        and change_pct >= min_change
        and has_active_range
    )


async def prefilter_one(stock: Dict[str, Any], mode: Mode, semaphore: asyncio.Semaphore, filter_intensity: int = 75, adaptive: bool = False) -> Optional[Dict[str, Any]]:
    ticker = stock["ticker"]
    cfg = MODE_CONFIG[mode]
    gate = _adaptive_gate(mode, filter_intensity, adaptive=adaptive)

    async with semaphore:
        try:
            ohlcv = await asyncio.wait_for(fetch_ohlcv_safe(ticker), timeout=10)
            metrics = calc_prefilter_metrics(ohlcv)
            if not metrics:
                return None

            price = metrics["price"]
            is_top_gainer_lane = stock.get("_opportunity_lane") == "top_gainer"
            price_min = 50 if is_top_gainer_lane and mode in ("intraday", "scalping") else cfg["price_min"]
            if price < price_min or price > cfg["price_max"]:
                return None

            # Filter saham suspended — dari field Invesgo + OHLCV check
            raw_stock = stock.get("raw", {}) if isinstance(stock.get("raw"), dict) else {}
            suspend_value = (
                stock.get("suspend", None)
                if stock.get("suspend", None) is not None
                else raw_stock.get("suspend", 0)
            )
            if int(suspend_value or 0) > 0:
                return None

            # Filter stale OHLCV untuk mode cepat:
            # jika candle terakhir bukan hari ini, anggap saham tidak aktif/suspended/stale.
            if mode in ("intraday", "scalping"):
                from datetime import datetime
                last_date_raw = str(metrics.get("date") or "")[:10]
                today_str = datetime.now().strftime("%Y-%m-%d")
                if last_date_raw and last_date_raw != today_str:
                    if is_top_gainer_lane and to_float(stock.get("_mover_change_pct")) >= 5:
                        mover_price = to_float(stock.get("_mover_price"))
                        if mover_price > 0:
                            metrics["price"] = mover_price
                        metrics["change_pct"] = round(to_float(stock.get("_mover_change_pct")), 2)
                        metrics["date_status"] = "STALE_DAILY_TOP_GAINER_FALLBACK"
                        metrics["data_warning"] = (
                            "Daily OHLCV belum update hari ini; top gainer dipertahankan sebagai radar opening, "
                            "bukan entry otomatis."
                        )
                    elif _allow_live_metrics_with_stale_date(metrics, gate):
                        metrics["date_status"] = "LIVE_PRICE_STALE_DATE"
                        metrics["data_warning"] = (
                            "Harga/volume sudah bergerak, tetapi tanggal OHLCV Invezgo masih hari bursa sebelumnya. "
                            "Sinyal boleh direview, entry tetap tunggu konfirmasi analytical."
                        )
                    else:
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

            effective_rvol_gate = min(gate["rvol_min"], 0.25) if is_top_gainer_lane and metrics.get("change_pct", 0) >= 5 else gate["rvol_min"]
            effective_change_gate = min(gate["change_min"], 5.0) if is_top_gainer_lane else gate["change_min"]

            if metrics["rvol"] < effective_rvol_gate:
                return None

            if metrics["change_pct"] < effective_change_gate:
                return None

            # Anti Climax Distribution Filter (Bandar Flow Secrets hal.26)
            # "Climax distribution: change > 15% + volume meledak = bandar pamit"
            if mode == "swing":
                # Swing: ketat — change > 15% + rvol > 2 = SKIP
                if change_pct_now > 15 and metrics["rvol"] > 2.0:
                    return None
            elif mode == "intraday":
                # Intraday: semi-ketat — change > 20% + rvol > 3 = SKIP
                # change 15-20% masih bisa valid untuk intraday momentum
                if change_pct_now > 20 and metrics["rvol"] > 3.0:
                    metrics["date_status"] = metrics.get("date_status") or "NO_CHASE_ANTI_CLIMAX_RADAR"
                    metrics["data_warning"] = (
                        "Kena anti-climax intraday: kenaikan >20% dengan RVOL tinggi. "
                        "Ditampilkan sebagai no-chase radar, bukan kandidat entry."
                    )
            elif mode == "scalping":
                # Scalping: longgar — hanya filter ARA murni (>= 24% sudah difilter)
                # TAPI filter saham dengan rvol sangat ekstrem + change tinggi
                # yang kemungkinan besar sudah di puncak distribusi
                if change_pct_now > 22 and metrics["rvol"] > 5.0:
                    metrics["date_status"] = metrics.get("date_status") or "NO_CHASE_ANTI_CLIMAX_RADAR"
                    metrics["data_warning"] = (
                        "Kena anti-climax scalping: extension terlalu tinggi dengan RVOL ekstrem. "
                        "Ditampilkan sebagai no-chase radar."
                    )

            if mode == "scalping" and metrics["downtrend_heavy"]:
                return None

            # ===== FASE 1: Smart Pre-Filter per Mode =====
            price = metrics["price"]
            ma5 = metrics.get("ma5", price)
            ma20 = metrics.get("ma20", price)
            candle_bullish = metrics.get("candle_bullish", False)
            candle_body_pct = metrics.get("candle_body_pct", 0)
            change_pct = metrics["change_pct"]

            # Intensity multiplier: 100=ketat, 75=sedang, 50=longgar
            intensity = filter_intensity
            if intensity >= 100:
                ma20_thr, ma5_thr = 0.98, 0.97
                chg_swing, chg_intraday, chg_scalping = -2.0, -0.5, 1.0
                body_min, price_min_scalping = 0.3, 200
                intensity_key = 1.0
            elif intensity >= 75:
                ma20_thr, ma5_thr = 0.95, 0.95
                chg_swing, chg_intraday, chg_scalping = -3.0, -1.5, 0.5
                body_min, price_min_scalping = 0.1, 100
                intensity_key = 0.75
            else:  # 50
                ma20_thr, ma5_thr = 0.90, 0.90
                chg_swing, chg_intraday, chg_scalping = -5.0, -3.0, 0.0
                body_min, price_min_scalping = 0.0, 50
                intensity_key = 0.5

            # Value IDR filter — pakai _liq_value dari Phase 1 jika tersedia
            liq_value = float(stock.get("_liq_value", 0) or 0)
            liq_freq  = float(stock.get("_liq_freq",  0) or 0)
            idx_tier  = int(stock.get("_idx_tier", 2))

            VALUE_INTENSITY = {
                "swing":    {1.0: 20e9, 0.75: 10e9, 0.5: 5e9},
                "intraday": {1.0: 40e9, 0.75: 20e9, 0.5: 10e9},
                "scalping": {1.0: 80e9, 0.75: 40e9, 0.5: 20e9},
            }
            FREQ_INTENSITY = {
                "swing":    {1.0: 3000,  0.75: 1500, 0.5: 500},
                "intraday": {1.0: 9000,  0.75: 4500, 0.5: 1500},
                "scalping": {1.0: 15000, 0.75: 7500, 0.5: 3000},
            }

            v_threshold = VALUE_INTENSITY.get(mode, {}).get(intensity_key, 5e9)
            f_threshold = FREQ_INTENSITY.get(mode, {}).get(intensity_key, 1000)

            # Tier 0+1 dapat diskon 50% dari threshold
            if idx_tier <= 1:
                v_threshold *= 0.5
                f_threshold  = int(f_threshold * 0.5)

            if liq_value > 0 and liq_value < v_threshold:
                return None
            if liq_freq > 0 and liq_freq < f_threshold:
                return None

            if mode == "swing":
                if price < ma20 * ma20_thr:
                    return None
                if change_pct < chg_swing:
                    return None

            elif mode == "intraday":
                if price < ma5 * ma5_thr:
                    return None
                if change_pct < chg_intraday:
                    return None

            elif mode == "scalping":
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
                "adaptive_prefilter": adaptive,
                "rvol_gate": round(effective_rvol_gate, 2),
                "change_gate": round(effective_change_gate, 2),
            }
        except Exception:
            return None


def calc_bfd_presort_score(candidate, mode="swing"):
    """BFD Pre-Sort Score — Mode Aware dari 3 buku IDX"""
    score         = 50.0
    rvol          = to_float(candidate.get("rvol", 1.0))
    change_pct    = to_float(candidate.get("change_pct", 0))
    value         = to_float(candidate.get("value", 0))
    price         = to_float(candidate.get("price", 0))
    ma20          = to_float(candidate.get("ma20", price))
    ma5           = to_float(candidate.get("ma5", price))
    candle_bullish = candidate.get("candle_bullish", False)
    candle_body   = to_float(candidate.get("candle_body_pct", 0))
    vpa = candidate.get("vpa") if isinstance(candidate.get("vpa"), dict) else {}
    vpa_score = to_float(vpa.get("score") or candidate.get("vpa_score"), 50)
    vpa_signals = set(vpa.get("signals") or candidate.get("vpa_signals") or [])
    vpa_distribution_risk = bool(vpa.get("distribution_risk") or candidate.get("vpa_distribution_risk"))
    liq_value = to_float(candidate.get("_liq_value", 0))
    liq_freq  = to_float(candidate.get("_liq_freq", 0))
    idx_tier  = int(candidate.get("_idx_tier", 2))

    # ANTI Climax Distribution — SEMUA MODE (Bandar Flow Secrets hal.26)
    if change_pct > 15 and rvol > 2.0:
        return 5.0
    if change_pct > 10 and rvol > 1.8:
        score -= 30
    elif change_pct > 7 and rvol > 1.5:
        score -= 15

    # Volume Price Analysis variables stay embedded in scoring, not as a
    # separate user-facing filter.
    score += max(-22.0, min(20.0, (vpa_score - 50.0) * 0.45))
    if vpa_distribution_risk:
        score -= 18
    if "BULLISH_EFFORT_CONFIRMED" in vpa_signals:
        score += 8
    if "ABSORPTION" in vpa_signals or "STOPPING_VOLUME" in vpa_signals:
        score += 5
    if "NO_DEMAND" in vpa_signals:
        score -= 8
    if "UPTHRUST" in vpa_signals or "CLIMAX_EXTENSION_RISK" in vpa_signals:
        score -= 15

    if mode == "swing":
        # VSR (hal.60)
        if rvol >= 2.0:    score += 18
        elif rvol >= 1.5:  score += 12
        elif rvol >= 1.2:  score += 5
        # Silent Accumulation (hal.26) — core signal
        if rvol >= 1.5 and abs(change_pct) <= 3.0:   score += 22
        elif rvol >= 1.5 and abs(change_pct) <= 5.0: score += 10
        # Price vs MA20
        if price > 0 and ma20 > 0:
            pct = (price - ma20) / ma20 * 100
            if -3 <= pct <= 5:   score += 10
            elif 5 < pct <= 15:  score += 5
            elif pct < -15:      score -= 12
        # Change ideal swing
        if 0 < change_pct <= 3:   score += 10
        elif change_pct > 0:      score += 3
        elif change_pct < -5:     score -= 8
        # Value (hal.36)
        if value > 50_000_000_000:    score += 8
        elif value > 10_000_000_000:  score += 4

    elif mode == "intraday":
        # VSR intraday butuh lebih kuat
        if rvol >= 2.5:    score += 20
        elif rvol >= 2.0:  score += 15
        elif rvol >= 1.5:  score += 8
        # Momentum awal hari (hal.57) — sweet spot 2-8%
        if 2 <= change_pct <= 8 and rvol >= 1.5:    score += 20
        elif 0 < change_pct <= 2 and rvol >= 1.5:   score += 10
        elif 8 < change_pct <= 12:                   score += 5
        elif change_pct < 0:                         score -= 10
        # Price vs MA5
        if price > 0 and ma5 > 0:
            pct = (price - ma5) / ma5 * 100
            if 0 <= pct <= 3:   score += 10
            elif pct > 3:       score += 5
            elif pct < -2:      score -= 8
        # Candle quality
        if candle_bullish and candle_body >= 0.5:  score += 10
        elif candle_bullish:                        score += 5
        # Value likuiditas intraday
        if value > 20_000_000_000:    score += 8
        elif value > 5_000_000_000:   score += 4

    elif mode == "scalping":
        # VSR scalping butuh ekstrem
        if rvol >= 3.0:    score += 25
        elif rvol >= 2.5:  score += 18
        elif rvol >= 2.0:  score += 12
        elif rvol >= 1.5:  score += 5
        # Momentum burst (Trader Dale)
        if change_pct >= 5 and rvol >= 2.0:    score += 20
        elif change_pct >= 3 and rvol >= 1.5:  score += 12
        elif change_pct >= 1:                   score += 5
        elif change_pct < 0:                    score -= 15
        # Price vs MA5 — harus di atas
        if price > 0 and ma5 > 0:
            if price > ma5:  score += 10
            else:            score -= 10
        # Candle kuat
        if candle_bullish and candle_body >= 1.0:   score += 12
        elif candle_bullish and candle_body >= 0.5: score += 6
        elif not candle_bullish:                     score -= 5
        # Value likuiditas scalping
        if value > 10_000_000_000:    score += 8
        elif value > 2_000_000_000:   score += 4
        elif value < 500_000_000:     score -= 10

    # Liquidity bonus dari Phase 1 Gate 4 — ALL modes
    effective_value = liq_value if liq_value > 0 else value
    if effective_value >= 50e9:   score += 15
    elif effective_value >= 20e9: score += 10
    elif effective_value >= 10e9: score += 5
    elif effective_value >= 5e9:  score += 2
    if liq_freq >= 10000: score += 10
    elif liq_freq >= 5000: score += 7
    elif liq_freq >= 2000: score += 4
    elif liq_freq >= 1000: score += 2
    if idx_tier == 0:   score += 10
    elif idx_tier == 1: score += 5

    return max(0.0, min(100.0, round(score, 2)))


async def ohlcv_prefilter(universe: List[Dict[str, Any]], mode: Mode, filter_intensity: int = 75, adaptive: bool = False) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(10)  # Rate limit Invesgo — max 10 paralel
    tasks = [prefilter_one(stock, mode, sem, filter_intensity, adaptive=adaptive) for stock in universe]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates = [r for r in results if isinstance(r, dict)]

    # BFD Pre-Sort — Bandar Flow Detector dari 3 buku IDX
    # Sort berdasarkan BFD score sebelum ambil top N
    # Ini memastikan 200 kandidat terbaik secara bandarmologi
    for c in candidates:
        c["bfd_presort_score"] = calc_bfd_presort_score(c, mode)

    candidates.sort(key=lambda x: x.get("bfd_presort_score", 0), reverse=True)

    limit = MODE_CONFIG[mode]["candidate_max"]
    top = candidates[:limit]

    if top:
        import logging as _log
        _log.getLogger(__name__).info(
            f"BFD PreSort: {len(candidates)} kandidat → top {limit} "
            f"| BFD range: {top[-1]['bfd_presort_score']:.1f}–{top[0]['bfd_presort_score']:.1f}"
        )

    return top


async def debug_prefilter_rejections(universe: List[Dict[str, Any]], mode: Mode, filter_intensity: int = 75, sample_limit: int = 40) -> Dict[str, Any]:
    """
    Debug-only mirror of prefilter_one().
    Does not affect production filtering; only explains why candidates are rejected.
    """
    from collections import Counter
    from datetime import datetime

    cfg = MODE_CONFIG[mode]
    gate = _adaptive_gate(mode, filter_intensity, adaptive=False)
    today_str = datetime.now().strftime("%Y-%m-%d")
    sem = asyncio.Semaphore(10)

    async def inspect_one(stock: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            ticker = stock.get("ticker")
            try:
                ohlcv = await asyncio.wait_for(fetch_ohlcv_safe(ticker), timeout=10)
                metrics = calc_prefilter_metrics(ohlcv)

                if not metrics:
                    return {"ticker": ticker, "reason": "NO_METRICS", "ohlcv_len": len(ohlcv or [])}

                raw_stock = stock.get("raw", {}) if isinstance(stock.get("raw"), dict) else {}
                suspend_value = (
                    stock.get("suspend", None)
                    if stock.get("suspend", None) is not None
                    else raw_stock.get("suspend", 0)
                )

                last_date_raw = str(metrics.get("date") or "")[:10]
                stale_fast_mode = mode in ("intraday", "scalping") and last_date_raw and last_date_raw != today_str
                stale_live_allowed = stale_fast_mode and _allow_live_metrics_with_stale_date(metrics, gate)

                reason = "PASS_LIVE_PRICE_STALE_DATE" if stale_live_allowed else "PASS_PREFILTER"
                if metrics["price"] < cfg["price_min"] or metrics["price"] > cfg["price_max"]:
                    reason = "PRICE_RANGE"
                elif int(suspend_value or 0) > 0:
                    reason = "SUSPENDED_FIELD"
                elif stale_fast_mode and not stale_live_allowed:
                    reason = "STALE_OHLCV_DATE"
                elif metrics["volume"] <= 0:
                    reason = "ZERO_VOLUME"
                elif metrics["avg_volume_20"] <= 0:
                    reason = "ZERO_AVG_VOLUME"
                elif metrics["rvol"] <= 0:
                    reason = "ZERO_RVOL"
                elif metrics.get("high", 0) == metrics.get("low", 0) == metrics["price"] and metrics["volume"] < 1000:
                    reason = "FLAT_LOW_VOLUME"
                elif metrics.get("change_pct", 0) >= 24.0:
                    reason = "ARA_FILTER"
                elif metrics.get("change_pct", 0) <= -24.0:
                    reason = "ARB_FILTER"
                elif metrics["rvol"] < cfg["rvol_min"]:
                    reason = "RVOL_TOO_LOW"
                elif metrics["change_pct"] < cfg["change_min"]:
                    reason = "CHANGE_TOO_LOW"
                elif mode == "swing" and metrics.get("change_pct", 0) > 15 and metrics["rvol"] > 2.0:
                    reason = "ANTI_CLIMAX_SWING"
                elif mode == "intraday" and metrics.get("change_pct", 0) > 20 and metrics["rvol"] > 3.0:
                    reason = "ANTI_CLIMAX_INTRADAY"
                elif mode == "scalping" and metrics.get("change_pct", 0) > 22 and metrics["rvol"] > 5.0:
                    reason = "ANTI_CLIMAX_SCALPING"

                return {
                    "ticker": ticker,
                    "reason": reason,
                    "date": metrics.get("date"),
                    "today": today_str,
                    "price": metrics.get("price"),
                    "change_pct": metrics.get("change_pct"),
                    "rvol": metrics.get("rvol"),
                    "volume": metrics.get("volume"),
                    "avg_volume_20": metrics.get("avg_volume_20"),
                    "suspend": suspend_value,
                }
            except Exception as exc:
                return {"ticker": ticker, "reason": f"ERROR_{type(exc).__name__}", "error": str(exc)[:200]}

    rows = await asyncio.gather(*(inspect_one(stock) for stock in universe[:sample_limit]))
    counts = Counter(row.get("reason") for row in rows)

    return {
        "sample_size": len(rows),
        "reason_counts": dict(counts.most_common()),
        "sample": rows,
    }




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
        # SC-3: keyword diperluas untuk engine IDX (BandarTypeClassifier, RetestClassifier, dll)
        if any(x in n for x in ("execution", "entry", "risk", "order", "liquidity", "setup",
                                  "retest", "retestclassifier", "support_resistance", "priceaction")):
            buckets["execution"].append(score)
        elif any(x in n for x in ("volume", "rvol", "vpa", "frequency", "volumeintelligence",
                                   "volume_intelligence")):
            buckets["volume"].append(score)
        elif any(x in n for x in ("structure", "trend", "support", "resistance", "breakout",
                                   "wyckoff", "weinstein", "marketstructure", "market_structure",
                                   "trendstructure", "trend_structure")):
            buckets["market_structure"].append(score)
        elif any(x in n for x in ("smart", "money", "bandar", "accum", "foreign", "institution",
                                   "bandartypeclassifier", "bandartype", "smartmoney", "smart_money",
                                   "momentumstrength", "momentum_strength")):
            buckets["smart_money"].append(score)
        elif any(x in n for x in ("decision", "control", "confidence", "signal",
                                   "tpprobability", "tp_probability", "enrichment")):
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
            # Tidak langsung disqualify — biarkan apply_disqualifiers yang handle
        elif wyckoff_phase == "MARKDOWN":
            phase2_bonus -= 20

        if weinstein_stage == 2:
            phase2_bonus += 10
        elif weinstein_stage == 1:
            phase2_bonus += 3
        elif weinstein_stage == 3:
            phase2_bonus -= 10
        elif weinstein_stage == 4:
            phase2_bonus -= 20

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
        "disqualify": bool(phase["disqualify"] or bandar_macd.get("disqualify")),
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
    Menggunakan insight dari 13 buku trading di Knowledge Base
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

    empirical = {"available": False}
    empirical_boost = 0
    try:
        from app.ml.historical_learning import get_empirical_context
        empirical = await get_empirical_context(ticker, mode=str(mode))
        if empirical.get("available") and empirical.get("sample_count", 0) >= 30:
            wr = float(empirical.get("winrate", 0) or 0)
            if wr >= 65:
                empirical_boost = 4
            elif wr >= 58:
                empirical_boost = 2
            elif wr <= 42:
                empirical_boost = -2
    except Exception:
        empirical = {"available": False}

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

    # ── Buku teknikal spesifik per phase ────────────────────
    try:
        from app.core.knowledge_base import query_murphy_ta, query_coulling_vpa, query_trade_setup
        import asyncio as _asyncio

        phase_val = context.get("phase", "neutral")
        rvol_val  = context.get("rvol", 1.0)

        murphy_q = (
            f"Setup {phase_val} dengan RVOL {rvol_val:.1f}x. "
            f"Technical analysis confirmation untuk IDX stock screening?"
        )
        vpa_q = (
            f"Volume {rvol_val:.1f}x average di fase {phase_val}. "
            f"Apakah volume mengkonfirmasi akumulasi atau distribusi?"
        )
        setup_q = (
            f"Screening criteria untuk fase {phase_val} di IDX. "
            f"Setup entry yang valid dengan RVOL {rvol_val:.1f}x?"
        )

        murphy_ctx, vpa_ctx, setup_ctx = await _asyncio.gather(
            query_murphy_ta(murphy_q, n=1),
            query_coulling_vpa(vpa_q, n=1),
            query_trade_setup(setup_q, n=1),
        )

        tech_insights = " ".join([
            t[:150] for t in [murphy_ctx, vpa_ctx, setup_ctx] if t
        ])
        if tech_insights:
            query = f"{query} {tech_insights}"

    except Exception:
        pass

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
            boost = max(0, min(8, net_boost + empirical_boost))

            # Bonus kalau phase match dengan KB content
            if phase in ["early_accumulation", "accumulation"] and bull_count >= 3:
                boost = min(8, boost + 2)

            return {
                "boost": boost,
                "reason": f"KB: {bull_count} bullish / {bear_count} bearish signals; empirical {empirical_boost:+d}",
                "source": method_name,
                "query_phase": phase,
                "bull_signals": bull_count,
                "bear_signals": bear_count,
                "empirical_memory": empirical,
            }
    except Exception as exc:
        return {"boost": max(0, empirical_boost), "reason": f"KB error: {exc}; empirical {empirical_boost:+d}", "empirical_memory": empirical}

    return {"boost": max(0, empirical_boost), "reason": f"compatible KB method not found; empirical {empirical_boost:+d}", "empirical_memory": empirical}


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
    score = _safe_akumulasi_multiplier(score, akumulasi_score, mode)  # SC-1: safe wrapper
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
    vpa = item.get("vpa") if isinstance(item.get("vpa"), dict) else {}
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
    if vpa:
        bits.append(f"VPA {vpa.get('state')} {vpa.get('score')}")
        signals = vpa.get("signals") or []
        if signals:
            bits.append("VPA signals " + "/".join(str(s) for s in signals[:3]))
    return "; ".join(bits)


async def _get_real_foreign_flow(ticker: str, ohlcv: list, bandarm: dict) -> dict:
    """SC-2: Foreign flow real dari broker_summary — fallback ke proxy"""
    FOREIGN_BROKERS_SET = {"YP","BK","RX","ZP","AK","CC","DB","MS","CS","ML","DP","KI","OD","LG"}
    try:
        broker_data = await asyncio.wait_for(
            invesgo_call("get_broker_summary", ticker), timeout=8
        )
        if broker_data and isinstance(broker_data, list):
            f_buy = 0.0; f_sell = 0.0; f_net = 0.0
            for b in broker_data:
                code = b.get("code", "")
                if code in FOREIGN_BROKERS_SET:
                    f_buy  += float(b.get("buy_value",  0) or 0)
                    f_sell += float(b.get("sell_value", 0) or 0)
                    f_net  += float(b.get("net_value",  0) or 0)
            if f_buy + f_sell > 0:
                if f_net > 2e9:   signal, score = "BUY", 80
                elif f_net > 0:   signal, score = "NEUTRAL_BUY", 65
                elif f_net < -2e9: signal, score = "SELL", 25
                elif f_net < 0:   signal, score = "NEUTRAL_SELL", 42
                else:             signal, score = "NEUTRAL", 50
                heavy_sell = signal == "SELL" and bandarm.get("phase") in {"distribution","decline"}
                return {
                    "score": round(min(100,max(0,score)),2),
                    "signal": signal, "streak": 0,
                    "heavy_sell": heavy_sell,
                    "source": "broker_summary",
                    "foreign_net_bil": round(f_net/1e9,2),
                    "foreign_buy_bil": round(f_buy/1e9,2),
                    "foreign_sell_bil": round(f_sell/1e9,2),
                }
    except Exception:
        pass
    proxy = calculate_foreign_flow_proxy(ohlcv, bandarm)
    proxy["source"] = "proxy_fallback"
    return proxy

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

        foreign = await _get_real_foreign_flow(ticker, ohlcv, bandarm)  # SC-2
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
        vpa = candidate.get("vpa") if isinstance(candidate.get("vpa"), dict) else {}
        vpa_score = to_float(vpa.get("score"), 50)
        fscore = round(clamp(fscore * 0.90 + vpa_score * 0.10), 2)
        if vpa.get("distribution_risk"):
            fscore = round(clamp(fscore - 8), 2)
        elif vpa.get("confirmation"):
            fscore = round(clamp(fscore + 3), 2)

        money_maker = {"available": False}
        if analyze_money_maker_context is not None:
            money_maker_previous = {}
            if get_latest_flow_snapshot_cloud is not None:
                money_maker_previous = await get_latest_flow_snapshot_cloud(ticker, mode)
            money_maker = analyze_money_maker_context(
                ticker=ticker,
                mode=mode,
                ohlcv=ohlcv,
                engine_result=engine_raw,
                bandarmology=bandarm,
                foreign_flow=foreign,
                pattern=pattern,
                screener_item=candidate,
                previous_snapshot=money_maker_previous,
            )
            if save_money_maker_cloud is not None:
                money_maker_persist = await save_money_maker_cloud(money_maker)
                money_maker.setdefault("flow_memory", {})["cloud_saved"] = bool(money_maker_persist.get("saved"))
                money_maker["flow_memory"]["persistent_backend"] = money_maker_persist.get("persistent_backend", "sqlite")
            mm_score = to_float(money_maker.get("score"), 50)
            fscore = round(clamp(fscore * 0.85 + mm_score * 0.15), 2)
            if money_maker.get("verdict") == "FLOW_OUT_AVOID":
                fscore = round(clamp(fscore - 12), 2)
            elif money_maker.get("verdict") == "STRONG_FLOW_IN":
                fscore = round(clamp(fscore + 4), 2)

        result = {
            "ticker": ticker,
            "code": ticker,
            "name": candidate.get("name"),
            "sector": candidate.get("sector"),
            "price": candidate.get("price"),
            "change_pct": candidate.get("change_pct"),
            "rvol": candidate.get("rvol"),
            "volume": candidate.get("volume"),
            "vpa": vpa,
            "vpa_score": vpa.get("score"),
            "vpa_state": vpa.get("state"),
            "vpa_signals": vpa.get("signals") or [],
            "vpa_distribution_risk": bool(vpa.get("distribution_risk")),
            "data_status": candidate.get("date_status"),
            "data_warning": candidate.get("data_warning"),
            "opportunity_lane": candidate.get("_opportunity_lane"),
            "mover_rank": candidate.get("_mover_rank"),
            "mover_source": candidate.get("_mover_source"),
            "final_score": fscore,
            "signal": signal_from_score(fscore),
            "money_maker": money_maker,
            "money_maker_score": money_maker.get("score"),
            "bfd_score": money_maker.get("bfd_score"),
            "flow_phase": money_maker.get("phase"),
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
            "disqualify": bool(
                bandarm.get("disqualify")
                or foreign.get("heavy_sell")
                or money_maker.get("verdict") == "FLOW_OUT_AVOID"
                or vpa.get("distribution_risk")
            ),
            "disqualify_reason": None,
            "reason": "",
        }

        if candidate.get("_opportunity_lane") == "top_gainer" or to_float(candidate.get("change_pct")) >= 5:
            chg = to_float(candidate.get("change_pct"))
            sweet_spot = 5 <= chg < 10
            extended = 10 <= chg < 20
            extreme = chg >= 20
            tier = "SWEET_SPOT_5_10" if sweet_spot else "EXTENDED_10_20" if extended else "EXTREME_20_PLUS"
            executable = sweet_spot and not vpa.get("distribution_risk")
            result["top_gainer_opportunity"] = {
                "available": executable,
                "lane": candidate.get("_opportunity_lane") or "PRICE_MOVER_MOMENTUM",
                "rank": candidate.get("_mover_rank"),
                "change_pct": chg,
                "opportunity_tier": tier,
                "executable": executable,
                "radar_only": not executable,
                "execution_bias": "MOMENTUM_CONFIRMATION_5_10" if executable else "VPA_DISTRIBUTION_RISK_RADAR" if vpa.get("distribution_risk") else "EXTENDED_NO_CHASE" if extended else "EXTREME_EXTENSION_RISK",
                "preferred_entry": "Breakout continuation or VWAP pullback with bid refill; no market chase." if executable else "Radar only; wait reset/base and VPA improvement before any execution review.",
                "risk_rule": "Avoid market chase; invalid below 5m base low/VWAP loss. Size tiny until broker/orderbook confirms.",
                "exit_rule": "Scale out into extension; trail under higher-low or VWAP for intraday/scalping.",
                "upgrade_rule": "Only 5%-10% movers can enter execution lane; above 10% is no-chase radar unless it resets cleanly.",
                "vpa_state": vpa.get("state"),
                "vpa_score": vpa.get("score"),
                "vpa_signals": vpa.get("signals") or [],
            }
            result["watchlist_only"] = True
            if result.get("data_status") == "STALE_DAILY_TOP_GAINER_FALLBACK":
                result["top_gainer_opportunity"]["data_quality"] = "OPENING_FEED_FALLBACK"
                result["top_gainer_opportunity"]["radar_only"] = True
                result["top_gainer_opportunity"]["executable"] = False
                result["top_gainer_opportunity"]["preferred_entry"] = (
                    "Radar opening only sampai official daily/live intraday data hari ini terkonfirmasi."
                )
            if not executable:
                result["no_chase_radar"] = True
                result["disqualify"] = True
                result["disqualify_reason"] = (
                    "VPA distribution risk; top gainer diturunkan menjadi no-chase radar."
                    if vpa.get("distribution_risk")
                    else f"Top gainer {chg:.2f}% di luar sweet spot 5%-10%; no-chase radar only."
                )
            if extreme:
                result["top_gainer_opportunity"]["preferred_entry"] = "No chase; extreme/ARA-risk extension. Observe distribution risk and wait next-cycle setup."

        if result.get("no_chase_radar"):
            pass
        elif vpa.get("distribution_risk"):
            result["disqualify_reason"] = "VPA distribution risk: " + "/".join(vpa.get("signals") or [])
        elif bandarm.get("disqualify"):
            result["disqualify_reason"] = "Bandarmology phase/MACD disqualify"
        elif foreign.get("heavy_sell"):
            result["disqualify_reason"] = "Foreign heavy sell + weak/distribution condition"
        elif money_maker.get("verdict") == "FLOW_OUT_AVOID":
            result["disqualify_reason"] = "Money Maker Core flow out/distribution trap"

        result["reason"] = build_reason(result)
        return result


async def score_candidates(candidates: List[Dict[str, Any]], mode: Mode) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(3)
    tasks = [score_one(c, mode, sem) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


async def build_opening_seed_radar(scored: List[Dict[str, Any]], mode: Mode) -> List[Dict[str, Any]]:
    if mode not in ("intraday", "scalping"):
        return []
    existing = {str(x.get("ticker") or x.get("code") or "").upper() for x in scored}
    radar: List[Dict[str, Any]] = []
    for ticker in OPENING_MOMENTUM_RADAR_TICKERS:
        code = ticker.upper()
        if code in existing:
            continue
        try:
            ohlcv = await asyncio.wait_for(fetch_ohlcv_safe(code), timeout=8)
            metrics = calc_prefilter_metrics(ohlcv)
            if not metrics:
                continue
            chg = to_float(metrics.get("change_pct"))
            price = to_float(metrics.get("price"))
            if chg < 5 or chg >= 24 or price < MODE_CONFIG[mode]["price_min"] or price > MODE_CONFIG[mode]["price_max"]:
                continue
            vpa = metrics.get("vpa") if isinstance(metrics.get("vpa"), dict) else {}
            sweet_spot = 5 <= chg < 10 and not vpa.get("distribution_risk")
            tier = "SWEET_SPOT_5_10" if sweet_spot else "EXTENDED_10_20" if chg < 20 else "EXTREME_20_PLUS"
            radar.append({
                "ticker": code,
                "code": code,
                "name": code,
                "sector": "",
                "price": price,
                "change_pct": round(chg, 2),
                "rvol": metrics.get("rvol"),
                "volume": metrics.get("volume"),
                "vpa": vpa,
                "vpa_score": vpa.get("score"),
                "vpa_state": vpa.get("state"),
                "vpa_signals": vpa.get("signals") or [],
                "vpa_distribution_risk": bool(vpa.get("distribution_risk")),
                "data_status": metrics.get("date_status") or "OPENING_SEED_RADAR",
                "data_warning": metrics.get("data_warning") or "Opening radar dari baseline ticker; gunakan Analytical untuk validasi eksekusi.",
                "final_score": 0,
                "signal": "RADAR" if not sweet_spot else "WATCHLIST",
                "watchlist_only": True,
                "disqualify": not sweet_spot,
                "disqualify_reason": None if sweet_spot else (
                    "VPA distribution risk; opening mover no-chase radar only."
                    if vpa.get("distribution_risk")
                    else f"Top gainer {chg:.2f}% di luar sweet spot 5%-10%; no-chase radar only."
                ),
                "reason": "Opening momentum radar; bukan sinyal beli otomatis.",
                "top_gainer_opportunity": {
                    "available": sweet_spot,
                    "lane": "OPENING_SEED_PRICE_MOVER",
                    "rank": None,
                    "change_pct": round(chg, 2),
                    "opportunity_tier": tier,
                    "executable": sweet_spot,
                    "radar_only": not sweet_spot,
                    "execution_bias": "MOMENTUM_CONFIRMATION_5_10" if sweet_spot else "VPA_DISTRIBUTION_RISK_RADAR" if vpa.get("distribution_risk") else "EXTENDED_NO_CHASE" if chg < 20 else "EXTREME_EXTENSION_RISK",
                    "preferred_entry": "Breakout continuation or VWAP pullback with bid refill; no market chase." if sweet_spot else "Radar only; wait reset/base and VPA improvement before any execution review.",
                    "risk_rule": "Avoid market chase; validate with Analytical, orderbook, and broker flow.",
                    "exit_rule": "Scale out into extension; trail under higher-low or VWAP for intraday/scalping.",
                    "upgrade_rule": "Only 5%-10% movers can enter execution lane; above 10% is no-chase radar unless it resets cleanly.",
                    "vpa_state": vpa.get("state"),
                    "vpa_score": vpa.get("score"),
                    "vpa_signals": vpa.get("signals") or [],
                },
                "no_chase_radar": not sweet_spot,
            })
        except Exception:
            continue
    return radar


# ===== Phase 4 and 5 =====

def apply_disqualifiers(scored: List[Dict[str, Any]], mode: Mode) -> List[Dict[str, Any]]:
    min_score = MODE_CONFIG[mode]["min_score"]
    qualified: List[Dict[str, Any]] = []

    for item in scored:
        if item.get("no_chase_radar") or (item.get("top_gainer_opportunity") or {}).get("radar_only"):
            item["disqualify"] = True
            item["disqualify_reason"] = item.get("disqualify_reason") or "Top gainer outside 5%-10% sweet spot; no-chase radar only."
            continue

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
            to_float(x.get("money_maker_score")),
            to_float(x.get("bfd_score")),
            to_float(x.get("bandarmology_composite")),
            to_float(x.get("rvol")),
        ),
        reverse=True,
    )
    return qualified[:limit]


def build_watchlist_fallback(scored: List[Dict[str, Any]], mode: Mode, limit: int) -> List[Dict[str, Any]]:
    floor = max(38, MODE_CONFIG[mode]["min_score"] - 20)
    pool: List[Dict[str, Any]] = []
    for item in scored:
        if item.get("no_chase_radar") or (item.get("top_gainer_opportunity") or {}).get("radar_only"):
            continue

        phase = str(item.get("phase", "")).lower()
        if phase in {"distribution", "decline"}:
            continue
        if item.get("vpa_distribution_risk") or (item.get("vpa") or {}).get("distribution_risk"):
            continue
        if item.get("money_maker", {}).get("verdict") == "FLOW_OUT_AVOID":
            continue
        if item.get("foreign_flow", {}).get("heavy_sell"):
            continue
        if to_float(item.get("final_score")) < floor:
            continue
        candidate = dict(item)
        candidate["watchlist_only"] = True
        candidate["disqualify"] = False
        candidate["fallback_reason"] = "Strict screener kosong; kandidat ini hanya adaptive watchlist/market radar, bukan sinyal entry otomatis."
        candidate["signal"] = "WATCHLIST" if to_float(candidate.get("final_score")) >= 55 else "NEUTRAL"
        candidate["reason"] = f"{candidate.get('fallback_reason')} {candidate.get('reason', '')}".strip()
        pool.append(candidate)
    return rank_top(pool, limit)


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


# ===== Manual Stockbit top gainer upload lane =====

def _manual_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    raw = str(value).strip()
    if raw in {"", "-", "nan", "None"}:
        return default
    raw = raw.replace("Rp", "").replace("IDR", "").replace(" ", "")
    multiplier = 1.0
    suffix = raw[-1:].upper()
    if suffix in {"K", "M", "B", "T"}:
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix]
        raw = raw[:-1]
    raw = raw.replace(",", "")
    try:
        return float(raw) * multiplier
    except Exception:
        return default


def _manual_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = re.sub(r"[^A-Z0-9-]", "", text.replace(".JK", ""))
    if not text or text in {"SYMBOL", "YMBOL", "CODE", "TICKER", "SAHAM"}:
        return ""
    if len(text) % 2 == 0:
        half = len(text) // 2
        if text[:half] == text[half:]:
            text = text[:half]
    return text


def _manual_price_change(value: Any) -> Tuple[float, float]:
    text = str(value or "").strip()
    match = re.search(r"([\d.,]+)\s*\(\s*([+-]?[\d.,]+)\s*%\s*\)", text)
    if match:
        return _manual_number(match.group(1)), _manual_number(match.group(2))
    return _manual_number(text), 0.0


def _xlsx_rows_from_bytes(content: bytes) -> List[List[str]]:
    rows: List[List[str]] = []
    with zipfile.ZipFile(BytesIO(content)) as zf:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            import xml.etree.ElementTree as ET

            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("x:si", ns):
                parts = [t.text or "" for t in si.findall(".//x:t", ns)]
                shared.append("".join(parts))

        sheet_names = sorted([n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
        if not sheet_names:
            return rows

        import xml.etree.ElementTree as ET

        root = ET.fromstring(zf.read(sheet_names[0]))
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for row in root.findall(".//x:sheetData/x:row", ns):
            values: List[str] = []
            for cell in row.findall("x:c", ns):
                cell_type = cell.attrib.get("t")
                value = ""
                if cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//x:t", ns))
                else:
                    node = cell.find("x:v", ns)
                    value = node.text if node is not None and node.text is not None else ""
                    if cell_type == "s":
                        idx = int(float(value or 0))
                        value = shared[idx] if 0 <= idx < len(shared) else ""
                values.append(str(value).strip())
            rows.append(values)
    return rows


def _text_rows_from_upload(filename: str, content: bytes) -> List[List[str]]:
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        return _xlsx_rows_from_bytes(content)
    text = content.decode("utf-8-sig", errors="ignore")
    return [re.split(r"[\t,;]+", line.strip()) for line in text.splitlines() if line.strip()]


def _parse_manual_top_gainer_rows(rows: List[List[Any]]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    seen = set()
    for row_idx, row in enumerate(rows, start=1):
        cells = [str(x).strip() for x in row if str(x or "").strip()]
        if len(cells) == 1:
            compact = cells[0]
            match = re.match(r"^\s*([A-Z0-9-]{3,12})\s+(.+)$", compact, re.IGNORECASE)
            if match:
                cells = [match.group(1)] + re.split(r"\s+", match.group(2).strip())
        if len(cells) < 2:
            continue
        joined = " ".join(cells).upper()
        if "SYMBOL" in joined or "PRICE" in joined or "NET FOREIGN" in joined:
            continue

        code = _manual_symbol(cells[0])
        if not code and len(cells) >= 2:
            code = _manual_symbol(cells[1])
        if not code or len(code) < 3:
            continue

        price = 0.0
        change_pct = 0.0
        price_cell_index = 1 if _manual_symbol(cells[0]) else 2
        for cell in cells[1:4]:
            p, chg = _manual_price_change(cell)
            if p > 0:
                price = p
            if chg:
                change_pct = chg
            if price > 0 and change_pct:
                break

        if price <= 0 and len(cells) > price_cell_index:
            price = _manual_number(cells[price_cell_index])
        if change_pct <= 0:
            pct_match = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%", " ".join(cells))
            if pct_match:
                change_pct = _manual_number(pct_match.group(1))
        if price <= 0 or change_pct <= 0:
            continue

        tail = cells[2:]
        value = _manual_number(tail[0]) if len(tail) >= 1 else 0.0
        volume = _manual_number(tail[1]) if len(tail) >= 2 else 0.0
        freq = _manual_number(tail[2]) if len(tail) >= 3 else 0.0
        net_foreign = _manual_number(tail[3]) if len(tail) >= 4 else 0.0
        if code in seen:
            continue
        seen.add(code)
        parsed.append({
            "ticker": code,
            "code": code,
            "price": round(price, 2),
            "last_price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "value": value,
            "volume": volume,
            "freq": freq,
            "net_foreign": net_foreign,
            "raw_line": " | ".join(cells),
            "row": row_idx,
        })
    return parsed


def _bucket_score(value: float, buckets: List[Tuple[float, float]]) -> float:
    score = 0.0
    for threshold, bucket_score in buckets:
        if value >= threshold:
            score = bucket_score
    return score


def _manual_top_gainer_score(item: Dict[str, Any], rank: int) -> Dict[str, Any]:
    chg = to_float(item.get("change_pct"))
    value = to_float(item.get("value"))
    volume = to_float(item.get("volume"))
    freq = to_float(item.get("freq"))
    net_foreign = to_float(item.get("net_foreign"))
    code = str(item.get("ticker") or "")

    if 5 <= chg < 9:
        momentum_score = 96
        tier = "SWEET_SPOT_5_9"
        preferred_entry = "VWAP pullback or buy-stop above intraday base; no market chase."
    elif 9 <= chg < 10:
        momentum_score = 78
        tier = "LATE_SWEET_SPOT_9_10"
        preferred_entry = "Conditional only after reset/base and bid refill."
    elif 3 <= chg < 5:
        momentum_score = 66
        tier = "EARLY_MOMENTUM_3_5"
        preferred_entry = "Early watch; execute only if volume/frequency expands."
    elif 10 <= chg < 20:
        momentum_score = 36
        tier = "EXTENDED_10_20"
        preferred_entry = "No chase; wait reset/base before analytic execution review."
    else:
        momentum_score = 18
        tier = "EXTREME_20_PLUS"
        preferred_entry = "No chase; likely extension/ARA-risk, observe only."

    value_score = _bucket_score(value, [(0, 20), (1e8, 35), (1e9, 58), (5e9, 72), (20e9, 85), (100e9, 96)])
    freq_score = _bucket_score(freq, [(0, 20), (100, 36), (500, 55), (1500, 72), (5000, 86), (15000, 96), (50000, 100)])
    volume_score = _bucket_score(volume, [(0, 20), (1_000, 35), (10_000, 50), (100_000, 70), (1_000_000, 88), (5_000_000, 96)])
    if net_foreign > 0:
        foreign_score = _bucket_score(net_foreign, [(1, 62), (10e6, 70), (100e6, 78), (1e9, 88), (10e9, 96)])
    elif net_foreign < 0:
        foreign_score = 35
    else:
        foreign_score = 50

    score = (
        momentum_score * 0.30
        + value_score * 0.25
        + freq_score * 0.20
        + foreign_score * 0.15
        + volume_score * 0.10
    )
    penalties: List[str] = []
    if value and value < 1e9:
        score -= 8
        penalties.append("value di bawah 1B")
    if freq and freq < 500:
        score -= 7
        penalties.append("frequency tipis")
    if chg >= 10:
        score -= 18
        penalties.append("di atas 10% = no-chase default")
    if chg >= 20:
        score -= 12
        penalties.append("extreme/ARA-risk")
    if "-" in code:
        score -= 30
        penalties.append("instrumen warrant/non-common stock")

    score = round(clamp(score), 2)
    executable = 5 <= chg < 10 and value >= 1e9 and freq >= 500 and "-" not in code
    conditional = (3 <= chg < 5 or 9 <= chg < 10) and value >= 1e9 and freq >= 500 and "-" not in code
    radar_only = not (executable or conditional)
    lane = "MANUAL_TOP_GAINER_OPPORTUNITY" if executable else "MANUAL_CONDITIONAL_EXECUTION" if conditional else "NO_CHASE_RADAR"
    expectation = "EXECUTABLE_TOP3" if executable else "CONDITIONAL_EXECUTION" if conditional else "RADAR_NO_CHASE"

    return {
        **item,
        "manual_rank": rank,
        "final_score": score,
        "score": score,
        "signal": "BUY" if executable and score >= 65 else "HOLD" if conditional else "NEUTRAL",
        "screener_lane": lane,
        "opportunity_lane": "manual_top_gainer",
        "_opportunity_lane": "top_gainer",
        "_mover_rank": rank,
        "_mover_source": "stockbit_manual_upload",
        "watchlist_only": not executable,
        "manual_feed": {
            "source": "stockbit_manual_upload",
            "rank": rank,
            "score_components": {
                "momentum": momentum_score,
                "value": value_score,
                "frequency": freq_score,
                "foreign": foreign_score,
                "volume": volume_score,
            },
            "penalties": penalties,
        },
        "top_gainer_opportunity": {
            "available": executable or conditional,
            "lane": "manual_top_gainer",
            "rank": rank,
            "change_pct": chg,
            "opportunity_tier": tier,
            "executable": executable,
            "conditional": conditional,
            "radar_only": radar_only,
            "manual_feed": True,
            "source": "stockbit_manual_upload",
            "execution_bias": expectation,
            "preferred_entry": preferred_entry,
            "risk_rule": "Analytic wajib validasi VWAP, orderbook, broker flow, spread, dan invalidation sebelum entry.",
            "exit_rule": "Target minimal +3%; scale out TP1/TP2/TP3 dan pindah ke Monitoring setelah user buy.",
            "upgrade_rule": "Manual lane hanya mempercepat radar; fatal risk di Analytic tetap boleh menolak.",
        },
        "analytic_expectation": expectation,
        "reason": f"Manual Stockbit top gainer {chg:.2f}% | value {value:,.0f} | freq {freq:,.0f} | {expectation}",
        "data_warning": "Manual Stockbit feed; Invezgo/Analytic tetap final validator sebelum execution.",
    }


@router.post("/manual-top-gainer/upload")
async def upload_manual_top_gainer(
    mode: Mode = Form(default="intraday"),
    raw_text: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
) -> Dict[str, Any]:
    started = time.time()
    source_name = "manual_text"
    rows: List[List[Any]] = []
    if file is not None:
        content = await file.read()
        source_name = file.filename or "uploaded_file"
        rows.extend(_text_rows_from_upload(source_name, content))
    if raw_text.strip():
        rows.extend([re.split(r"[\t,; ]{2,}", line.strip()) for line in raw_text.splitlines() if line.strip()])

    parsed = _parse_manual_top_gainer_rows(rows)
    scored = [_manual_top_gainer_score(item, idx) for idx, item in enumerate(parsed, start=1)]
    scored.sort(
        key=lambda x: (
            1 if x.get("analytic_expectation") == "EXECUTABLE_TOP3" else 0,
            to_float(x.get("final_score")),
            to_float(x.get("value")),
            to_float(x.get("freq")),
        ),
        reverse=True,
    )
    for idx, item in enumerate(scored, start=1):
        item["manual_rank"] = idx
        item["mover_rank"] = idx
        if isinstance(item.get("top_gainer_opportunity"), dict):
            item["top_gainer_opportunity"]["rank"] = idx

    executable = [x for x in scored if x.get("analytic_expectation") == "EXECUTABLE_TOP3"]
    conditional = [x for x in scored if x.get("analytic_expectation") == "CONDITIONAL_EXECUTION"]
    radar = [x for x in scored if x.get("analytic_expectation") == "RADAR_NO_CHASE"]
    top3 = (executable + conditional + radar)[:3]
    return {
        "status": "ok" if parsed else "empty",
        "mode": mode,
        "source": source_name,
        "duration_sec": round(time.time() - started, 2),
        "parsed_count": len(parsed),
        "top_3": top3,
        "results": top3,
        "manual_top_gainer_candidates": scored,
        "execution_candidates": executable[:3],
        "conditional_candidates": conditional[:5],
        "no_chase_radar": radar[:10],
        "quota_policy": "Manual lane hanya enrich saham yang diupload; tidak scan 970 saham sehingga hemat token Invezgo.",
        "message": (
            "Upload berhasil; Top 3 siap dikirim ke Analytic sebagai Manual Top Gainer Lane."
            if parsed else
            "Tidak ada baris top gainer valid. Pastikan ada kolom Symbol dan Price(+%)."
        ),
    }


# ===== Main API =====

@router.post("/run")
async def run_screener(request: ScreenerRequest) -> Dict[str, Any]:
    started = time.time()
    mode: Mode = request.mode
    cfg = MODE_CONFIG[mode]

    try:
        market_execution_regime = await build_market_execution_regime()
        universe = await build_universe(mode)
        candidates = await ohlcv_prefilter(universe, mode, request.filter_intensity)
        strict_candidate_count = len(candidates)
        adaptive_used = False
        if not candidates:
            candidates = await ohlcv_prefilter(universe, mode, 50, adaptive=True)
            candidates = candidates[:25]
            adaptive_used = bool(candidates)
        scored = await score_candidates(candidates, mode)
        opening_seed_radar = await build_opening_seed_radar(scored, mode)
        if opening_seed_radar:
            scored.extend(opening_seed_radar)
        qualified = apply_disqualifiers(scored, mode)
        strict_qualified_count = len(qualified)
        watchlist_fallback_used = False
        if not qualified and scored:
            qualified = build_watchlist_fallback(scored, mode, request.limit)
            watchlist_fallback_used = bool(qualified)
        top = rank_top(qualified, request.limit)
        top = annotate_screener_lanes(top, market_execution_regime, watchlist_fallback_used)
        top_gainer_universe_count = len([x for x in universe if x.get("_opportunity_lane") == "top_gainer"])
        opening_feed_fallback_count = len([x for x in scored if x.get("data_status") == "STALE_DAILY_TOP_GAINER_FALLBACK"])
        top_gainer_opportunities = annotate_screener_lanes(
            [
                x for x in scored
                if isinstance(x.get("top_gainer_opportunity"), dict)
                and x["top_gainer_opportunity"].get("available")
            ][:10],
            market_execution_regime,
            watchlist_fallback_used,
        )
        no_chase_radar = annotate_screener_lanes(
            [
                x for x in scored
                if x.get("no_chase_radar")
                or (isinstance(x.get("top_gainer_opportunity"), dict) and x["top_gainer_opportunity"].get("radar_only"))
            ][:10],
            market_execution_regime,
            watchlist_fallback_used,
        )
        official_enrichment = {"available": False}
        if enrich_screener_results is not None and top:
            try:
                official_enrichment = await enrich_screener_results(top, mode)
            except Exception as exc:
                logger.warning("[SCREENER] official enrichment skipped: %s", exc)
                official_enrichment = {"available": False, "reason": str(exc)[:160]}

        response: Dict[str, Any] = {
            "status": "watchlist" if watchlist_fallback_used else "ok",
            "mode": mode,
            "message": "Strict screener kosong; menampilkan adaptive watchlist untuk observasi, bukan entry otomatis." if watchlist_fallback_used else "",
            "market_execution_regime": market_execution_regime,
            "duration_sec": round(time.time() - started, 2),
            "universe_count": len(universe),
            "candidate_count": len(candidates),
            "strict_candidate_count": strict_candidate_count,
            "scored_count": len(scored),
            "qualified_count": len(qualified),
            "strict_qualified_count": strict_qualified_count,
            "top_gainer_universe_count": top_gainer_universe_count,
            "opening_feed_fallback_count": opening_feed_fallback_count,
            "adaptive_prefilter_used": adaptive_used,
            "watchlist_fallback_used": watchlist_fallback_used,
            "top_5": top,
            "results": top,
            "execution_candidates": [x for x in top if x.get("screener_lane") in ("EXECUTION_CANDIDATE", "DEFENSIVE_QUALIFIED_CANDIDATE")],
            "top_gainer_opportunities": top_gainer_opportunities,
            "no_chase_radar": no_chase_radar,
            "official_enrichment": official_enrichment,
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
                "prefilter": await debug_prefilter_rejections(universe, mode, request.filter_intensity),
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
    except Exception as exc:
        logger.exception("[SCREENER] run failed")
        return {
            "status": "degraded",
            "mode": mode,
            "duration_sec": round(time.time() - started, 2),
            "universe_count": 0,
            "candidate_count": 0,
            "scored_count": 0,
            "qualified_count": 0,
            "top_5": [],
            "results": [],
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "message": "Screener sementara berjalan dalam mode aman karena data upstream belum tersedia.",
            "config": {
                "rvol_min": cfg["rvol_min"],
                "change_min": cfg["change_min"],
                "candidate_max": cfg["candidate_max"],
                "min_score": cfg["min_score"],
            },
        }
