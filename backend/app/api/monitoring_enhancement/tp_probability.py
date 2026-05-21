"""
Engine 7 — TP Probability Calculator
Path: backend/app/api/monitoring_enhancement/tp_probability.py

Multiplier stack:
- Bandar Type     : INSTITUTIONAL x1.30 / FOREIGN x1.20 / RETAIL_BIG x0.90 / RETAIL_CROWD x0.60
- Momentum        : VERY_STRONG x1.25 / EXHAUSTED x0.50
- Retest          : NORMAL_RETEST x1.20 / REVERSAL_CONFIRMED x0.30
- Enrichment      : PROCEED x1.10 / SKIP x0.60
- VWAP deviation  : khusus DAYTRADING
- Orderbook       : khusus SCALPING
"""

import logging
from typing import Optional

from .models import (
    BandarType, MomentumLabel, RetestVerdict,
    EnrichmentVerdict, FinalAction, TPProbResult
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# MULTIPLIER TABLES
# ─────────────────────────────────────────────

BANDAR_MULTIPLIER = {
    BandarType.INSTITUTIONAL: 1.30,
    BandarType.FOREIGN:       1.20,
    BandarType.RETAIL_BIG:    0.90,
    BandarType.RETAIL_CROWD:  0.60,
    BandarType.UNCLEAR:       0.85,
}

MOMENTUM_MULTIPLIER = {
    MomentumLabel.VERY_STRONG: 1.25,
    MomentumLabel.STRONG:      1.10,
    MomentumLabel.MODERATE:    1.00,
    MomentumLabel.WEAK:        0.75,
    MomentumLabel.EXHAUSTED:   0.50,
}

RETEST_MULTIPLIER = {
    RetestVerdict.STRONG_HOLD: 1.20,
    RetestVerdict.HOLD:        1.00,
    RetestVerdict.REDUCE_50:   0.65,
    RetestVerdict.EXIT_ALL:    0.30,
}

ENRICHMENT_MULTIPLIER = {
    EnrichmentVerdict.PROCEED: 1.10,
    EnrichmentVerdict.CAUTION: 0.90,
    EnrichmentVerdict.SKIP:    0.60,
}

# Base probability per TP level
BASE_PROB = {
    "tp1": 65.0,
    "tp2": 40.0,
    "tp3": 20.0,
}

# TP decay factor (tp2 lebih susah dari tp1, tp3 lebih susah dari tp2)
TP_DECAY = {
    "tp1": 1.00,
    "tp2": 0.70,
    "tp3": 0.45,
}


# ─────────────────────────────────────────────
# HELPER — VWAP DEVIATION (DAYTRADING)
# ─────────────────────────────────────────────

def _vwap_multiplier(last_price: float, vwap: float) -> tuple:
    """
    Hitung multiplier dari VWAP deviation.
    Harga di bawah VWAP = momentum lemah untuk long.
    Return: (multiplier, description)
    """
    if vwap <= 0:
        return 1.0, "VWAP_NA"

    dev_pct = ((last_price - vwap) / vwap) * 100

    if dev_pct >= 1.5:
        return 1.15, f"ABOVE_VWAP+{dev_pct:.1f}%"
    elif dev_pct >= 0.5:
        return 1.08, f"ABOVE_VWAP+{dev_pct:.1f}%"
    elif dev_pct >= -0.5:
        return 1.00, "AT_VWAP"
    elif dev_pct >= -1.5:
        return 0.88, f"BELOW_VWAP{dev_pct:.1f}%"
    else:
        return 0.75, f"BELOW_VWAP{dev_pct:.1f}%"


# ─────────────────────────────────────────────
# HELPER — ORDERBOOK IMBALANCE (SCALPING)
# ─────────────────────────────────────────────

def _orderbook_multiplier(imbalance: float) -> tuple:
    """
    Hitung multiplier dari bid/ask imbalance.
    imbalance = bid_lot / offer_lot
    > 1 = tekanan beli, < 1 = tekanan jual
    Return: (multiplier, description)
    """
    if imbalance >= 2.0:
        return 1.20, f"STRONG_BID_PRESSURE_{imbalance:.2f}x"
    elif imbalance >= 1.3:
        return 1.10, f"BID_PRESSURE_{imbalance:.2f}x"
    elif imbalance >= 0.7:
        return 1.00, f"BALANCED_{imbalance:.2f}x"
    elif imbalance >= 0.4:
        return 0.85, f"OFFER_PRESSURE_{imbalance:.2f}x"
    else:
        return 0.65, f"STRONG_OFFER_PRESSURE_{imbalance:.2f}x"


# ─────────────────────────────────────────────
# HELPER — EXPECTED VALUE
# ─────────────────────────────────────────────

def _calc_expected_value(
    entry_price: float,
    sl_price:    float,
    tp1_price:   float,
    tp2_price:   float,
    tp3_price:   float,
    prob_tp1:    float,
    prob_tp2:    float,
    prob_tp3:    float,
    lots:        int = 10,
) -> float:
    """
    Hitung expected value dalam Rupiah per N lot.
    EV = (prob_tp1 * gain_tp1) + (prob_tp2 * gain_tp2) + (prob_tp3 * gain_tp3)
       - (prob_loss * loss_sl)
    IDX: 1 lot = 100 lembar
    """
    lot_size    = 100
    prob_loss   = max(0.0, 1.0 - (prob_tp1 / 100))

    gain_tp1 = (tp1_price - entry_price) * lots * lot_size
    gain_tp2 = (tp2_price - entry_price) * lots * lot_size
    gain_tp3 = (tp3_price - entry_price) * lots * lot_size
    loss_sl  = (entry_price - sl_price)  * lots * lot_size

    ev = (
        (prob_tp1 / 100 * gain_tp1) +
        (prob_tp2 / 100 * gain_tp2) +
        (prob_tp3 / 100 * gain_tp3) -
        (prob_loss * loss_sl)
    )
    return round(ev, 0)


# ─────────────────────────────────────────────
# HELPER — FINAL RECOMMENDATION
# ─────────────────────────────────────────────

def _determine_action(
    bandar_type:    BandarType,
    momentum_label: MomentumLabel,
    retest_verdict: RetestVerdict,
    prob_tp1:       float,
    prob_tp2:       float,
    distribution:   bool,
    sl_hit:         bool,
) -> FinalAction:
    """
    Tentukan action final berdasarkan semua kondisi.
    Sesuai logic di Master Doc REV22 Section 5.8.
    """
    # EXIT_ALL
    if sl_hit:
        return FinalAction.EXIT_ALL
    if retest_verdict == RetestVerdict.EXIT_ALL:
        return FinalAction.EXIT_ALL
    if distribution and momentum_label in (MomentumLabel.WEAK, MomentumLabel.EXHAUSTED):
        return FinalAction.EXIT_ALL

    # REDUCE_50
    if retest_verdict == RetestVerdict.REDUCE_50:
        return FinalAction.REDUCE_50
    if distribution:
        return FinalAction.REDUCE_50
    if momentum_label == MomentumLabel.WEAK:
        return FinalAction.REDUCE_50

    # HOLD_TP2
    if (bandar_type in (BandarType.INSTITUTIONAL, BandarType.FOREIGN)
            and momentum_label in (MomentumLabel.VERY_STRONG, MomentumLabel.STRONG)
            and retest_verdict in (RetestVerdict.STRONG_HOLD, RetestVerdict.HOLD)
            and prob_tp2 >= 45.0):
        return FinalAction.HOLD_TP2

    # HOLD_TP1
    if (bandar_type != BandarType.RETAIL_CROWD
            and momentum_label != MomentumLabel.EXHAUSTED
            and prob_tp1 >= 50.0):
        return FinalAction.HOLD_TP1

    return FinalAction.REDUCE_50


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def calculate_tp_probability(
    ticker:          str,
    trade_mode:      str,
    entry_price:     float,
    sl_price:        float,
    tp1_price:       float,
    tp2_price:       float,
    tp3_price:       float,
    last_price:      float,
    bandar_type:     BandarType,
    momentum_label:  MomentumLabel,
    retest_verdict:  RetestVerdict,
    enrichment_verdict: EnrichmentVerdict,
    distribution_detected: bool       = False,
    sl_hit:          bool             = False,
    prev_prob_tp1:   Optional[float]  = None,
    vwap:            float            = 0.0,
    orderbook_imbalance: float        = 1.0,
    lots:            int              = 10,
    wyckoff_phase:   str              = "UNKNOWN",
    weinstein_stage: int              = 0,
    vsa_background:  str              = "NEUTRAL",
) -> TPProbResult:
    """
    Hitung probabilitas TP1/TP2/TP3 dengan multiplier stack.

    Parameters
    ----------
    ticker               : kode saham
    trade_mode           : SWING / DAYTRADING / SCALPING
    entry_price          : harga entry posisi
    sl_price             : stop loss price
    tp1/tp2/tp3_price    : target harga
    last_price           : harga terakhir
    bandar_type          : hasil Engine 3
    momentum_label       : hasil Engine 5
    retest_verdict       : hasil Engine 6
    enrichment_verdict   : hasil Enrichment REV21
    distribution_detected: hasil Engine 4
    sl_hit               : apakah SL sudah kena
    prev_prob_tp1        : prob_tp1 poll sebelumnya
    vwap                 : VWAP price (DAYTRADING)
    orderbook_imbalance  : bid/offer ratio (SCALPING)
    lots                 : jumlah lot untuk EV calculation
    """
    try:
        multiplier_stack = {}

        # ── Core multipliers ──
        m_bandar = BANDAR_MULTIPLIER.get(bandar_type, 0.85)
        multiplier_stack["bandar_type"] = m_bandar

        m_momentum = MOMENTUM_MULTIPLIER.get(momentum_label, 1.0)
        multiplier_stack["momentum"] = m_momentum

        m_retest = RETEST_MULTIPLIER.get(retest_verdict, 1.0)
        multiplier_stack["retest"] = m_retest

        m_enrichment = ENRICHMENT_MULTIPLIER.get(enrichment_verdict, 1.0)
        multiplier_stack["enrichment"] = m_enrichment

        # Distribution penalty
        m_distribution = 0.70 if distribution_detected else 1.0
        multiplier_stack["distribution"] = m_distribution

        # ── Phase 2 multipliers ──
        m_wyckoff = 1.0
        if wyckoff_phase in ("ACCUMULATION", "MARKUP", "REACCUMULATION"):
            m_wyckoff = 1.10
        elif wyckoff_phase in ("DISTRIBUTION", "MARKDOWN"):
            m_wyckoff = 0.75
        multiplier_stack["wyckoff"] = m_wyckoff

        m_weinstein = 1.0
        if weinstein_stage == 2:
            m_weinstein = 1.10
        elif weinstein_stage == 4:
            m_weinstein = 0.75
        elif weinstein_stage == 3:
            m_weinstein = 0.90
        multiplier_stack["weinstein"] = m_weinstein

        m_vsa = 1.0
        if vsa_background == "BULLISH":
            m_vsa = 1.05
        elif vsa_background == "BEARISH":
            m_vsa = 0.85
        multiplier_stack["vsa_background"] = m_vsa

        # ── Mode-specific multipliers ──
        m_vwap     = 1.0
        m_orderbook = 1.0

        if trade_mode == "DAYTRADING" and vwap > 0:
            m_vwap, vwap_desc = _vwap_multiplier(last_price, vwap)
            multiplier_stack["vwap"] = m_vwap
            multiplier_stack["vwap_desc"] = vwap_desc

        if trade_mode == "SCALPING":
            m_orderbook, ob_desc = _orderbook_multiplier(orderbook_imbalance)
            multiplier_stack["orderbook"] = m_orderbook
            multiplier_stack["orderbook_desc"] = ob_desc

        # ── Total multiplier ──
        total_multiplier = (
            m_bandar *
            m_momentum *
            m_retest *
            m_enrichment *
            m_distribution *
            m_vwap *
            m_orderbook *
            m_wyckoff *
            m_weinstein *
            m_vsa
        )
        multiplier_stack["total"] = round(total_multiplier, 4)

        # ── Calculate probabilities ──
        prob_tp1 = min(95.0, max(5.0,
            BASE_PROB["tp1"] * total_multiplier * TP_DECAY["tp1"]
        ))
        prob_tp2 = min(90.0, max(3.0,
            BASE_PROB["tp2"] * total_multiplier * TP_DECAY["tp2"]
        ))
        prob_tp3 = min(85.0, max(1.0,
            BASE_PROB["tp3"] * total_multiplier * TP_DECAY["tp3"]
        ))

        prob_tp1 = round(prob_tp1, 1)
        prob_tp2 = round(prob_tp2, 1)
        prob_tp3 = round(prob_tp3, 1)

        # ── Expected Value ──
        ev = _calc_expected_value(
            entry_price, sl_price,
            tp1_price, tp2_price, tp3_price,
            prob_tp1, prob_tp2, prob_tp3,
            lots,
        )

        # ── Prob drop dari poll sebelumnya ──
        prob_tp1_drop = 0.0
        if prev_prob_tp1 is not None:
            prob_tp1_drop = round(max(0.0, prev_prob_tp1 - prob_tp1), 1)

        # ── RAG trigger ──
        rag_triggered = prob_tp1_drop >= 20.0

        # ── Final action ──
        recommendation = _determine_action(
            bandar_type, momentum_label, retest_verdict,
            prob_tp1, prob_tp2, distribution_detected, sl_hit,
        )

        return TPProbResult(
            prob_tp1         = prob_tp1,
            prob_tp2         = prob_tp2,
            prob_tp3         = prob_tp3,
            expected_value   = ev,
            recommendation   = recommendation,
            multiplier_stack = multiplier_stack,
            prev_prob_tp1    = prev_prob_tp1,
            prob_tp1_drop    = prob_tp1_drop,
            tp1_price        = tp1_price,
            tp2_price        = tp2_price,
            tp3_price        = tp3_price,
            entry_price      = entry_price,
            rag_triggered    = rag_triggered,
        )

    except Exception as e:
        logger.error(f"TPProbability error [{ticker}]: {e}")
        return TPProbResult(
            prob_tp1         = 50.0,
            prob_tp2         = 30.0,
            prob_tp3         = 15.0,
            expected_value   = 0.0,
            recommendation   = FinalAction.HOLD_TP1,
            multiplier_stack = {},
            tp1_price        = tp1_price,
            tp2_price        = tp2_price,
            tp3_price        = tp3_price,
            entry_price      = entry_price,
            rag_triggered    = False,
        )
