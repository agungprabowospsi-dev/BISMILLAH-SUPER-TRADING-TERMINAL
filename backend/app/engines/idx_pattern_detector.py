"""idx_pattern_detector.py — Deteksi chart patterns dari OHLCV data."""
import statistics
from typing import Dict, Any, List, Optional


def detect_patterns(ohlcv: List[Dict], mode: str = "swing") -> List[Dict]:
    if not ohlcv or len(ohlcv) < 10:
        return []
    lookback = min(20, len(ohlcv)) if mode == "intraday" else min(120, len(ohlcv))
    data = ohlcv[-lookback:]
    closes = [float(c["close"]) for c in data]
    highs  = [float(c["high"])  for c in data]
    lows   = [float(c["low"])   for c in data]
    vols   = [float(c.get("volume", 0)) for c in data]
    patterns = []
    for detector in [
        _detect_double_bottom, _detect_double_top,
        _detect_head_shoulders_bottom, _detect_head_shoulders_top,
        _detect_ascending_triangle, _detect_descending_triangle,
        _detect_symmetrical_triangle, _detect_rectangle,
        _detect_bull_flag, _detect_falling_wedge, _detect_rising_wedge,
        _detect_cup_with_handle, _detect_rounding_bottom,
    ]:
        try:
            result = detector(closes, highs, lows, vols, mode)
            if result:
                patterns.append(result)
        except Exception:
            continue
    patterns.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return patterns[:3]


def _find_local_minima(prices, window=5):
    minima = []
    for i in range(window, len(prices) - window):
        if prices[i] == min(prices[i-window:i+window+1]):
            minima.append(i)
    return minima


def _find_local_maxima(prices, window=5):
    maxima = []
    for i in range(window, len(prices) - window):
        if prices[i] == max(prices[i-window:i+window+1]):
            maxima.append(i)
    return maxima


def _detect_double_bottom(closes, highs, lows, vols, mode):
    window = 3 if mode == "intraday" else 5
    minima = _find_local_minima(closes, window)
    if len(minima) < 2:
        return None
    for i in range(len(minima)-1, 0, -1):
        b2 = minima[i]
        for j in range(i-1, max(i-5, -1), -1):
            b1 = minima[j]
            if b2 - b1 < 5:
                continue
            p1, p2 = closes[b1], closes[b2]
            if abs(p1 - p2) / max(p1, p2) > 0.03:
                continue
            neckline = max(highs[b1:b2+1])
            current = closes[-1]
            confidence = 70
            if len(vols) > b2 and vols[b2] < vols[b1]:
                confidence += 10
            status = "BREAKOUT_NEAR" if current >= neckline * 0.98 else "FORMING"
            if status == "BREAKOUT_NEAR":
                confidence += 15
            return {
                "pattern": "DOUBLE_BOTTOM",
                "status": status,
                "confidence": min(confidence, 95),
                "formation_high": neckline,
                "formation_low": min(p1, p2),
                "breakout_price": neckline,
                "current_price": current,
                "pattern_days": b2 - b1,
                "description": "Double Bottom lembah " + str(round(p1)) + " dan " + str(round(p2)) + " neckline " + str(round(neckline)),
            }
    return None


def _detect_double_top(closes, highs, lows, vols, mode):
    window = 3 if mode == "intraday" else 5
    maxima = _find_local_maxima(closes, window)
    if len(maxima) < 2:
        return None
    for i in range(len(maxima)-1, 0, -1):
        t2 = maxima[i]
        for j in range(i-1, max(i-5, -1), -1):
            t1 = maxima[j]
            if t2 - t1 < 5:
                continue
            p1, p2 = closes[t1], closes[t2]
            if abs(p1 - p2) / max(p1, p2) > 0.03:
                continue
            neckline = min(lows[t1:t2+1])
            current = closes[-1]
            confidence = 65
            status = "BREAKDOWN_NEAR" if current <= neckline * 1.02 else "FORMING"
            if status == "BREAKDOWN_NEAR":
                confidence += 15
            return {
                "pattern": "DOUBLE_TOP",
                "status": status,
                "confidence": min(confidence, 88),
                "formation_high": max(p1, p2),
                "formation_low": neckline,
                "breakout_price": neckline,
                "current_price": current,
                "pattern_days": t2 - t1,
                "description": "Double Top puncak " + str(round(p1)) + " dan " + str(round(p2)) + " neckline " + str(round(neckline)),
            }
    return None


