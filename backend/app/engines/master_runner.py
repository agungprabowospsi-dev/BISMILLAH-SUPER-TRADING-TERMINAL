import asyncio
import numpy as np
from app.engines.group1_runner import run_group1
from app.engines.smart_money_engines import (
    BandarmologyEngine, InventoryEngine, FlowMappingEngine,
    IntradayPositioningEngine, ForeignFlowEngine
)
from app.engines.execution_engines import (
    QuantEdgeEngine, OrderbookEngine, RelativeStrengthEngine,
    FibonacciEngine, AIPatternRecognitionEngine, SectorRotationEngine,
    MacroMarketEngine, MacroEconomicsEngine, GeopoliticsEngine,
    NewsSentimentEngine, InsiderOwnershipEngine, ProbabilityEngine,
    TradingSetupEngine
)
from app.engines.decision_engines import (
    RiskManagementEngine, FinalScorecardEngine, AIConfidenceEngine,
    SmartRotationEngine, RealtimeAlertEngine, LiquidityQualityEngine
)

# Singleton engines
_g2 = [BandarmologyEngine(), InventoryEngine(), FlowMappingEngine(),
       IntradayPositioningEngine(), ForeignFlowEngine()]

_g3 = [QuantEdgeEngine(), OrderbookEngine(), RelativeStrengthEngine(),
       FibonacciEngine(), AIPatternRecognitionEngine(), SectorRotationEngine(),
       MacroMarketEngine(), MacroEconomicsEngine(), GeopoliticsEngine(),
       NewsSentimentEngine(), InsiderOwnershipEngine(), ProbabilityEngine(),
       TradingSetupEngine()]

_g4 = [RiskManagementEngine(), FinalScorecardEngine(), AIConfidenceEngine(),
       SmartRotationEngine(), RealtimeAlertEngine(), LiquidityQualityEngine()]

G2_WEIGHTS = {"swing": [25,20,20,15,20], "daytrading": [28,20,20,20,12], "scalping": [30,20,20,20,10]}
G3_WEIGHTS = {"swing": [10,5,8,10,12,10,8,8,5,8,6,5,5], "daytrading": [10,8,8,8,10,8,6,6,4,10,5,8,9], "scalping": [12,15,8,6,8,5,4,4,3,8,3,12,12]}

async def run_all_engines(ticker: str, ohlcv: list, mode: str, **kwargs) -> dict:
    """Jalankan semua 34 engines dan return hasil lengkap"""

    # Group 1 (sudah ada)
    g1_task = run_group1(ticker, ohlcv, mode, **kwargs)

    # Group 2 paralel
    g2_tasks = [e.analyze(ticker, ohlcv, mode, **kwargs) for e in _g2]

    # Group 3 paralel
    g3_tasks = [e.analyze(ticker, ohlcv, mode, **kwargs) for e in _g3]

    # Run G1, G2, G3 paralel
    g1, *g2_g3 = await asyncio.gather(g1_task, *g2_tasks, *g3_tasks, return_exceptions=True)
    g2_results = g2_g3[:5]
    g3_results = g2_g3[5:]

    # Hitung group scores
    def group_score(results, weights_key, weights_dict):
        weights = weights_dict.get(mode, list(weights_dict.values())[0])
        total_w = sum(weights)
        score = 0
        for i, r in enumerate(results):
            if not isinstance(r, Exception) and hasattr(r, 'score'):
                score += r.score * (weights[i] / total_w)
        return score

    g2_score = group_score(g2_results, mode, G2_WEIGHTS)
    g3_score = group_score(g3_results, mode, G3_WEIGHTS)
    g1_score = g1["group_score"] if isinstance(g1, dict) else 50.0

    # Group 4 butuh hasil sebelumnya
    all_scores = {
        "market_structure": g1_score,
        "smart_money": g2_score,
        "execution": g3_score,
        "decision": 50.0,
    }

    all_results = []
    if isinstance(g1, dict):
        all_results.extend(g1.get("engines", []))
    for r in g2_results + g3_results:
        if not isinstance(r, Exception) and hasattr(r, 'to_dict'):
            all_results.append(r.to_dict())

    # Composite sementara untuk G4
    gw = {"swing": [0.35,0.30,0.25,0.10], "daytrading": [0.30,0.35,0.25,0.10], "scalping": [0.20,0.40,0.30,0.10]}
    w = gw.get(mode, gw["swing"])
    composite = g1_score*w[0] + g2_score*w[1] + g3_score*w[2] + 50*w[3]

    # Group 4
    g4_kwargs = {**kwargs, "composite_score": composite, "all_engine_scores": all_scores, "engine_results": all_results}
    g4_tasks = [e.analyze(ticker, ohlcv, mode, **g4_kwargs) for e in _g4]
    g4_results = await asyncio.gather(*g4_tasks, return_exceptions=True)

    g4_score = np.mean([r.score for r in g4_results if not isinstance(r, Exception) and hasattr(r, 'score')])
    all_scores["decision"] = float(g4_score)

    # Final composite
    final_composite = g1_score*w[0] + g2_score*w[1] + g3_score*w[2] + g4_score*w[3]

    for r in g4_results:
        if not isinstance(r, Exception) and hasattr(r, 'to_dict'):
            all_results.append(r.to_dict())

    return {
        "ticker": ticker,
        "mode": mode,
        "composite_score": round(final_composite, 2),
        "group_scores": {k: round(v, 2) for k, v in all_scores.items()},
        "signal": "bullish" if final_composite >= 60 else "bearish" if final_composite <= 40 else "neutral",
        "total_engines": len(all_results),
        "engines": all_results,
    }


# ─── MONITORING-ONLY RUNNER (6 engines) ──────────────────────────────────────
from app.engines.price_action_engine import PriceActionEngine
from app.engines.volume_intelligence_engine import VolumeIntelligenceEngine
from app.engines.support_resistance_engine import SupportResistanceEngine
from app.engines.trend_structure_engine import TrendStructureEngine

_monitoring_engines = [
    PriceActionEngine(),
    VolumeIntelligenceEngine(),
    BandarmologyEngine(),
    TrendStructureEngine(),
    SupportResistanceEngine(),
    OrderbookEngine(),
    ForeignFlowEngine(),
]

async def run_monitoring_engines(ticker: str, ohlcv: list, mode: str, **kwargs) -> dict:
    """Jalankan hanya 5 engines untuk monitoring — lebih cepat."""
    tasks = [e.analyze(ticker, ohlcv, mode, **kwargs) for e in _monitoring_engines]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    scores = []
    for r in results:
        if not isinstance(r, Exception) and hasattr(r, "score"):
            all_results.append(r.to_dict())
            scores.append(r.score)

    composite = float(np.mean(scores)) if scores else 50.0

    return {
        "ticker": ticker,
        "mode": mode,
        "composite_score": round(composite, 2),
        "signal": "bullish" if composite >= 60 else "bearish" if composite <= 40 else "neutral",
        "total_engines": len(all_results),
        "engines": all_results,
    }
