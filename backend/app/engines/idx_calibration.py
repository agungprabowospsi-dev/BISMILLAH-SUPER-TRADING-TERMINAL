"""idx_calibration.py — IDX calibration factors untuk Bulkowski baseline."""

LQ45_TICKERS = ["BBCA","BBRI","BMRI","TLKM","ASII","MAPI","KLBF","INDF","ICBP","ANTM","ADRO","PTBA","PGAS","SMGR","LSIP","AALI","UNVR","SCMA","MNCN","BYAN"]

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
