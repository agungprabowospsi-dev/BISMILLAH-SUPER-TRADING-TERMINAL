"""
Phase 2 Engine 2 — Weinstein Stage Analysis
Path: backend/app/api/enrichment/weinstein_stage.py

Stage 1: Base/Basing — sideways, volume rendah
Stage 2: Advancing — break above MA30, volume naik ← BUY
Stage 3: Top/Topping — sideways di atas MA30, vol tidak menentu
Stage 4: Declining — break below MA30, volume naik ← AVOID
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MA_PERIOD = 30  # 30-week MA (pakai daily = ~30 candle)


@dataclass
class WeinsteinResult:
    stage:               int   = 0
    stage_name:          str   = "UNKNOWN"
    ma30:                float = 0.0
    price_vs_ma:         str   = "AT"      # ABOVE / BELOW / AT
    ma_slope:            str   = "FLAT"    # RISING / FALLING / FLAT
    volume_confirmation: bool  = False
    implication:         str   = "NEUTRAL" # BUY / HOLD / AVOID / EXIT
    confidence:          float = 0.0
    breakout_detected:   bool  = False
    breakdown_detected:  bool  = False
    weeks_in_stage:      int   = 0


def _sma(data: list, period: int) -> float:
    if len(data) < period:
        return sum(data) / len(data) if data else 0.0
    return sum(data[-period:]) / period


def _ma_slope(closes: list, period: int = 30) -> str:
    """Hitung slope MA: RISING / FALLING / FLAT"""
    if len(closes) < period + 5:
        return "FLAT"
    ma_now  = _sma(closes, period)
    ma_prev = _sma(closes[:-5], period)
    diff_pct = (ma_now - ma_prev) / ma_prev * 100 if ma_prev else 0
    if diff_pct > 0.5:
        return "RISING"
    elif diff_pct < -0.5:
        return "FALLING"
    return "FLAT"


def _count_weeks_in_stage(closes: list, ma30: float, above: bool) -> int:
    """Hitung berapa candle harga konsisten di atas/bawah MA30"""
    count = 0
    for c in reversed(closes[-30:]):
        if above and c > ma30:
            count += 1
        elif not above and c < ma30:
            count += 1
        else:
            break
    return count


def classify_weinstein(
    closes:  list,
    volumes: list,
) -> WeinsteinResult:
    """
    Klasifikasi Weinstein Stage dari data harian.
    Minimal 30 candle dibutuhkan untuk akurasi optimal.
    """
    try:
        if len(closes) < 10:
            return WeinsteinResult(stage=0, stage_name="INSUFFICIENT_DATA")

        ma30       = _sma(closes, MA_PERIOD)
        current    = closes[-1]
        prev       = closes[-2] if len(closes) >= 2 else current
        slope      = _ma_slope(closes, MA_PERIOD)

        # Price vs MA
        diff_pct = (current - ma30) / ma30 * 100 if ma30 else 0
        if diff_pct > 1.0:
            price_vs_ma = "ABOVE"
        elif diff_pct < -1.0:
            price_vs_ma = "BELOW"
        else:
            price_vs_ma = "AT"

        # Volume analysis
        avg_vol_20 = sum(volumes[-20:]) / min(20, len(volumes))
        avg_vol_5  = sum(volumes[-5:]) / min(5, len(volumes))
        vol_expanding = avg_vol_5 > avg_vol_20 * 1.15
        vol_contracting = avg_vol_5 < avg_vol_20 * 0.85

        # Breakout / Breakdown detection
        prev_ma30 = _sma(closes[:-1], MA_PERIOD) if len(closes) > MA_PERIOD else ma30
        breakout  = prev < prev_ma30 and current > ma30 and vol_expanding
        breakdown = prev > prev_ma30 and current < ma30 and vol_expanding

        # Weeks in stage
        above = price_vs_ma == "ABOVE"
        weeks_in_stage = _count_weeks_in_stage(closes, ma30, above)

        # ── STAGE CLASSIFICATION ──
        stage = 0
        stage_name = "UNKNOWN"
        implication = "NEUTRAL"
        confidence = 0.0
        vol_confirm = False

        if breakout:
            # Fresh breakout = Stage 2 entry
            stage      = 2
            stage_name = "ADVANCING"
            implication = "BUY"
            confidence  = 85.0
            vol_confirm = True

        elif breakdown:
            # Fresh breakdown = Stage 4 entry
            stage      = 4
            stage_name = "DECLINING"
            implication = "EXIT"
            confidence  = 85.0
            vol_confirm = True

        elif price_vs_ma == "ABOVE" and slope == "RISING":
            # Above rising MA = Stage 2
            stage      = 2
            stage_name = "ADVANCING"
            implication = "HOLD"
            confidence  = 75.0
            vol_confirm = vol_expanding
            # Cek apakah sudah terlalu lama = Stage 3 warning
            if weeks_in_stage > 60 and vol_contracting:
                stage      = 3
                stage_name = "TOPPING"
                implication = "REDUCE"
                confidence  = 60.0

        elif price_vs_ma == "ABOVE" and slope in ("FLAT", "FALLING"):
            # Above but MA flattening = Stage 3
            stage      = 3
            stage_name = "TOPPING"
            implication = "REDUCE"
            confidence  = 65.0
            vol_confirm = not vol_expanding

        elif price_vs_ma == "BELOW" and slope == "FALLING":
            # Below falling MA = Stage 4
            stage      = 4
            stage_name = "DECLINING"
            implication = "AVOID"
            confidence  = 75.0
            vol_confirm = vol_expanding

        elif price_vs_ma in ("BELOW", "AT") and slope in ("FLAT", "RISING"):
            # Below/at flat MA = Stage 1 basing
            stage      = 1
            stage_name = "BASING"
            implication = "WATCH"
            confidence  = 60.0
            vol_confirm = vol_contracting
            # Jika MA mulai rising dan harga di AT = potensi breakout
            if slope == "RISING" and price_vs_ma == "AT":
                implication = "BUY"
                confidence  = 70.0

        else:
            stage      = 1
            stage_name = "BASING"
            implication = "WATCH"
            confidence  = 40.0

        return WeinsteinResult(
            stage               = stage,
            stage_name          = stage_name,
            ma30                = round(ma30, 2),
            price_vs_ma         = price_vs_ma,
            ma_slope            = slope,
            volume_confirmation = vol_confirm,
            implication         = implication,
            confidence          = confidence,
            breakout_detected   = breakout,
            breakdown_detected  = breakdown,
            weeks_in_stage      = weeks_in_stage,
        )

    except Exception as e:
        logger.error(f"WeinsteinStage error: {e}")
        return WeinsteinResult(stage=0, stage_name="ERROR")
