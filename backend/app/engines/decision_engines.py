import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude


# ─── ENGINE #29: RISK MANAGEMENT ─────────────────────────────────────────────
class RiskManagementEngine(BaseEngine):
    def __init__(self):
        super().__init__("RiskManagementEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = np.array([c["close"] for c in ohlcv])
            highs  = [c["high"] for c in ohlcv]
            lows   = [c["low"]  for c in ohlcv]
            current = closes[-1]

            # ATR untuk SL
            atr = self._calc_atr(ohlcv)
            atr_pct = atr / current * 100

            # Volatility regime
            vol_20 = np.std(np.diff(closes[-20:]) / closes[-21:-1]) * np.sqrt(252)
            vol_regime = "high" if vol_20 > 0.4 else "medium" if vol_20 > 0.2 else "low"

            # SL/TP per mode
            sl_mult = {"swing": 2.0, "daytrading": 1.5, "scalping": 1.0}.get(mode, 1.5)
            tp_mult = {"swing": 4.0, "daytrading": 2.5, "scalping": 1.5}.get(mode, 2.5)

            sl = round(current - atr * sl_mult, 0)
            tp1 = round(current + atr * tp_mult * 0.6, 0)
            tp2 = round(current + atr * tp_mult, 0)
            tp3 = round(current + atr * tp_mult * 1.5, 0)
            rr  = round((tp1 - current) / (current - sl), 2) if current != sl else 0

            # Position sizing (% risiko 2%)
            risk_per_trade = 0.02
            risk_per_share = current - sl
            position_size_pct = (risk_per_trade / (risk_per_share / current)) * 100 if risk_per_share > 0 else 5

            score = 70.0 if rr >= 2 else 55.0 if rr >= 1.5 else 35.0

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=85.0,
                rationale=f"ATR: {atr:.0f} ({atr_pct:.1f}%). Vol regime: {vol_regime}. SL: {sl:.0f}, TP1: {tp1:.0f}, TP2: {tp2:.0f}. R:R = {rr}. Position size: {position_size_pct:.1f}% of capital.",
                data={
                    "atr": round(atr, 2), "atr_pct": round(atr_pct, 2),
                    "vol_regime": vol_regime, "vol_annual": round(vol_20, 3),
                    "stop_loss": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
                    "rr_ratio": rr, "position_size_pct": round(position_size_pct, 1),
                }
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _calc_atr(self, ohlcv, period=14):
        trs = []
        for i in range(1, len(ohlcv)):
            h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return np.mean(trs[-period:]) if trs else ohlcv[-1]["close"] * 0.02


# ─── ENGINE #30: FINAL SCORECARD ─────────────────────────────────────────────
class FinalScorecardEngine(BaseEngine):
    def __init__(self):
        super().__init__("FinalScorecardEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            all_scores = kwargs.get("all_engine_scores", {})

            if not all_scores:
                return self._safe_result("No engine scores provided")

            # Weights per group per mode
            group_weights = {
                "swing":      {"market_structure": 0.35, "smart_money": 0.30, "execution": 0.25, "decision": 0.10},
                "daytrading": {"market_structure": 0.30, "smart_money": 0.35, "execution": 0.25, "decision": 0.10},
                "scalping":   {"market_structure": 0.20, "smart_money": 0.40, "execution": 0.30, "decision": 0.10},
            }
            weights = group_weights.get(mode, group_weights["swing"])

            composite = (
                all_scores.get("market_structure", 50) * weights["market_structure"] +
                all_scores.get("smart_money", 50)      * weights["smart_money"] +
                all_scores.get("execution", 50)        * weights["execution"] +
                all_scores.get("decision", 50)         * weights["decision"]
            )

            grade = "A+" if composite >= 80 else "A" if composite >= 70 else \
                    "B+" if composite >= 65 else "B" if composite >= 60 else \
                    "C"  if composite >= 50 else "D"

            recommendation = "STRONG BUY" if composite >= 78 else \
                            "BUY"         if composite >= 65 else \
                            "NEUTRAL"     if composite >= 50 else \
                            "AVOID"       if composite >= 35 else "STRONG AVOID"

            return EngineResult(
                engine_name=self.name, score=composite,
                signal=self._signal_from_score(composite), confidence=min(95, composite),
                rationale=f"Final composite: {composite:.1f}/100 (Grade {grade}). Recommendation: {recommendation}. Group scores — Market: {all_scores.get('market_structure', 0):.0f}, Smart Money: {all_scores.get('smart_money', 0):.0f}, Execution: {all_scores.get('execution', 0):.0f}.",
                data={
                    "composite_score": round(composite, 2),
                    "grade": grade,
                    "recommendation": recommendation,
                    "group_scores": all_scores,
                    "weights_used": weights,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #31: AI CONFIDENCE ────────────────────────────────────────────────
class AIConfidenceEngine(BaseEngine):
    def __init__(self):
        super().__init__("AIConfidenceEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            composite = kwargs.get("composite_score", 50)
            all_scores = kwargs.get("all_engine_scores", {})
            engine_results = kwargs.get("engine_results", [])

            # Konsistensi antar engines
            scores_list = [r.get("score", 50) for r in engine_results if "score" in r]
            score_std = np.std(scores_list) if scores_list else 25
            consistency = max(0, 100 - score_std)

            # AI generate confidence assessment
            bullish_engines = sum(1 for r in engine_results if r.get("signal") == "bullish")
            bearish_engines = sum(1 for r in engine_results if r.get("signal") == "bearish")
            total_engines = len(engine_results)

            consensus_strength = abs(bullish_engines - bearish_engines) / total_engines if total_engines > 0 else 0
            confidence = consistency * 0.5 + consensus_strength * 100 * 0.5

            rationale = await ask_claude(
                system="You are an AI trading confidence assessor. Be concise and honest about uncertainty.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Composite score: {composite:.1f}/100
Bullish engines: {bullish_engines}/{total_engines}
Bearish engines: {bearish_engines}/{total_engines}
Score consistency (low std = high consistency): {score_std:.1f}
Consensus strength: {consensus_strength*100:.0f}%

Give a 2-sentence AI confidence assessment. Be honest if signals are mixed.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name, score=composite,
                signal=self._signal_from_score(composite),
                confidence=round(confidence, 1),
                rationale=rationale,
                data={
                    "ai_confidence": round(confidence, 1),
                    "score_consistency": round(consistency, 1),
                    "consensus_strength_pct": round(consensus_strength * 100, 1),
                    "bullish_engines": bullish_engines,
                    "bearish_engines": bearish_engines,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #32: SMART ROTATION ───────────────────────────────────────────────
class SmartRotationEngine(BaseEngine):
    def __init__(self):
        super().__init__("SmartRotationEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            composite = kwargs.get("composite_score", 50)
            alternatives = kwargs.get("alternative_stocks", [])
            closes = [c["close"] for c in ohlcv]

            ret_1m = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0

            rotation_needed = composite < 50 or ret_1m < -5
            hold_recommendation = "HOLD" if composite >= 65 else "ROTATE" if composite < 50 else "MONITOR"

            score = composite

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=65.0,
                rationale=f"Rotation recommendation: {hold_recommendation}. Composite: {composite:.0f}/100, 1M return: {ret_1m:.1f}%. {'No rotation needed — stock performing well.' if hold_recommendation == 'HOLD' else 'Consider rotating to stronger opportunities.' if hold_recommendation == 'ROTATE' else 'Monitor closely for deterioration.'}",
                data={
                    "recommendation": hold_recommendation,
                    "rotation_needed": rotation_needed,
                    "alternatives": alternatives[:3],
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #33: REALTIME ALERT ───────────────────────────────────────────────
class RealtimeAlertEngine(BaseEngine):
    def __init__(self):
        super().__init__("RealtimeAlertEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]

            alerts = []
            avg_vol = np.mean(volumes[-20:])

            # Volume spike alert
            if volumes[-1] > avg_vol * 3:
                alerts.append({"type": "volume_spike", "level": "high", "msg": f"Volume {volumes[-1]/avg_vol:.1f}x above average!"})
            elif volumes[-1] > avg_vol * 2:
                alerts.append({"type": "volume_surge", "level": "medium", "msg": f"Volume {volumes[-1]/avg_vol:.1f}x above average"})

            # Price breakout alert
            range_high = max(highs[-21:-1])
            range_low  = min(lows[-21:-1])
            if closes[-1] > range_high:
                alerts.append({"type": "breakout", "level": "high", "msg": f"Breakout above {range_high:.0f}!"})
            elif closes[-1] < range_low:
                alerts.append({"type": "breakdown", "level": "high", "msg": f"Breakdown below {range_low:.0f}!"})

            # Volatility alert
            atr = np.mean([highs[i] - lows[i] for i in range(-5, 0)])
            avg_atr = np.mean([highs[i] - lows[i] for i in range(-20, -5)])
            if atr > avg_atr * 2:
                alerts.append({"type": "volatility", "level": "medium", "msg": "Abnormal volatility detected"})

            score = 70.0 if alerts else 50.0
            high_alerts = [a for a in alerts if a["level"] == "high"]

            return EngineResult(
                engine_name=self.name, score=score,
                signal="bullish" if any(a["type"] == "breakout" for a in alerts) else
                       "bearish" if any(a["type"] == "breakdown" for a in alerts) else "neutral",
                confidence=80.0,
                rationale=f"{len(alerts)} alert(s) triggered. {high_alerts[0]['msg'] if high_alerts else 'No critical alerts.'} {'Immediate attention required.' if high_alerts else 'Monitor for developing signals.'}",
                data={"alerts": alerts, "alert_count": len(alerts), "high_priority": len(high_alerts)}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #34: LIQUIDITY QUALITY ────────────────────────────────────────────
class LiquidityQualityEngine(BaseEngine):
    def __init__(self):
        super().__init__("LiquidityQualityEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes  = [c["close"]  for c in ohlcv]
            volumes = [c["volume"] for c in ohlcv]
            highs   = [c["high"]   for c in ohlcv]
            lows    = [c["low"]    for c in ohlcv]

            # Value traded
            value_traded = [v * c for v, c in zip(volumes[-20:], closes[-20:])]
            avg_value = np.mean(value_traded)

            # Spread quality
            spreads = [(h - l) / c for h, l, c in zip(highs[-20:], lows[-20:], closes[-20:])]
            avg_spread = np.mean(spreads)

            # Market impact estimation
            market_impact = avg_spread * 100

            # Execution quality score
            min_value_by_mode = {"swing": 5e9, "daytrading": 10e9, "scalping": 20e9}
            min_val = min_value_by_mode.get(mode, 5e9)

            value_score  = min(100, avg_value / min_val * 100)
            spread_score = max(0, 100 - market_impact * 20)
            score = value_score * 0.6 + spread_score * 0.4

            quality = "EXCELLENT" if score > 80 else "GOOD" if score > 60 else "FAIR" if score > 40 else "POOR"

            return EngineResult(
                engine_name=self.name, score=score,
                signal="bullish" if score > 60 else "neutral",
                confidence=85.0,
                rationale=f"Execution quality: {quality}. Avg daily value: {avg_value/1e9:.1f}B IDR. Avg spread: {avg_spread*100:.2f}%. {'Excellent liquidity — large orders can be filled efficiently.' if quality == 'EXCELLENT' else 'Good liquidity for normal trading.' if quality == 'GOOD' else 'Fair liquidity — use limit orders.' if quality == 'FAIR' else 'Poor liquidity — avoid large positions, high slippage risk.'}",
                data={
                    "quality": quality,
                    "avg_value_idr": round(avg_value),
                    "avg_spread_pct": round(avg_spread * 100, 3),
                    "market_impact_pct": round(market_impact, 3),
                }
            )
        except Exception as e:
            return self._safe_result(str(e))
