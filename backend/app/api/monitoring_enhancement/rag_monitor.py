"""
Engine 9 — RAG Monitor
Path: backend/app/api/monitoring_enhancement/rag_monitor.py

Trigger kondisi:
- BANDAR_TYPE_UNCLEAR     : confidence bandar < 50%
- DISTRIBUTION_DETECTED   : 2+ sinyal distribusi aktif
- RETEST_UNCLEAR          : bandar_retest_type == UNCLEAR
- RETEST_DEEP_BUT_VALID   : fib >= 50% tapi masih hold
- MOMENTUM_DROP           : score drop >= 20 poin
- TP_PROB_DROP            : prob_tp1 drop >= 20%

Rate limit: Redis 15 menit per ticker
Fallback  : in-memory cache kalau Redis tidak available
"""

import logging
import time
from typing import Optional

from .models import RAGMonitorResult, RAGTrigger

logger = logging.getLogger(__name__)

# In-memory fallback cache: {ticker: last_query_time}
_memory_cache: dict = {}
RAG_COOLDOWN_SEC = 900  # 15 menit

# 13 buku knowledge base
ALL_KB_SOURCES = [
    "file_1766768812634",
    "file_1766768868107",
    "E-Book Bandar Flow Secrets.pdf",
    "Encyclopedia of Chart Patterns",
    "Trading and Exchanges - Larry Harris",
    "Market Microstructure Theory",
    "Reminiscences of a Stock Operator",
    "The Art and Science of Technical Analysis",
    "Evidence-Based Technical Analysis",
    "How to Make Money in Stocks - O'Neil",
    "Secrets of the Trading Pros",
    "The Master Swing Trader",
    "Come Into My Trading Room - Elder",
]

# Query template per trigger
QUERY_TEMPLATES = {
    RAGTrigger.BANDAR_TYPE_UNCLEAR: (
        "Bagaimana mengidentifikasi tipe bandar IDX ketika sinyal tidak jelas? "
        "Karakteristik bandar institusional vs retail vs asing saat aksi tidak terdeteksi?"
    ),
    RAGTrigger.DISTRIBUTION_DETECTED: (
        "Sinyal distribusi terdeteksi: {signals}. "
        "Apa yang harus dilakukan trader saat bandar mulai distribusi di IDX? "
        "Kapan exit dan bagaimana membedakan distribusi asli vs fake distribution?"
    ),
    RAGTrigger.RETEST_UNCLEAR: (
        "Pullback {fib_pct}% dengan volume {vol_ratio}x average. "
        "Bagaimana membedakan retest normal bandar IDX vs awal reversal? "
        "Apa konfirmasi yang dibutuhkan sebelum add posisi?"
    ),
    RAGTrigger.RETEST_DEEP_BUT_VALID: (
        "Pullback dalam {fib_pct}% Fibonacci tapi belum reversal confirmed. "
        "Strategi manajemen posisi saat retest dalam di IDX? "
        "Apakah partial exit atau tunggu konfirmasi bounce?"
    ),
    RAGTrigger.MOMENTUM_DROP: (
        "Momentum turun {score_drop} poin dari {prev_score} ke {current_score}. "
        "Penyebab momentum drop dan strategi menghadapi perlambatan momentum? "
        "Apakah tanda distribusi atau hanya konsolidasi normal?"
    ),
    RAGTrigger.TP_PROB_DROP: (
        "Probabilitas TP1 turun {prob_drop}% menjadi {current_prob}%. "
        "Kondisi apa yang menyebabkan penurunan drastis probabilitas target? "
        "Apakah perlu revisi target atau exit parsial?"
    ),
}


# ─────────────────────────────────────────────
# RATE LIMIT
# ─────────────────────────────────────────────

async def _check_rate_limit(ticker: str) -> bool:
    """
    Cek rate limit Redis, fallback ke memory.
    Return: True = boleh query, False = rate limited
    """
    cache_key = f"rag_monitor:{ticker}"

    # Coba Redis dulu
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if redis:
            exists = await redis.get(cache_key)
            if exists:
                return False  # rate limited
            await redis.setex(cache_key, RAG_COOLDOWN_SEC, "1")
            return True
    except Exception:
        pass

    # Fallback: in-memory
    now = time.time()
    last = _memory_cache.get(ticker, 0)
    if (now - last) < RAG_COOLDOWN_SEC:
        return False
    _memory_cache[ticker] = now
    return True


