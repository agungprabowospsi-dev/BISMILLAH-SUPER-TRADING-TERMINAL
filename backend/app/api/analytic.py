# ─── ANALYTIC ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _R, HTTPException
from fastapi.responses import JSONResponse
import numpy as np
from sqlalchemy import text as sql_text
from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
from app.ml.signal_quality import predict_win_probability, get_model_status
from app.ml.dynamic_sltp import calculate_dynamic_sltp
from pydantic import BaseModel
from app.core import invesgo
from app.engines.master_runner import run_all_engines
from app.core.claude_client import ask_claude
from app.knowledge_base import kb_service
import logging

logger = logging.getLogger(__name__)

router = _R()

@router.get("/debug")
async def debug():
    import traceback
    results = {}
    try:
        from app.core import invesgo
        ohlcv = await invesgo.get_ohlcv_daily("BBCA")
        results["step1_ohlcv"] = f"OK {len(ohlcv)} candles"
    except Exception as e:
        return {"failed_at": "step1_ohlcv", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.engines.master_runner import run_all_engines
        all_eng = await run_all_engines("BBCA", ohlcv, "swing")
        results["step2_engines"] = f"OK score={all_eng['composite_score']} engines={all_eng['total_engines']}"
    except Exception as e:
        return {"failed_at": "step2_engines", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.api.analytic import _calc_atr
        atr = _calc_atr(ohlcv)
        results["step3_atr"] = f"OK atr={atr}"
    except Exception as e:
        return {"failed_at": "step3_atr", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.knowledge_base import kb_service
        ctx = await kb_service.get_kb_context_for_engine("PriceActionEngine", "BBCA")
        results["step4_rag"] = f"OK len={len(ctx)}"
    except Exception as e:
        return {"failed_at": "step4_rag", "error": str(e), "trace": traceback.format_exc()}
    try:
        from app.core.claude_client import ask_claude
        r = await ask_claude(system="test", prompt="say OK", max_tokens=10)
        results["step5_claude"] = f"OK: {r}"
    except Exception as e:
        return {"failed_at": "step5_claude", "error": str(e), "trace": traceback.format_exc()}
    # Test invesgo endpoints
    for name, coro in [
        ("price_table", invesgo.get_price_table("BBCA")),
        ("orderbook", invesgo.get_orderbook("BBCA")),
        ("broker", invesgo.get_broker_summary("BBCA")),
        ("company", invesgo.get_company_info("BBCA")),
    ]:
        try:
            data = await coro
            k = list(data.keys())[:5] if isinstance(data, dict) else f"list[{len(data)}]"
            results[f"step_{name}"] = f"OK keys={k}"
        except Exception as e:
            results[f"step_{name}"] = f"ERROR: {str(e)[:80]}"
    return {"all_ok": True, "results": results}

class AnalyticRequest(BaseModel):
    ticker: str
    mode: str = "swing"

@router.post("/analyze")
async def analyze(req: AnalyticRequest):
    try:
        ohlcv = await invesgo.get_ohlcv_daily(req.ticker)
        if not ohlcv or len(ohlcv) < 20:
            raise HTTPException(400, "Insufficient OHLCV data")

        # Inject harga realtime ke candle terakhir
        try:
            ctx = await invesgo.get_market_context(req.ticker)
            if ctx and ctx.get("price", {}).get("last"):
                realtime_price = float(ctx["price"]["last"])
                realtime_high = float(ctx["price"].get("high", ohlcv[-1].get("high", realtime_price)))
                realtime_low = float(ctx["price"].get("low", ohlcv[-1].get("low", realtime_price)))
                ohlcv[-1]["close"] = realtime_price
                ohlcv[-1]["high"] = max(realtime_high, realtime_price)
                ohlcv[-1]["low"] = min(realtime_low, realtime_price)
                logger.info(f"Injected realtime price {realtime_price} for {req.ticker}")
        except Exception as e:
            logger.warning(f"Could not inject realtime price: {e}")

        # Cast OHLCV ke float
        ohlcv = [{
            **c,
            "open":   float(c.get("open",   0) or 0),
            "high":   float(c.get("high",   0) or 0),
            "low":    float(c.get("low",    0) or 0),
            "close":  float(c.get("close",  0) or 0),
            "volume": float(c.get("volume", 0) or 0),
        } for c in ohlcv]
        all_engines = await run_all_engines(req.ticker, ohlcv, req.mode)
        current = ohlcv[-1]["close"]
        score   = all_engines["composite_score"]

        # ── Enrichment + Phase 2 Integration ──────────────────────
        enrichment_verdict  = "CAUTION"
        phase2_verdict      = "HOLD"
        wyckoff_phase       = "UNKNOWN"
        weinstein_stage     = 0
        vsa_signal          = "NONE"

        try:
            from app.api.enrichment.router import _run_phase2
            from app.api.enrichment.smart_mfi import SmartMFI
            from app.api.enrichment.kama_bands import KAMABands
            from app.api.enrichment.lele_exhaustion import LeleExhaustion
            from app.api.enrichment.divergence import DivergenceStateMachine

            mfi_r  = SmartMFI().compute(ohlcv)
            kama_r = KAMABands().compute(ohlcv)
            lele_r = LeleExhaustion().compute(ohlcv)
            redis  = None
            div_r  = await DivergenceStateMachine().compute(ohlcv, redis, req.ticker)

            warn = sum([
                mfi_r.get("signal") == "BEARISH",
                kama_r.get("entry_signal") in ("BELOW_LOWER3", "BELOW_LOWER2"),
                lele_r.get("detected", False),
                div_r.get("state") in ("BEARISH_WARN", "HIDDEN_BEAR"),
            ])
            enrichment_verdict = "SKIP" if warn >= 3 else "CAUTION" if warn == 2 else "PROCEED"

            p2 = _run_phase2(ohlcv)
            if p2:
                phase2_verdict  = p2.phase2_verdict
                wyckoff_phase   = p2.wyckoff.phase
                weinstein_stage = p2.weinstein.stage
                vsa_signal      = p2.vsa.signal

        except Exception as e:
            logger.warning(f"Enrichment/Phase2 in analytic failed: {e}")

        # ── GO / NO GO Logic ────────────────────────────────────────
        go_reasons    = []
        no_go_reasons = []

        if score >= 65:
            go_reasons.append(f"Bandar score {score:.0f} — TIER {'1' if score >= 80 else '2'}")
        else:
            no_go_reasons.append(f"Bandar score {score:.0f} terlalu rendah (min 65)")

        if enrichment_verdict == "PROCEED":
            go_reasons.append("Enrichment PROCEED — timing entry valid")
        elif enrichment_verdict == "SKIP":
            no_go_reasons.append("Enrichment SKIP — sinyal kontradiksi")

        if wyckoff_phase in ("ACCUMULATION", "MARKUP", "REACCUMULATION"):
            go_reasons.append(f"Wyckoff {wyckoff_phase} — fase bullish")
        elif wyckoff_phase in ("DISTRIBUTION", "MARKDOWN"):
            no_go_reasons.append(f"Wyckoff {wyckoff_phase} — fase bearish")

        if weinstein_stage == 2:
            go_reasons.append("Weinstein Stage 2 — ADVANCING")
        elif weinstein_stage == 4:
            no_go_reasons.append("Weinstein Stage 4 — DECLINING")

        if vsa_signal in ("STOPPING_VOLUME", "NO_SUPPLY", "TEST"):
            go_reasons.append(f"VSA {vsa_signal} — bullish microstructure")
        elif vsa_signal in ("UP_THRUST", "NO_DEMAND"):
            no_go_reasons.append(f"VSA {vsa_signal} — bearish microstructure")

        # Final GO/NO GO
        go_score = len(go_reasons)
        no_score = len(no_go_reasons)

        if enrichment_verdict == "SKIP" or weinstein_stage == 4 or score < 55:
            go_no_go = "NO GO"
            go_confidence = max(0, 100 - (no_score * 20))
        elif go_score >= 3 and no_score == 0:
            go_no_go = "STRONG GO"
            go_confidence = min(95, 70 + go_score * 5)
        elif go_score >= 2 and go_score > no_score:
            go_no_go = "GO"
            go_confidence = min(85, 60 + go_score * 5)
        elif no_score >= 2:
            go_no_go = "WAIT"
            go_confidence = max(30, 60 - no_score * 10)
        else:
            go_no_go = "WAIT"
            go_confidence = 50

        # ── Setup Type Detector (additive) ─────────────────────────
        closes = [c["close"] for c in ohlcv]
        highs = [c["high"] for c in ohlcv]
        lows = [c["low"] for c in ohlcv]
        volumes = [c["volume"] for c in ohlcv]

        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current
        ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
        range_high_20 = max(highs[-20:]) if len(highs) >= 20 else current
        range_low_20 = min(lows[-20:]) if len(lows) >= 20 else current
        avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else max(volumes[-1], 1)
        rvol = volumes[-1] / avg_vol_20 if avg_vol_20 else 1

        trend_up = current >= ma20 >= ma50
        trend_down = current <= ma20 <= ma50
        near_low = current <= range_low_20 * 1.03
        near_high = current >= range_high_20 * 0.97
        breakout_up = current >= range_high_20 and rvol >= 1.3
        breakdown_down = current <= range_low_20 and rvol >= 1.3

        setup_type = "neutral"
        setup_reason = "Belum ada pola setup dominan."

        if breakout_up:
            setup_type = "bullish_breakout"
            setup_reason = "Harga menembus range high 20 hari dengan volume relatif kuat."
        elif breakdown_down:
            setup_type = "bearish_breakdown"
            setup_reason = "Harga menembus range low 20 hari dengan volume relatif kuat."
        elif trend_up and near_high:
            setup_type = "bullish_continuation"
            setup_reason = "Trend naik dan harga berada dekat area high, mengarah ke continuation."
        elif trend_up and current <= ma20 * 1.02:
            setup_type = "bullish_pullback"
            setup_reason = "Trend naik namun harga pullback dekat MA20."
        elif trend_down and near_low and score >= 55:
            setup_type = "bullish_reversal"
            setup_reason = "Harga berada dekat range low dalam downtrend, tetapi score mulai membaik."
        elif trend_down:
            setup_type = "bearish_continuation"
            setup_reason = "Trend turun masih dominan dan belum ada reversal kuat."
        elif near_low and score >= 55:
            setup_type = "bullish_reversal"
            setup_reason = "Harga dekat support/range low dengan score positif."
        elif near_high and score <= 45:
            setup_type = "bearish_reversal"
            setup_reason = "Harga dekat resistance/range high dengan score lemah."

        # ───────────────────────────────────────────────────────────

        # Hitung SL/TP sederhana
        atr = _calc_atr(ohlcv)
        sl_mult = {"swing": 2.0, "daytrading": 1.5, "scalping": 1.0}.get(req.mode, 1.5)

        entry = current
        sl    = round(entry - atr * sl_mult, 0)
        tp1   = round(entry + atr * sl_mult * 1.5, 0)
        tp2   = round(entry + atr * sl_mult * 2.5, 0)
        tp3   = round(entry + atr * sl_mult * 4.0, 0)
        rr    = round((tp1 - entry) / (entry - sl), 2) if entry != sl else 0

        # ── RAG KB CONTEXT ──────────────────────────────────────────
        kb_context = ""
        try:
            from app.core.knowledge_base import query_bandarmologi_specific
            analytic_engines = [
                "PriceActionEngine", "VolumeIntelligenceEngine",
                "TrendStructureEngine", "RiskManagementEngine"
            ]
            kb_parts = []

            # Bandarmologi IDX — query khusus 3 buku murni IDX
            bandar_ctx = await query_bandarmologi_specific(
                ticker       = req.ticker,
                bandar_score = float(score),
                phase        = wyckoff_phase,
                signal       = all_engines.get('signal', 'NEUTRAL'),
            )
            if bandar_ctx:
                kb_parts.append(
                    f"=== BANDARMOLOGI IDX (3 Buku Khusus IDX) ===\n{bandar_ctx}"
                )

            # Buku teknikal spesifik per fungsi
            from app.core.knowledge_base import (
                query_trade_setup, query_murphy_ta,
                query_coulling_vpa, query_lopezdeprado
            )
            import asyncio as _asyncio

            setup_query = (
                f"Setup {setup_type} untuk {req.mode} trading, "
                f"score {score:.0f}, signal {all_engines.get('signal','NEUTRAL')}. "
                f"Apakah setup ini valid? Kriteria entry dan manajemen risiko?"
            )
            murphy_query = (
                f"Trend analysis {setup_type}, MA20={ma20:.0f}, MA50={ma50:.0f}, "
                f"harga {'di atas' if trend_up else 'di bawah'} MA. "
                f"Konfirmasi technical analysis?"
            )
            vpa_query = (
                f"Volume {rvol:.1f}x average, setup {setup_type}. "
                f"Apakah volume mengkonfirmasi price movement ini?"
            )
            ml_query = (
                f"Score {score:.0f}/100, win probability setup {setup_type}. "
                f"Statistical edge dan feature importance?"
            )

            setup_ctx, murphy_ctx, vpa_ctx, ml_ctx = await _asyncio.gather(
                query_trade_setup(setup_query, n=2),
                query_murphy_ta(murphy_query, n=2),
                query_coulling_vpa(vpa_query, n=2),
                query_lopezdeprado(ml_query, n=1),
            )

            for label, ctx in [
                ("Trade Setup Handbook", setup_ctx),
                ("Murphy TA", murphy_ctx),
                ("Coulling VPA", vpa_ctx),
                ("Lopez de Prado ML", ml_ctx),
            ]:
                if ctx:
                    kb_parts.append(f"=== {label} ===\n{ctx}")
            if kb_parts:
                kb_context = "\n\n=== REFERENSI KNOWLEDGE BASE ===\n" + "\n---\n".join(kb_parts[:4])
                logger.info(f"[RAG] Analytic {req.ticker}: {len(kb_parts)} KB contexts injected")
        except Exception as kb_err:
            logger.debug(f"[RAG] analytic skip: {kb_err}")
        # ────────────────────────────────────────────────────────────

        # Market Regime Context
        market_regime_context = ""
        try:
            regime_data = await invesgo.get_market_regime()
            ihsg = regime_data.get("IHSG", {}) or {}
            lq45 = regime_data.get("LQ45", {}) or {}
            
            ihsg_close = ihsg.get("close")
            ihsg_prev = ihsg.get("prev")
            ihsg_change_pct = 0
            if ihsg_close and ihsg_prev and ihsg_prev != 0:
                ihsg_change_pct = ((ihsg_close - ihsg_prev) / ihsg_prev) * 100
            
            top_gainer = regime_data.get("top_gainer", [])
            top_loser = regime_data.get("top_loser", [])
            
            # Determine regime
            if ihsg_change_pct > 1:
                regime = "STRONG BULL"
            elif ihsg_change_pct > 0:
                regime = "BULL"
            elif ihsg_change_pct > -1:
                regime = "SIDEWAYS/BEAR"
            else:
                regime = "STRONG BEAR"
            
            lq45_close = lq45.get("close", 0)
            
            market_regime_context = f"""
=== MARKET REGIME ===
Regime: {regime}
IHSG: {ihsg_close or "N/A"} ({ihsg_change_pct:+.2f}%)
LQ45: {lq45_close}
Top Gainers: {", ".join([s.get("code","") for s in (top_gainer[:3] if top_gainer else [])])}
Top Losers: {", ".join([s.get("code","") for s in (top_loser[:3] if top_loser else [])])}
"""
        except Exception as regime_err:
            logger.debug(f"[REGIME] skip: {regime_err}")
            market_regime_context = ""

        rationale = await ask_claude(
            system="Kamu adalah analis saham IDX profesional. Berikan analisis trading yang jelas dan actionable dalam Bahasa Indonesia.",
            prompt=f"""
Ticker: {req.ticker} | Mode: {req.mode}
Score: {score:.1f}/100 | Signal: {all_engines['signal']}
Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
R:R = {rr}
Setup Type: {setup_type}
Setup Reason: {setup_reason}
Engine: {all_engines.get('bullish_count', 0)} bullish, {all_engines.get('bearish_count', 0)} bearish dari 10 engines
{market_regime_context}
{kb_context}

Tulis analisis trading 3-4 kalimat dalam Bahasa Indonesia:
1. Kondisi market saat ini (sertakan regime market jika tersedia)
2. Jenis setup berdasarkan Setup Type, jangan otomatis menyebut continuation jika Setup Type bukan continuation
3. Alasan entry dan level kunci
4. Manajemen risiko (SL/TP)
Jika ada referensi Knowledge Base di atas, gunakan insight tersebut untuk memperkuat analisis.
""",
            max_tokens=400
        )

        import json as _json
        class NumpyEncoder(_json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer): return int(obj)
                if isinstance(obj, np.floating): return float(obj)
                if isinstance(obj, np.bool_): return bool(obj)
                if isinstance(obj, np.ndarray): return obj.tolist()
                return super().default(obj)

        result = {
            "ticker": req.ticker,
            "mode": req.mode,
            "entry": float(entry) if entry else 0,
            "stop_loss": float(sl) if sl else 0,
            "tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp3),
            "rr_ratio": float(rr),
            "score": float(score),
            "confidence": float(min(95, score)),
            "signal": all_engines['signal'],
            "market_regime": regime if 'regime' in dir() else "N/A",
            "setup_type": setup_type,
            "setup_reason": setup_reason,
            "setup_metrics": {
                "ma20": float(ma20),
                "ma50": float(ma50),
                "range_high_20": float(range_high_20),
                "range_low_20": float(range_low_20),
                "rvol": float(round(rvol, 2)),
                "trend_up": bool(trend_up),
                "trend_down": bool(trend_down),
                "near_low": bool(near_low),
                "near_high": bool(near_high),
            },
            "rationale": rationale,
            "engines": all_engines,

            # RAG / Knowledge Base validation metadata
            "rag_used": bool(kb_context),
            "rag_context_count": len(kb_parts) if "kb_parts" in locals() else 0,
            "rag_engines": analytic_engines if "analytic_engines" in locals() else [],
            # GO / NO GO
            "go_no_go":          go_no_go,
            "go_confidence":     go_confidence,
            "go_reasons":        go_reasons,
            "no_go_reasons":     no_go_reasons,
            # Enrichment + Phase 2
            "enrichment_verdict": enrichment_verdict,
            "phase2_verdict":    phase2_verdict,
            "wyckoff_phase":     wyckoff_phase,
            "weinstein_stage":   weinstein_stage,
            "vsa_signal":        vsa_signal,
        }

        # ML — Win Probability
        try:
            regime_str = str(result.get("market_regime", "SIDEWAYS"))
            lq45_chg = 0.0
            breadth = 50.0
            eng_list = all_engines.get('engines', [])
            eng_dict = {}
            if isinstance(eng_list, list):
                for e in eng_list:
                    eng_dict[e.get('engine','?')] = e.get('score', 0)
            elif isinstance(eng_list, dict):
                eng_dict = eng_list
            win_prob = predict_win_probability(
                engine_scores=eng_dict,
                market_regime=regime_str,
                lq45_change=lq45_chg,
                breadth_ratio=breadth,
                final_score=float(score),
                kb_context=kb_context if 'kb_context' in locals() else ""
            )
            result["win_probability"] = win_prob
            result["ml_status"] = get_model_status()
        except Exception as e:
            import traceback
            result["win_probability"] = {"probability": 50.0, "grade": "C", "grade_label": "Moderate", "color": "#fbbf24", "method": "fallback", "error": str(e), "trace": traceback.format_exc()[:200]}
        # Dynamic SL/TP
        try:
            dynamic = calculate_dynamic_sltp(
                entry_price=float(entry) if entry else float(result.get("entry", 0)),
                ohlcv=normalized_ohlcv,
                market_regime=str(result.get("market_regime", "SIDEWAYS")),
                final_score=float(score),
                mode=req.mode,
                akumulasi_score=50.0
            )
            result["dynamic_sltp"] = dynamic
        except Exception as e:
            result["dynamic_sltp"] = {"method": "error", "error": str(e)}

        return JSONResponse(content=_json.loads(_json.dumps(result, cls=NumpyEncoder)))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Analytic error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, detail=f"{type(e).__name__}: {str(e)}")

@router.get("/market-context/{ticker}")
async def market_context(ticker: str):
    """4 box: price, volume, company, technical"""

    class NumpyEncoder(_json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.bool_): return bool(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    result = {}
    ohlcv = []

    # OHLCV untuk box 1, 2, 4
    try:
        raw = await invesgo.get_ohlcv_daily(ticker)
        ohlcv = [{**c,
            "open": float(c.get("open",0) or 0),
            "high": float(c.get("high",0) or 0),
            "low": float(c.get("low",0) or 0),
            "close": float(c.get("close",0) or 0),
            "volume": float(c.get("volume",0) or 0),
        } for c in raw]
    except Exception as e:
        ohlcv = []

    # Box 1: Price
    try:
        last = ohlcv[-1]; prev = ohlcv[-2]
        change = last["close"] - prev["close"]
        change_pct = round(change/prev["close"]*100, 2) if prev["close"] > 0 else 0
        result["price"] = {
            "last": last["close"], "change": round(change,0),
            "change_pct": change_pct, "high": last["high"],
            "low": last["low"], "open": last["open"],
        }
    except:
        result["price"] = {"error": "No data"}

    # Box 2: Volume
    try:
        vols = [c["volume"] for c in ohlcv[-20:]]
        avg_vol = sum(vols)/len(vols) if vols else 1
        last_vol = ohlcv[-1]["volume"]
        rvol = round(last_vol/avg_vol, 2) if avg_vol > 0 else 1
        vol_5 = sum(c["volume"] for c in ohlcv[-5:])/5
        result["volume"] = {
            "last_volume": int(last_vol),
            "avg_volume_20": int(avg_vol),
            "rvol": rvol,
            "vol_trend": "NAIK" if vol_5 > avg_vol*1.2 else "TURUN" if vol_5 < avg_vol*0.8 else "NORMAL",
            "signal": "HIGH" if rvol > 2 else "MEDIUM" if rvol > 1.3 else "NORMAL" if rvol > 0.7 else "LOW",
        }
    except:
        result["volume"] = {"error": "No data"}

    # Box 3: Company info
    try:
        info = await invesgo.get_company_info(ticker)
        result["company"] = {
            "name": info.get("company_name") or info.get("name") or ticker,
            "sector": info.get("sector") or info.get("industry") or "-",
            "subsector": info.get("subsindustry") or "-",
            "activity": info.get("activity") or "-",
            "code": info.get("code") or ticker,
        }
    except Exception as e:
        result["company"] = {"error": str(e)}

    # Box 4: Technical summary
    try:
        closes = [c["close"] for c in ohlcv]
        highs = [c["high"] for c in ohlcv]
        lows = [c["low"] for c in ohlcv]
        current = closes[-1]
        w52_high = max(highs[-252:]) if len(highs)>=252 else max(highs)
        w52_low = min(lows[-252:]) if len(lows)>=252 else min(lows)
        ma20 = sum(closes[-20:])/20
        ma50 = sum(closes[-50:])/50 if len(closes)>=50 else ma20
        result["technical"] = {
            "52w_high": w52_high,
            "52w_low": w52_low,
            "pct_from_high": round((current-w52_high)/w52_high*100, 2),
            "pct_from_low": round((current-w52_low)/w52_low*100, 2),
            "ma20": round(ma20, 0),
            "ma50": round(ma50, 0),
            "above_ma20": bool(current > ma20),
            "above_ma50": bool(current > ma50),
            "trend": "UPTREND" if current>ma20>ma50 else "DOWNTREND" if current<ma20<ma50 else "SIDEWAYS",
        }
    except:
        result["technical"] = {"error": "No data"}

    return JSONResponse(content=_json.loads(_json.dumps(result, cls=NumpyEncoder)))


def _calc_atr(ohlcv, period=14):
    import numpy as np
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02

@router.get("/test-period/{ticker}/{period}")
async def test_period(ticker: str, period: str):
    try:
        data = await invesgo.get_ohlcv_daily(ticker, period=period)
        if isinstance(data, list):
            return {"period": period, "candles": len(data), "first": data[0] if data else None, "last": data[-1] if data else None}
        return {"period": period, "type": type(data).__name__, "keys": list(data.keys()) if isinstance(data, dict) else None}
    except Exception as e:
        return {"error": str(e)}

@router.get("/market-regime")
async def get_market_regime_endpoint():
    try:
        data = await invesgo.get_market_regime()
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/top-movers/{sort_type}")
async def get_top_movers_endpoint(sort_type: str = "gainer"):
    try:
        data = await invesgo.get_top_movers(sort=sort_type, limit=20)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/financial/{ticker}")
async def get_financial_endpoint(ticker: str):
    try:
        data = await invesgo.get_financial_statement(ticker)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ============ FOREIGN FLOW DASHBOARD ============
LQ45_STOCKS = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BYAN","GOTO","UNVR",
    "ICBP","INDF","ANTM","PTBA","ADRO","ESSA","SMGR","PGAS",
    "EXCL","KLBF","MAPI","SIDO"
]

# Broker asing yang dikenal di IDX
FOREIGN_BROKERS = {
    "YP":"Indo Premier","BK":"J.P Morgan","RX":"Macquarie",
    "ZP":"Kim Eng","AK":"UBS","CC":"Mandiri","DB":"Deutsche",
    "MS":"Morgan Stanley","CS":"Credit Suisse","ML":"Merrill Lynch",
    "DP":"DBS Vickers","KI":"Citi","OD":"Mirae","LG":"Trimegah"
}

@router.get("/foreign-flow")
async def get_foreign_flow_dashboard():
    import asyncio
    from app.core import invesgo

    async def fetch_broker(ticker):
        try:
            data = await invesgo.get_broker_summary(ticker)
            return ticker, data
        except:
            return ticker, []

    # Fetch 10 saham LQ45 terbesar secara parallel
    tasks = [fetch_broker(t) for t in LQ45_STOCKS[:10]]
    results = await asyncio.gather(*tasks)

    stocks = []
    total_foreign_buy = 0
    total_foreign_sell = 0

    for ticker, brokers in results:
        if not brokers:
            continue

        # Filter broker asing
        foreign_net = 0
        foreign_buy = 0
        foreign_sell = 0
        top_foreign = []

        for b in brokers:
            code = b.get("code","")
            if code in FOREIGN_BROKERS:
                net = float(b.get("net_value",0) or 0)
                buy = float(b.get("buy_value",0) or 0)
                sell = float(b.get("sell_value",0) or 0)
                foreign_net += net
                foreign_buy += buy
                foreign_sell += sell
                top_foreign.append({
                    "broker": code,
                    "name": FOREIGN_BROKERS[code],
                    "net_value": net,
                    "buy_value": buy,
                    "sell_value": sell
                })

        # Sort by abs net value
        top_foreign.sort(key=lambda x: abs(x["net_value"]), reverse=True)

        total_foreign_buy += foreign_buy
        total_foreign_sell += foreign_sell

        stocks.append({
            "ticker": ticker,
            "foreign_net": round(foreign_net/1e9, 2),
            "foreign_buy": round(foreign_buy/1e9, 2),
            "foreign_sell": round(foreign_sell/1e9, 2),
            "signal": "BUY" if foreign_net > 0 else "SELL" if foreign_net < 0 else "NEUTRAL",
            "top_brokers": top_foreign[:3]
        })

    # Sort by foreign net
    stocks.sort(key=lambda x: x["foreign_net"], reverse=True)

    return {
        "status": "ok",
        "data": {
            "summary": {
                "total_foreign_buy": round(total_foreign_buy/1e9, 2),
                "total_foreign_sell": round(total_foreign_sell/1e9, 2),
                "total_net": round((total_foreign_buy-total_foreign_sell)/1e9, 2),
                "signal": "NET BUY" if total_foreign_buy > total_foreign_sell else "NET SELL"
            },
            "stocks": stocks,
            "universe": "LQ45 Top 10",
            "period": "30 hari terakhir"
        }
    }


# ============ DATA ACCUMULATION ============

DATA_WATCHLIST = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BYAN","GOTO","UNVR",
    "ICBP","INDF","ANTM","PTBA","ADRO","ESSA","SMGR","PGAS",
    "EXCL","KLBF","MAPI","SIDO","MDKA","AMMN","EMTK","BUKA",
    "ACES","MNCN","SCMA","LSIP","AALI","HRUM"
]

@router.post("/data/create-table")
async def create_ohlcv_table():
    try:
        async with _AsyncSessionLocal() as db:
            await db.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS ohlcv_daily (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    date DATE NOT NULL,
                    open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                    volume BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(ticker, date)
                )
            """))
            await db.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_daily(ticker, date)"))
            await db.commit()
        return {"status": "ok", "message": "Table ohlcv_daily ready"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@router.post("/data/accumulate")
async def accumulate_ohlcv():
    import asyncio as _asyncio
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    results = {"success": [], "failed": []}

    # Cari hari bursa valid — cek hari ini dulu, mundur max 7 hari
    import httpx as _httpx
    INVESGO_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImNtbnVmb2s2bTAwMDcxa21wM25lODlqanEiLCJlbWFpbCI6ImFndW5ndHJhZGVyY3VhbkBnbWFpbC5jb20iLCJ1c2VybmFtZSI6InNhbWJlcmN1YW4iLCJuYW1lIjoiQUdVTkciLCJyb2xlIjoiUFJJTUUiLCJzY29wZSI6WyJwdWJsaWMiXSwidmVyaWZpZWQiOmZhbHNlLCJkZXZpY2UiOiJBUEkiLCJpYXQiOjE3Nzg2MzI2MjYsImV4cCI6MTc4MTMzNjAzNX0.XgcvzxL_Y-JIxYpH6DxtRnz1N-eWnSVddLfMoUeGmfA"
    trade_date = None
    for days_back in range(0, 8):
        candidate_dt = _dt.now() - _td(days=days_back)
        candidate = candidate_dt.strftime("%Y-%m-%d")
        if candidate_dt.weekday() in (5, 6):
            continue
        try:
            async with _httpx.AsyncClient(timeout=10) as _client:
                _r = await _client.get(
                    "https://api.invesgo.id/analysis/chart/stock/BBCA",
                    headers={"Authorization": f"Bearer {INVESGO_TOKEN}"},
                    params={"from": candidate, "to": candidate}
                )
                _data = _r.json()
                if _data and len(_data) > 0 and float(_data[-1].get("close", 0)) > 0:
                    trade_date = candidate
                    break
        except:
            continue
    if not trade_date:
        trade_date = (_dt.now() - _td(days=4)).strftime("%Y-%m-%d")

    async def save_one(ticker):
        try:
            ohlcv = await _asyncio.wait_for(
                invesgo.get_ohlcv_daily(ticker, from_date=trade_date, to_date=trade_date),
                timeout=15
            )
            if not ohlcv:
                results["failed"].append({"ticker": ticker, "reason": "no data from Invesgo"})
                return

            # Ambil candle valid terakhir
            last = None
            for candle in reversed(ohlcv):
                if candle.get("close") and float(candle.get("close", 0)) > 0:
                    last = candle
                    break

            if not last:
                results["failed"].append({"ticker": ticker, "reason": "no valid candle"})
                return

            async with _AsyncSessionLocal() as db:
                await db.execute(sql_text("""
                    INSERT INTO ohlcv_daily (ticker, date, open, high, low, close, volume, created_at)
                    VALUES (:ticker, :date, :open, :high, :low, :close, :volume, NOW())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high,
                    low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume
                """), {
                    "ticker": ticker, "date": _dt.strptime(last.get("date", trade_date)[:10], "%Y-%m-%d").date(),
                    "open": float(last.get("open", 0) or 0),
                    "high": float(last.get("high", 0) or 0),
                    "low": float(last.get("low", 0) or 0),
                    "close": float(last.get("close", 0) or 0),
                    "volume": int(float(last.get("volume", 0) or 0)),
                })
                await db.commit()
            results["success"].append(ticker)
        except Exception as e:
            results["failed"].append({"ticker": ticker, "reason": str(e)[:200]})

    for i in range(0, len(DATA_WATCHLIST), 10):
        await _asyncio.gather(*[save_one(t) for t in DATA_WATCHLIST[i:i+10]])
        await _asyncio.sleep(1)

    return {"status": "ok", "date": today, "trade_date": trade_date, "success": len(results["success"]), "failed": len(results["failed"]), "details": results}

@router.get("/data/status")
async def ohlcv_status():
    try:
        async with _AsyncSessionLocal() as db:
            result = await db.execute(sql_text("""
                SELECT ticker, COUNT(*) as days, MIN(date) as from_date, MAX(date) as to_date
                FROM ohlcv_daily GROUP BY ticker ORDER BY days DESC LIMIT 20
            """))
            rows = result.fetchall()
        return {"status": "ok", "tickers": [{"ticker": r[0], "days": r[1], "from": str(r[2]), "to": str(r[3])} for r in rows], "total": len(rows)}
    except Exception as e:
        return {"status": "error", "error": str(e)}