def _detect_head_shoulders_bottom(closes, highs, lows, vols, mode):
    if len(closes) < 15:
        return None
    window = 3 if mode == "intraday" else 5
    minima = _find_local_minima(closes, window)
    if len(minima) < 3:
        return None
    for i in range(len(minima)-3, len(minima)-1):
        if i < 0 or i+2 >= len(minima):
            continue
        ls, head, rs = minima[i], minima[i+1], minima[i+2]
        ls_p, head_p, rs_p = closes[ls], closes[head], closes[rs]
        if not (head_p < ls_p and head_p < rs_p):
            continue
        if abs(ls_p - rs_p) / max(ls_p, rs_p) > 0.05:
            continue
        neckline = (max(closes[ls:head+1]) + max(closes[head:rs+1])) / 2
        current = closes[-1]
        confidence = 75
        status = "BREAKOUT_NEAR" if current >= neckline * 0.97 else "FORMING"
        if status == "BREAKOUT_NEAR":
            confidence += 15
        return {
            "pattern": "HEAD_SHOULDERS_BOTTOM",
            "status": status,
            "confidence": min(confidence, 92),
            "formation_high": neckline,
            "formation_low": head_p,
            "breakout_price": neckline,
            "current_price": current,
            "pattern_days": rs - ls,
            "description": "Inverted HS shoulder " + str(round(ls_p)) + "/" + str(round(rs_p)) + " head " + str(round(head_p)) + " neckline " + str(round(neckline)),
        }
    return None


def _detect_head_shoulders_top(closes, highs, lows, vols, mode):
    if len(closes) < 15:
        return None
    window = 3 if mode == "intraday" else 5
    maxima = _find_local_maxima(closes, window)
    if len(maxima) < 3:
        return None
    for i in range(len(maxima)-3, len(maxima)-1):
        if i < 0 or i+2 >= len(maxima):
            continue
        ls, head, rs = maxima[i], maxima[i+1], maxima[i+2]
        ls_p, head_p, rs_p = closes[ls], closes[head], closes[rs]
        if not (head_p > ls_p and head_p > rs_p):
            continue
        if abs(ls_p - rs_p) / max(ls_p, rs_p) > 0.05:
            continue
        neckline = (min(closes[ls:head+1]) + min(closes[head:rs+1])) / 2
        current = closes[-1]
        confidence = 70
        status = "BREAKDOWN_NEAR" if current <= neckline * 1.02 else "FORMING"
        if status == "BREAKDOWN_NEAR":
            confidence += 10
        return {
            "pattern": "HEAD_SHOULDERS_TOP",
            "status": status,
            "confidence": min(confidence, 88),
            "formation_high": head_p,
            "formation_low": neckline,
            "breakout_price": neckline,
            "current_price": current,
            "pattern_days": rs - ls,
            "description": "HS Top shoulder " + str(round(ls_p)) + "/" + str(round(rs_p)) + " head " + str(round(head_p)) + " neckline " + str(round(neckline)),
        }
    return None


def _detect_ascending_triangle(closes, highs, lows, vols, mode):
    if len(closes) < 10:
        return None
    maxima = _find_local_maxima(closes, 3)
    minima = _find_local_minima(closes, 3)
    if len(maxima) < 2 or len(minima) < 2:
        return None
    recent_max = [closes[m] for m in maxima[-4:]]
    resistance = sum(recent_max) / len(recent_max)
    max_dev = max(abs(p - resistance) / resistance for p in recent_max)
    if max_dev > 0.03:
        return None
    recent_min_vals = [closes[m] for m in minima[-3:]]
    if len(recent_min_vals) >= 2:
        slope = (recent_min_vals[-1] - recent_min_vals[0]) / max(1, len(recent_min_vals))
        if slope <= 0:
            return None
    current = closes[-1]
    support = min(recent_min_vals)
    confidence = 72
    status = "BREAKOUT_NEAR" if current >= resistance * 0.97 else "FORMING"
    if status == "BREAKOUT_NEAR":
        confidence += 18
    return {
        "pattern": "TRIANGLE_ASCENDING",
        "status": status,
        "confidence": min(confidence, 90),
        "formation_high": resistance,
        "formation_low": support,
        "breakout_price": resistance,
        "current_price": current,
        "description": "Ascending Triangle resistance " + str(round(resistance)) + " support rising dari " + str(round(support)),
    }


def _detect_descending_triangle(closes, highs, lows, vols, mode):
    if len(closes) < 10:
        return None
    minima = _find_local_minima(closes, 3)
    if len(minima) < 2:
        return None
    recent_min = [closes[m] for m in minima[-4:]]
    support = sum(recent_min) / len(recent_min)
    max_dev = max(abs(p - support) / support for p in recent_min)
    if max_dev > 0.03:
        return None
    maxima = _find_local_maxima(closes, 3)
    if len(maxima) < 2:
        return None
    recent_max_vals = [closes[m] for m in maxima[-3:]]
    if len(recent_max_vals) >= 2:
        slope = (recent_max_vals[-1] - recent_max_vals[0]) / max(1, len(recent_max_vals))
        if slope >= 0:
            return None
    current = closes[-1]
    resistance = max(recent_max_vals)
    confidence = 65
    status = "BREAKDOWN_NEAR" if current <= support * 1.02 else "FORMING"
    if status == "BREAKDOWN_NEAR":
        confidence += 10
    return {
        "pattern": "TRIANGLE_DESCENDING",
        "status": status,
        "confidence": min(confidence, 82),
        "formation_high": resistance,
        "formation_low": support,
        "breakout_price": support,
        "current_price": current,
        "description": "Descending Triangle support " + str(round(support)) + " resistance falling",
    }


