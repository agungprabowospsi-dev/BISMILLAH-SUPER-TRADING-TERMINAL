"""
Phase 2 Engine 3 — VSA (Volume Spread Analysis) Engine
Path: backend/app/api/enrichment/vsa_engine.py

VSA Signals:
- STOPPING_VOLUME  : volume ekstrem saat harga turun + lower wick = bullish
- NO_SUPPLY        : volume rendah saat pullback = supply habis = bullish
- NO_DEMAND        : volume rendah saat rally = lemah = bearish warning
- UP_THRUST        : new high + close rendah + volume tinggi = bearish
- EFFORT_VS_RESULT : volume besar + movement kecil = absorpsi
- TEST             : retest support + volume rendah = bullish konfirmasi
- NONE             : tidak ada sinyal jelas
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VSAResult:
    signal:      str   = "NONE"
    background:  str   = "NEUTRAL"   # BULLISH / NEUTRAL / BEARISH
    strength:    str   = "MODERATE"  # STRONG / MODERATE / WEAK
    tradeable:   bool  = False
    description: str   = ""
    vol_ratio:   float = 1.0         # volume candle / avg volume
    spread_ratio: float = 1.0        # spread candle / avg spread
    close_position: float = 0.5      # 0=low, 1=high (close position in range)
    raw_signals: dict  = field(default_factory=dict)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _avg(data: list, period: int) -> float:
    if not data:
        return 0.0
    subset = data[-period:] if len(data) >= period else data
    return sum(subset) / len(subset)


def _close_position(open_, high, low, close) -> float:
    """Posisi close dalam range candle: 0=bawah, 1=atas"""
    total = high - low
    if total <= 0:
        return 0.5
    return (close - low) / total


def _spread(high, low) -> float:
    return high - low


# ─────────────────────────────────────────────
# SIGNAL DETECTORS
# ─────────────────────────────────────────────

def _detect_stopping_volume(
    opens, highs, lows, closes, volumes,
    avg_vol: float, avg_spread: float, idx: int
) -> bool:
    """
    Stopping Volume:
    - Volume sangat tinggi (>2x avg)
    - Harga turun dari candle sebelumnya
    - Lower wick panjang (> 40% range)
    - Close di upper half candle
    """
    if idx < 1:
        return False
    vol_ratio   = volumes[idx] / avg_vol if avg_vol > 0 else 1
    price_down  = closes[idx] <= closes[idx-1]
    total_range = highs[idx] - lows[idx]
    if total_range <= 0:
        return False
    lower_wick  = min(opens[idx], closes[idx]) - lows[idx]
    close_pos   = _close_position(opens[idx], highs[idx], lows[idx], closes[idx])
    return (
        vol_ratio >= 2.0
        and price_down
        and (lower_wick / total_range) > 0.35
        and close_pos > 0.4
    )


def _detect_no_supply(
    opens, highs, lows, closes, volumes,
    avg_vol: float, idx: int
) -> bool:
    """
    No Supply:
    - Volume rendah (<0.6x avg)
    - Harga turun atau sideways
    - Spread sempit
    - Lower wick kecil
    """
    if idx < 1:
        return False
    vol_ratio  = volumes[idx] / avg_vol if avg_vol > 0 else 1
    price_down = closes[idx] <= closes[idx-1]
    spread     = highs[idx] - lows[idx]
    avg_s      = _avg([highs[i]-lows[i] for i in range(max(0,idx-10), idx)], 10)
    narrow     = spread < avg_s * 0.7 if avg_s > 0 else True
    return vol_ratio < 0.6 and price_down and narrow


def _detect_no_demand(
    opens, highs, lows, closes, volumes,
    avg_vol: float, idx: int
) -> bool:
    """
    No Demand:
    - Volume rendah (<0.7x avg)
    - Harga naik
    - Spread sempit
    - Upper wick ada
    """
    if idx < 1:
        return False
    vol_ratio  = volumes[idx] / avg_vol if avg_vol > 0 else 1
    price_up   = closes[idx] > closes[idx-1]
    total      = highs[idx] - lows[idx]
    upper_wick = highs[idx] - max(opens[idx], closes[idx])
    has_wick   = (upper_wick / total) > 0.2 if total > 0 else False
    return vol_ratio < 0.7 and price_up and has_wick


def _detect_up_thrust(
    opens, highs, lows, closes, volumes,
    avg_vol: float, resistance: float, idx: int
) -> bool:
    """
    Up Thrust:
    - Spike above resistance
    - Close kembali di bawah resistance
    - Volume tinggi
    - Upper wick panjang
    """
    if idx < 1 or resistance <= 0:
        return False
    spiked   = highs[idx] > resistance * 1.001
    closed_b = closes[idx] < resistance
    vol_high = volumes[idx] > avg_vol * 1.3
    total    = highs[idx] - lows[idx]
    upper_w  = highs[idx] - max(opens[idx], closes[idx])
    long_wick = (upper_w / total) > 0.4 if total > 0 else False
    return spiked and closed_b and vol_high and long_wick


def _detect_effort_vs_result(
    opens, highs, lows, closes, volumes,
    avg_vol: float, avg_spread: float, idx: int
) -> bool:
    """
    Effort vs Result:
    - Volume sangat tinggi (>1.8x avg)
    - Spread sempit (movement kecil)
    - Close di middle candle
    """
    if idx < 1:
        return False
    vol_ratio  = volumes[idx] / avg_vol if avg_vol > 0 else 1
    spread     = highs[idx] - lows[idx]
    narrow     = spread < avg_spread * 0.6 if avg_spread > 0 else False
    close_pos  = _close_position(opens[idx], highs[idx], lows[idx], closes[idx])
    middle     = 0.3 < close_pos < 0.7
    return vol_ratio >= 1.8 and narrow and middle


def _detect_test(
    opens, highs, lows, closes, volumes,
    avg_vol: float, support: float, idx: int
) -> bool:
    """
    Test (after Spring/SC):
    - Harga turun ke area support
    - Volume sangat rendah (<0.5x avg)
    - Close di atas support
    """
    if idx < 1 or support <= 0:
        return False
    near_support = lows[idx] <= support * 1.01
    above        = closes[idx] > support
    low_vol      = volumes[idx] < avg_vol * 0.5
    return near_support and above and low_vol


# ─────────────────────────────────────────────
# BACKGROUND ANALYZER
# ─────────────────────────────────────────────

def _analyze_background(
    closes: list,
    volumes: list,
    bullish_signals: int,
    bearish_signals: int,
) -> tuple:
    """
    Analisis background market berdasarkan akumulasi sinyal.
    Return: (background, strength)
    """
    if bullish_signals >= 2:
        bg = "BULLISH"
        strength = "STRONG" if bullish_signals >= 3 else "MODERATE"
    elif bearish_signals >= 2:
        bg = "BEARISH"
        strength = "STRONG" if bearish_signals >= 3 else "MODERATE"
    else:
        bg = "NEUTRAL"
        strength = "WEAK"
    return bg, strength


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def analyze_vsa(
    opens:   list,
    highs:   list,
    lows:    list,
    closes:  list,
    volumes: list,
) -> VSAResult:
    """
    Analisis VSA dari OHLCV data.
    Minimal 10 candle dibutuhkan.
    """
    try:
        if len(closes) < 5:
            return VSAResult(signal="NONE", description="Insufficient data")

        n         = len(closes)
        avg_vol   = _avg(volumes, min(20, n))
        spreads   = [highs[i] - lows[i] for i in range(n)]
        avg_spread = _avg(spreads, min(20, n))
        support   = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        resistance = max(highs[-20:]) if len(highs) >= 20 else max(highs)

        # Scan 3 candle terakhir
        idx = n - 1

        # Deteksi semua sinyal
        stopping_vol = _detect_stopping_volume(opens, highs, lows, closes, volumes, avg_vol, avg_spread, idx)
        no_supply    = _detect_no_supply(opens, highs, lows, closes, volumes, avg_vol, idx)
        no_demand    = _detect_no_demand(opens, highs, lows, closes, volumes, avg_vol, idx)
        up_thrust    = _detect_up_thrust(opens, highs, lows, closes, volumes, avg_vol, resistance, idx)
        effort_res   = _detect_effort_vs_result(opens, highs, lows, closes, volumes, avg_vol, avg_spread, idx)
        test_signal  = _detect_test(opens, highs, lows, closes, volumes, avg_vol, support, idx)

        # Prioritas sinyal (dari yang paling kuat)
        signal = "NONE"
        description = "Tidak ada sinyal VSA yang jelas"
        tradeable = False

        if stopping_vol:
            signal = "STOPPING_VOLUME"
            description = "Volume ekstrem saat turun + lower wick = bandar serap supply"
            tradeable = True
        elif up_thrust:
            signal = "UP_THRUST"
            description = "Spike di atas resistance + close rendah = distribusi terselubung"
            tradeable = True
        elif no_supply:
            signal = "NO_SUPPLY"
            description = "Volume rendah saat pullback = supply habis, siap naik"
            tradeable = True
        elif test_signal:
            signal = "TEST"
            description = "Retest support + volume rendah = konfirmasi bullish"
            tradeable = True
        elif effort_res:
            signal = "EFFORT_VS_RESULT"
            description = "Volume besar + movement kecil = absorpsi, waspadai arah"
            tradeable = False
        elif no_demand:
            signal = "NO_DEMAND"
            description = "Volume rendah saat naik = rally lemah, waspadai reversal"
            tradeable = False

        # Background
        bullish_count = sum([stopping_vol, no_supply, test_signal])
        bearish_count = sum([up_thrust, no_demand])
        background, strength = _analyze_background(
            closes, volumes, bullish_count, bearish_count
        )

        # Metrics candle terakhir
        vol_ratio    = volumes[idx] / avg_vol if avg_vol > 0 else 1.0
        spread_ratio = spreads[idx] / avg_spread if avg_spread > 0 else 1.0
        close_pos    = _close_position(opens[idx], highs[idx], lows[idx], closes[idx])

        return VSAResult(
            signal       = signal,
            background   = background,
            strength     = strength,
            tradeable    = tradeable,
            description  = description,
            vol_ratio    = round(vol_ratio, 2),
            spread_ratio = round(spread_ratio, 2),
            close_position = round(close_pos, 2),
            raw_signals  = {
                "stopping_volume": stopping_vol,
                "no_supply":       no_supply,
                "no_demand":       no_demand,
                "up_thrust":       up_thrust,
                "effort_vs_result": effort_res,
                "test":            test_signal,
            }
        )

    except Exception as e:
        logger.error(f"VSAEngine error: {e}")
        return VSAResult(signal="NONE", description=f"Error: {str(e)}")
