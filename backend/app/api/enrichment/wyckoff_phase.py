"""
Phase 2 Engine 1 — Wyckoff Phase Classifier
Path: backend/app/api/enrichment/wyckoff_phase.py

Deteksi fase Wyckoff dan events kritis:
- PS, SC, AR, ST, Spring, SOS, LPS (Accumulation)
- BC, AR, ST, LPSY, Upthrust, UTAD (Distribution)
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

PHASE_LABELS = {
    "ACCUMULATION":   "Akumulasi — bandar sedang mengumpulkan",
    "MARKUP":         "Markup — harga dalam uptrend",
    "DISTRIBUTION":   "Distribusi — bandar sedang menjual",
    "MARKDOWN":       "Markdown — harga dalam downtrend",
    "REACCUMULATION": "Re-akumulasi — konsolidasi di uptrend",
    "UNKNOWN":        "Tidak diketahui",
}

# ─────────────────────────────────────────────
# DATACLASS
# ─────────────────────────────────────────────

@dataclass
class WyckoffResult:
    phase:            str = "UNKNOWN"
    sub_event:        str = "NONE"
    confidence:       float = 0.0
    implication:      str = "NEUTRAL"  # BUY / HOLD / REDUCE / EXIT
    phase_label:      str = ""
    is_spring:        bool = False
    is_sos:           bool = False
    is_upthrust:      bool = False
    is_distribution:  bool = False
    support_level:    float = 0.0
    resistance_level: float = 0.0
    raw_signals:      dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def _rolling_avg(data: list, period: int) -> float:
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    return sum(data[-period:]) / period


def _is_high_volume(vol: float, avg_vol: float, multiplier: float = 1.5) -> bool:
    return vol > avg_vol * multiplier


def _is_low_volume(vol: float, avg_vol: float, multiplier: float = 0.6) -> bool:
    return vol < avg_vol * multiplier


def _find_support(lows: list, lookback: int = 20) -> float:
    if not lows:
        return 0.0
    return min(lows[-lookback:])


def _find_resistance(highs: list, lookback: int = 20) -> float:
    if not highs:
        return 0.0
    return max(highs[-lookback:])


def _is_wide_spread(opens, closes, highs, lows, idx: int) -> bool:
    """Candle dengan spread lebar (body > 60% total range)"""
    total = highs[idx] - lows[idx]
    if total <= 0:
        return False
    body = abs(closes[idx] - opens[idx])
    return (body / total) > 0.6


def _lower_wick_pct(opens, closes, lows, idx: int) -> float:
    """% lower wick dari total range"""
    total_range = abs(closes[idx] - lows[idx])
    if total_range <= 0:
        return 0.0
    lower_wick = min(opens[idx], closes[idx]) - lows[idx]
    return lower_wick / total_range if lower_wick > 0 else 0.0


# ─────────────────────────────────────────────
# EVENT DETECTORS
# ─────────────────────────────────────────────

def _detect_selling_climax(
    opens, highs, lows, closes, volumes,
    avg_vol: float, idx: int
) -> bool:
    """
    Selling Climax (SC): volume ekstrem + spread lebar +
    close di lower half + harga turun drastis
    """
    if idx < 1:
        return False
    price_drop = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100
    return (
        _is_high_volume(volumes[idx], avg_vol, 2.5)
        and price_drop < -3.0
        and _is_wide_spread(opens, closes, highs, lows, idx)
    )


def _detect_spring(
    opens, highs, lows, closes, volumes,
    support: float, avg_vol: float, idx: int
) -> bool:
    """
    Spring: brief break di bawah support + recovery cepat +
    volume rendah/moderat
    """
    if idx < 1 or support <= 0:
        return False
    broke_support = lows[idx] < support * 0.998
    recovered     = closes[idx] > support * 0.999
    low_vol       = volumes[idx] < avg_vol * 1.2
    return broke_support and recovered and low_vol


def _detect_sos(
    opens, highs, lows, closes, volumes,
    resistance: float, avg_vol: float, idx: int
) -> bool:
    """
    Sign of Strength (SOS): break above resistance +
    volume tinggi + wide spread bullish
    """
    if idx < 1 or resistance <= 0:
        return False
    broke_resistance = closes[idx] > resistance * 1.001
    high_vol         = _is_high_volume(volumes[idx], avg_vol, 1.5)
    bullish          = closes[idx] > opens[idx]
    return broke_resistance and high_vol and bullish


def _detect_upthrust(
    opens, highs, lows, closes, volumes,
    resistance: float, avg_vol: float, idx: int
) -> bool:
    """
    Upthrust: spike above resistance + close kembali di bawah +
    volume tinggi
    """
    if idx < 1 or resistance <= 0:
        return False
    spiked_above = highs[idx] > resistance * 1.001
    closed_below = closes[idx] < resistance
    high_vol     = _is_high_volume(volumes[idx], avg_vol, 1.3)
    return spiked_above and closed_below and high_vol


def _detect_no_demand(
    opens, highs, lows, closes, volumes,
    avg_vol: float, idx: int
) -> bool:
    """No Demand: harga naik + volume sangat rendah"""
    if idx < 1:
        return False
    price_up = closes[idx] > closes[idx-1]
    low_vol  = _is_low_volume(volumes[idx], avg_vol, 0.5)
    return price_up and low_vol


def _detect_stopping_volume(
    opens, highs, lows, closes, volumes,
    avg_vol: float, idx: int
) -> bool:
    """
    Stopping Volume: volume ekstrem saat harga turun +
    lower wick panjang
    """
    if idx < 1:
        return False
    price_down    = closes[idx] < closes[idx-1]
    extreme_vol   = _is_high_volume(volumes[idx], avg_vol, 2.0)
    lower_wick    = _lower_wick_pct(opens, closes, lows, idx) > 0.4
    return price_down and extreme_vol and lower_wick


# ─────────────────────────────────────────────
# PHASE CLASSIFIER
# ─────────────────────────────────────────────

def _classify_phase(
    closes: list,
    volumes: list,
    avg_vol: float,
    support: float,
    resistance: float,
    sc_detected:    bool,
    spring_detected: bool,
    sos_detected:   bool,
    upthrust_detected: bool,
    no_demand_count: int,
    stopping_vol:   bool,
) -> tuple:
    """
    Classify Wyckoff phase.
    Return: (phase, sub_event, confidence, implication)
    """
    if len(closes) < 10:
        return "UNKNOWN", "NONE", 0.0, "NEUTRAL"

    # Price vs range
    price_range = resistance - support
    if price_range <= 0:
        return "UNKNOWN", "NONE", 0.0, "NEUTRAL"

    current    = closes[-1]
    range_pos  = (current - support) / price_range  # 0=support, 1=resistance

    # Trend
    ma_short = _rolling_avg(closes, 10)
    ma_long  = _rolling_avg(closes, 30) if len(closes) >= 30 else ma_short
    uptrend  = ma_short > ma_long * 1.005
    downtrend = ma_short < ma_long * 0.995

    # Volume trend
    vol_recent = _rolling_avg(volumes[-5:], 5)
    vol_old    = _rolling_avg(volumes[-20:-5], 15) if len(volumes) >= 20 else avg_vol
    vol_increasing = vol_recent > vol_old * 1.1

    # ── MARKDOWN ──
    if downtrend and range_pos < 0.3 and not stopping_vol:
        return "MARKDOWN", "DOWNTREND", 70.0, "EXIT"

    # ── DISTRIBUTION ──
    if upthrust_detected or (no_demand_count >= 2 and range_pos > 0.7):
        event = "UPTHRUST" if upthrust_detected else "NO_DEMAND"
        return "DISTRIBUTION", event, 75.0, "REDUCE"

    # ── MARKUP ──
    if uptrend and sos_detected and range_pos > 0.6:
        return "MARKUP", "SOS", 80.0, "HOLD"

    if uptrend and range_pos > 0.5 and vol_increasing:
        return "MARKUP", "ADVANCING", 65.0, "HOLD"

    # ── ACCUMULATION ──
    if spring_detected:
        return "ACCUMULATION", "SPRING", 85.0, "BUY"

    if sc_detected and range_pos < 0.4:
        return "ACCUMULATION", "SC", 70.0, "BUY"

    if stopping_vol and range_pos < 0.5:
        return "ACCUMULATION", "STOPPING_VOLUME", 65.0, "BUY"

    # ── REACCUMULATION ──
    if uptrend and range_pos < 0.5 and not downtrend:
        return "REACCUMULATION", "CONSOLIDATION", 60.0, "HOLD"

    # ── DEFAULT ──
    if range_pos < 0.4:
        return "ACCUMULATION", "POSSIBLE", 40.0, "BUY"
    elif range_pos > 0.7:
        return "DISTRIBUTION", "POSSIBLE", 40.0, "REDUCE"

    return "UNKNOWN", "NONE", 30.0, "NEUTRAL"


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def classify_wyckoff(
    opens:   list,
    highs:   list,
    lows:    list,
    closes:  list,
    volumes: list,
) -> WyckoffResult:
    """
    Klasifikasi fase Wyckoff dari OHLCV data.
    Minimal 20 candle dibutuhkan.
    """
    try:
        if len(closes) < 10:
            return WyckoffResult(phase="UNKNOWN", phase_label=PHASE_LABELS["UNKNOWN"])

        avg_vol    = _rolling_avg(volumes, min(20, len(volumes)))
        support    = _find_support(lows, min(20, len(lows)))
        resistance = _find_resistance(highs, min(20, len(highs)))

        # Scan events di 5 candle terakhir
        n = len(closes)
        scan_range = range(max(1, n-5), n)

        sc_detected       = False
        spring_detected   = False
        sos_detected      = False
        upthrust_detected = False
        stopping_vol      = False
        no_demand_count   = 0
        sub_event_latest  = "NONE"

        for i in scan_range:
            if _detect_selling_climax(opens, highs, lows, closes, volumes, avg_vol, i):
                sc_detected = True
                sub_event_latest = "SC"
            if _detect_spring(opens, highs, lows, closes, volumes, support, avg_vol, i):
                spring_detected = True
                sub_event_latest = "SPRING"
            if _detect_sos(opens, highs, lows, closes, volumes, resistance, avg_vol, i):
                sos_detected = True
                sub_event_latest = "SOS"
            if _detect_upthrust(opens, highs, lows, closes, volumes, resistance, avg_vol, i):
                upthrust_detected = True
                sub_event_latest = "UPTHRUST"
            if _detect_no_demand(opens, highs, lows, closes, volumes, avg_vol, i):
                no_demand_count += 1
            if _detect_stopping_volume(opens, highs, lows, closes, volumes, avg_vol, i):
                stopping_vol = True
                sub_event_latest = "STOPPING_VOLUME"

        phase, sub_event, confidence, implication = _classify_phase(
            closes, volumes, avg_vol, support, resistance,
            sc_detected, spring_detected, sos_detected,
            upthrust_detected, no_demand_count, stopping_vol,
        )

        return WyckoffResult(
            phase            = phase,
            sub_event        = sub_event,
            confidence       = confidence,
            implication      = implication,
            phase_label      = PHASE_LABELS.get(phase, ""),
            is_spring        = spring_detected,
            is_sos           = sos_detected,
            is_upthrust      = upthrust_detected,
            is_distribution  = phase == "DISTRIBUTION",
            support_level    = round(support, 2),
            resistance_level = round(resistance, 2),
            raw_signals      = {
                "sc":            sc_detected,
                "spring":        spring_detected,
                "sos":           sos_detected,
                "upthrust":      upthrust_detected,
                "stopping_vol":  stopping_vol,
                "no_demand_count": no_demand_count,
            }
        )

    except Exception as e:
        logger.error(f"WyckoffClassifier error: {e}")
        return WyckoffResult(phase="UNKNOWN", phase_label=PHASE_LABELS["UNKNOWN"])
