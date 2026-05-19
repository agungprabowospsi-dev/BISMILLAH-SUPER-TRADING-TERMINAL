# enrichment/divergence.py
import logging, json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _ema(data, period):
    k = 2/(period+1)
    result = []
    for i,v in enumerate(data):
        result.append(v if i==0 or result[i-1] is None else v*k+result[i-1]*(1-k))
    return result

def _wavetrend(ohlcv, n1=10, n2=21):
    hlc3  = [(b["high"]+b["low"]+b["close"])/3 for b in ohlcv]
    ema1  = _ema(hlc3, n1)
    adev  = [abs(hlc3[i]-(ema1[i] or hlc3[i])) for i in range(len(hlc3))]
    edev  = _ema(adev, n1)
    ci    = [(hlc3[i]-(ema1[i] or hlc3[i]))/(0.015*(edev[i] or 1e-10)) for i in range(len(hlc3))]
    wt1   = _ema(ci, n2)
    return [v or 0.0 for v in wt1]

def _pivot_high(highs, idx, left=3, right=3):
    if idx < left or idx+right >= len(highs): return False
    v = highs[idx]
    return all(highs[j] < v for j in range(idx-left,idx)) and \
           all(highs[j] < v for j in range(idx+1,idx+right+1))

def _pivot_low(lows, idx, left=3, right=3):
    if idx < left or idx+right >= len(lows): return False
    v = lows[idx]
    return all(lows[j] > v for j in range(idx-left,idx)) and \
           all(lows[j] > v for j in range(idx+1,idx+right+1))

class DivergenceStateMachine:
    def __init__(self, pivot_left=3, pivot_right=3):
        self.pl = pivot_left; self.pr = pivot_right

    async def compute(self, ohlcv, redis_client, ticker) -> Dict[str, Any]:
        try:
            highs = [b["high"] for b in ohlcv]
            lows  = [b["low"]  for b in ohlcv]
            n     = len(ohlcv)
            wt    = _wavetrend(ohlcv)
            cur_wt = wt[-1]

            end = n - self.pr - 1
            ph_list, pl_list = [], []
            for i in range(self.pl, end+1):
                if _pivot_high(highs, i, self.pl, self.pr):
                    ph_list.append({"idx":i,"price":highs[i],"wt":wt[i],"bars_ago":n-1-i})
                if _pivot_low(lows, i, self.pl, self.pr):
                    pl_list.append({"idx":i,"price":lows[i],"wt":wt[i],"bars_ago":n-1-i})

            lph = ph_list[-1] if len(ph_list)>=1 else None
            pph = ph_list[-2] if len(ph_list)>=2 else None
            lpl = pl_list[-1] if len(pl_list)>=1 else None
            ppl = pl_list[-2] if len(pl_list)>=2 else None

            state="CLEAR"; div_type=None; bars_ago=0; sl_action="NORMAL"

            if lph and pph:
                if lph["price"]>pph["price"] and lph["wt"]<pph["wt"]:
                    state="BEARISH_WARN"; div_type="REGULAR"; bars_ago=lph["bars_ago"]
                    sl_action="SKIP_ENTRY" if bars_ago<=3 else "TIGHTEN"
                elif lph["price"]<pph["price"] and lph["wt"]>pph["wt"]:
                    state="HIDDEN_BEAR"; div_type="HIDDEN"; bars_ago=lph["bars_ago"]
                    sl_action="TIGHTEN"

            if lpl and ppl and state=="CLEAR":
                if lpl["price"]<ppl["price"] and lpl["wt"]>ppl["wt"]:
                    state="BULLISH_DIV"; div_type="REGULAR"; bars_ago=lpl["bars_ago"]
                elif lpl["price"]>ppl["price"] and lpl["wt"]<ppl["wt"]:
                    state="HIDDEN_BULL"; div_type="HIDDEN"; bars_ago=lpl["bars_ago"]

            interp_map = {
                "BEARISH_WARN": f"Regular BEARISH div {bars_ago} bar lalu. {'Skip entry.' if sl_action=='SKIP_ENTRY' else 'SL diperketat.'}",
                "HIDDEN_BEAR":  f"Hidden BEARISH div {bars_ago} bar lalu. Downtrend berlanjut.",
                "BULLISH_DIV":  f"Regular BULLISH div {bars_ago} bar lalu. Sinyal reversal naik.",
                "HIDDEN_BULL":  f"Hidden BULLISH div {bars_ago} bar lalu. Uptrend berlanjut.",
                "CLEAR":        "Tidak ada divergence. Harga dan momentum searah.",
            }

            # Simpan ke Redis
            try:
                new_state = {"ticker":ticker,"state":state,"div_type":div_type,
                             "sl_action":sl_action,"bars_ago":bars_ago,
                             "updated_at":datetime.now(timezone.utc).isoformat()}
                await redis_client.setex(f"enrich:div:{ticker}", 86400, json.dumps(new_state))
            except Exception as re:
                logger.warning(f"Redis save divergence failed: {re}")

            return {"state":state,"div_type":div_type,"bars_ago":bars_ago,
                    "oscillator_val":round(cur_wt,2),"sl_action":sl_action,
                    "cached":False,"interpretation":interp_map.get(state,"")}

        except Exception as e:
            logger.error(f"Divergence error [{ticker}]: {e}")
            return {"state":"CLEAR","div_type":None,"bars_ago":0,
                    "oscillator_val":0.0,"sl_action":"NORMAL",
                    "cached":False,"interpretation":f"Error: {e} — default CLEAR"}
