import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.knowledge_base import query_knowledge_base
from app.core.claude_client import ask_claude

class PriceActionEngine(BaseEngine):
    def __init__(self):
        super().__init__("PriceActionEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            closes = np.array([c["close"] for c in ohlcv])
            highs  = np.array([c["high"]  for c in ohlcv])
            lows   = np.array([c["low"]   for c in ohlcv])
            volumes = np.array([c["volume"] for c in ohlcv])

            # 1. Trend direction
            sma20 = np.mean(closes[-20:])
            sma5  = np.mean(closes[-5:])
            current_price = closes[-1]
            trend_score = 50.0
            if current_price > sma20 and sma5 > sma20:
                trend_score = 75.0
            elif current_price < sma20 and sma5 < sma20:
                trend_score = 25.0

            # 2. Price momentum
            momentum = (closes[-1] - closes[-10]) / closes[-10] * 100
            momentum_score = self._normalize_score(momentum, -10, 10)

            # 3. Volume confirmation
            avg_vol = np.mean(volumes[-20:])
            last_vol = volumes[-1]
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1
            vol_score = min(100, vol_ratio * 50)

            # 4. Candle body strength
            last_body = abs(closes[-1] - ohlcv[-1]["open"])
            last_range = highs[-1] - lows[-1]
            body_ratio = last_body / last_range if last_range > 0 else 0.5
            body_score = body_ratio * 100

            # Composite score
            raw_score = (trend_score * 0.35 + momentum_score * 0.25 +
                        vol_score * 0.25 + body_score * 0.15)

            # RAG context dari Anna Couling
            kb_context = await query_knowledge_base(
                "anna_couling",
                f"price action {self._signal_from_score(raw_score)} trend volume confirmation"
            )

            # Claude rationale
            rationale = await ask_claude(
                system="You are an expert price action analyst. Analyze concisely based on the reference material provided.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Price: {current_price:.0f} | SMA20: {sma20:.0f} | SMA5: {sma5:.0f}
Momentum 10-bar: {momentum:.2f}%
Volume ratio: {vol_ratio:.2f}x average
Body strength: {body_ratio:.2f}

Reference (Anna Couling - Volume Price Action):
{kb_context[:800] if kb_context else 'Knowledge base not available'}

Provide a 2-sentence price action analysis with specific observation and trading implication.
""",
                max_tokens=200
            )

            return EngineResult(
                engine_name=self.name,
                score=raw_score,
                signal=self._signal_from_score(raw_score),
                confidence=min(95, raw_score + vol_score * 0.2),
                rationale=rationale,
                data={
                    "current_price": float(current_price),
                    "sma5": float(sma5),
                    "sma20": float(sma20),
                    "momentum_pct": round(float(momentum), 2),
                    "volume_ratio": round(float(vol_ratio), 2),
                    "body_strength": round(float(body_ratio), 2),
                    "trend_score": round(trend_score, 2),
                }
            )
        except Exception as e:
            self.logger.error(f"PriceActionEngine error: {e}")
            return self._safe_result(str(e))
