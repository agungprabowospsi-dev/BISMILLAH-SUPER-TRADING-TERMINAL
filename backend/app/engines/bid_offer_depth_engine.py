"""
BidOfferDepthEngine — Bid-Offer Depth Ratio
Membaca bahasa rahasia bandar di bid-offer
Referensi: Bandar Flow Secrets Bab 5 (Buku 3)
"""
from typing import Dict, Any, Optional

def analyze_bid_offer_depth(
    intraday_data: Dict,
    price_table: list = None
) -> Dict[str, Any]:
    """
    Analisis bid-offer untuk deteksi:
    - Absorption (bandar absorb supply)
    - Fake wall (tembok palsu untuk manipulasi)
    - Real support vs fake support
    
    Input dari get_ohlcv_intraday():
      bid_price, bid_lot, bid_freq
      offer_price, offer_lot, offer_freq
    """
    if not intraday_data:
        return {"score": 50, "signal": "NEUTRAL", "reason": "no intraday data"}

    bid_price  = float(intraday_data.get("bid_price",  0) or 0)
    bid_lot    = float(intraday_data.get("bid_lot",    0) or 0)
    bid_freq   = float(intraday_data.get("bid_freq",   0) or 0)
    offer_price = float(intraday_data.get("offer_price", 0) or 0)
    offer_lot  = float(intraday_data.get("offer_lot",  0) or 0)
    offer_freq = float(intraday_data.get("offer_freq", 0) or 0)

    if bid_price == 0 or offer_price == 0:
        return {"score": 50, "signal": "NEUTRAL", "reason": "zero bid/offer"}

    # Spread
    spread = offer_price - bid_price
    spread_pct = (spread / bid_price * 100) if bid_price > 0 else 0

    # Depth Ratio = (bid_lot × bid_freq) / (offer_lot × offer_freq)
    bid_pressure   = bid_lot   * bid_freq   if bid_freq   > 0 else bid_lot
    offer_pressure = offer_lot * offer_freq if offer_freq > 0 else offer_lot

    depth_ratio = (bid_pressure / offer_pressure) if offer_pressure > 0 else 1.0

    # Fake wall detection:
    # Bid wall besar TAPI freq rendah = fake wall (1 order besar = mudah dicabut)
    fake_bid_wall   = bid_lot > offer_lot * 3 and bid_freq < offer_freq * 0.5
    fake_offer_wall = offer_lot > bid_lot * 3 and offer_freq < bid_freq * 0.5

    # IEP analysis
    iep = float(intraday_data.get("iep", 0) or 0)
    iev = float(intraday_data.get("iev", 0) or 0)
    avg = float(intraday_data.get("avg", 0) or 0)  # VWAP

    # Scoring
    score = 50.0
    signals = []

    if depth_ratio >= 3.0:
        score += 25
        signals.append(f"BID_DOMINANCE_STRONG ({depth_ratio:.1f}x)")
    elif depth_ratio >= 2.0:
        score += 15
        signals.append(f"BID_DOMINANCE ({depth_ratio:.1f}x)")
    elif depth_ratio >= 1.5:
        score += 8
        signals.append(f"BID_SLIGHT_DOMINANCE ({depth_ratio:.1f}x)")
    elif depth_ratio <= 0.5:
        score -= 20
        signals.append(f"OFFER_DOMINANCE ({depth_ratio:.1f}x)")
    elif depth_ratio <= 0.33:
        score -= 30
        signals.append(f"OFFER_DOMINANCE_STRONG ({depth_ratio:.1f}x)")

    if fake_bid_wall:
        score -= 10
        signals.append("FAKE_BID_WALL_DETECTED")
    if fake_offer_wall:
        score += 10
        signals.append("FAKE_OFFER_WALL — potential breakout")

    # Tight spread = liquid = institutional friendly
    if spread_pct < 0.1:
        score += 5
        signals.append("TIGHT_SPREAD")
    elif spread_pct > 1.0:
        score -= 5
        signals.append("WIDE_SPREAD")

    score = max(0, min(100, score))

    # Final signal
    if score >= 70:
        final_signal = "ABSORPTION"  # Bandar absorb supply
    elif score >= 60:
        final_signal = "BID_STRONG"
    elif score <= 30:
        final_signal = "DISTRIBUTION_PRESSURE"
    elif score <= 40:
        final_signal = "OFFER_STRONG"
    else:
        final_signal = "BALANCED"

    return {
        "score": round(score, 2),
        "signal": final_signal,
        "depth_ratio": round(depth_ratio, 2),
        "bid_pressure": round(bid_pressure),
        "offer_pressure": round(offer_pressure),
        "spread": spread,
        "spread_pct": round(spread_pct, 3),
        "fake_bid_wall": fake_bid_wall,
        "fake_offer_wall": fake_offer_wall,
        "bid_price": bid_price,
        "offer_price": offer_price,
        "iep": iep,
        "vwap": avg,
        "signals": signals,
    }
