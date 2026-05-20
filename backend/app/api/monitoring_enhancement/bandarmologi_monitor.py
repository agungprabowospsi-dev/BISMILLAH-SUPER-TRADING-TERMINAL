"""
Engine 4 — Bandarmologi Monitor
Path: backend/app/api/monitoring_enhancement/bandarmologi_monitor.py

5 Engine Subset:
- BandarmologyEngine  : fase akumulasi/distribusi
- VolumeIntelligenceEngine : OBV + A/D line
- FlowMappingEngine   : institutional flow map
- ForeignFlowEngine   : net foreign buy/sell
- InventoryEngine     : inventory cycle position

Distribution Signal Detector (4 sinyal kritis IDX):
- Upthrust        : new high + volume sangat tinggi + close < high
- No Demand       : volume sangat rendah saat harga naik
- Effort vs Result: volume besar + harga flat
- Top Volume      : volume tertinggi 20 hari di resistance
"""

import logging
from typing import Optional

from .models import (
    BandarPhase, BandarmologiMonitorResult, DistributionSignal, RAGTrigger
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# KONSTANTA
# ─────────────────────────────────────────────

# Threshold volume untuk sinyal distribusi
UPTHRUST_VOLUME_MULTIPLIER  = 2.0   # volume > 2x avg = sangat tinggi
NO_DEMAND_VOLUME_MULTIPLIER = 0.5   # volume < 0.5x avg = sangat rendah
EFFORT_VOLUME_MULTIPLIER    = 1.5   # volume > 1.5x avg = besar
EFFORT_PRICE_THRESHOLD      = 0.3   # harga flat = perubahan < 0.3%
TOP_VOLUME_LOOKBACK         = 20    # hari lookback untuk top volume


# ─────────────────────────────────────────────
# ENGINE 1 — BANDARMOLOGY (Fase)
# ─────────────────────────────────────────────

def _detect_phase(
    bandar_score: float,
    score_delta: float,
    obv_trend: str,
    net_foreign_lot: int,
    price_change_pct: float,
) -> BandarPhase:
    """
    Deteksi fase bandar berdasarkan kombinasi sinyal.
    """
    # DISTRIBUTION: score turun drastis + OBV turun + harga masih tinggi
    if score_delta < -15 and obv_trend == "DOWN":
        return BandarPhase.DISTRIBUTION

    # MARKDOWN: score < 40 + harga turun + foreign sell
    if bandar_score < 40 and price_change_pct < -1.0 and net_foreign_lot < -100_000:
        return BandarPhase.MARKDOWN

    # MARKUP: score tinggi + OBV naik + harga naik
    if bandar_score >= 65 and obv_trend == "UP" and price_change_pct > 0:
        return BandarPhase.MARKUP

    # REACCUMULATION: score turun sedikit + OBV flat + harga sideways
    if -10 <= score_delta <= -3 and obv_trend == "FLAT" and abs(price_change_pct) < 1.0:
        return BandarPhase.REACCUMULATION

    # ACCUMULATION: score >= 55 + OBV naik/flat
    if bandar_score >= 55 and obv_trend in ("UP", "FLAT"):
        return BandarPhase.ACCUMULATION

    return BandarPhase.UNKNOWN


# ─────────────────────────────────────────────
# ENGINE 2 — VOLUME INTELLIGENCE (OBV + A/D)
# ─────────────────────────────────────────────

def _calculate_obv_trend(
    closes: list[float],
    volumes: list[int],
) -> str:
    """
    Hitung OBV dan tentukan tren: UP / FLAT / DOWN
    Minimal 5 candle dibutuhkan.
    """
    if len(closes) < 5 or len(volumes) < 5:
        return "FLAT"

    obv = 0.0
    obv_values = []
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
        obv_values.append(obv)

    if len(obv_values) < 3:
        return "FLAT"

    recent  = sum(obv_values[-3:]) / 3
    earlier = sum(obv_values[-6:-3]) / 3 if len(obv_values) >= 6 else obv_values[0]

    if recent > earlier * 1.05:
        return "UP"
    elif recent < earlier * 0.95:
        return "DOWN"
    return "FLAT"


def _calculate_ad_trend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int],
) -> str:
    """
    Hitung Accumulation/Distribution line trend.
    """
    if len(closes) < 5:
        return "FLAT"

    ad = 0.0
    ad_values = []
    for i in range(len(closes)):
        hl_range = highs[i] - lows[i]
        if hl_range == 0:
            clv = 0
        else:
            clv = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl_range
        ad += clv * volumes[i]
        ad_values.append(ad)

    if len(ad_values) < 3:
        return "FLAT"

    recent  = ad_values[-1]
    earlier = ad_values[-4] if len(ad_values) >= 4 else ad_values[0]

    if recent > earlier * 1.02:
        return "UP"
    elif recent < earlier * 0.98:
        return "DOWN"
    return "FLAT"


