import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude


# ─── ENGINE #5: RELATIVE VOLUME ───────────────────────────────────────────────
class RelativeVolumeEngine(BaseEngine):
    def __init__(self):
        super().__init__("RelativeVolumeEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")
            volumes = [c["volume"] for c in ohlcv]
            closes  = [c["close"]  for c in ohlcv]

            # RVOL = volume sekarang vs rata-rata jam/hari yang sama
            avg_10 = np.mean(volumes[-11:-1])
            avg_20 = np.mean(volumes[-20:])
            rvol_10 = volumes[-1] / avg_10 if avg_10 > 0 else 1.0
            rvol_20 = volumes[-1] / avg_20 if avg_20 > 0 else 1.0

            # Score berdasarkan RVOL dan arah harga
            price_up = closes[-1] > closes[-2]
            score = 50.0
            if rvol_10 >= 3.0:
                score = 85 if price_up else 25
            elif rvol_10 >= 2.0:
                score = 75 if price_up else 35
            elif rvol_10 >= 1.5:
                score = 65 if price_up else 40
            elif rvol_10 < 0.5:
                score = 45  # sangat sepi

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=min(90, 40 + rvol_10 * 15),
                rationale=f"RVOL {rvol_10:.2f}x vs 10-period avg. {'Bullish' if price_up else 'Bearish'} volume surge indicates {'strong buying' if price_up and rvol_10 > 1.5 else 'strong selling' if not price_up and rvol_10 > 1.5 else 'moderate'} conviction.",
                data={"rvol_10": round(rvol_10, 2), "rvol_20": round(rvol_20, 2),
                      "current_volume": int(volumes[-1]), "avg_20": int(avg_20)}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #6: MULTI TIMEFRAME ───────────────────────────────────────────────
