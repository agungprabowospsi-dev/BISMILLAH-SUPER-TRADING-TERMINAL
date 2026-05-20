"""
Engine 5 — Momentum Strength
Path: backend/app/api/monitoring_enhancement/momentum_strength.py

Score 0-100 dari 3 komponen:
- ROC (Rate of Change)       : 40 poin
- Volume Confirmation        : 35 poin
- Candle Quality             : 25 poin

Label:
- 80-100 : VERY_STRONG
- 60-79  : STRONG
- 40-59  : MODERATE
- 20-39  : WEAK
- 0-19   : EXHAUSTED
"""

import logging
from typing import Optional

from .models import MomentumLabel, MomentumResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# KONSTANTA
# ─────────────────────────────────────────────

ROC_PERIOD       = 5     # ROC periode 5 candle
ROC_MAX_PCT      = 5.0   # ROC >= 5% = full score
VOLUME_AVG_DAYS  = 10    # rata-rata volume N hari


# ─────────────────────────────────────────────
# HELPER — LABEL
# ─────────────────────────────────────────────

def _score_to_label(score: float) -> MomentumLabel:
    if score >= 80:
        return MomentumLabel.VERY_STRONG
    elif score >= 60:
        return MomentumLabel.STRONG
    elif score >= 40:
        return MomentumLabel.MODERATE
    elif score >= 20:
        return MomentumLabel.WEAK
    return MomentumLabel.EXHAUSTED


# ─────────────────────────────────────────────
# KOMPONEN 1 — ROC (40 poin)
# ─────────────────────────────────────────────

def _calc_roc(closes: list[float], period: int = ROC_PERIOD) -> tuple[float, float]:
    """
    Hitung ROC dan akselerasinya.
    Return: (roc_pct, acceleration)
    """
    if len(closes) < period + 2:
        return 0.0, 0.0

    roc_now  = ((closes[-1] - closes[-period - 1]) / closes[-period - 1]) * 100
    roc_prev = ((closes[-2] - closes[-period - 2]) / closes[-period - 2]) * 100
    acceleration = roc_now - roc_prev

    return round(roc_now, 4), round(acceleration, 4)


def _roc_score(roc_pct: float) -> float:
    """
    Konversi ROC ke skor 0-40.
    ROC >= ROC_MAX_PCT  = 40 poin
    ROC <= -ROC_MAX_PCT = 0 poin
    """
    clamped = max(-ROC_MAX_PCT, min(ROC_MAX_PCT, roc_pct))
    normalized = (clamped + ROC_MAX_PCT) / (2 * ROC_MAX_PCT)
    return round(normalized * 40, 2)


# ─────────────────────────────────────────────
# KOMPONEN 2 — VOLUME CONFIRMATION (35 poin)
# ─────────────────────────────────────────────

def _volume_score(
    volumes: list[int],
    closes: list[float],
    avg_vol: float,
) -> tuple[float, bool]:
    """
    Cek volume confirming momentum.
    Return: (score 0-35, is_confirming)

    Aturan:
    - Volume naik saat harga naik  = konfirmasi bullish
    - Volume turun saat harga turun = konfirmasi bearish (negatif untuk long)
    - Volume naik saat harga turun = distribusi (buruk)
    - Volume turun saat harga naik  = no demand (lemah)
    """
    if len(volumes) < 3 or len(closes) < 3 or avg_vol <= 0:
        return 17.5, False  # neutral

    vol_ratio = volumes[-1] / avg_vol
    price_up  = closes[-1] > closes[-2]

    if price_up and vol_ratio >= 1.2:
        # Volume tinggi + harga naik = KONFIRMASI KUAT
        score = min(35.0, 25 + (vol_ratio - 1.2) * 10)
        return round(score, 2), True
    elif price_up and vol_ratio >= 0.8:
        # Volume normal + harga naik = konfirmasi moderat
        return 20.0, True
    elif price_up and vol_ratio < 0.8:
        # No demand
        return 10.0, False
    elif not price_up and vol_ratio >= 1.5:
        # Distribusi — sangat buruk untuk long
        return 0.0, False
    else:
        return 15.0, False


# ─────────────────────────────────────────────
# KOMPONEN 3 — CANDLE QUALITY (25 poin)
# ─────────────────────────────────────────────

def _candle_quality_score(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> float:
    """
    Kualitas candle terakhir berdasarkan body/shadow ratio.
    Candle bullish dengan body besar = kualitas tinggi.
    Return: score 0-25
    """
    if not all([opens, highs, lows, closes]):
        return 12.5  # neutral

    o = opens[-1]
    h = highs[-1]
    l = lows[-1]
    c = closes[-1]

    total_range = h - l
    if total_range == 0:
        return 12.5

    body       = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    body_ratio  = body / total_range
    is_bullish  = c > o

    if is_bullish:
        # Bullish candle: body besar + lower wick kecil = bagus
        wick_penalty = (upper_wick / total_range) * 0.5
        quality = body_ratio - wick_penalty
    else:
        # Bearish candle: buruk untuk long
        quality = (1 - body_ratio) * 0.3

    quality = max(0.0, min(1.0, quality))
    return round(quality * 25, 2)


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def calculate_momentum_strength(
    ticker:        str,
    opens:         list[float],
    highs:         list[float],
    lows:          list[float],
    closes:        list[float],
    volumes:       list[int],
    prev_score:    Optional[float] = None,
) -> MomentumResult:
    """
    Hitung momentum strength score 0-100.

    Parameters
    ----------
    ticker     : kode saham
    opens      : list harga open (min 10 candle)
    highs      : list harga high
    lows       : list harga low
    closes     : list harga close
    volumes    : list volume (lot)
    prev_score : score dari poll sebelumnya (untuk hitung drop)
    """
    try:
        # Rata-rata volume
        avg_vol = (
            sum(volumes[-VOLUME_AVG_DAYS:]) / min(len(volumes), VOLUME_AVG_DAYS)
            if volumes else 1
        )

        # Komponen 1: ROC
        roc_pct, roc_accel = _calc_roc(closes)
        score_roc = _roc_score(roc_pct)

        # Komponen 2: Volume
        score_vol, vol_confirming = _volume_score(volumes, closes, avg_vol)

        # Komponen 3: Candle quality
        score_candle = _candle_quality_score(opens, highs, lows, closes)

        # Total score
        total = score_roc + score_vol + score_candle
        total = round(max(0.0, min(100.0, total)), 1)

        label = _score_to_label(total)

        # Score drop dari poll sebelumnya
        score_drop = 0.0
        if prev_score is not None:
            score_drop = round(max(0.0, prev_score - total), 1)

        return MomentumResult(
            score             = total,
            label             = label,
            roc_pct           = roc_pct,
            roc_acceleration  = roc_accel,
            volume_confirming = vol_confirming,
            candle_quality    = round(score_candle / 25 * 100, 1),
            prev_score        = prev_score,
            score_drop        = score_drop,
            rag_triggered     = score_drop >= 20.0,
        )

    except Exception as e:
        logger.error(f"MomentumStrength error [{ticker}]: {e}")
        return MomentumResult(
            score             = 50.0,
            label             = MomentumLabel.MODERATE,
            roc_pct           = 0.0,
            roc_acceleration  = 0.0,
            candle_quality    = 50.0,
            rag_triggered     = False,
        )
