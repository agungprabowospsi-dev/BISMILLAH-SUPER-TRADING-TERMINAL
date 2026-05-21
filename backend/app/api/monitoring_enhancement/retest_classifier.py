"""
Engine 6 — Retest Classifier (Full Version)
Path: backend/app/api/monitoring_enhancement/retest_classifier.py

5 Layer:
1. Fibonacci Boroden    — kalkulasi lokal
2. VSA Signal          — kalkulasi lokal
3. Bandar Context      — RAG 3 buku bandarmologi IDX
4. Chart Pattern       — RAG Bulkowski
5. Synthesis           — verdict final
"""

import logging
from typing import Optional

from app.api.enrichment.wyckoff_phase import classify_wyckoff
from app.api.enrichment.weinstein_stage import classify_weinstein
from app.api.enrichment.vsa_engine import analyze_vsa

from .models import (
    RetestClassification, RetestResult,
    BandarRetestType, PatternName, RetestVerdict
)

logger = logging.getLogger(__name__)

FIB_LEVELS = {
    "0.0":   0.000,
    "23.6":  0.236,
    "38.2":  0.382,
    "50.0":  0.500,
    "61.8":  0.618,
    "78.6":  0.786,
    "100.0": 1.000,
}

# Rate limit cache: {ticker: last_query_timestamp}
_rag_cache: dict = {}
RAG_COOLDOWN_SEC = 180  # 3 menit


def _find_swing_high(highs: list, lookback: int = 20) -> float:
    if not highs:
        return 0.0
    return max(highs[-lookback:])


def _find_swing_low(lows: list, lookback: int = 20) -> float:
    if not lows:
        return 0.0
    return min(lows[-lookback:])


def _calc_fib_prices(swing_high: float, swing_low: float) -> dict:
    diff = swing_high - swing_low
    return {
        label: round(swing_high - (diff * ratio), 2)
        for label, ratio in FIB_LEVELS.items()
    }


def _classify_fib(fib_pct: float) -> RetestClassification:
    if fib_pct <= 23.6:
        return RetestClassification.VERY_SHALLOW
    elif fib_pct <= 38.2:
        return RetestClassification.NORMAL_RETEST
    elif fib_pct <= 50.0:
        return RetestClassification.MEDIUM_RETEST
    elif fib_pct <= 61.8:
        return RetestClassification.DEEP_BUT_VALID
    elif fib_pct <= 78.6:
        return RetestClassification.REVERSAL_WARNING
    return RetestClassification.REVERSAL_CONFIRMED


def _detect_vsa(
    current_volume: int,
    avg_volume:     float,
    current_close:  float,
    current_low:    float,
    current_high:   float,
    price_change_pct: float,
) -> Optional[str]:
    vol_ratio   = current_volume / avg_volume if avg_volume > 0 else 1.0
    total_range = current_high - current_low
    lower_wick  = (current_close - current_low) if total_range > 0 else 0

    if vol_ratio >= 2.0 and abs(price_change_pct) < 1.0:
        return "ABSORPTION"
    elif vol_ratio < 0.6 and price_change_pct < 0:
        return "NO_SUPPLY"
    elif vol_ratio >= 3.0 and total_range > 0 and (lower_wick / total_range) > 0.6:
        return "SELLING_CLIMAX"
    return None


import time

async def _rag_bandar_context(
    ticker:       str,
    fib_pct:      float,
    vol_ratio:    float,
    bandar_phase: str,
    net_foreign:  int,
) -> tuple:
    """
    Layer 3 — Query RAG 3 buku bandarmologi IDX.
    Return: (bandar_retest_type, bandar_still_holding, kb_insight, confidence)
    """
    try:
        from app.core.knowledge_base import query_knowledge_base

        query = (
            f"retest pullback {fib_pct:.1f}% setelah fase {bandar_phase}, "
            f"volume pullback {vol_ratio:.2f}x rata-rata, "
            f"net foreign {net_foreign} lot. "
            f"Apakah ini retest normal bandar IDX, distribusi terselubung, atau parking?"
        )

        sources = [
            "file_1766768812634",
            "file_1766768868107",
            "E-Book Bandar Flow Secrets.pdf",
        ]

        result_text = await query_knowledge_base("bandarmologi", query, n_results=3)
        result = {"answer": result_text} if result_text else None






        if not result or not result.get("answer"):
            return BandarRetestType.UNCLEAR, False, None, 0.0

        answer = result["answer"].lower()

        # Parse jawaban RAG
        if any(w in answer for w in ["distribusi", "jual", "terselubung", "sell"]):
            retest_type   = BandarRetestType.DISTRIBUSI_TERSELUBUNG
            still_holding = False
            confidence    = 75.0
        elif any(w in answer for w in ["parking", "parkir", "hold support"]):
            retest_type   = BandarRetestType.PARKING
            still_holding = True
            confidence    = 80.0
        elif any(w in answer for w in ["normal", "akumulasi", "retest wajar", "hold"]):
            retest_type   = BandarRetestType.NORMAL_BANDAR_RETEST
            still_holding = True
            confidence    = 70.0
        else:
            retest_type   = BandarRetestType.UNCLEAR
            still_holding = False
            confidence    = 30.0

        return retest_type, still_holding, result["answer"][:300], confidence

    except Exception as e:
        logger.warning(f"RAG bandar context failed [{ticker}]: {e}")
        return BandarRetestType.UNCLEAR, False, None, 0.0


