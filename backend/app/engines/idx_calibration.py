"""idx_calibration.py — IDX calibration factors untuk Bulkowski baseline."""

# Tier 1: Intersection LQ45 + MSCI Indonesia — paling reliable untuk calibration
MSCI_LQ45_INTERSECTION = [
    "BBCA", "BBRI", "BMRI", "TLKM", "ASII",
    "ADRO", "ANTM", "BYAN", "ICBP", "INDF",
    "KLBF", "MAPI", "MDKA", "PTBA", "SMGR",
    "UNVR", "AMMN", "PGAS", "GOTO", "EXCL",
]

# Tier 2: LQ45 only — dipakai jika sampel Tier 1 kurang
LQ45_ONLY = [
    "AALI", "LSIP", "SCMA", "MNCN", "EMTK",
]

# Primary calibration universe
LQ45_TICKERS = MSCI_LQ45_INTERSECTION  # Use intersection for best accuracy

IDX_CALIBRATION = {
    "DOUBLE_BOTTOM":         {"failure_rate_mult": 1.3, "avg_rise_mult": 0.85, "samples": 0},
    "HEAD_SHOULDERS_BOTTOM": {"failure_rate_mult": 1.2, "avg_rise_mult": 0.80, "samples": 0},
    "CUP_WITH_HANDLE":       {"failure_rate_mult": 1.4, "avg_rise_mult": 0.75, "samples": 0},
    "TRIANGLE_ASCENDING":    {"failure_rate_mult": 1.25,"avg_rise_mult": 0.85, "samples": 0},
    "TRIANGLE_SYMMETRICAL":  {"failure_rate_mult": 1.5, "avg_rise_mult": 0.80, "samples": 0},
    "RECTANGLE_BOTTOM":      {"failure_rate_mult": 1.2, "avg_rise_mult": 0.90, "samples": 0},
    "FLAG_BULL":             {"failure_rate_mult": 1.1, "avg_rise_mult": 0.95, "samples": 0},
    "WEDGE_FALLING":         {"failure_rate_mult": 1.3, "avg_rise_mult": 0.85, "samples": 0},
    "ROUNDING_BOTTOM":       {"failure_rate_mult": 1.2, "avg_rise_mult": 0.90, "samples": 0},
    "DOUBLE_TOP":            {"failure_rate_mult": 1.4, "avg_rise_mult": 0.70, "samples": 0},
    "HEAD_SHOULDERS_TOP":    {"failure_rate_mult": 1.3, "avg_rise_mult": 0.75, "samples": 0},
    "WEDGE_RISING":          {"failure_rate_mult": 1.5, "avg_rise_mult": 0.70, "samples": 0},
    "BUMP_AND_RUN_BOTTOM":   {"failure_rate_mult": 1.2, "avg_rise_mult": 0.80, "samples": 0},
}

def get_idx_calibration(pattern_name: str) -> dict:
    return IDX_CALIBRATION.get(pattern_name, {"failure_rate_mult": 1.3, "avg_rise_mult": 0.85})


# Bulkowski baseline failure rates and avg rises (US market)
_BULKOWSKI_BASELINE = {
    "DOUBLE_BOTTOM":         {"failure_rate": 11.0, "avg_rise": 40.0},
    "HEAD_SHOULDERS_BOTTOM": {"failure_rate": 12.0, "avg_rise": 38.0},
    "CUP_WITH_HANDLE":       {"failure_rate": 5.0,  "avg_rise": 34.0},
    "TRIANGLE_ASCENDING":    {"failure_rate": 13.0, "avg_rise": 35.0},
    "TRIANGLE_SYMMETRICAL":  {"failure_rate": 9.0,  "avg_rise": 31.0},
    "RECTANGLE_BOTTOM":      {"failure_rate": 15.0, "avg_rise": 38.0},
    "FLAG_BULL":             {"failure_rate": 4.0,  "avg_rise": 23.0},
    "WEDGE_FALLING":         {"failure_rate": 13.0, "avg_rise": 32.0},
    "ROUNDING_BOTTOM":       {"failure_rate": 11.0, "avg_rise": 43.0},
    "DOUBLE_TOP":            {"failure_rate": 14.0, "avg_rise": 20.0},
    "HEAD_SHOULDERS_TOP":    {"failure_rate": 11.0, "avg_rise": 22.0},
    "WEDGE_RISING":          {"failure_rate": 14.0, "avg_rise": 19.0},
    "BUMP_AND_RUN_BOTTOM":   {"failure_rate": 15.0, "avg_rise": 37.0},
}

