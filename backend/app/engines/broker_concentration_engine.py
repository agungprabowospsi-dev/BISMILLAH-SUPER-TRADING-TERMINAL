"""
BrokerConcentrationEngine — Herfindahl-Hirschman Index
Mengidentifikasi konsentrasi broker = jejak bandar
Referensi: Bandarmology Advanced (Buku 2), Bandar Flow Secrets (Buku 3)
"""
from typing import Dict, Any, List

# Kategorisasi broker IDX
FOREIGN_BROKERS   = {"YP","BK","RX","ZP","AK","CC","DB","MS","CS","ML","DP","KI","OD","LG"}
PREMIUM_LOCAL     = {"GS","MU","NK","LS","EP","FZ","YU","KK","DH","PC","RO","BW","GA","CP"}
RETAIL_BROKERS    = {"YP","IF","OD","PD","HP","KS","FH","IN","RB","ID"}

def analyze_broker_concentration(broker_data: List[Dict]) -> Dict[str, Any]:
    """
    Hitung Herfindahl Index dari broker_summary.
    HHI > 0.25 = 1-2 broker dominasi = bandar teridentifikasi
    HHI < 0.10 = tersebar merata = retail market
    """
    if not broker_data or len(broker_data) < 3:
        return {"score": 50, "signal": "NEUTRAL", "reason": "insufficient data"}

    # Total value (buy + sell)
    total_val = sum(
        abs(float(b.get("buy_value", 0) or 0)) + abs(float(b.get("sell_value", 0) or 0))
        for b in broker_data
    )
    if total_val == 0:
        return {"score": 50, "signal": "NEUTRAL", "reason": "zero value"}

    # Hitung HHI dari buy_value
    total_buy = sum(float(b.get("buy_value", 0) or 0) for b in broker_data)
    hhi = 0.0
    dominant_broker = ""
    dominant_share  = 0.0
    broker_scores   = []

    for b in broker_data:
        buy_val = float(b.get("buy_value", 0) or 0)
        if total_buy > 0 and buy_val > 0:
            share = buy_val / total_buy
            hhi += share ** 2
            if share > dominant_share:
                dominant_share  = share
                dominant_broker = b.get("code", "")
            broker_scores.append({
                "code": b.get("code", ""),
                "share": round(share * 100, 1),
                "buy_value": buy_val,
                "net_value": float(b.get("net_value", 0) or 0),
            })

    # Sort by share
    broker_scores.sort(key=lambda x: x["share"], reverse=True)

    # Kategorisasi dominant broker
    bandar_type = "UNKNOWN"
    if dominant_broker in FOREIGN_BROKERS:
        bandar_type = "FOREIGN_INSTITUTIONAL"
    elif dominant_broker in PREMIUM_LOCAL:
        bandar_type = "LOCAL_INSTITUTIONAL"
    elif dominant_broker in RETAIL_BROKERS:
        bandar_type = "RETAIL_DOMINATED"

    # Scoring dari HHI
    score = 50.0
    if hhi >= 0.35:
        score = 85  # Sangat terkonsentrasi = bandar kuat
        signal = "BANDAR_STRONG"
    elif hhi >= 0.25:
        score = 72  # Terkonsentrasi = bandar aktif
        signal = "BANDAR_ACTIVE"
    elif hhi >= 0.15:
        score = 58  # Semi-terkonsentrasi
        signal = "SEMI_CONCENTRATED"
    elif hhi >= 0.10:
        score = 48  # Normal
        signal = "NORMAL"
    else:
        score = 35  # Tersebar = retail market
        signal = "RETAIL_MARKET"

    # Bonus: dominant broker adalah asing = lebih kuat
    if bandar_type == "FOREIGN_INSTITUTIONAL" and signal in ("BANDAR_STRONG", "BANDAR_ACTIVE"):
        score = min(95, score + 10)
        signal = "FOREIGN_BANDAR_" + ("STRONG" if hhi >= 0.35 else "ACTIVE")

    return {
        "score": round(score, 2),
        "signal": signal,
        "hhi": round(hhi, 4),
        "dominant_broker": dominant_broker,
        "dominant_share_pct": round(dominant_share * 100, 1),
        "bandar_type": bandar_type,
        "top_brokers": broker_scores[:5],
        "concentration_level": (
            "VERY_HIGH" if hhi >= 0.35 else
            "HIGH"      if hhi >= 0.25 else
            "MEDIUM"    if hhi >= 0.15 else
            "LOW"       if hhi >= 0.10 else "VERY_LOW"
        ),
    }
