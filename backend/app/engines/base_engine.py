from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class EngineResult:
    engine_name: str
    score: float          # 0-100
    signal: str           # bullish | bearish | neutral
    confidence: float     # 0-100
    rationale: str
    data: dict

    def to_dict(self):
        return {
            "engine": self.engine_name,
            "score": round(self.score, 2),
            "signal": self.signal,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
            "data": self.data
        }

class BaseEngine(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"engine.{name}")

    @abstractmethod
    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        pass

    def _normalize_score(self, value: float, min_val: float, max_val: float) -> float:
        if max_val == min_val:
            return 50.0
        return max(0, min(100, ((value - min_val) / (max_val - min_val)) * 100))

    def _signal_from_score(self, score: float) -> str:
        if score >= 60:
            return "bullish"
        elif score <= 40:
            return "bearish"
        return "neutral"

    def _safe_result(self, error_msg: str) -> EngineResult:
        return EngineResult(
            engine_name=self.name,
            score=50.0,
            signal="neutral",
            confidence=0.0,
            rationale=f"Analysis unavailable: {error_msg}",
            data={}
        )
