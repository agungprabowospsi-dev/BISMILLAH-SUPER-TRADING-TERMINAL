"""bulkowski_stats.py — Bulkowski 3rd Edition (2021) baseline stats."""

BULKOWSKI_PATTERNS = {
    "DOUBLE_BOTTOM": {
        "name": "Double Bottom",
        "type": "bullish_reversal",
        "failure_rate_5pct": 20,
        "avg_rise_bull": 40,
        "throwback_pct": 66,
        "throwback_days": 11,
        "gain_with_tb": 37,
        "gain_without_tb": 46,
        "measure_rule_pct": 68,
        "entry_type": "BUY_STOP",
        "entry_note": "BUY STOP satu tick di atas neckline saat CLOSE konfirmasi.",
        "stop_pct": 5,
        "performance_rank": 12,
        "bull_ok": True,
        "bear_ok": True,
    },
    "HEAD_SHOULDERS_BOTTOM": {
        "name": "Head and Shoulders Bottom",
        "type": "bullish_reversal",
        "failure_rate_5pct": 16,
        "avg_rise_bull": 45,
        "throwback_pct": 68,
        "throwback_days": 12,
        "gain_with_tb": 41,
        "gain_without_tb": 53,
        "measure_rule_pct": 74,
        "entry_type": "BUY_STOP",
        "entry_note": "Close di atas neckline. Throwback 68% - tanpa throwback plus 53 persen.",
        "stop_pct": 5,
        "performance_rank": 5,
        "bull_ok": True,
        "bear_ok": True,
    },
    "CUP_WITH_HANDLE": {
        "name": "Cup with Handle",
        "type": "bullish_continuation",
        "failure_rate_5pct": 5,
        "avg_rise_bull": 54,
        "throwback_pct": 62,
        "throwback_days": 11,
        "gain_with_tb": 48,
        "gain_without_tb": 63,
        "measure_rule_pct": 61,
        "entry_type": "BUY_STOP",
        "entry_note": "BUY STOP saat close di atas right cup rim. Failure rate hanya 5 persen.",
        "stop_pct": 8,
        "performance_rank": 3,
        "bull_ok": True,
        "bear_ok": False,
    },
    "BUMP_AND_RUN_BOTTOM": {
        "name": "Bump and Run Reversal Bottom",
        "type": "bullish_reversal",
        "failure_rate_5pct": 9,
        "avg_rise_bull": 55,
        "throwback_pct": 61,
        "throwback_days": 13,
        "gain_with_tb": 53,
        "gain_without_tb": 58,
        "measure_rule_pct": 76,
        "entry_type": "BUY_STOP",
        "entry_note": "BEST PERFORMER 55 persen average. Tembus trendline utama.",
        "stop_pct": 5,
        "performance_rank": 1,
        "bull_ok": True,
        "bear_ok": True,
    },
    "TRIANGLE_ASCENDING": {
        "name": "Ascending Triangle",
        "type": "bullish_continuation",
        "failure_rate_5pct": 13,
        "avg_rise_bull": 47,
        "throwback_pct": 57,
        "throwback_days": 11,
        "gain_with_tb": 42,
        "gain_without_tb": 54,
        "measure_rule_pct": 75,
        "entry_type": "BUY_STOP",
        "entry_note": "BUY STOP saat close di atas upper resistance. Sangat reliable.",
        "stop_pct": 5,
        "performance_rank": 6,
        "bull_ok": True,
        "bear_ok": True,
    },
    "TRIANGLE_SYMMETRICAL": {
        "name": "Symmetrical Triangle",
        "type": "neutral",
        "failure_rate_5pct": 22,
        "avg_rise_bull": 39,
        "throwback_pct": 66,
        "throwback_days": 12,
        "gain_with_tb": 35,
        "gain_without_tb": 46,
        "measure_rule_pct": 39,
        "entry_type": "WAIT_CLOSE",
        "entry_note": "WARNING measure rule hanya 39 persen. Pakai half-height TP.",
        "stop_pct": 5,
        "performance_rank": 30,
        "bull_ok": True,
        "bear_ok": False,
    },
    "RECTANGLE_BOTTOM": {
        "name": "Rectangle Bottom",
        "type": "bullish_reversal",
        "failure_rate_5pct": 20,
        "avg_rise_bull": 44,
        "throwback_pct": 64,
        "throwback_days": 11,
        "gain_with_tb": 40,
        "gain_without_tb": 51,
        "measure_rule_pct": 66,
        "entry_type": "BUY_STOP",
        "entry_note": "BUY STOP close di atas upper boundary. Konsolidasi adalah akumulasi.",
        "stop_pct": 5,
        "performance_rank": 10,
        "bull_ok": True,
        "bear_ok": True,
    },
    "FLAG_BULL": {
        "name": "Bull Flag",
        "type": "bullish_continuation",
        "failure_rate_5pct": 14,
        "avg_rise_bull": 23,
        "throwback_pct": 57,
        "throwback_days": 11,
        "gain_with_tb": 20,
        "gain_without_tb": 27,
        "measure_rule_pct": 64,
        "entry_type": "BUY_STOP",
        "entry_note": "Entry cepat saat breakout. Gain kecil tapi fast. Stop ketat 3 persen.",
        "stop_pct": 3,
        "performance_rank": 22,
        "bull_ok": True,
        "bear_ok": True,
    },
    "WEDGE_FALLING": {
        "name": "Falling Wedge",
        "type": "bullish_reversal",
        "failure_rate_5pct": 18,
        "avg_rise_bull": 39,
        "throwback_pct": 62,
        "throwback_days": 12,
        "gain_with_tb": 35,
        "gain_without_tb": 46,
        "measure_rule_pct": 83,
        "entry_type": "BUY_STOP",
        "entry_note": "Measure rule 83 persen akurat. Close di atas upper trendline.",
        "stop_pct": 5,
        "performance_rank": 16,
        "bull_ok": True,
        "bear_ok": True,
    },
    "ROUNDING_BOTTOM": {
        "name": "Rounding Bottom",
        "type": "bullish_reversal",
        "failure_rate_5pct": 7,
        "avg_rise_bull": 48,
        "throwback_pct": 55,
        "throwback_days": 12,
        "gain_with_tb": 43,
        "gain_without_tb": 55,
        "measure_rule_pct": 67,
        "entry_type": "BUY_STOP",
        "entry_note": "Failure rate 7 persen. Pattern panjang adalah akumulasi bandar.",
        "stop_pct": 5,
        "performance_rank": 4,
        "bull_ok": True,
        "bear_ok": False,
    },
    "DOUBLE_TOP": {
        "name": "Double Top",
        "type": "bearish_reversal",
        "failure_rate_5pct": 18,
        "avg_drop_bull": -15,
        "pullback_pct": 66,
        "pullback_days": 12,
        "drop_with_pb": -13,
        "drop_without_pb": -18,
        "measure_rule_pct": 62,
        "entry_type": "NO_ENTRY",
        "entry_note": "IDX tidak dianjurkan short. NO GO untuk long.",
        "stop_pct": 5,
        "performance_rank": 19,
        "bull_ok": True,
        "bear_ok": True,
    },
    "HEAD_SHOULDERS_TOP": {
        "name": "Head and Shoulders Top",
        "type": "bearish_reversal",
        "failure_rate_5pct": 19,
        "avg_drop_bull": -17,
        "pullback_pct": 65,
        "pullback_days": 12,
        "drop_with_pb": -15,
        "drop_without_pb": -21,
        "measure_rule_pct": 55,
        "entry_type": "NO_ENTRY",
        "entry_note": "IDX tidak dianjurkan short. NO GO untuk long.",
        "stop_pct": 5,
        "performance_rank": 14,
        "bull_ok": True,
        "bear_ok": True,
    },
    "WEDGE_RISING": {
        "name": "Rising Wedge",
        "type": "bearish_reversal",
        "failure_rate_5pct": 35,
        "avg_drop_bull": -13,
        "pullback_pct": 64,
        "pullback_days": 12,
        "drop_with_pb": -11,
        "drop_without_pb": -17,
        "measure_rule_pct": 32,
        "entry_type": "NO_ENTRY",
        "entry_note": "WARNING 47 persen akan BUST menjadi bullish plus 65 persen. Monitor untuk busted pattern.",
        "stop_pct": 5,
        "busted_avg_rise": 65,
        "busted_single_pct": 75,
        "performance_rank": 29,
        "bull_ok": False,
        "bear_ok": True,
    },
}

