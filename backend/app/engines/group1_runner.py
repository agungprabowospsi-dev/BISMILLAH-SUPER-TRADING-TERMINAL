import asyncio
from app.engines.price_action_engine import PriceActionEngine
from app.engines.trend_structure_engine import TrendStructureEngine
from app.engines.support_resistance_engine import SupportResistanceEngine
from app.engines.volume_intelligence_engine import VolumeIntelligenceEngine
from app.engines.market_structure_engines import (
    RelativeVolumeEngine, MultiTimeframeEngine, OrderBlockEngine,
    BreakOrderEngine, FairValueGapEngine, LiquidityEngine
)

# Weights per mode
WEIGHTS = {
    "swing":      [15, 12, 12, 10, 8, 15, 10, 8, 5, 5],
    "daytrading": [12, 10, 10, 12, 10, 15, 10, 10, 8, 3],
    "scalping":   [10, 5, 10, 12, 15, 10, 12, 12, 8, 6],
}

_engines = [
    PriceActionEngine(),
    TrendStructureEngine(),
    SupportResistanceEngine(),
    VolumeIntelligenceEngine(),
    RelativeVolumeEngine(),
    MultiTimeframeEngine(),
    OrderBlockEngine(),
    BreakOrderEngine(),
    FairValueGapEngine(),
    LiquidityEngine(),
]

async def run_group1(ticker: str, ohlcv: list, mode: str, **kwargs) -> dict:
    """Jalankan semua 10 engines Group 1 secara paralel"""
    # Fix: cast semua field numeric ke float agar numpy tidak error
    ohlcv = [{
        **c,
        "open":   float(c.get("open",   0) or 0),
        "high":   float(c.get("high",   0) or 0),
        "low":    float(c.get("low",    0) or 0),
        "close":  float(c.get("close",  0) or 0),
        "volume": float(c.get("volume", 0) or 0),
    } for c in ohlcv]
    tasks = [e.analyze(ticker, ohlcv, mode, **kwargs) for e in _engines]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    weights = WEIGHTS.get(mode, WEIGHTS["swing"])
    total_weight = sum(weights)

    engine_results = []
    weighted_score = 0.0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            continue
        engine_results.append(result.to_dict())
        weighted_score += result.score * (weights[i] / total_weight)

    bullish = sum(1 for r in engine_results if r["signal"] == "bullish")
    bearish = sum(1 for r in engine_results if r["signal"] == "bearish")
    consensus = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

    return {
        "group": "market_structure",
        "group_score": round(weighted_score, 2),
        "consensus": consensus,
        "engines": engine_results,
        "bullish_count": bullish,
        "bearish_count": bearish,
    }
