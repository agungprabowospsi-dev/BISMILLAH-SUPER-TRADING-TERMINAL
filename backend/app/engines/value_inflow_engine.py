"""
ValueInflowEngine — Value Inflow Index
Mengukur aliran nilai Rupiah dari broker institusi vs retail
Referensi: Bandar Flow Secrets Toolkit (Buku 3)
"""
from typing import Dict, Any, List

FOREIGN_BROKERS   = {"YP","BK","RX","ZP","AK","CC","DB","MS","CS","ML","DP","KI","OD","LG"}
PREMIUM_BROKERS   = {"GS","MU","NK","LS","EP","FZ","YU","KK","DH","PC","BW","GA","RO","CP",
                     "BK","RX","ZP","AK","MS","CS","ML","DP","KI"}
RETAIL_BROKERS    = {"IF","PD","HP","KS","FH","IN","RB","ID","YP","OD"}

def analyze_value_inflow(broker_data: List[Dict]) -> Dict[str, Any]:
    """
    Hitung Value Inflow Index:
    - Institutional inflow (Rupiah masuk dari broker premium/asing)
    - Retail inflow (Rupiah masuk dari broker retail)
    - Smart Money Ratio = institutional / total
    """
    if not broker_data:
        return {"score": 50, "signal": "NEUTRAL", "reason": "no data"}

    inst_buy = inst_sell = 0.0
    retail_buy = retail_sell = 0.0
    foreign_buy = foreign_sell = 0.0
    total_buy = total_sell = 0.0

    for b in broker_data:
        code     = b.get("code", "")
        buy_val  = float(b.get("buy_value",  0) or 0)
        sell_val = float(b.get("sell_value", 0) or 0)
        total_buy  += buy_val
        total_sell += sell_val

        if code in FOREIGN_BROKERS:
            foreign_buy  += buy_val
            foreign_sell += sell_val
            inst_buy     += buy_val
            inst_sell    += sell_val
        elif code in PREMIUM_BROKERS:
            inst_buy  += buy_val
            inst_sell += sell_val
        elif code in RETAIL_BROKERS:
            retail_buy  += buy_val
            retail_sell += sell_val

    total_val = total_buy + total_sell
    if total_val == 0:
        return {"score": 50, "signal": "NEUTRAL", "reason": "zero value"}

    # Value Inflow Index
    inst_net    = inst_buy    - inst_sell
    retail_net  = retail_buy  - retail_sell
    foreign_net = foreign_buy - foreign_sell
    total_net   = total_buy   - total_sell

    # Smart Money Ratio
    sm_ratio = (inst_buy / total_buy) if total_buy > 0 else 0

    # Scoring
    score = 50.0
    if inst_net > 0 and sm_ratio > 0.4:
        score = 80
        signal = "SMART_MONEY_INFLOW"
    elif inst_net > 0 and foreign_net > 0:
        score = 72
        signal = "INSTITUTIONAL_BUYING"
    elif inst_net > 0:
        score = 62
        signal = "MILD_INSTITUTIONAL"
    elif retail_net > 0 and inst_net < 0:
        score = 35
        signal = "RETAIL_CHASING_DISTRIBUTION"
    elif inst_net < 0 and foreign_net < 0:
        score = 28
        signal = "SMART_MONEY_OUTFLOW"
    else:
        score = 50
        signal = "NEUTRAL"

    return {
        "score": round(score, 2),
        "signal": signal,
        "institutional_net_bil": round(inst_net / 1e9, 2),
        "foreign_net_bil":       round(foreign_net / 1e9, 2),
        "retail_net_bil":        round(retail_net / 1e9, 2),
        "total_net_bil":         round(total_net / 1e9, 2),
        "smart_money_ratio":     round(sm_ratio * 100, 1),
        "inst_buy_bil":          round(inst_buy / 1e9, 2),
        "retail_buy_bil":        round(retail_buy / 1e9, 2),
        "divergence": (
            "ACCUMULATION"  if inst_net > 0 and retail_net < 0 else
            "DISTRIBUTION"  if inst_net < 0 and retail_net > 0 else
            "ALIGNED_BULL"  if inst_net > 0 and retail_net > 0 else
            "ALIGNED_BEAR"  if inst_net < 0 and retail_net < 0 else
            "NEUTRAL"
        ),
    }