MARKET_ADJ = {
    "STRONG_BULL": {"fail_mult": 0.80, "gain_mult": 1.20},
    "BULL":        {"fail_mult": 0.90, "gain_mult": 1.05},
    "SIDEWAYS":    {"fail_mult": 1.10, "gain_mult": 0.90},
    "BEAR":        {"fail_mult": 1.30, "gain_mult": 0.75},
    "STRONG_BEAR": {"fail_mult": 1.50, "gain_mult": 0.60},
}

def get_pattern_stats(pattern_name, market_regime="SIDEWAYS", idx_calibration=None):
    base = BULKOWSKI_PATTERNS.get(pattern_name)
    if not base:
        return {}
    result = dict(base)
    adj = MARKET_ADJ.get(market_regime, MARKET_ADJ["SIDEWAYS"])
    result["adj_failure_rate"] = round(base.get("failure_rate_5pct", 20) * adj["fail_mult"], 1)
    result["adj_avg_rise"] = round(base.get("avg_rise_bull", 30) * adj["gain_mult"], 1)
    if idx_calibration:
        result["adj_failure_rate"] = round(result["adj_failure_rate"] * idx_calibration.get("failure_rate_mult", 1.0), 1)
        result["adj_avg_rise"] = round(result["adj_avg_rise"] * idx_calibration.get("avg_rise_mult", 1.0), 1)
        result["idx_calibrated"] = True
    result["market_regime"] = market_regime
    return result

