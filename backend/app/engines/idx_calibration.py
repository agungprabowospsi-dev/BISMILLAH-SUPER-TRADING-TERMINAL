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