async def _rag_chart_pattern(
    ticker:    str,
    fib_pct:   float,
    vol_ratio: float,
    vsa_signal: Optional[str],
) -> tuple:
    """
    Layer 4 — Query RAG Bulkowski.
    Hanya dijalankan kalau fib_pct >= 38.2%.
    Return: (pattern_name, win_rate, implication, kb_insight)
    """
    if fib_pct < 38.2:
        return PatternName.NONE, 0.0, "NEUTRAL", None

    try:
        from app.core.knowledge_base import query_knowledge_base

        query = (
            f"pullback retracement {fib_pct:.1f}% setelah breakout, "
            f"volume ratio {vol_ratio:.2f}x, "
            f"VSA signal {vsa_signal or 'none'}. "
            f"Chart pattern name, win rate percentage, dan target measured move?"
        )

        result_text = await query_knowledge_base("technical", query, n_results=2)
        result = {"answer": result_text} if result_text else None

        if not result or not result.get("answer"):
            return PatternName.NONE, 0.0, "NEUTRAL", None

        answer = result["answer"].lower()

        # Parse pattern dari jawaban
        if "bull flag" in answer:
            pattern    = PatternName.BULL_FLAG
            win_rate   = 67.0
            implication = "BULLISH"
        elif "wyckoff spring" in answer or "spring" in answer:
            pattern    = PatternName.WYCKOFF_SPRING
            win_rate   = 72.0
            implication = "BULLISH"
        elif "higher low" in answer:
            pattern    = PatternName.HIGHER_LOW
            win_rate   = 65.0
            implication = "BULLISH"
        elif "dead cat" in answer:
            pattern    = PatternName.DEAD_CAT_BOUNCE
            win_rate   = 20.0
            implication = "BEARISH"
        elif "bear flag" in answer:
            pattern    = PatternName.BEAR_FLAG
            win_rate   = 25.0
            implication = "BEARISH"
        else:
            pattern    = PatternName.NONE
            win_rate   = 50.0
            implication = "NEUTRAL"

        return pattern, win_rate, implication, result["answer"][:300]

    except Exception as e:
        logger.warning(f"RAG chart pattern failed [{ticker}]: {e}")
        return PatternName.NONE, 0.0, "NEUTRAL", None