def compute_entry_strategy(pattern_name, current_price, formation_high, formation_low, breakout_price=None):
    stats = BULKOWSKI_PATTERNS.get(pattern_name, {})
    if not stats:
        return {}
    entry_type = stats.get("entry_type", "WAIT_CLOSE")
    stop_pct = stats.get("stop_pct", 5)
    height = abs(formation_high - formation_low)
    bp = breakout_price or formation_high
    is_bull = "bullish" in stats.get("type", "") or "continuation" in stats.get("type", "")
    if entry_type == "BUY_STOP":
        entry = round(bp * 1.001, 2)
        entry_note = "BUY STOP di " + str(entry) + " satu tick di atas breakout " + str(bp)
    elif entry_type == "NO_ENTRY":
        return {"entry_type": "NO_ENTRY", "entry_note": stats.get("entry_note", "NO GO")}
    else:
        entry = current_price
        entry_note = "Tunggu CLOSE konfirmasi di atas " + str(bp)
    if is_bull:
        sl  = round(bp * (1 - stop_pct/100), 2)
        tp1 = round(bp + height, 2)
        tp2 = round(bp + height * 1.5, 2)
        tp3 = round(bp + height * 2.0, 2)
    else:
        sl  = round(bp * (1 + stop_pct/100), 2)
        tp1 = round(bp - height, 2)
        tp2 = round(bp - height * 1.5, 2)
        tp3 = round(bp - height * 2.0, 2)
    rr = abs(tp1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    tb_pct = stats.get("throwback_pct", 60)
    tb_days = stats.get("throwback_days", 11)
    gain_tb = stats.get("gain_with_tb", 35)
    gain_no_tb = stats.get("gain_without_tb", 46)
    fail_rate = stats.get("failure_rate_5pct", 20)
    fail_label = "RENDAH" if fail_rate < 15 else "MEDIUM" if fail_rate < 25 else "TINGGI"
    mr_pct = stats.get("measure_rule_pct", 60)
    return {
        "entry_type": entry_type,
        "entry_price": entry,
        "entry_note": entry_note,
        "stop_loss": sl,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "formation_height": height,
        "breakout_price": bp,
        "risk_reward": round(rr, 2),
        "measure_rule_note": "Measure Rule TP " + str(bp) + " + " + str(round(height,0)) + " = " + str(tp1) + " (" + str(mr_pct) + " persen accuracy Bulkowski)",
        "throwback_note": str(tb_pct) + " persen kemungkinan throwback " + str(tb_days) + " hari. Gain TANPA throwback " + str(gain_no_tb) + " persen vs DENGAN throwback " + str(gain_tb) + " persen",
        "failure_note": "Failure rate US " + str(fail_rate) + " persen - " + fail_label,
    }
