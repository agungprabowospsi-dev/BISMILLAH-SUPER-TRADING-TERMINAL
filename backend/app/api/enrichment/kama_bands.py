# enrichment/kama_bands.py
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def _kama(data, period=50):
    fast_sc = 2/(2+1)
    slow_sc = 2/(30+1)
    n = len(data)
    result = [None]*n
    if n < period:
        return result
    result[period-1] = data[period-1]
    for i in range(period, n):
        direction  = abs(data[i] - data[i-period])
        volatility = sum(abs(data[j]-data[j-1]) for j in range(i-period+1, i+1))
        er = 0.0 if volatility == 0 else direction/volatility
        sc = (er*(fast_sc-slow_sc)+slow_sc)**2
        result[i] = result[i-1] + sc*(data[i]-result[i-1])
    return result

class KAMABands:
    def __init__(self, length=50, bd1=9.0, bd2=11.0, bd3=14.0):
        self.length = length
        self.bd1 = bd1; self.bd2 = bd2; self.bd3 = bd3

    def compute(self, ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            if len(ohlcv) < self.length + 5:
                raise ValueError("Data terlalu pendek")

            closes = [b["close"] for b in ohlcv]
            tr = []
            for i in range(len(ohlcv)):
                hl = ohlcv[i]["high"] - ohlcv[i]["low"]
                if i == 0: tr.append(hl)
                else:
                    tr.append(max(hl,
                        abs(ohlcv[i]["high"]-ohlcv[i-1]["close"]),
                        abs(ohlcv[i]["low"] -ohlcv[i-1]["close"])))

            kama_rg    = _kama(tr, self.length)
            kama_basis = _kama(closes, self.length)

            last_idx = next((i for i in range(len(kama_basis)-1,-1,-1)
                             if kama_basis[i] is not None and kama_rg[i] is not None), None)
            if last_idx is None:
                raise ValueError("Tidak ada nilai KAMA valid")

            basis = kama_basis[last_idx]
            rg    = kama_rg[last_idx]
            price = closes[-1]

            l1=basis-rg*self.bd1; l2=basis-rg*self.bd2; l3=basis-rg*self.bd3
            u1=basis+rg*self.bd1; u2=basis+rg*self.bd2; u3=basis+rg*self.bd3

            if price <= l3:
                zone,sig,interp = "BELOW_L3","INVALIDATED",f"Harga {price:,.0f} di bawah l3 ({l3:,.0f}). Setup INVALID."
            elif price <= l1:
                zone,sig,interp = "NEAR_L1","IDEAL",f"Harga {price:,.0f} di zona entry ideal (l1:{l1:,.0f}). Entry VALID."
            elif price <= l2:
                zone,sig,interp = "NEAR_L2","CONSERVATIVE",f"Harga {price:,.0f} di zona konservatif (l2:{l2:,.0f})."
            elif price <= basis:
                zone,sig,interp = "BELOW_BASIS","WAIT",f"Harga {price:,.0f} belum di zona entry. Tunggu pullback ke l1."
            elif price <= u1:
                zone,sig,interp = "ABOVE_BASIS","WAIT",f"Harga {price:,.0f} di atas basis. Tunggu pullback."
            elif price <= u3:
                zone,sig,interp = "NEAR_UPPER","WAIT",f"Harga mendekati resistance. Jangan entry."
            else:
                zone,sig,interp = "ABOVE_U3","OVERBOUGHT",f"Harga {price:,.0f} overbought ekstrem."

            return {
                "basis":round(basis,2),"lower1":round(l1,2),"lower2":round(l2,2),
                "lower3":round(l3,2),"upper1":round(u1,2),"upper2":round(u2,2),
                "upper3":round(u3,2),"current_price":round(price,2),
                "price_zone":zone,"entry_signal":sig,
                "band_width_pct":round((u3-l3)/basis*100,2),
                "interpretation":interp,
            }
        except Exception as e:
            logger.error(f"KAMABands error: {e}")
            return {"basis":0.0,"lower1":0.0,"lower2":0.0,"lower3":0.0,
                    "upper1":0.0,"upper2":0.0,"upper3":0.0,"current_price":0.0,
                    "price_zone":"ERROR","entry_signal":"ERROR",
                    "band_width_pct":0.0,"interpretation":str(e)}
