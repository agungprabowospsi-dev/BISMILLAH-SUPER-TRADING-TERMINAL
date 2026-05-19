# enrichment/lele_exhaustion.py
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class LeleExhaustion:
    def __init__(self, maj_qual=13, maj_len=40, min_qual=5, min_len=13):
        self.maj_qual=maj_qual; self.maj_len=maj_len
        self.min_qual=min_qual; self.min_len=min_len

    def compute(self, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            if len(ohlcv) < self.maj_len + 5:
                raise ValueError("Data terlalu pendek")

            closes = [b["close"] for b in ohlcv]
            opens  = [b["open"]  for b in ohlcv]
            highs  = [b["high"]  for b in ohlcv]
            lows   = [b["low"]   for b in ohlcv]
            n = len(closes)

            bull_count = bear_count = 0
            for i in range(4, n):
                if closes[i] > closes[i-4]:
                    bull_count += 1; bear_count = 0
                elif closes[i] < closes[i-4]:
                    bear_count += 1; bull_count = 0
                else:
                    bull_count = bear_count = 0

            i = n-1
            bearish_c = closes[i] < opens[i]
            bullish_c = closes[i] > opens[i]

            def highest(arr, length, idx):
                return max(arr[max(0,idx-length+1):idx+1])
            def lowest(arr, length, idx):
                return min(arr[max(0,idx-length+1):idx+1])

            maj_h = highest(highs, self.maj_len, i)
            maj_l = lowest(lows,   self.maj_len, i)
            min_h = highest(highs, self.min_len, i)
            min_l = lowest(lows,   self.min_len, i)

            tol = 0.01
            maj_bull = bull_count>=self.maj_qual and bearish_c and abs(highs[i]-maj_h)<tol*highs[i]
            maj_bear = bear_count>=self.maj_qual and bullish_c and abs(lows[i]-maj_l)<tol*lows[i]
            min_bull = bull_count>=self.min_qual and bearish_c and abs(highs[i]-min_h)<tol*highs[i]
            min_bear = bear_count>=self.min_qual and bullish_c and abs(lows[i]-min_l)<tol*lows[i]

            cur_count = max(bull_count, bear_count)

            if maj_bull or maj_bear:
                return {"detected":True,"severity":"MAJOR","count":int(cur_count),
                        "bars_ago":0,"bullish_exhaust":maj_bull,"bearish_exhaust":maj_bear,
                        "tp_signal":"TAKE_PARTIAL",
                        "interpretation":f"MAJOR exhaustion setelah {cur_count} bar. Ambil TP1 sekarang."}
            elif min_bull or min_bear:
                return {"detected":True,"severity":"MINOR","count":int(cur_count),
                        "bars_ago":0,"bullish_exhaust":min_bull,"bearish_exhaust":min_bear,
                        "tp_signal":"TAKE_PARTIAL",
                        "interpretation":f"MINOR exhaustion ({cur_count} bar). Pertimbangkan partial profit."}
            else:
                tp = "HOLD" if cur_count >= self.min_qual else "NO_ACTION"
                return {"detected":False,"severity":"NONE","count":int(cur_count),
                        "bars_ago":0,"bullish_exhaust":False,"bearish_exhaust":False,
                        "tp_signal":tp,
                        "interpretation":f"Tidak ada exhaustion. Momentum count: {cur_count}. {'Hold ke TP2/TP3.' if tp=='HOLD' else ''}"}
        except Exception as e:
            logger.error(f"LeleExhaustion error: {e}")
            return {"detected":False,"severity":"ERROR","count":0,"bars_ago":0,
                    "bullish_exhaust":False,"bearish_exhaust":False,
                    "tp_signal":"NO_ACTION","interpretation":str(e)}
