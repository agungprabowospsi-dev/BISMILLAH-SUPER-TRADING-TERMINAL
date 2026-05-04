import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude

class VolumeIntelligenceEngine(BaseEngine):
    def __init__(self):
        super().__init__("VolumeIntelligenceEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            closes  = np.array([c["close"]  for c in ohlcv])
            volumes = np.array([c["volume"] for c in ohlcv])
            opens   = np.array([c["open"]   for c in ohlcv])

            avg_vol_20 = np.mean(volumes[-20:])
            last_vol   = volumes[-1]
            vol_ratio  = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

            # OBV (On Balance Volume)
            obv = self._calc_obv(closes, volumes)
            obv_trend = "rising" if obv[-1] > obv[-5] else "falling"

            # Volume Price Trend (VPT)
            vpt = self._calc_vpt(closes, volumes)
            vpt_trend = "positive" if vpt[-1] > vpt[-5] else "negative"

            # Accumulation/Distribution
            ad = self._calc_ad(ohlcv)
            ad_trend = "accumulation" if ad[-1] > ad[-5] else "distribution"

            # Scoring
            score = 50.0

            # Volume spike up dengan harga naik = bullish
            price_up = closes[-1] > closes[-2]
            if vol_ratio > 1.5 and price_up:
                score += 20
            elif vol_ratio > 1.5 and not price_up:
                score -= 15
            elif vol_ratio < 0.7:
                score -= 5  # Low volume = weak signal

            if obv_trend == "rising":
                score += 10
            else:
                score -= 10

            if ad_trend == "accumulation":
                score += 10
            else:
                score -= 10

            score = max(0, min(100, score))

            rationale = await ask_claude(
                system="You are a volume analysis expert for IDX stocks.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Volume Ratio (vs 20-avg): {vol_ratio:.2f}x
OBV Trend: {obv_trend}
A/D Trend: {ad_trend}
Price action: {"UP" if price_up else "DOWN"} with {vol_ratio:.2f}x volume

Provide 2-sentence volume analysis indicating accumulation/distribution and trading implication.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=min(90, 50 + vol_ratio * 15),
                rationale=rationale,
                data={
                    "volume_ratio": round(float(vol_ratio), 2),
                    "avg_volume_20": int(avg_vol_20),
                    "last_volume": int(last_vol),
                    "obv_trend": obv_trend,
                    "vpt_trend": vpt_trend,
                    "ad_trend": ad_trend,
                }
            )
        except Exception as e:
            self.logger.error(f"VolumeIntelligenceEngine error: {e}")
            return self._safe_result(str(e))

    def _calc_obv(self, closes, volumes):
        obv = [0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i-1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])
        return obv

    def _calc_vpt(self, closes, volumes):
        vpt = [0]
        for i in range(1, len(closes)):
            change = (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] > 0 else 0
            vpt.append(vpt[-1] + volumes[i] * change)
        return vpt

    def _calc_ad(self, ohlcv):
        ad = [0]
        for c in ohlcv[1:]:
            h, l, cl, v = c["high"], c["low"], c["close"], c["volume"]
            mfm = ((cl - l) - (h - cl)) / (h - l) if (h - l) > 0 else 0
            ad.append(ad[-1] + mfm * v)
        return ad
