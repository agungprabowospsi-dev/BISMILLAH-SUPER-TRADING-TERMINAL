from typing import Any, Dict, List, Tuple


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_level(level: Any, side: str) -> Tuple[float, float, float]:
    if isinstance(level, (list, tuple)):
        price = _to_float(level[0] if len(level) > 0 else 0)
        lot = _to_float(level[1] if len(level) > 1 else 0)
        freq = _to_float(level[2] if len(level) > 2 else 0)
        return price, lot, freq

    if not isinstance(level, dict):
        return 0.0, 0.0, 0.0

    if side == "bid":
        price_keys = ("bid", "bid_price", "bid1price", "price")
        lot_keys = ("bid_lot", "bid1lot", "lot", "volume", "qty")
        freq_keys = ("bid_freq", "bid1freq", "freq", "frequency")
    else:
        price_keys = ("ask", "offer", "ask_price", "offer_price", "offer1price", "price")
        lot_keys = ("ask_lot", "offer_lot", "offer1lot", "lot", "volume", "qty")
        freq_keys = ("ask_freq", "offer_freq", "offer1freq", "freq", "frequency")

    price = next((_to_float(level.get(k)) for k in price_keys if level.get(k) not in (None, "")), 0.0)
    lot = next((_to_float(level.get(k)) for k in lot_keys if level.get(k) not in (None, "")), 0.0)
    freq = next((_to_float(level.get(k)) for k in freq_keys if level.get(k) not in (None, "")), 0.0)
    return price, lot, freq


def _levels_from_rows(rows: Any, side: str) -> List[Dict[str, float]]:
    levels: List[Dict[str, float]] = []
    if not isinstance(rows, list):
        return levels

    for row in rows:
        price, lot, freq = _extract_level(row, side)
        if price > 0 and lot > 0:
            levels.append({"price": price, "lot": lot, "freq": freq})
    return levels


def normalize_orderbook(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"available": False, "bids": [], "asks": [], "source": "none"}

    bids = _levels_from_rows(raw.get("bids") or raw.get("bid") or raw.get("bid_levels"), "bid")
    asks = _levels_from_rows(raw.get("asks") or raw.get("offers") or raw.get("offer") or raw.get("ask_levels"), "ask")

    row_candidates = raw.get("levels") or raw.get("data") or raw.get("orderbook") or raw.get("rows")
    if (not bids or not asks) and isinstance(row_candidates, list):
        for row in row_candidates:
            if not isinstance(row, dict):
                continue
            bid_price, bid_lot, bid_freq = _extract_level(row, "bid")
            ask_price, ask_lot, ask_freq = _extract_level(row, "ask")
            if bid_price > 0 and bid_lot > 0:
                bids.append({"price": bid_price, "lot": bid_lot, "freq": bid_freq})
            if ask_price > 0 and ask_lot > 0:
                asks.append({"price": ask_price, "lot": ask_lot, "freq": ask_freq})

    if not bids:
        bid_price, bid_lot, bid_freq = _extract_level(raw, "bid")
        if bid_price > 0 and bid_lot > 0:
            bids.append({"price": bid_price, "lot": bid_lot, "freq": bid_freq})
    if not asks:
        ask_price, ask_lot, ask_freq = _extract_level(raw, "ask")
        if ask_price > 0 and ask_lot > 0:
            asks.append({"price": ask_price, "lot": ask_lot, "freq": ask_freq})

    bids = sorted([x for x in bids if x["price"] > 0 and x["lot"] > 0], key=lambda x: x["price"], reverse=True)
    asks = sorted([x for x in asks if x["price"] > 0 and x["lot"] > 0], key=lambda x: x["price"])
    best_bid = bids[0]["price"] if bids else 0.0
    best_ask = asks[0]["price"] if asks else 0.0
    spread_pct = ((best_ask - best_bid) / best_bid * 100) if best_bid > 0 and best_ask > 0 else 0.0

    return {
        "available": bool(bids and asks),
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": round(spread_pct, 3),
        "source": raw.get("source") or ("orderbook" if len(bids) > 1 or len(asks) > 1 else "top_of_book"),
    }