# ─────────────────────────────────────────────
# ENGINE 3 — FLOW MAPPING (Institutional Flow)
# ─────────────────────────────────────────────

def _map_institutional_flow(
    obv_trend: str,
    ad_trend: str,
    net_foreign_lot: int,
    bandar_score: float,
) -> str:
    """
    Mapping institutional flow: ACCUMULATING / NEUTRAL / DISTRIBUTING
    """
    bull_signals = 0
    bear_signals = 0

    if obv_trend == "UP":
        bull_signals += 1
    elif obv_trend == "DOWN":
        bear_signals += 1

    if ad_trend == "UP":
        bull_signals += 1
    elif ad_trend == "DOWN":
        bear_signals += 1

    if net_foreign_lot > 100_000:
        bull_signals += 1
    elif net_foreign_lot < -100_000:
        bear_signals += 1

    if bandar_score >= 65:
        bull_signals += 1
    elif bandar_score < 45:
        bear_signals += 1

    if bull_signals >= 3:
        return "ACCUMULATING"
    elif bear_signals >= 3:
        return "DISTRIBUTING"
    return "NEUTRAL"


# ─────────────────────────────────────────────
# ENGINE 4 — FOREIGN FLOW
# ─────────────────────────────────────────────

def _assess_foreign_flow(net_foreign_lot: int) -> str:
    """Simplified foreign flow assessment"""
    if net_foreign_lot > 500_000:
        return "STRONG_BUY"
    elif net_foreign_lot > 100_000:
        return "BUY"
    elif net_foreign_lot < -500_000:
        return "STRONG_SELL"
    elif net_foreign_lot < -100_000:
        return "SELL"
    return "NEUTRAL"


# ─────────────────────────────────────────────
# ENGINE 5 — INVENTORY CYCLE
# ─────────────────────────────────────────────

def _assess_inventory(
    bandar_score: float,
    obv_trend: str,
    score_delta: float,
) -> str:
    """
    Posisi inventory cycle: ACCUMULATION / NEUTRAL / DISTRIBUTION
    """
    if bandar_score >= 65 and obv_trend in ("UP", "FLAT") and score_delta >= -5:
        return "ACCUMULATION"
    elif bandar_score < 50 or (score_delta < -10 and obv_trend == "DOWN"):
        return "DISTRIBUTION"
    return "NEUTRAL"


# ─────────────────────────────────────────────
# DISTRIBUTION SIGNAL DETECTOR
# ─────────────────────────────────────────────

