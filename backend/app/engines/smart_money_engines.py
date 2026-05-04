import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude
from app.core import invesgo


# ─── ENGINE #11: BANDARMOLOGY ─────────────────────────────────────────────────
class BandarmologyEngine(BaseEngine):
    def __init__(self):
        super().__init__("BandarmologyEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            broker_data = kwargs.get("broker_data") or {}
            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]

            # Proxy bandarmology dari price+volume jika broker data tidak ada
            avg_vol = np.mean(volumes[-20:])
            big_vol_days = sum(1 for v in volumes[-10:] if v > avg_vol * 2)

            # Akumulasi proxy: big volume + harga naik = akumulasi bandar
            up_days_big_vol = sum(
                1 for i in range(-10, 0)
                if volumes[i] > avg_vol * 1.5 and closes[i] > closes[i-1]
            )
            down_days_big_vol = sum(
                1 for i in range(-10, 0)
                if volumes[i] > avg_vol * 1.5 and closes[i] < closes[i-1]
            )

            # Score
            if up_days_big_vol > down_days_big_vol * 2:
                score = 80.0
                phase = "accumulation"
            elif down_days_big_vol > up_days_big_vol * 2:
                score = 20.0
                phase = "distribution"
            elif up_days_big_vol > down_days_big_vol:
                score = 65.0
                phase = "early_accumulation"
            else:
                score = 40.0
                phase = "uncertain"

            # Bonus dari broker data jika ada
            top_broker_net = broker_data.get("top_broker_net_buy", 0)
            if top_broker_net > 0:
                score = min(90, score + 10)
            elif top_broker_net < 0:
                score = max(10, score - 10)

            rationale = await ask_claude(
                system="You are a bandarmology expert for IDX stocks. Analyze institutional accumulation/distribution.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Big volume up days (10-bar): {up_days_big_vol}
Big volume down days (10-bar): {down_days_big_vol}
Bandar phase detected: {phase}
Top broker net: {top_broker_net}

2-sentence bandarmology analysis with trading implication.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=70.0,
                rationale=rationale,
                data={
                    "phase": phase,
                    "big_vol_up_days": up_days_big_vol,
                    "big_vol_down_days": down_days_big_vol,
                    "top_broker_net": top_broker_net,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #12: INVENTORY ────────────────────────────────────────────────────
class InventoryEngine(BaseEngine):
    def __init__(self):
        super().__init__("InventoryEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]

            # Inventory level proxy: kumulatif net volume
            net_vol = []
            for i in range(len(ohlcv)):
                body = closes[i] - ohlcv[i]["open"]
                direction = 1 if body > 0 else -1
                net_vol.append(volumes[i] * direction)

            cum_net = np.cumsum(net_vol)
            inventory_trend = "building" if cum_net[-1] > cum_net[-10] else "reducing"

            # Days to cover proxy
            avg_daily_vol = np.mean(volumes[-20:])
            est_inventory = abs(cum_net[-1])
            days_to_cover = est_inventory / avg_daily_vol if avg_daily_vol > 0 else 0

            score = 50.0
            if inventory_trend == "building" and closes[-1] > closes[-5]:
                score = 72.0
            elif inventory_trend == "building" and closes[-1] < closes[-5]:
                score = 35.0  # Inventory naik tapi harga turun = distribusi
            elif inventory_trend == "reducing":
                score = 45.0

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=60.0,
                rationale=f"Broker inventory {inventory_trend}. Est. {days_to_cover:.1f} days to cover. {'Bullish inventory build with rising price confirms accumulation.' if score > 60 else 'Inventory building while price declining suggests distribution pressure.' if score < 40 else 'Neutral inventory positioning.'}",
                data={
                    "inventory_trend": inventory_trend,
                    "days_to_cover": round(days_to_cover, 1),
                    "cumulative_net_volume": int(cum_net[-1]),
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #13: FLOW MAPPING ─────────────────────────────────────────────────
class FlowMappingEngine(BaseEngine):
    def __init__(self):
        super().__init__("FlowMappingEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]

            # Money flow index (MFI)
            mfi = self._calc_mfi(ohlcv, period=14)
            mfi_signal = "overbought" if mfi > 80 else "oversold" if mfi < 20 else "neutral"

            # Chaikin Money Flow
            cmf = self._calc_cmf(ohlcv, period=20)
            cmf_signal = "inflow" if cmf > 0.1 else "outflow" if cmf < -0.1 else "neutral"

            score = 50.0
            if cmf > 0.1 and mfi > 50:
                score = 75.0
            elif cmf > 0.2:
                score = 82.0
            elif cmf < -0.1 and mfi < 50:
                score = 30.0
            elif cmf < -0.2:
                score = 18.0

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=72.0,
                rationale=f"MFI: {mfi:.1f} ({mfi_signal}), CMF: {cmf:.3f} ({cmf_signal}). {'Strong money inflow confirms bullish bias.' if score > 65 else 'Money outflow suggests selling pressure.' if score < 40 else 'Neutral money flow — no strong directional bias.'}",
                data={
                    "mfi": round(mfi, 2),
                    "mfi_signal": mfi_signal,
                    "cmf": round(cmf, 4),
                    "cmf_signal": cmf_signal,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _calc_mfi(self, ohlcv, period=14):
        typical_prices = [(c["high"] + c["low"] + c["close"]) / 3 for c in ohlcv]
        volumes = [c["volume"] for c in ohlcv]
        pos_flow, neg_flow = 0, 0
        for i in range(1, min(period + 1, len(ohlcv))):
            mf = typical_prices[i] * volumes[i]
            if typical_prices[i] > typical_prices[i-1]:
                pos_flow += mf
            else:
                neg_flow += mf
        if neg_flow == 0:
            return 100.0
        mfr = pos_flow / neg_flow
        return 100 - (100 / (1 + mfr))

    def _calc_cmf(self, ohlcv, period=20):
        mfv_sum, vol_sum = 0, 0
        for c in ohlcv[-period:]:
            h, l, cl, v = c["high"], c["low"], c["close"], c["volume"]
            mfm = ((cl - l) - (h - cl)) / (h - l) if (h - l) > 0 else 0
            mfv_sum += mfm * v
            vol_sum += v
        return mfv_sum / vol_sum if vol_sum > 0 else 0


# ─── ENGINE #14: INTRADAY POSITIONING ────────────────────────────────────────
class IntradayPositioningEngine(BaseEngine):
    def __init__(self):
        super().__init__("IntradayPositioningEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = [c["close"] for c in ohlcv]
            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]

            # VWAP proxy dari daily data
            vwap = self._calc_vwap(ohlcv)
            current = closes[-1]
            above_vwap = current > vwap

            # Posisi dalam range hari ini
            day_high = highs[-1]
            day_low  = lows[-1]
            day_range = day_high - day_low
            position_in_range = (current - day_low) / day_range if day_range > 0 else 0.5

            # Score
            score = 50.0
            if above_vwap and position_in_range > 0.6:
                score = 75.0
            elif above_vwap and position_in_range > 0.4:
                score = 65.0
            elif not above_vwap and position_in_range < 0.4:
                score = 25.0
            elif not above_vwap:
                score = 38.0

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=65.0,
                rationale=f"Price {'above' if above_vwap else 'below'} VWAP ({vwap:.0f}). Position in day range: {position_in_range*100:.0f}%. {'Institutional buyers in control above VWAP.' if above_vwap else 'Sellers dominating below VWAP — caution for longs.'}",
                data={
                    "vwap": round(vwap, 2),
                    "current": current,
                    "above_vwap": above_vwap,
                    "position_in_range_pct": round(position_in_range * 100, 1),
                    "day_high": day_high,
                    "day_low": day_low,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _calc_vwap(self, ohlcv):
        tp_vol = sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in ohlcv[-20:])
        vol    = sum(c["volume"] for c in ohlcv[-20:])
        return tp_vol / vol if vol > 0 else ohlcv[-1]["close"]


# ─── ENGINE #15: FOREIGN FLOW ─────────────────────────────────────────────────
class ForeignFlowEngine(BaseEngine):
    def __init__(self):
        super().__init__("ForeignFlowEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            foreign_data = kwargs.get("foreign_data") or {}

            net_foreign = foreign_data.get("net_foreign_buy", 0)
            foreign_buy  = foreign_data.get("foreign_buy", 0)
            foreign_sell = foreign_data.get("foreign_sell", 0)

            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]

            # Jika tidak ada data foreign, gunakan proxy
            if not foreign_data:
                # Proxy: hari dengan volume sangat besar = kemungkinan foreign
                avg_vol = np.mean(volumes[-20:])
                big_days = [(closes[i], volumes[i]) for i in range(-5, 0) if volumes[i] > avg_vol * 2]
                foreign_proxy_bullish = sum(1 for c, v in big_days if c > closes[-2])
                net_foreign = foreign_proxy_bullish - (len(big_days) - foreign_proxy_bullish)

            score = 50.0
            if net_foreign > 0:
                score = min(85, 55 + net_foreign * 0.001)
            elif net_foreign < 0:
                score = max(15, 45 + net_foreign * 0.001)

            trend = "net_buy" if net_foreign > 0 else "net_sell" if net_foreign < 0 else "neutral"

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=75.0 if foreign_data else 45.0,
                rationale=f"Foreign flow: {trend}. Net: {net_foreign:,.0f}. {'Foreign buying adds bullish confirmation — smart money entering.' if net_foreign > 0 else 'Foreign selling pressure — monitor for continuation.' if net_foreign < 0 else 'Neutral foreign activity.'}",
                data={
                    "net_foreign": net_foreign,
                    "foreign_buy": foreign_buy,
                    "foreign_sell": foreign_sell,
                    "trend": trend,
                    "data_source": "api" if foreign_data else "proxy",
                }
            )
        except Exception as e:
            return self._safe_result(str(e))
