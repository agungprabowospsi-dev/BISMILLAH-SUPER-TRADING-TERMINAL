import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude

class SupportResistanceEngine(BaseEngine):
    def __init__(self):
        super().__init__("SupportResistanceEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]
            closes = [c["close"] for c in ohlcv]
            current = closes[-1]

            # Identifikasi S/R levels
            levels = self._find_sr_levels(highs, lows, closes)
            nearest_support    = self._nearest_below(levels, current)
            nearest_resistance = self._nearest_above(levels, current)

            # Jarak ke S/R
            support_dist    = ((current - nearest_support)    / current * 100) if nearest_support    else 999
            resistance_dist = ((nearest_resistance - current) / current * 100) if nearest_resistance else 999

            # Score: makin dekat ke support = lebih bullish (buying opportunity)
            # makin dekat ke resistance = lebih bearish (selling pressure)
            if support_dist < resistance_dist:
                # Dekat resistance
                score = 50 - (resistance_dist * 2)
                score = max(20, score)
            else:
                # Dekat support / sudah bounce
                score = 50 + (support_dist * 2)
                score = min(80, score)

            # Bonus: apakah harga baru bounce dari support?
            if len(closes) >= 3:
                prev_low = min(lows[-3:])
                if nearest_support and abs(prev_low - nearest_support) / nearest_support < 0.01:
                    score = min(90, score + 15)

            rationale = await ask_claude(
                system="You are a support/resistance level analyst for IDX stocks.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Current Price: {current:.0f}
Key S/R Levels: {levels[:8]}
Nearest Support: {nearest_support} (distance: {support_dist:.2f}%)
Nearest Resistance: {nearest_resistance} (distance: {resistance_dist:.2f}%)

Provide 2-sentence S/R analysis with actionable insight.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name,
                score=float(score),
                signal=self._signal_from_score(score),
                confidence=75.0,
                rationale=rationale,
                data={
                    "current_price": current,
                    "key_levels": levels[:8],
                    "nearest_support": nearest_support,
                    "nearest_resistance": nearest_resistance,
                    "support_distance_pct": round(support_dist, 2),
                    "resistance_distance_pct": round(resistance_dist, 2),
                }
            )
        except Exception as e:
            self.logger.error(f"SREngine error: {e}")
            return self._safe_result(str(e))

    def _find_sr_levels(self, highs, lows, closes, window=5) -> list:
        levels = set()
        for i in range(window, len(closes) - window):
            if highs[i] == max(highs[i-window:i+window+1]):
                levels.add(round(highs[i], 0))
            if lows[i] == min(lows[i-window:i+window+1]):
                levels.add(round(lows[i], 0))
        # Cluster levels yang berdekatan (dalam 0.5%)
        sorted_levels = sorted(levels)
        clustered = []
        for lv in sorted_levels:
            if not clustered or abs(lv - clustered[-1]) / clustered[-1] > 0.005:
                clustered.append(lv)
        return clustered

    def _nearest_below(self, levels, price):
        below = [l for l in levels if l < price * 0.999]
        return max(below) if below else None

    def _nearest_above(self, levels, price):
        above = [l for l in levels if l > price * 1.001]
        return min(above) if above else None