def _synthesize(
    classification:  RetestClassification,
    bandar_type:     BandarRetestType,
    pattern:         PatternName,
    pattern_impl:    str,
    vsa_signal:      Optional[str],
    confidence_bandar: float,
) -> tuple:
    """
    Layer 5 — Synthesis verdict final.
    Return: (RetestVerdict, confidence)
    """
    # EXIT_ALL conditions
    if classification == RetestClassification.REVERSAL_CONFIRMED:
        return RetestVerdict.EXIT_ALL, 90.0
    if (classification == RetestClassification.REVERSAL_WARNING
            and bandar_type == BandarRetestType.DISTRIBUSI_TERSELUBUNG):
        return RetestVerdict.EXIT_ALL, 85.0
    if pattern == PatternName.DEAD_CAT_BOUNCE:
        return RetestVerdict.EXIT_ALL, 80.0

    # REDUCE_50 conditions
    if (classification == RetestClassification.REVERSAL_WARNING
            or bandar_type == BandarRetestType.DISTRIBUSI_TERSELUBUNG
            or pattern == PatternName.BEAR_FLAG):
        return RetestVerdict.REDUCE_50, 70.0

    if (classification == RetestClassification.DEEP_BUT_VALID
            and bandar_type == BandarRetestType.UNCLEAR):
        return RetestVerdict.REDUCE_50, 60.0

    # STRONG_HOLD conditions
    if (classification in (
            RetestClassification.VERY_SHALLOW,
            RetestClassification.NORMAL_RETEST)
            and bandar_type in (
            BandarRetestType.NORMAL_BANDAR_RETEST,
            BandarRetestType.PARKING)
            and pattern in (
            PatternName.BULL_FLAG,
            PatternName.WYCKOFF_SPRING,
            PatternName.HIGHER_LOW)):
        return RetestVerdict.STRONG_HOLD, 88.0

    if (classification == RetestClassification.NORMAL_RETEST
            and bandar_type == BandarRetestType.NORMAL_BANDAR_RETEST):
        return RetestVerdict.STRONG_HOLD, 78.0

    if (classification == RetestClassification.MEDIUM_RETEST
            and vsa_signal == "WYCKOFF_SPRING"):
        return RetestVerdict.STRONG_HOLD, 72.0

    # HOLD — default
    confidence = 55.0
    if bandar_type == BandarRetestType.NORMAL_BANDAR_RETEST:
        confidence += 10.0
    if pattern_impl == "BULLISH":
        confidence += 8.0
    if vsa_signal in ("ABSORPTION", "NO_SUPPLY"):
        confidence += 7.0

    return RetestVerdict.HOLD, min(confidence, 75.0)


