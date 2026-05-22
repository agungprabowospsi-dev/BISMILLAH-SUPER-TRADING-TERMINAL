"""
Price Distribution Engine — Bandarmologi dari Volume Profile
Menganalisis distribusi volume per level harga (price-table Invesgo)
untuk mendeteksi akumulasi/distribusi bandar secara real-time.
"""
from typing import Dict, Any, List, Optional


def analyze_price_distribution(price_table: List[Dict]) -> Dict[str, Any]:
    """
    Analisis price distribution table untuk sinyal bandarmologi.
    
    Returns:
        poc_price: Point of Control (level volume terbesar)
        signal: ACCUMULATION / DISTRIBUTION / NEUTRAL
        score: 0-100 (bandarmologi score dari price distribution)
        bandar_absorption: level dimana bandar absorb supply
        distribution_levels: level dimana distribusi terdeteksi
        support_levels: support dari volume profile
        resistance_levels: resistance dari volume profile
        net_bias: net buy/sell total
    """
    if not price_table or len(price_table) < 2:
        return {
            "score": 50, "signal": "NEUTRAL",
            "poc_price": 0, "reason": "insufficient data"
        }

    # Hitung total volume
    total_buy  = sum(float(d.get("buy_volume",  0) or 0) for d in price_table)
    total_sell = sum(float(d.get("sell_volume", 0) or 0) for d in price_table)
    total_vol  = total_buy + total_sell

    if total_vol == 0:
        return {"score": 50, "signal": "NEUTRAL", "poc_price": 0, "reason": "zero volume"}

    # POC = level dengan volume terbesar
    poc_price = 0
    poc_vol   = 0
    for d in price_table:
        vol = float(d.get("buy_volume", 0) or 0) + float(d.get("sell_volume", 0) or 0)
        if vol > poc_vol:
            poc_vol   = vol
            poc_price = float(d.get("price", 0) or 0)

    # HVA = level dengan volume > 15% total
    hva = [d for d in price_table
           if (float(d.get("buy_volume",0) or 0) + float(d.get("sell_volume",0) or 0)) > total_vol * 0.15]

    # Bandar absorption = buy_freq >> sell_freq (bandar absorb supply retail)
    bandar_absorption = []
    for d in price_table:
        bf = float(d.get("buy_freq",  0) or 0)
        sf = float(d.get("sell_freq", 0) or 0)
        price = float(d.get("price", 0) or 0)
        if bf > 500 and sf == 0:
            bandar_absorption.append({"price": price, "type": "PURE_BUY", "ratio": 999})
        elif bf > 0 and sf > 0 and (bf / sf) >= 2.5:
            bandar_absorption.append({"price": price, "type": "ABSORB", "ratio": round(bf/sf, 1)})

    # Distribution = sell_freq >> buy_freq
    distribution_levels = []
    for d in price_table:
        bf = float(d.get("buy_freq",  0) or 0)
        sf = float(d.get("sell_freq", 0) or 0)
        price = float(d.get("price", 0) or 0)
        if sf > 500 and bf == 0:
            distribution_levels.append({"price": price, "type": "PURE_SELL", "ratio": 999})
        elif sf > 0 and bf > 0 and (sf / bf) >= 2.5:
            distribution_levels.append({"price": price, "type": "DISTRIBUTION", "ratio": round(sf/bf, 1)})

    # Support/Resistance dari volume profile
    prices_sorted = sorted([float(d.get("price",0) or 0) for d in price_table])
    current_price = prices_sorted[len(prices_sorted)//2] if prices_sorted else poc_price

    # Scoring
    score = 50.0
    net_ratio = (total_buy - total_sell) / total_vol if total_vol > 0 else 0

    # Net buy/sell contribution
    if net_ratio > 0.20:   score += 20
    elif net_ratio > 0.10: score += 12
    elif net_ratio > 0.05: score += 6
    elif net_ratio < -0.20: score -= 20
    elif net_ratio < -0.10: score -= 12
    elif net_ratio < -0.05: score -= 6

    # Bandar absorption bonus
    score += min(15, len(bandar_absorption) * 5)

    # Distribution penalty
    score -= min(15, len(distribution_levels) * 5)

    # Clamp
    score = max(0, min(100, score))

    # Signal
    if score >= 65 and len(bandar_absorption) >= 2:
        signal = "ACCUMULATION"
    elif score <= 35 and len(distribution_levels) >= 2:
        signal = "DISTRIBUTION"
    elif score >= 60:
        signal = "MILD_ACCUMULATION"
    elif score <= 40:
        signal = "MILD_DISTRIBUTION"
    else:
        signal = "NEUTRAL"

    return {
        "score": round(score, 2),
        "signal": signal,
        "poc_price": poc_price,
        "poc_vol": poc_vol,
        "net_ratio": round(net_ratio, 3),
        "net_bias": "BUY" if net_ratio > 0 else "SELL" if net_ratio < 0 else "NEUTRAL",
        "total_buy_vol": total_buy,
        "total_sell_vol": total_sell,
        "bandar_absorption": bandar_absorption,
        "distribution_levels": distribution_levels,
        "hva_levels": [float(d.get("price",0) or 0) for d in hva],
        "accumulation_count": len(bandar_absorption),
        "distribution_count": len(distribution_levels),
    }