def _detect_symmetrical_triangle(closes, highs, lows, vols, mode):
    if len(closes) < 12:
        return None
    maxima = _find_local_maxima(closes, 3)
    minima = _find_local_minima(closes, 3)
    if len(maxima) < 2 or len(minima) < 2:
        return None
    max_vals = [closes[m] for m in maxima[-3:]]
    min_vals = [closes[m] for m in minima[-3:]]
    max_slope = (max_vals[-1] - max_vals[0]) / max(1, len(max_vals))
    min_slope = (min_vals[-1] - min_vals[0]) / max(1, len(min_vals))
    if not (max_slope < 0 and min_slope > 0):
        return None
    current = closes[-1]
    resistance = max_vals[-1]
    support = min_vals[-1]
    apex = (resistance + support) / 2
    return {
        "pattern": "TRIANGLE_SYMMETRICAL",
        "status": "FORMING",
        "confidence": 60,
        "formation_high": resistance,
        "formation_low": support,
        "breakout_price": max(current * 1.01, apex),
        "current_price": current,
        "description": "Symmetrical Triangle converging ke apex " + str(round(apex)) + " WARNING measure rule hanya 39 persen",
    }


def _detect_rectangle(closes, highs, lows, vols, mode):
    if len(closes) < 8:
        return None
    recent = closes[-15:] if len(closes) >= 15 else closes
    high_val = max(recent)
    low_val = min(recent)
    range_pct = (high_val - low_val) / low_val
    if not (0.03 <= range_pct <= 0.15):
        return None
    mean_price = sum(recent) / len(recent)
    std_price = statistics.stdev(recent) if len(recent) > 1 else 0
    cv = std_price / mean_price if mean_price > 0 else 0
    if cv > 0.05:
        return None
    current = closes[-1]
    confidence = 65
    if current >= high_val * 0.97:
        status = "BREAKOUT_NEAR"
        confidence += 15
        pattern_type = "RECTANGLE_BOTTOM"
    elif current <= low_val * 1.03:
        status = "BREAKDOWN_NEAR"
        pattern_type = "DOUBLE_TOP"
    else:
        status = "FORMING"
        pattern_type = "RECTANGLE_BOTTOM"
    return {
        "pattern": pattern_type,
        "status": status,
        "confidence": min(confidence, 80),
        "formation_high": high_val,
        "formation_low": low_val,
        "breakout_price": high_val,
        "current_price": current,
        "description": "Rectangle " + str(round(low_val)) + "-" + str(round(high_val)) + " range " + str(round(range_pct*100, 1)) + " persen. Konsolidasi adalah akumulasi.",
    }