async def classify_retest(
    ticker:           str,
    highs:            list,
    lows:             list,
    closes:           list,
    volumes:          list,
    avg_volume:       float,
    bandar_phase:     str   = "UNKNOWN",
    net_foreign_lot:  int   = 0,
    swing_lookback:   int   = 20,
) -> RetestResult:
    """
    Main function Engine 6 — Full 5 layer retest classifier.
    """
    try:
        import time

        current_close  = closes[-1]  if closes  else 0.0
        current_high   = highs[-1]   if highs   else 0.0
        current_low    = lows[-1]    if lows    else 0.0
        current_volume = volumes[-1] if volumes else 0

        # Layer 1 — Fibonacci
        swing_high = _find_swing_high(highs, swing_lookback)
        swing_low  = _find_swing_low(lows,   swing_lookback)
        if swing_high <= swing_low:
            swing_high = current_high
            swing_low  = current_low

        diff    = swing_high - swing_low
        fib_pct = ((swing_high - current_close) / diff * 100) if diff > 0 else 0.0
        fib_pct = max(0.0, min(100.0, fib_pct))

        pullback_points = round(swing_high - current_close, 2)
        pullback_pct    = round((pullback_points / swing_high * 100), 2) if swing_high > 0 else 0.0
        fib_levels      = _calc_fib_prices(swing_high, swing_low)
        classification  = _classify_fib(fib_pct)

        # Layer 2 — VSA (lokal + Phase 2 VSA Engine)
        vol_ratio = round(current_volume / avg_volume, 2) if avg_volume > 0 else 1.0
        price_change_pct = (
            ((current_close - closes[-2]) / closes[-2] * 100)
            if len(closes) >= 2 else 0.0
        )
        vsa_signal = _detect_vsa(
            current_volume, avg_volume,
            current_close, current_low, current_high,
            price_change_pct,
        )

        # Phase 2 — Wyckoff + Weinstein + VSA Engine (lokal, non-blocking)
        try:
            opens_proxy = closes  # proxy kalau opens tidak tersedia
            p2_wyckoff   = classify_wyckoff(opens_proxy, highs, lows, closes, volumes)
            p2_weinstein = classify_weinstein(closes, volumes)
            p2_vsa       = analyze_vsa(opens_proxy, highs, lows, closes, volumes)

            # Override vsa_signal kalau Phase 2 VSA lebih kuat
            if p2_vsa.signal != "NONE" and vsa_signal is None:
                vsa_signal = p2_vsa.signal

            # Wyckoff context untuk bandar_retest_type
            wyckoff_phase   = p2_wyckoff.phase
            wyckoff_impl    = p2_wyckoff.implication
            weinstein_stage = p2_weinstein.stage
            weinstein_impl  = p2_weinstein.implication
            vsa_background  = p2_vsa.background
        except Exception as e:
            logger.warning(f"Phase2 in retest failed [{ticker}]: {e}")
            wyckoff_phase   = "UNKNOWN"
            wyckoff_impl    = "NEUTRAL"
            weinstein_stage = 0
            weinstein_impl  = "NEUTRAL"
            vsa_background  = "NEUTRAL" 

        # RAG rate limit check
        now         = time.time()
        last_query  = _rag_cache.get(ticker, 0)
        use_rag     = (now - last_query) >= RAG_COOLDOWN_SEC

        # Layer 3 — Bandar Context RAG
        bandar_retest_type = BandarRetestType.UNCLEAR
        bandar_holding     = False
        kb_bandar          = None
        conf_bandar        = 0.0

        if use_rag:
            bandar_retest_type, bandar_holding, kb_bandar, conf_bandar = \
                await _rag_bandar_context(
                    ticker, fib_pct, vol_ratio,
                    bandar_phase, net_foreign_lot,
                )

        # Layer 4 — Chart Pattern RAG (hanya fib >= 38.2%)
        pattern_name  = PatternName.NONE
        pattern_wr    = 0.0
        pattern_impl  = "NEUTRAL"
        kb_pattern    = None

        if use_rag and fib_pct >= 38.2:
            pattern_name, pattern_wr, pattern_impl, kb_pattern = \
                await _rag_chart_pattern(ticker, fib_pct, vol_ratio, vsa_signal)

        if use_rag:
            _rag_cache[ticker] = now

        # Layer 5 — Synthesis (dengan Phase 2 context)
        verdict, confidence = _synthesize(
            classification, bandar_retest_type,
            pattern_name, pattern_impl,
            vsa_signal, conf_bandar,
        )

        # Phase 2 confidence boost/penalty
        if wyckoff_impl == "BUY" and verdict in ("STRONG_HOLD", "HOLD"):
            confidence = min(95.0, confidence + 8.0)
        elif wyckoff_impl in ("EXIT", "REDUCE") and verdict == "HOLD":
            verdict    = RetestVerdict.REDUCE_50
            confidence = min(80.0, confidence + 5.0)

        if weinstein_stage == 2 and verdict in ("STRONG_HOLD", "HOLD"):
            confidence = min(95.0, confidence + 5.0)
        elif weinstein_stage == 4 and verdict not in ("EXIT_ALL",):
            verdict    = RetestVerdict.REDUCE_50
            confidence = min(85.0, confidence + 5.0)

        if vsa_background == "BULLISH" and verdict in ("STRONG_HOLD", "HOLD"):
            confidence = min(95.0, confidence + 5.0)
        elif vsa_background == "BEARISH" and verdict == "HOLD":
            verdict    = RetestVerdict.REDUCE_50

        rag_triggered = classification in (
            RetestClassification.DEEP_BUT_VALID,
            RetestClassification.REVERSAL_WARNING,
            RetestClassification.REVERSAL_CONFIRMED,
        ) or bandar_retest_type == BandarRetestType.DISTRIBUSI_TERSELUBUNG

        return RetestResult(
            classification        = classification,
            fib_level_pct         = round(fib_pct, 2),
            pullback_points       = pullback_points,
            pullback_pct          = pullback_pct,
            swing_high            = swing_high,
            swing_low             = swing_low,
            fib_levels            = fib_levels,
            volume_ratio_pullback = vol_ratio,
            vsa_signal            = vsa_signal,
            bandar_retest_type    = bandar_retest_type,
            bandar_still_holding  = bandar_holding,
            kb_insight_bandar     = kb_bandar,
            confidence_bandar     = conf_bandar,
            pattern_name          = pattern_name,
            pattern_win_rate      = pattern_wr,
            pattern_implication   = pattern_impl,
            kb_insight_pattern    = kb_pattern,
            retest_verdict        = verdict,
            retest_confidence     = confidence,
            rag_triggered         = rag_triggered,
            wyckoff_phase         = wyckoff_phase,
            weinstein_stage       = weinstein_stage,
            vsa_background        = vsa_background,
        )

    except Exception as e:
        logger.error(f"RetestClassifier error [{ticker}]: {e}")
        return RetestResult(
            classification        = RetestClassification.MEDIUM_RETEST,
            fib_level_pct         = 50.0,
            pullback_points       = 0.0,
            pullback_pct          = 0.0,
            swing_high            = 0.0,
            swing_low             = 0.0,
            fib_levels            = {},
            volume_ratio_pullback = 1.0,
            retest_verdict        = RetestVerdict.HOLD,
            retest_confidence     = 0.0,
            rag_triggered         = True,
        )
