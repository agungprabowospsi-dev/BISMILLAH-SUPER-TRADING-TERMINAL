import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude

class TrendStructureEngine(BaseEngine):
    def __init__(self):
        super().__init__("TrendStructureEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            if len(ohlcv) < 30:
                return self._safe_result("Insufficient data")

            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]
            closes = [c["close"] for c in ohlcv]

            # Deteksi HH/HL/LH/LL (Higher Highs, Higher Lows, etc.)
            swing_highs = self._find_swings(highs, is_high=True)
            swing_lows  = self._find_swings(lows,  is_high=False)

            structure = self._classify_structure(swing_highs, swing_lows)
            structure_score = {"uptrend": 80, "downtrend": 20, "ranging": 50, "unclear": 50}[structure]

            # EMA trend alignment
            ema9  = self._ema(closes, 9)
            ema21 = self._ema(closes, 21)
            ema50 = self._ema(closes, 50) if len(closes) >= 50 else ema21

            ema_score = 50.0
            if ema9[-1] > ema21[-1] > ema50[-1]:
                ema_score = 85.0
            elif ema9[-1] < ema21[-1] < ema50[-1]:
                ema_score = 15.0
            elif ema9[-1] > ema21[-1]:
                ema_score = 65.0
            elif ema9[-1] < ema21[-1]:
                ema_score = 35.0

            # Trend strength (ADX proxy)
            adx_score = self._adx_proxy(highs, lows, closes)

            raw_score = structure_score * 0.4 + ema_score * 0.4 + adx_score * 0.2

            rationale = await ask_claude(
                system="You are a trend structure analyst for IDX stocks.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Market Structure: {structure}
EMA9: {ema9[-1]:.0f} | EMA21: {ema21[-1]:.0f} | EMA50: {ema50[-1]:.0f}
Recent swing highs: {swing_highs[-3:]}
Recent swing lows: {swing_lows[-3:]}

Provide 2-sentence trend structure analysis with trading implication.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name,
                score=raw_score,
                signal=self._signal_from_score(raw_score),
                confidence=min(90, adx_score + 30),
                rationale=rationale,
                data={
                    "structure": structure,
                    "ema9": round(ema9[-1], 2),
                    "ema21": round(ema21[-1], 2),
                    "ema50": round(ema50[-1], 2),
                    "swing_highs": swing_highs[-5:],
                    "swing_lows": swing_lows[-5:],
                    "adx_proxy": round(adx_score, 2),
                }
            )
        except Exception as e:
            self.logger.error(f"TrendStructureEngine error: {e}")
            return self._safe_result(str(e))

    def _find_swings(self, data: list, is_high: bool, window: int = 3) -> list:
        swings = []
        for i in range(window, len(data) - window):
            if is_high:
                if data[i] == max(data[i-window:i+window+1]):
                    swings.append(round(data[i], 2))
            else:
                if data[i] == min(data[i-window:i+window+1]):
                    swings.append(round(data[i], 2))
        return swings

    def _classify_structure(self, swing_highs: list, swing_lows: list) -> str:
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "unclear"
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1] > swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        ll = swing_lows[-1] < swing_lows[-2]
        if hh and hl:
            return "uptrend"
        if lh and ll:
            return "downtrend"
        return "ranging"

    def _ema(self, data: list, period: int) -> list:
        k = 2 / (period + 1)
        ema = [data[0]]
        for price in data[1:]:
            ema.append(price * k + ema[-1] * (1 - k))
        return ema

    def _adx_proxy(self, highs: list, lows: list, closes: list, period: int = 14) -> float:
        try:
            tr_list = []
            for i in range(1, len(closes)):
                tr = max(highs[i] - lows[i],
                         abs(highs[i] - closes[i-1]),
                         abs(lows[i] - closes[i-1]))
                tr_list.append(tr)
            atr = np.mean(tr_list[-period:]) if tr_list else 1
            price_move = abs(closes[-1] - closes[-period])
            adx = min(100, (price_move / atr) * 25) if atr > 0 else 25
            return float(adx)
        except:
            return 25.0