def _detect_bull_flag(closes, highs, lows, vols, mode):
    if len(closes) < 10:
        return None
    n = len(closes)
    pole_len = min(7, n // 3)
    if n < pole_len + 8:
        return None
    pole_start = closes[-(pole_len+8)]
    pole_end = closes[-8]
    pole_rise = (pole_end - pole_start) / max(pole_start, 1)
    if pole_rise < 0.05:
        return None
    flag = closes[-8:-1]
    flag_high = max(flag)
    flag_low = min(flag)
    flag_range = (flag_high - flag_low) / max(flag_high, 1)
    if flag_range > 0.07:
        return None
    current = closes[-1]
    confidence = 68
    status = "BREAKOUT_NEAR" if current >= flag_high * 0.98 else "FORMING"
    if status == "BREAKOUT_NEAR":
        confidence += 15
    return {
        "pattern": "FLAG_BULL",
        "status": status,
        "confidence": min(confidence, 85),
        "formation_high": flag_high,
        "formation_low": flag_low,
        "breakout_price": flag_high,
        "flagpole_height": pole_end - pole_start,
        "current_price": current,
        "description": "Bull Flag flagpole naik " + str(round(pole_rise*100, 1)) + " persen flag " + str(round(flag_low)) + "-" + str(round(flag_high)),
    }


def _detect_falling_wedge(closes, highs, lows, vols, mode):
    if len(closes) < 12:
        return None
    maxima = _find_local_maxima(closes, 3)
    minima = _find_local_minima(closes, 3)
    if len(maxima) < 2 or len(minima) < 2:
        return None
    max_vals = [closes[m] for m in maxima[-3:]]
    min_vals = [closes[m] for m in minima[-3:]]
    max_slope = (max_vals[-1] - max_vals[0]) / max(1, len(max_vals))
    min_slope = (min_vals[-1] - min_vals[0]) / max(1, len(min_vals))
    if not (max_slope < 0 and min_slope < 0):
        return None
    if not (abs(max_slope) > abs(min_slope)):
        return None
    current = closes[-1]
    resistance = max_vals[-1]
    confidence = 68
    status = "BREAKOUT_NEAR" if current >= resistance * 0.97 else "FORMING"
    if status == "BREAKOUT_NEAR":
        confidence += 15
    return {
        "pattern": "WEDGE_FALLING",
        "status": status,
        "confidence": min(confidence, 85),
        "formation_high": max_vals[0],
        "formation_low": min_vals[-1],
        "breakout_price": resistance,
        "current_price": current,
        "description": "Falling Wedge converging downward. Measure rule 83 persen akurat.",
    }


def _detect_rising_wedge(closes, highs, lows, vols, mode):
    if len(closes) < 12:
        return None
    maxima = _find_local_maxima(closes, 3)
    minima = _find_local_minima(closes, 3)
    if len(maxima) < 2 or len(minima) < 2:
        return None
    max_vals = [closes[m] for m in maxima[-3:]]
    min_vals = [closes[m] for m in minima[-3:]]
    max_slope = (max_vals[-1] - max_vals[0]) / max(1, len(max_vals))
    min_slope = (min_vals[-1] - min_vals[0]) / max(1, len(min_vals))
    if not (max_slope > 0 and min_slope > 0):
        return None
    if not (abs(min_slope) > abs(max_slope)):
        return None
    current = closes[-1]
    return {
        "pattern": "WEDGE_RISING",
        "status": "FORMING",
        "confidence": 60,
        "formation_high": max_vals[-1],
        "formation_low": min_vals[0],
        "breakout_price": min_vals[-1],
        "current_price": current,
        "bust_opportunity": True,
        "description": "Rising Wedge BEARISH tapi 47 persen akan bust menjadi bullish plus 65 persen.",
    }


def _detect_cup_with_handle(closes, highs, lows, vols, mode):
    if mode == "intraday" or len(closes) < 30:
        return None
    n = len(closes)
    left_high  = max(closes[:n//3])
    right_high = max(closes[2*n//3:])
    cup_low    = min(closes[n//3:2*n//3])
    if abs(left_high - right_high) / max(left_high, right_high) > 0.05:
        return None
    cup_depth = (right_high - cup_low) / right_high
    if cup_depth < 0.15:
        return None
    handle = closes[-8:-1]
    if not handle:
        return None
    handle_high = max(handle)
    handle_low  = min(handle)
    handle_depth = (handle_high - handle_low) / max(handle_high, 1)
    if handle_depth > cup_depth * 0.5:
        return None
    current = closes[-1]
    confidence = 78
    status = "BREAKOUT_NEAR" if current >= right_high * 0.97 else "FORMING"
    if status == "BREAKOUT_NEAR":
        confidence += 12
    return {
        "pattern": "CUP_WITH_HANDLE",
        "status": status,
        "confidence": min(confidence, 90),
        "formation_high": right_high,
        "formation_low": cup_low,
        "breakout_price": right_high,
        "current_price": current,
        "description": "Cup with Handle rim " + str(round(right_high)) + " cup low " + str(round(cup_low)) + " failure rate hanya 5 persen.",
    }


def _detect_rounding_bottom(closes, highs, lows, vols, mode):
    if mode == "intraday" or len(closes) < 30:
        return None
    n = len(closes)
    left  = sum(closes[:n//3]) / (n//3)
    mid   = sum(closes[n//3:2*n//3]) / (n//3)
    right = sum(closes[2*n//3:]) / max(len(closes[2*n//3:]), 1)
    if not (left > mid and right > mid):
        return None
    if right < left * 0.95:
        return None
    std = statistics.stdev(closes) if len(closes) > 1 else 0
    mean = sum(closes) / len(closes)
    cv = std / mean if mean > 0 else 0
    if cv > 0.12:
        return None
    current = closes[-1]
    rim = max(closes[:n//4]) if n >= 4 else closes[0]
    low = min(closes[n//4:3*n//4]) if n >= 4 else closes[-1]
    confidence = 72
    status = "BREAKOUT_NEAR" if current >= rim * 0.97 else "FORMING"
    if status == "BREAKOUT_NEAR":
        confidence += 12
    return {
        "pattern": "ROUNDING_BOTTOM",
        "status": status,
        "confidence": min(confidence, 88),
        "formation_high": rim,
        "formation_low": low,
        "breakout_price": rim,
        "current_price": current,
        "description": "Rounding Bottom rim " + str(round(rim)) + " low " + str(round(low)) + " failure rate hanya 7 persen.",
    }
