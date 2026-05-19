# enrichment/smart_mfi.py
import logging
from typing import List, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)

def _sma(data, period):
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i-period+1:i+1]) / period)
    return result

def _compute_mfi_raw(highs, lows, closes, volumes, period):
    n = len(closes)
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(n)]
    mf = [tp[i]*volumes[i] for i in range(n)]
    result = []
    for i in range(n):
        if i < period:
            result.append(None)
            continue
        pos = neg = 0.0
        for j in range(i-period+1, i+1):
            if tp[j] > tp[j-1]: pos += mf[j]
            elif tp[j] < tp[j-1]: neg += mf[j]
        result.append(50.0 if pos+neg == 0 else 100*pos/(pos+neg))
    return result

class SmartMFI:
    def __init__(self, mfL=35, mfS=6):
        self.mfL = mfL
        self.mfS = mfS

    def compute(self, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            if len(ohlcv) < self.mfL + self.mfS:
                raise ValueError("Data terlalu pendek")

            highs   = [b["high"]   for b in ohlcv]
            lows    = [b["low"]    for b in ohlcv]
            closes  = [b["close"]  for b in ohlcv]
            volumes = [b["volume"] for b in ohlcv]

            mfi_raw     = _compute_mfi_raw(highs, lows, closes, volumes, self.mfL)
            mfi_shifted = [(v-50) if v is not None else None for v in mfi_raw]
            mfi_smooth  = _sma([v if v is not None else 0 for v in mfi_shifted], self.mfS)

            bull_vals = deque(maxlen=self.mfL)
            bear_vals = deque(maxlen=self.mfL)
            t_bull_series = []
            t_bear_series = []

            for v in mfi_smooth:
                if v is None:
                    t_bull_series.append(5.0)
                    t_bear_series.append(-5.0)
                    continue
                if v > 0: bull_vals.append(v)
                elif v < 0: bear_vals.append(v)
                t_bull_series.append(sum(bull_vals)/len(bull_vals) if bull_vals else 5.0)
                t_bear_series.append(sum(bear_vals)/len(bear_vals) if bear_vals else -5.0)

            cur      = mfi_smooth[-1] or 0.0
            t_bull   = t_bull_series[-1]
            t_bear   = t_bear_series[-1]
            above    = cur > 0 and cur > t_bull
            below    = cur < 0 and cur < t_bear

            if above:
                signal = "BULLISH"
                interp = f"Flow positif ({cur:+.1f}) melampaui threshold ({t_bull:.1f}). Timing VALID."
            elif below:
                signal = "BEARISH"
                interp = f"Flow negatif ({cur:+.1f}) di bawah threshold ({t_bear:.1f}). Hindari entry."
            elif cur > 0:
                signal = "NEUTRAL_POSITIVE"
                interp = f"Flow positif ({cur:+.1f}) belum melampaui threshold. Tunggu konfirmasi."
            else:
                signal = "NEUTRAL"
                interp = f"Flow netral ({cur:+.1f})."

            history = [round(v,2) for v in mfi_smooth[-10:] if v is not None]

            return {
                "value": round(cur,2), "signal": signal,
                "above_thresh": above, "threshold_bull": round(t_bull,2),
                "threshold_bear": round(t_bear,2), "mfi_history": history,
                "interpretation": interp,
            }
        except Exception as e:
            logger.error(f"SmartMFI error: {e}")
            return {"value":0.0,"signal":"ERROR","above_thresh":False,
                    "threshold_bull":5.0,"threshold_bear":-5.0,
                    "mfi_history":[],"interpretation":str(e)}