_FORWARD_CANDLES = 20   # window to measure outcome after pattern detected
_MIN_CONFIDENCE  = 70   # skip low-confidence detections
_SUCCESS_THRESH  = 0.05 # 5% rise = success


async def run_backtest_calibration() -> dict:
    """
    Sliding-window backtest over MSCI_LQ45_INTERSECTION OHLCV data.
    Updates IDX_CALIBRATION multipliers in-place and returns a summary.
    """
    import asyncio
    import logging as _log
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text as _text
    from app.engines.idx_pattern_detector import detect_patterns

    _logger = _log.getLogger("idx_calibration.backtest")

    # pattern → {successes, failures, total_rise}
    stats: dict[str, dict] = {p: {"success": 0, "fail": 0, "total_rise": 0.0} for p in IDX_CALIBRATION}

    async def _process_ticker(ticker: str):
        try:
            async with AsyncSessionLocal() as db:
                rows = await db.execute(_text("""
                    SELECT date, open, high, low, close, volume
                    FROM ohlcv_daily
                    WHERE ticker = :t
                    ORDER BY date ASC
                """), {"t": ticker})
                raw = rows.fetchall()
            if not raw:
                return
            ohlcv = [
                {"date": str(r[0]), "open": float(r[1] or 0), "high": float(r[2] or 0),
                 "low": float(r[3] or 0), "close": float(r[4] or 0), "volume": float(r[5] or 0)}
                for r in raw
            ]
        except Exception as e:
            _logger.warning(f"[{ticker}] OHLCV fetch error: {e}")
            return

        window, step = 80, 20
        n = len(ohlcv)
        for start in range(0, n - window - _FORWARD_CANDLES, step):
            window_candles = ohlcv[start: start + window]
            future_candles = ohlcv[start + window: start + window + _FORWARD_CANDLES]
            if not future_candles:
                continue

            try:
                patterns = detect_patterns(window_candles, mode="swing")
            except Exception:
                continue

            for pat in patterns:
                pname = pat.get("pattern", "")
                conf  = float(pat.get("confidence", 0))
                if pname not in stats or conf < _MIN_CONFIDENCE:
                    continue
                entry_price = window_candles[-1]["close"]
                if entry_price <= 0:
                    continue
                max_future = max((c["high"] for c in future_candles), default=0)
                rise_pct = (max_future - entry_price) / entry_price if entry_price > 0 else 0
                if rise_pct >= _SUCCESS_THRESH:
                    stats[pname]["success"] += 1
                else:
                    stats[pname]["fail"] += 1
                stats[pname]["total_rise"] += rise_pct * 100

    await asyncio.gather(*[_process_ticker(t) for t in MSCI_LQ45_INTERSECTION])

    # Compute multipliers and update IDX_CALIBRATION
    summary = {}
    for pname, s in stats.items():
        total = s["success"] + s["fail"]
        if total < 5:
            summary[pname] = {"status": "insufficient_data", "samples": total}
            continue

        idx_failure_rate = round(s["fail"] / total * 100, 1)
        idx_avg_rise     = round(s["total_rise"] / total, 1)
        baseline         = _BULKOWSKI_BASELINE.get(pname, {"failure_rate": 15.0, "avg_rise": 30.0})

        fail_mult = round(idx_failure_rate / baseline["failure_rate"], 3) if baseline["failure_rate"] > 0 else 1.3
        rise_mult = round(idx_avg_rise     / baseline["avg_rise"],     3) if baseline["avg_rise"] > 0     else 0.85

        # Clamp to reasonable bounds
        fail_mult = max(0.5, min(3.0, fail_mult))
        rise_mult = max(0.3, min(2.0, rise_mult))

        IDX_CALIBRATION[pname]["failure_rate_mult"] = fail_mult
        IDX_CALIBRATION[pname]["avg_rise_mult"]     = rise_mult
        IDX_CALIBRATION[pname]["samples"]           = total

        summary[pname] = {
            "samples":           total,
            "idx_failure_rate":  idx_failure_rate,
            "idx_avg_rise":      idx_avg_rise,
            "bulkowski_baseline_failure": baseline["failure_rate"],
            "bulkowski_baseline_rise":    baseline["avg_rise"],
            "failure_rate_mult": fail_mult,
            "avg_rise_mult":     rise_mult,
        }
        _logger.info(f"[CALIB] {pname}: samples={total} fail={idx_failure_rate}% rise={idx_avg_rise}% → mult_fail={fail_mult} mult_rise={rise_mult}")

    return {
        "status":  "ok",
        "tickers": MSCI_LQ45_INTERSECTION,
        "patterns": summary,
    }