def build_orderbook_execution_overlay(
    raw_orderbook: Any,
    action_plan: Dict[str, Any] = None,
    mode: str = "swing",
) -> Dict[str, Any]:
    normalized = normalize_orderbook(raw_orderbook)
    bids = normalized["bids"]
    asks = normalized["asks"]
    action_plan = action_plan or {}
    mode_l = str(mode or "swing").lower()

    if not normalized["available"]:
        return {
            "available": False,
            "execution_recommendation": "USE_EXISTING_PLAN",
            "liquidity_bias": "unknown",
            "spread_health": "unknown",
            "reason": "Orderbook belum tersedia; gunakan action plan existing tanpa override.",
            "normalized": normalized,
        }

    depth = 10 if mode_l in ("intraday", "daytrading", "scalping") else 5
    bid_lot = sum(x["lot"] for x in bids[:depth])
    ask_lot = sum(x["lot"] for x in asks[:depth])
    bid_freq = sum(x["freq"] for x in bids[:depth])
    ask_freq = sum(x["freq"] for x in asks[:depth])
    ratio = bid_lot / ask_lot if ask_lot > 0 else 1.0

    best_bid = normalized["best_bid"]
    best_ask = normalized["best_ask"]
    spread_pct = normalized["spread_pct"]
    largest_bid = max(bids[:depth], key=lambda x: x["lot"])
    largest_ask = max(asks[:depth], key=lambda x: x["lot"])

    if ratio >= 1.35:
        liquidity_bias = "bid_dominant"
    elif ratio <= 0.75:
        liquidity_bias = "ask_dominant"
    else:
        liquidity_bias = "balanced"

    spread_limit = 0.35 if mode_l == "scalping" else 0.5 if mode_l in ("intraday", "daytrading") else 0.8
    spread_health = "healthy" if spread_pct <= spread_limit else "wide"
    has_freq = bid_freq > 0 and ask_freq > 0
    fake_bid_wall = has_freq and largest_bid["lot"] >= max(1, largest_ask["lot"] * 3) and largest_bid["freq"] <= max(1, ask_freq / max(1, len(asks[:depth])) * 0.7)
    fake_ask_wall = has_freq and largest_ask["lot"] >= max(1, largest_bid["lot"] * 3) and largest_ask["freq"] <= max(1, bid_freq / max(1, len(bids[:depth])) * 0.7)

    base_order = str(action_plan.get("order_type") or "").upper()
    if spread_health == "wide":
        recommendation = "WAIT_SPREAD_TIGHTEN"
        execution_style = "WAIT"
        reason = "Spread melebar; jangan mengejar harga walaupun setup existing valid."
    elif fake_bid_wall:
        recommendation = "WAIT_CONFIRMATION"
        execution_style = "WAIT"
        reason = "Bid wall besar terlihat rapuh karena frekuensi rendah; butuh konfirmasi buyer sungguhan."
    elif liquidity_bias == "bid_dominant" and mode_l in ("intraday", "daytrading", "scalping"):
        recommendation = "GO_LIMIT_PULLBACK"
        execution_style = "LIMIT"
        reason = "Bid support dominan; entry lebih tajam dengan limit di area bid support."
    elif liquidity_bias == "bid_dominant" and "MARKET" in base_order:
        recommendation = "GO_MARKET_IF_TRIGGERED"
        execution_style = "MARKET"
        reason = "Likuiditas mendukung dan spread sehat; market order hanya setelah trigger existing terpenuhi."
    elif liquidity_bias == "ask_dominant":
        recommendation = "WAIT_ASK_ABSORPTION"
        execution_style = "WAIT"
        reason = "Ask lebih tebal; tunggu absorption atau ask wall ditembus sebelum agresif."
    else:
        recommendation = "USE_EXISTING_PLAN"
        execution_style = "FOLLOW_PLAN"
        reason = "Orderbook seimbang; ikuti action plan existing."

    return {
        "available": True,
        "execution_recommendation": recommendation,
        "execution_style": execution_style,
        "liquidity_bias": liquidity_bias,
        "spread_health": spread_health,
        "bid_ask_ratio": round(ratio, 3),
        "total_bid_lot": round(bid_lot, 2),
        "total_ask_lot": round(ask_lot, 2),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": spread_pct,
        "suggested_limit_entry": best_bid if execution_style == "LIMIT" else 0,
        "suggested_market_trigger": best_ask if execution_style == "MARKET" else 0,
        "support_wall_price": largest_bid["price"],
        "support_wall_lot": largest_bid["lot"],
        "resistance_wall_price": largest_ask["price"],
        "resistance_wall_lot": largest_ask["lot"],
        "fake_bid_wall": bool(fake_bid_wall),
        "fake_ask_wall": bool(fake_ask_wall),
        "reason": reason,
        "overlay_policy": "additive_only_no_decision_override",
        "normalized": {
            **normalized,
            "bids": bids[:depth],
            "asks": asks[:depth],
        },
    }
