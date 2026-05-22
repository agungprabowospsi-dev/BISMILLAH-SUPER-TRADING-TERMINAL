"""
Dynamic SL/TP Adaptive — ML Engine #3
SL/TP berdasarkan volatility + regime + score + KB
Bukan fixed ATR multiplier
"""
import numpy as np
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def calculate_dynamic_sltp(
    entry_price: float,
    ohlcv: List[Dict],
    market_regime: str = 'SIDEWAYS',
    final_score: float = 50.0,
    mode: str = 'swing',
    akumulasi_score: float = 50.0,
) -> Dict[str, Any]:
    """
    Hitung SL/TP dinamis berdasarkan:
    1. ATR adaptif (volatility)
    2. Market regime (bull/bear/sideways)
    3. Engine score (signal quality)
    4. Mode trading (swing/intraday/scalping)
    5. Akumulasi score (bandar confidence)
    """
    if not ohlcv or len(ohlcv) < 14:
        return _fallback_sltp(entry_price, mode)

    # 1. Hitung ATR 14
    atr = _calc_atr(ohlcv, period=14)
    atr_pct = (atr / entry_price) * 100 if entry_price > 0 else 2.0

    # 2. Regime multiplier
    regime_multipliers = {
        'STRONG BULL': {'sl': 0.8, 'tp': 1.4},
        'BULL':        {'sl': 0.9, 'tp': 1.2},
        'SIDEWAYS':    {'sl': 1.0, 'tp': 1.0},
        'BEAR':        {'sl': 1.2, 'tp': 0.8},
        'STRONG BEAR': {'sl': 1.4, 'tp': 0.7},
    }
    rm = regime_multipliers.get(market_regime, regime_multipliers['SIDEWAYS'])

    # 3. Score multiplier — makin tinggi score, SL lebih ketat, TP lebih jauh
    score_factor = final_score / 100.0
    sl_score_adj = 1.0 - (score_factor - 0.5) * 0.3
    tp_score_adj = 1.0 + (score_factor - 0.5) * 0.5

    # 4. Mode base multiplier
    # FIX-5: intraday TP diperkecil — realistis untuk IDX range harian 1-2%
    # intraday pakai ATR fraction (1/3 daily) via atr_fraction
    atr_fraction = 1.0 / 3.0 if mode == 'intraday' else 1.0
    atr = atr * atr_fraction  # Scale ATR untuk intraday

    mode_base = {
        'swing':    {'sl': 2.0, 'tp1': 2.5, 'tp2': 4.0, 'tp3': 6.0},  # SW-3: TP diperbesar IDX swing
        'intraday': {'sl': 1.0, 'tp1': 1.0, 'tp2': 1.8, 'tp3': 2.8},  # FIX-5: TP realistis IDX
        'scalping': {'sl': 0.7, 'tp1': 0.7, 'tp2': 1.2, 'tp3': 1.8},
    }
    mb = mode_base.get(mode, mode_base['swing'])

    # 5. Akumulasi bonus — kalau bandar kuat, TP bisa lebih jauh
    akum_factor = akumulasi_score / 100.0
    akum_tp_bonus = 1.0 + (akum_factor - 0.5) * 0.3

    # Hitung SL
    sl_atr = atr * mb['sl'] * rm['sl'] * sl_score_adj
    sl_price = round(entry_price - sl_atr, 0)

    # Hitung TP1, TP2, TP3
    tp1_atr = atr * mb['tp1'] * rm['tp'] * tp_score_adj * akum_tp_bonus
    tp2_atr = atr * mb['tp2'] * rm['tp'] * tp_score_adj * akum_tp_bonus
    tp3_atr = atr * mb['tp3'] * rm['tp'] * tp_score_adj * akum_tp_bonus

    tp1 = round(entry_price + tp1_atr, 0)
    tp2 = round(entry_price + tp2_atr, 0)
    tp3 = round(entry_price + tp3_atr, 0)

    # Risk/Reward
    risk = entry_price - sl_price
    rr1 = round((tp1 - entry_price) / risk, 2) if risk > 0 else 0
    rr2 = round((tp2 - entry_price) / risk, 2) if risk > 0 else 0
    rr3 = round((tp3 - entry_price) / risk, 2) if risk > 0 else 0

    return {
        "sl": sl_price,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "rr1": rr1,
        "rr2": rr2,
        "rr3": rr3,
        "method": "Dynamic ATR + Regime + Score",
        "regime": market_regime,
        "regime_sl_mult": rm['sl'],
        "regime_tp_mult": rm['tp'],
        "score_adj": round(score_factor, 2),
        "akum_bonus": round(akum_tp_bonus, 2),
    }

def _calc_atr(ohlcv: List[Dict], period: int = 14) -> float:
    """Hitung Average True Range"""
    if len(ohlcv) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(ohlcv)):
        high = float(ohlcv[i].get('high', 0) or 0)
        low = float(ohlcv[i].get('low', 0) or 0)
        prev_close = float(ohlcv[i-1].get('close', 0) or 0)
        if high <= 0 or low <= 0 or prev_close <= 0:
            continue
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    return sum(true_ranges[-period:]) / period

def _fallback_sltp(entry_price: float, mode: str) -> Dict[str, Any]:
    """Fallback ke fixed % kalau tidak ada data"""
    pcts = {
        'swing':    {'sl': 0.05, 'tp1': 0.08, 'tp2': 0.13, 'tp3': 0.20},
        'intraday': {'sl': 0.02, 'tp1': 0.03, 'tp2': 0.05, 'tp3': 0.08},
        'scalping': {'sl': 0.01, 'tp1': 0.015,'tp2': 0.025,'tp3': 0.04},
    }
    p = pcts.get(mode, pcts['swing'])
    return {
        "sl":  round(entry_price * (1 - p['sl']), 0),
        "tp1": round(entry_price * (1 + p['tp1']), 0),
        "tp2": round(entry_price * (1 + p['tp2']), 0),
        "tp3": round(entry_price * (1 + p['tp3']), 0),
        "method": "Fixed % fallback",
        "atr": 0,
        "atr_pct": 0,
    }
