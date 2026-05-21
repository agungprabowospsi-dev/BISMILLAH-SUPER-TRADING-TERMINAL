"""
Engine 3 — Bandar Type Classifier
Path: backend/app/api/monitoring_enhancement/bandar_type_classifier.py

Identifikasi tipe bandar:
- INSTITUTIONAL : lot besar tersebar, jam 09-10 & 15-15:30, price impact kecil, LQ45
- FOREIGN       : net foreign buy > 500K lot, korelasi USD/IDR, MSCI driven
- RETAIL_BIG    : lot besar sekaligus, jam random, price impact besar, saham kecil
- RETAIL_CROWD  : banyak lot kecil, sosmed driven, spread melebar, pump pattern
"""

import logging
from datetime import datetime
from typing import Optional

from .models import (
    BandarType, BandarTypeResult, BandarTypeSignal, RAGTrigger
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# KONSTANTA SCORING
# ─────────────────────────────────────────────

# Bobot per sinyal per tipe bandar
INSTITUTIONAL_WEIGHTS = {
    "large_lot_spread":  30,
    "peak_hour_trading": 25,
    "low_price_impact":  25,
    "lq45_member":       20,
}

FOREIGN_WEIGHTS = {
    "net_foreign_buy_500k": 40,   # net foreign > 500K lot
    "net_foreign_buy_100k": 20,   # net foreign > 100K lot (partial)
    "usd_idr_corr_high":    30,   # |korelasi| > 0.6
    "lq45_member":          10,
}

RETAIL_BIG_WEIGHTS = {
    "single_large_lot":  35,
    "random_hour":       25,
    "high_price_impact": 25,
    "small_cap":         15,
}

RETAIL_CROWD_WEIGHTS = {
    "many_small_lots":   35,
    "social_media_spike": 25,
    "spread_widening":   25,
    "pump_pattern":      15,
}

# Market cap estimasi dalam miliar Rupiah (update berkala)
MARKET_CAP_BILLION = {
    "BBCA": 900000, "BBRI": 600000, "BMRI": 550000, "BBNI": 200000,
    "TLKM": 250000, "ASII": 180000, "UNVR": 150000, "ICBP": 120000,
    "INDF": 80000,  "KLBF": 70000,  "HMSP": 90000,  "GGRM": 60000,
    "PGAS": 50000,  "PTBA": 40000,  "ANTM": 35000,  "INCO": 45000,
    "ADRO": 80000,  "ITMG": 30000,  "SMGR": 25000,  "WIKA": 15000,
    "BSDE": 20000,  "CTRA": 18000,  "JSMR": 35000,  "TOWR": 40000,
    "MDKA": 55000,  "ESSA": 20000,  "GOTO": 70000,  "BYAN": 120000,
}

# LQ45 list (subset representatif — update berkala)
LQ45_TICKERS = {
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP",
    "INDF", "KLBF", "HMSP", "GGRM", "PGAS", "PTBA", "ANTM", "INCO",
    "ADRO", "ITMG", "SMGR", "WIKA", "WSKT", "PTPP", "JSMR", "BSDE",
    "CTRA", "PWON", "LPKR", "MNCN", "EMTK", "SCMA", "TOWR", "EXCL",
    "ISAT", "AKRA", "UNTR", "AALI", "LSIP", "MAPI", "ACES", "ERAA",
    "SIDO", "HEAL", "MIKA", "MDKA", "ESSA"
}


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def _is_peak_hour() -> bool:
    """Cek apakah sekarang jam peak institutional IDX"""
    now = datetime.now()
    hour, minute = now.hour, now.minute
    time_val = hour * 100 + minute
    # 09:00-10:00 atau 15:00-15:30
    return (900 <= time_val <= 1000) or (1500 <= time_val <= 1530)


def _classify_lot_pattern(
    avg_lot_size: float,
    lot_count: int,
    total_volume: int
) -> dict:
    """
    Analisis pola lot dari data transaksi.
    avg_lot_size : rata-rata ukuran lot per transaksi
    lot_count    : jumlah transaksi
    total_volume : total volume hari ini (lot)
    """
    result = {
        "large_lot_spread": False,
        "single_large_lot": False,
        "many_small_lots": False,
    }

    if avg_lot_size >= 500 and lot_count >= 20:
        # Lot besar tersebar = INSTITUTIONAL
        result["large_lot_spread"] = True
    elif avg_lot_size >= 500 and lot_count < 10:
        # Lot besar sekaligus = RETAIL_BIG
        result["single_large_lot"] = True
    elif avg_lot_size < 50 and lot_count >= 100:
        # Banyak lot kecil = RETAIL_CROWD
        result["many_small_lots"] = True

    return result


def _detect_pump_pattern(
    price_changes: list[float],
    volume_changes: list[float]
) -> bool:
    """
    Deteksi pump pattern:
    - Harga naik > 5% dalam 3 hari
    - Volume spike > 3x rata-rata
    """
    if len(price_changes) < 3 or len(volume_changes) < 3:
        return False

    recent_price_change = sum(price_changes[-3:])
    avg_vol = sum(volume_changes[:-3]) / max(len(volume_changes[:-3]), 1)
    recent_vol = volume_changes[-1]

    return recent_price_change > 5.0 and recent_vol > avg_vol * 3


def _calculate_price_impact(
    volume: int,
    price_change_pct: float,
    market_cap_billion: Optional[float]
) -> str:
    """
    Estimasi price impact relatif volume.
    Return: "LOW" / "HIGH"
    """
    if market_cap_billion is None or market_cap_billion <= 0:
        return "HIGH"

    # Impact = % perubahan harga / (volume / market_cap)
    volume_ratio = volume / (market_cap_billion * 1_000_000_000 / 100)
    if volume_ratio <= 0:
        return "HIGH"

    impact_score = abs(price_change_pct) / volume_ratio
    return "LOW" if impact_score < 2.0 else "HIGH"


# ─────────────────────────────────────────────
# MAIN CLASSIFIER
# ─────────────────────────────────────────────

def classify_bandar_type(
    ticker: str,
    net_foreign_lot: int,
    usd_idr_correlation: Optional[float],
    avg_lot_size: float,
    lot_count: int,
    total_volume: int,
    price_change_pct: float,
    market_cap_billion: Optional[float],
    spread_pct: float,
    price_changes_3d: Optional[list[float]] = None,
    volume_changes_3d: Optional[list[float]] = None,
) -> BandarTypeResult:
    """
    Klasifikasi tipe bandar berdasarkan karakteristik market microstructure.

    Parameters
    ----------
    ticker              : kode saham
    net_foreign_lot     : net foreign buy/sell dalam lot (+ = buy)
    usd_idr_correlation : korelasi harga saham vs USD/IDR (-1 to 1)
    avg_lot_size        : rata-rata ukuran lot per transaksi hari ini
    lot_count           : jumlah transaksi hari ini
    total_volume        : total volume hari ini (lot)
    price_change_pct    : % perubahan harga dari prev close
    market_cap_billion  : market cap dalam miliar Rupiah
    spread_pct          : bid-ask spread dalam %
    price_changes_3d    : list % perubahan harga 3 hari terakhir
    volume_changes_3d   : list volume 3 hari terakhir
    """

    try:
        ticker_upper = ticker.upper()
        is_lq45 = ticker_upper in LQ45_TICKERS
        is_peak = _is_peak_hour()

        # Gunakan market cap dari lookup table kalau tidak dipass
        if market_cap_billion is None or market_cap_billion <= 0:
            market_cap_billion = MARKET_CAP_BILLION.get(ticker_upper, None)

        price_impact = _calculate_price_impact(
            total_volume, price_change_pct, market_cap_billion
        )

        lot_pattern = _classify_lot_pattern(avg_lot_size, lot_count, total_volume)

        # Pump pattern
        pump = False
        if price_changes_3d and volume_changes_3d:
            pump = _detect_pump_pattern(price_changes_3d, volume_changes_3d)

        # Spread widening: > 1% dianggap melebar
        spread_wide = spread_pct > 1.0

        # Social media spike proxy: volume spike + saham kecil + spread lebar
        social_spike = (
            not is_lq45
            and lot_pattern["many_small_lots"]
            and spread_wide
        )

        # ── Build signals ──
        signals = BandarTypeSignal(
            large_lot_spread   = lot_pattern["large_lot_spread"],
            peak_hour_trading  = is_peak,
            low_price_impact   = price_impact == "LOW",
            lq45_member        = is_lq45,
            net_foreign_buy    = net_foreign_lot,
            usd_idr_corr       = usd_idr_correlation,
            single_large_lot   = lot_pattern["single_large_lot"],
            random_hour        = not is_peak,
            high_price_impact  = price_impact == "HIGH",
            small_cap          = (market_cap_billion or 0) < 1_000,
            many_small_lots    = lot_pattern["many_small_lots"],
            social_media_spike = social_spike,
            spread_widening    = spread_wide,
            pump_pattern       = pump,
        )

        # ── Score per tipe ──
        score_institutional = 0
        if signals.large_lot_spread:
            score_institutional += INSTITUTIONAL_WEIGHTS["large_lot_spread"]
        if signals.peak_hour_trading:
            score_institutional += INSTITUTIONAL_WEIGHTS["peak_hour_trading"]
        if signals.low_price_impact:
            score_institutional += INSTITUTIONAL_WEIGHTS["low_price_impact"]
        if signals.lq45_member:
            score_institutional += INSTITUTIONAL_WEIGHTS["lq45_member"]

        score_foreign = 0
        if net_foreign_lot > 500_000:
            score_foreign += FOREIGN_WEIGHTS["net_foreign_buy_500k"]
        elif net_foreign_lot > 100_000:
            score_foreign += FOREIGN_WEIGHTS["net_foreign_buy_100k"]
        if usd_idr_correlation and abs(usd_idr_correlation) > 0.6:
            score_foreign += FOREIGN_WEIGHTS["usd_idr_corr_high"]
        if signals.lq45_member:
            score_foreign += FOREIGN_WEIGHTS["lq45_member"]

        score_retail_big = 0
        if signals.single_large_lot:
            score_retail_big += RETAIL_BIG_WEIGHTS["single_large_lot"]
        if signals.random_hour:
            score_retail_big += RETAIL_BIG_WEIGHTS["random_hour"]
        if signals.high_price_impact:
            score_retail_big += RETAIL_BIG_WEIGHTS["high_price_impact"]
        if signals.small_cap:
            score_retail_big += RETAIL_BIG_WEIGHTS["small_cap"]

        score_retail_crowd = 0
        if signals.many_small_lots:
            score_retail_crowd += RETAIL_CROWD_WEIGHTS["many_small_lots"]
        if signals.social_media_spike:
            score_retail_crowd += RETAIL_CROWD_WEIGHTS["social_media_spike"]
        if signals.spread_widening:
            score_retail_crowd += RETAIL_CROWD_WEIGHTS["spread_widening"]
        if signals.pump_pattern:
            score_retail_crowd += RETAIL_CROWD_WEIGHTS["pump_pattern"]

        score_breakdown = {
            "INSTITUTIONAL": score_institutional,
            "FOREIGN":       score_foreign,
            "RETAIL_BIG":    score_retail_big,
            "RETAIL_CROWD":  score_retail_crowd,
        }

        # ── Determine winner ──
        max_score = max(score_breakdown.values())
        total_possible = 100

        if max_score < 20:
            bandar_type = BandarType.UNCLEAR
            confidence = 0.0
        else:
            # Tie-breaking: LQ45 besar dengan large_lot_spread = INSTITUTIONAL
            inst_score = score_breakdown["INSTITUTIONAL"]
            rb_score   = score_breakdown["RETAIL_BIG"]
            if inst_score == rb_score and signals.lq45_member and signals.large_lot_spread:
                winner = "INSTITUTIONAL"
            else:
                winner = max(score_breakdown, key=score_breakdown.get)
            bandar_type = BandarType(winner)
            confidence = round((max_score / total_possible) * 100, 1)
            confidence = min(confidence, 99.0)

        # RAG trigger kalau confidence < 50%
        rag_triggered = confidence < 50.0

        return BandarTypeResult(
            bandar_type     = bandar_type,
            confidence      = confidence,
            signals         = signals,
            net_foreign_lot = net_foreign_lot,
            score_breakdown = score_breakdown,
            rag_triggered   = rag_triggered,
        )

    except Exception as e:
        logger.error(f"BandarTypeClassifier error [{ticker}]: {e}")
        return BandarTypeResult(
            bandar_type     = BandarType.UNCLEAR,
            confidence      = 0.0,
            signals         = BandarTypeSignal(),
            net_foreign_lot = 0,
            score_breakdown = {},
            rag_triggered   = True,
        )