def _detect_distribution_signals(
    current_high:   float,
    prev_high:      float,
    current_close:  float,
    current_volume: int,
    avg_volume:     float,
    price_change_pct: float,
    volume_history: list[int],
    resistance_price: Optional[float],
) -> DistributionSignal:
    """
    Deteksi 4 sinyal distribusi kritis IDX.
    """
    signals = DistributionSignal()

    # 1. UPTHRUST: new high + volume sangat tinggi + close di bawah high
    if (current_high > prev_high
            and current_volume > avg_volume * UPTHRUST_VOLUME_MULTIPLIER
            and current_close < current_high * 0.995):
        signals.upthrust = True

    # 2. NO DEMAND: volume sangat rendah saat harga coba naik
    if (price_change_pct > 0
            and current_volume < avg_volume * NO_DEMAND_VOLUME_MULTIPLIER):
        signals.no_demand = True

    # 3. EFFORT VS RESULT: volume besar + harga flat
    if (current_volume > avg_volume * EFFORT_VOLUME_MULTIPLIER
            and abs(price_change_pct) < EFFORT_PRICE_THRESHOLD):
        signals.effort_vs_result = True

    # 4. TOP VOLUME: volume tertinggi 20 hari di resistance
    if (resistance_price is not None
            and volume_history
            and len(volume_history) >= TOP_VOLUME_LOOKBACK):
        is_top_volume = current_volume >= max(volume_history[-TOP_VOLUME_LOOKBACK:])
        near_resistance = abs(current_close - resistance_price) / resistance_price < 0.02
        if is_top_volume and near_resistance:
            signals.top_volume = True

    signals.count = sum([
        signals.upthrust,
        signals.no_demand,
        signals.effort_vs_result,
        signals.top_volume,
    ])

    return signals


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def run_bandarmologi_monitor(
    ticker:           str,
    current_score:    float,
    entry_score:      float,
    net_foreign_lot:  int,
    closes:           list[float],
    highs:            list[float],
    lows:             list[float],
    volumes:          list[int],
    avg_volume:       float,
    price_change_pct: float,
    resistance_price: Optional[float] = None,
    prev_phase:       Optional[str]   = None,
) -> BandarmologiMonitorResult:
    """
    Jalankan 5 engine subset bandarmologi monitor.

    Parameters
    ----------
    ticker           : kode saham
    current_score    : bandar_score poll sekarang
    entry_score      : bandar_score saat entry posisi
    net_foreign_lot  : net foreign buy/sell (lot)
    closes           : list harga close (min 10 candle)
    highs            : list harga high
    lows             : list harga low
    volumes          : list volume (lot)
    avg_volume       : rata-rata volume 20 hari
    price_change_pct : % perubahan harga dari prev close
    resistance_price : level resistance terdekat (opsional)
    prev_phase       : fase sebelumnya untuk deteksi perubahan
    """
    try:
        score_delta = current_score - entry_score

        # Engine 2: OBV + A/D
        obv_trend = _calculate_obv_trend(closes, volumes)
        ad_trend  = _calculate_ad_trend(highs, lows, closes, volumes)

        # Engine 1: Fase
        current_phase = _detect_phase(
            current_score, score_delta, obv_trend,
            net_foreign_lot, price_change_pct
        )

        phase_changed = (
            prev_phase is not None
            and prev_phase != current_phase.value
        )

        # Engine 3: Flow mapping
        institutional_flow = _map_institutional_flow(
            obv_trend, ad_trend, net_foreign_lot, current_score
        )

        # Engine 4: Foreign flow (used in phase detection already)

        # Engine 5: Inventory
        inventory_position = _assess_inventory(
            current_score, obv_trend, score_delta
        )

        # Distribution signals
        current_high  = highs[-1]  if highs   else 0.0
        prev_high     = highs[-2]  if len(highs) >= 2 else current_high
        current_close = closes[-1] if closes  else 0.0

        dist_signals = _detect_distribution_signals(
            current_high    = current_high,
            prev_high       = prev_high,
            current_close   = current_close,
            current_volume  = volumes[-1] if volumes else 0,
            avg_volume      = avg_volume,
            price_change_pct= price_change_pct,
            volume_history  = volumes,
            resistance_price= resistance_price,
        )

        distribution_detected = (
            dist_signals.count >= 2
            or current_phase == BandarPhase.DISTRIBUTION
        )

        # Status message
        if distribution_detected:
            status_message = "⚠️ DISTRIBUSI TERDETEKSI — pertimbangkan exit"
        elif current_phase == BandarPhase.MARKUP:
            status_message = "✅ BANDAR MASIH BERSAMA KITA — markup aktif"
        elif current_phase == BandarPhase.REACCUMULATION:
            status_message = "🔄 REACCUMULATION — hold, monitor ketat"
        elif current_phase == BandarPhase.ACCUMULATION:
            status_message = "📦 AKUMULASI — posisi aman"
        else:
            status_message = "⚠️ FASE TIDAK JELAS — waspadai perubahan"

        # RAG trigger
        rag_triggered = (
            distribution_detected
            or phase_changed
            or current_phase == BandarPhase.UNKNOWN
        )

        return BandarmologiMonitorResult(
            current_score         = round(current_score, 1),
            score_delta           = round(score_delta, 1),
            current_phase         = current_phase,
            phase_changed         = phase_changed,
            distribution_detected = distribution_detected,
            distribution_signals  = dist_signals,
            obv_trend             = obv_trend,
            ad_line_trend         = ad_trend,
            institutional_flow    = institutional_flow,
            net_foreign_lot       = net_foreign_lot,
            inventory_position    = inventory_position,
            rag_triggered         = rag_triggered,
            status_message        = status_message,
        )

    except Exception as e:
        logger.error(f"BandarmologiMonitor error [{ticker}]: {e}")
        return BandarmologiMonitorResult(
            current_score         = current_score,
            score_delta           = 0.0,
            current_phase         = BandarPhase.UNKNOWN,
            distribution_signals  = DistributionSignal(),
            rag_triggered         = True,
            status_message        = f"Error: {str(e)}",
        )