# ─────────────────────────────────────────────
# TRIGGER DETECTOR
# ─────────────────────────────────────────────

def detect_trigger(
    bandar_confidence:     float,
    distribution_detected: bool,
    distribution_signals:  Optional[list] = None,
    bandar_retest_type:    Optional[str]  = None,
    fib_pct:               float          = 0.0,
    momentum_score_drop:   float          = 0.0,
    prob_tp1_drop:         float          = 0.0,
) -> RAGTrigger:
    """
    Deteksi trigger RAG berdasarkan prioritas.
    Urutan: distribusi > retest > momentum > tp_prob > bandar type
    """
    if distribution_detected:
        return RAGTrigger.DISTRIBUTION_DETECTED

    if fib_pct >= 50.0 and bandar_retest_type == "DEEP_BUT_VALID":
        return RAGTrigger.RETEST_DEEP_BUT_VALID

    if bandar_retest_type == "UNCLEAR" and fib_pct >= 38.2:
        return RAGTrigger.RETEST_UNCLEAR

    if momentum_score_drop >= 20.0:
        return RAGTrigger.MOMENTUM_DROP

    if prob_tp1_drop >= 20.0:
        return RAGTrigger.TP_PROB_DROP

    if bandar_confidence < 50.0:
        return RAGTrigger.BANDAR_TYPE_UNCLEAR

    return RAGTrigger.NONE


# ─────────────────────────────────────────────
# QUERY BUILDER
# ─────────────────────────────────────────────

def _build_query(
    trigger:       RAGTrigger,
    context:       dict,
) -> str:
    """Build query string dari template + context"""
    template = QUERY_TEMPLATES.get(trigger, "")
    if not template:
        return ""
    try:
        return template.format(**context)
    except KeyError:
        return template


def _select_sources(trigger: RAGTrigger) -> list:
    """
    Pilih source KB yang paling relevan per trigger.
    Tidak selalu query semua 13 buku — lebih efisien.
    """
    bandarmologi_books = ALL_KB_SOURCES[:3]
    technical_books    = ALL_KB_SOURCES[3:8]
    all_books          = ALL_KB_SOURCES

    if trigger in (RAGTrigger.BANDAR_TYPE_UNCLEAR,
                   RAGTrigger.DISTRIBUTION_DETECTED):
        return bandarmologi_books + ALL_KB_SOURCES[7:10]

    elif trigger in (RAGTrigger.RETEST_UNCLEAR,
                     RAGTrigger.RETEST_DEEP_BUT_VALID):
        return bandarmologi_books + technical_books

    elif trigger == RAGTrigger.MOMENTUM_DROP:
        return technical_books + ALL_KB_SOURCES[8:11]

    elif trigger == RAGTrigger.TP_PROB_DROP:
        return all_books[:8]

    return bandarmologi_books


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