class MultiTimeframeEngine(BaseEngine):
    def __init__(self):
        super().__init__("MultiTimeframeEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 60:
                return self._safe_result("Insufficient data for MTF")
            closes = [c["close"] for c in ohlcv]

            # Simulate multiple timeframes dari data harian
            # TF1: 5 bars (short), TF2: 20 bars (medium), TF3: 60 bars (long)
            def trend(n):
                if len(closes) < n:
                    return "neutral"
                ma = np.mean(closes[-n:])
                return "bull" if closes[-1] > ma else "bear"

            tf_short  = trend(5)
            tf_medium = trend(20)
            tf_long   = trend(60)

            # Alignment score
            bull_count = [tf_short, tf_medium, tf_long].count("bull")
            bear_count = 3 - bull_count

            if bull_count == 3:
                score, signal = 85.0, "bullish"
            elif bull_count == 2:
                score, signal = 65.0, "bullish"
            elif bear_count == 3:
                score, signal = 15.0, "bearish"
            elif bear_count == 2:
                score, signal = 35.0, "bearish"
            else:
                score, signal = 50.0, "neutral"

            alignment = "ALIGNED" if bull_count == 3 or bear_count == 3 else "MIXED"

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=signal,
                confidence=85.0 if alignment == "ALIGNED" else 50.0,
                rationale=f"MTF {alignment}: Short={tf_short}, Medium={tf_medium}, Long={tf_long}. {'All timeframes confirm direction — high conviction setup.' if alignment == 'ALIGNED' else 'Mixed signals across timeframes — wait for alignment before entry.'}",
                data={"tf_short": tf_short, "tf_medium": tf_medium, "tf_long": tf_long,
                      "alignment": alignment, "bull_count": bull_count}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #7: ORDER BLOCK ────────────────────────────────────────────────────
class OrderBlockEngine(BaseEngine):
    def __init__(self):
        super().__init__("OrderBlockEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            closes  = [c["close"]  for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]
            current = closes[-1]

            # Order block = candle sebelum big move dengan volume tinggi
            avg_vol = np.mean(volumes[-20:])
            order_blocks = []

            for i in range(5, len(ohlcv) - 1):
                if volumes[i] > avg_vol * 1.8:  # high volume candle
                    ob_high = highs[i]
                    ob_low  = lows[i]
                    order_blocks.append({"high": ob_high, "low": ob_low, "index": i})

            # Cari OB terdekat dengan harga saat ini
            bullish_obs = [ob for ob in order_blocks if ob["high"] < current]
            bearish_obs = [ob for ob in order_blocks if ob["low"] > current]

            nearest_bull_ob = max(bullish_obs, key=lambda x: x["high"]) if bullish_obs else None
            nearest_bear_ob = min(bearish_obs, key=lambda x: x["low"])  if bearish_obs else None

            score = 50.0
            if nearest_bull_ob:
                dist = (current - nearest_bull_ob["high"]) / current * 100
                if dist < 2:
                    score = 75  # Harga di atas OB bullish = support kuat
                elif dist < 5:
                    score = 65

            if nearest_bear_ob:
                dist = (nearest_bear_ob["low"] - current) / current * 100
                if dist < 2:
                    score = min(score, 35)  # Harga dekat OB bearish = resistance

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=70.0,
                rationale=f"Found {len(bullish_obs)} bullish OBs below, {len(bearish_obs)} bearish OBs above. {'Price trading above institutional order block — bullish structure intact.' if score > 60 else 'Price approaching bearish order block — potential resistance zone.' if score < 40 else 'No significant order block influence at current price.'}",
                data={
                    "bullish_ob_count": len(bullish_obs),
                    "bearish_ob_count": len(bearish_obs),
                    "nearest_bullish_ob": nearest_bull_ob,
                    "nearest_bearish_ob": nearest_bear_ob,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #8: BREAK ORDER ────────────────────────────────────────────────────
class BreakOrderEngine(BaseEngine):
    def __init__(self):
        super().__init__("BreakOrderEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            closes  = [c["close"]  for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]

            # Deteksi breakout dari range 20 bar
            range_high = max(highs[-21:-1])
            range_low  = min(lows[-21:-1])
            current    = closes[-1]
            last_vol   = volumes[-1]
            avg_vol    = np.mean(volumes[-20:])

            breakout_up   = current > range_high
            breakout_down = current < range_low
            vol_confirm   = last_vol > avg_vol * 1.3

            score = 50.0
            breakout_type = "none"

            if breakout_up and vol_confirm:
                score = 85.0
                breakout_type = "bullish_breakout"
            elif breakout_up and not vol_confirm:
                score = 65.0
                breakout_type = "weak_bullish_breakout"
            elif breakout_down and vol_confirm:
                score = 15.0
                breakout_type = "bearish_breakdown"
            elif breakout_down and not vol_confirm:
                score = 30.0
                breakout_type = "weak_bearish_breakdown"

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=85.0 if vol_confirm and (breakout_up or breakout_down) else 40.0,
                rationale=f"20-bar range: {range_low:.0f}-{range_high:.0f}. {breakout_type.replace('_', ' ').title()} detected. {'Volume confirms breakout — valid signal.' if vol_confirm else 'Low volume — potential false breakout, wait for confirmation.'}",
                data={
                    "range_high": range_high, "range_low": range_low,
                    "current": current, "breakout_type": breakout_type,
                    "volume_confirmed": vol_confirm,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #9: FAIR VALUE GAP ────────────────────────────────────────────────
class FairValueGapEngine(BaseEngine):
    def __init__(self):
        super().__init__("FairValueGapEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 10:
                return self._safe_result("Insufficient data")

            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]
            closes = [c["close"] for c in ohlcv]
            current = closes[-1]

            fvgs = []
            for i in range(1, len(ohlcv) - 1):
                # Bullish FVG: low[i+1] > high[i-1]
                if lows[i+1] > highs[i-1]:
                    fvgs.append({"type": "bullish", "low": highs[i-1], "high": lows[i+1]})
                # Bearish FVG: high[i+1] < low[i-1]
                elif highs[i+1] < lows[i-1]:
                    fvgs.append({"type": "bearish", "low": highs[i+1], "high": lows[i-1]})

            # Cek apakah harga sedang di dalam atau mendekati FVG
            score = 50.0
            active_fvg = None
            for fvg in reversed(fvgs[-10:]):
                if fvg["low"] <= current <= fvg["high"]:
                    active_fvg = fvg
                    score = 70 if fvg["type"] == "bullish" else 30
                    break

            unfilled_count = len([f for f in fvgs[-20:] if not (f["low"] <= current <= f["high"])])

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=65.0 if active_fvg else 40.0,
                rationale=f"Found {len(fvgs)} FVGs in dataset, {unfilled_count} unfilled. {'Price inside ' + active_fvg['type'] + ' FVG — potential magnet zone for price.' if active_fvg else 'No active FVG at current price — clean price action.'}",
                data={
                    "total_fvgs": len(fvgs),
                    "unfilled_fvgs": unfilled_count,
                    "active_fvg": active_fvg,
                    "recent_fvgs": fvgs[-5:],
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #10: LIQUIDITY ─────────────────────────────────────────────────────
class LiquidityEngine(BaseEngine):
    def __init__(self):
        super().__init__("LiquidityEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 20:
                return self._safe_result("Insufficient data")

            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]

            # Liquidity proxy: volume * price = value traded
            value_traded = [v * c for v, c in zip(volumes, closes)]
            avg_value = np.mean(value_traded[-20:])

            # Spread proxy: (high - low) / close
            spreads = [(h - l) / c for h, l, c in zip(highs, lows, closes)]
            avg_spread = np.mean(spreads[-20:])

            # Liquidity score
            # High value + low spread = good liquidity = easier execution
            value_score  = min(100, (avg_value / 1_000_000_000) * 50)  # normalize ke 1B IDR
            spread_score = max(0, 100 - avg_spread * 1000)

            score = value_score * 0.6 + spread_score * 0.4

            liquidity_level = "HIGH" if score > 70 else "MEDIUM" if score > 40 else "LOW"

            return EngineResult(
                engine_name=self.name,
                score=float(score),
                signal="bullish" if score > 60 else "neutral",
                confidence=80.0,
                rationale=f"Liquidity: {liquidity_level}. Avg daily value traded: {avg_value/1e9:.2f}B IDR, avg spread: {avg_spread*100:.2f}%. {'Good execution conditions.' if score > 60 else 'Moderate liquidity — use limit orders.' if score > 40 else 'Low liquidity — high slippage risk, trade with caution.'}",
                data={
                    "liquidity_level": liquidity_level,
                    "avg_value_traded_idr": round(avg_value),
                    "avg_spread_pct": round(avg_spread * 100, 3),
                    "value_score": round(value_score, 2),
                    "spread_score": round(spread_score, 2),
                }
            )
        except Exception as e:
            return self._safe_result(str(e))