async def run_rag_monitor(
    ticker:                str,
    bandar_confidence:     float = 100.0,
    distribution_detected: bool  = False,
    distribution_signals:  Optional[list] = None,
    bandar_retest_type:    Optional[str]  = None,
    fib_pct:               float = 0.0,
    momentum_score:        float = 50.0,
    momentum_prev_score:   float = 50.0,
    momentum_score_drop:   float = 0.0,
    prob_tp1:              float = 50.0,
    prob_tp1_drop:         float = 0.0,
    extra_context:         Optional[dict] = None,
) -> RAGMonitorResult:
    """
    Engine 9 — RAG Monitor dengan rate limit 15 menit.

    Parameters
    ----------
    ticker                 : kode saham
    bandar_confidence      : confidence Engine 3 (0-100)
    distribution_detected  : dari Engine 4
    distribution_signals   : list sinyal distribusi aktif
    bandar_retest_type     : dari Engine 6
    fib_pct                : % retracement dari Engine 6
    momentum_score         : score Engine 5 sekarang
    momentum_prev_score    : score Engine 5 sebelumnya
    momentum_score_drop    : delta negatif momentum
    prob_tp1               : probabilitas TP1 sekarang
    prob_tp1_drop          : delta negatif prob_tp1
    extra_context          : context tambahan untuk query
    """
    try:
        # Deteksi trigger
        trigger = detect_trigger(
            bandar_confidence     = bandar_confidence,
            distribution_detected = distribution_detected,
            distribution_signals  = distribution_signals,
            bandar_retest_type    = bandar_retest_type,
            fib_pct               = fib_pct,
            momentum_score_drop   = momentum_score_drop,
            prob_tp1_drop         = prob_tp1_drop,
        )

        # Tidak ada trigger = return kosong
        if trigger == RAGTrigger.NONE:
            return RAGMonitorResult(
                triggered      = False,
                trigger_reason = RAGTrigger.NONE,
            )

        # Cek rate limit
        allowed = await _check_rate_limit(ticker)
        if not allowed:
            return RAGMonitorResult(
                triggered      = True,
                trigger_reason = trigger,
                rate_limited   = True,
                kb_insight     = "Rate limited — query berikutnya dalam 15 menit",
            )

        # Build context untuk query
        signals_str = ", ".join(distribution_signals or [])
        context = {
            "signals":       signals_str or "upthrust, no_demand",
            "fib_pct":       f"{fib_pct:.1f}",
            "vol_ratio":     "1.0",
            "score_drop":    f"{momentum_score_drop:.1f}",
            "prev_score":    f"{momentum_prev_score:.1f}",
            "current_score": f"{momentum_score:.1f}",
            "prob_drop":     f"{prob_tp1_drop:.1f}",
            "current_prob":  f"{prob_tp1:.1f}",
        }
        if extra_context:
            context.update(extra_context)

        query   = _build_query(trigger, context)
        sources = _select_sources(trigger)

        if not query:
            return RAGMonitorResult(
                triggered      = True,
                trigger_reason = trigger,
                rate_limited   = False,
            )

        # Query knowledge base — gabungkan semua buku relevan
        try:
            from app.core.knowledge_base import (
                query_bandarmologi_kb,
                query_kb_for_engine,
                query_all_technical,
            )
            import asyncio

            # Selalu query 3 buku bandarmologi IDX
            bandar_text = await query_bandarmologi_kb(query, n_results=3)

            # Query buku teknikal berdasarkan trigger
            if trigger in (RAGTrigger.BANDAR_TYPE_UNCLEAR, RAGTrigger.DISTRIBUTION_DETECTED):
                tech_text = await query_kb_for_engine("BandarTypeClassifier", query)
            elif trigger in (RAGTrigger.RETEST_UNCLEAR, RAGTrigger.RETEST_DEEP_BUT_VALID):
                tech_text = await query_kb_for_engine("RetestClassifier", query)
            elif trigger == RAGTrigger.MOMENTUM_DROP:
                tech_text = await query_kb_for_engine("MomentumStrength", query)
            elif trigger == RAGTrigger.TP_PROB_DROP:
                tech_text = await query_kb_for_engine("TPProbability", query)
            else:
                tech_text = await query_all_technical(query, n_per_book=1)

            combined = "\n\n===\n\n".join([t for t in [bandar_text, tech_text] if t])
            result = {"answer": combined} if combined else None

            insight = None
            confidence_boost = 0.0

            if result and result.get("answer"):
                insight = result["answer"][:500]
                # Confidence boost berdasarkan kualitas jawaban
                if len(insight) > 200:
                    confidence_boost = 8.0
                elif len(insight) > 100:
                    confidence_boost = 5.0
                else:
                    confidence_boost = 2.0

            return RAGMonitorResult(
                triggered        = True,
                trigger_reason   = trigger,
                query_used       = query[:200],
                kb_insight       = insight,
                books_queried    = sources,
                confidence_boost = confidence_boost,
                rate_limited     = False,
            )

        except Exception as e:
            logger.warning(f"KB query failed [{ticker}]: {e}")
            return RAGMonitorResult(
                triggered      = True,
                trigger_reason = trigger,
                query_used     = query[:200],
                kb_insight     = None,
                rate_limited   = False,
            )

    except Exception as e:
        logger.error(f"RAGMonitor error [{ticker}]: {e}")
        return RAGMonitorResult(
            triggered      = False,
            trigger_reason = RAGTrigger.NONE,
        )
