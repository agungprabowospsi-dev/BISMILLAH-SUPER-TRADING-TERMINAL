import numpy as np
from app.engines.base_engine import BaseEngine, EngineResult
from app.core.claude_client import ask_claude
from app.core.knowledge_base import query_knowledge_base
from app.engines.orderbook_microstructure import build_orderbook_execution_overlay, normalize_orderbook


# ─── ENGINE #16: QUANT EDGE ───────────────────────────────────────────────────
class QuantEdgeEngine(BaseEngine):
    def __init__(self):
        super().__init__("QuantEdgeEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = np.array([c["close"] for c in ohlcv])
            returns = np.diff(closes) / closes[:-1]

            sharpe = self._sharpe(returns)
            win_rate = sum(1 for r in returns[-20:] if r > 0) / 20
            avg_win  = np.mean([r for r in returns[-20:] if r > 0]) if any(r > 0 for r in returns[-20:]) else 0
            avg_loss = abs(np.mean([r for r in returns[-20:] if r < 0])) if any(r < 0 for r in returns[-20:]) else 0.001
            profit_factor = (win_rate * avg_win) / ((1 - win_rate) * avg_loss) if avg_loss > 0 else 1

            score = 50.0
            if sharpe > 1.5 and win_rate > 0.55:
                score = 82.0
            elif sharpe > 1.0 and win_rate > 0.5:
                score = 68.0
            elif sharpe < 0:
                score = 25.0
            elif win_rate < 0.4:
                score = 35.0

            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=70.0,
                rationale=f"Sharpe: {sharpe:.2f}, Win rate: {win_rate*100:.0f}%, Profit factor: {profit_factor:.2f}. {'Strong quantitative edge detected.' if score > 65 else 'Weak edge — unfavorable risk/reward statistics.' if score < 40 else 'Moderate edge.'}",
                data={"sharpe": round(sharpe, 2), "win_rate": round(win_rate, 3), "profit_factor": round(profit_factor, 2)}
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _sharpe(self, returns, rf=0.0):
        if len(returns) < 2:
            return 0
        excess = returns - rf / 252
        return float(np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0


# ─── ENGINE #17: ORDERBOOK ────────────────────────────────────────────────────
class OrderbookEngine(BaseEngine):
    def __init__(self):
        super().__init__("OrderbookEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            ob = kwargs.get("orderbook") or {}
            normalized = normalize_orderbook(ob)
            bids = normalized.get("bids", [])
            asks = normalized.get("asks", [])

            if not bids or not asks:
                # Proxy dari OHLCV
                closes = [c["close"] for c in ohlcv]
                spread_proxy = (ohlcv[-1]["high"] - ohlcv[-1]["low"]) / closes[-1] * 100
                score = max(20, 70 - spread_proxy * 10)
                return EngineResult(
                    engine_name=self.name, score=score,
                    signal=self._signal_from_score(score), confidence=30.0,
                    rationale=f"No orderbook data. Spread proxy: {spread_proxy:.2f}%.",
                    data={"data_source": "proxy", "spread_proxy_pct": round(spread_proxy, 3)}
                )

            depth = 10 if str(mode).lower() in ("intraday", "daytrading", "scalping") else 5
            total_bid = sum(b["lot"] for b in bids[:depth]) if bids else 0
            total_ask = sum(a["lot"] for a in asks[:depth]) if asks else 0
            bid_ask_ratio = total_bid / total_ask if total_ask > 0 else 1
            overlay = build_orderbook_execution_overlay(ob, mode=mode)

            score = 50.0
            if bid_ask_ratio > 2:
                score = 80.0
            elif bid_ask_ratio > 1.3:
                score = 65.0
            elif bid_ask_ratio < 0.5:
                score = 20.0
            elif bid_ask_ratio < 0.8:
                score = 35.0
            if overlay.get("spread_health") == "wide":
                score = max(20, score - 10)
            if overlay.get("fake_bid_wall"):
                score = max(20, score - 12)

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=80.0,
                rationale=f"Bid/Ask ratio: {bid_ask_ratio:.2f}. Total bid: {total_bid:,.0f}, Total ask: {total_ask:,.0f}. {'Strong buy wall — bullish orderbook pressure.' if bid_ask_ratio > 1.5 else 'Heavy ask wall — selling pressure dominates.' if bid_ask_ratio < 0.7 else 'Balanced orderbook.'}",
                data={
                    "bid_ask_ratio": round(bid_ask_ratio, 3),
                    "total_bid": total_bid,
                    "total_ask": total_ask,
                    "spread_pct": normalized.get("spread_pct", 0),
                    "execution_recommendation": overlay.get("execution_recommendation"),
                    "liquidity_bias": overlay.get("liquidity_bias"),
                    "spread_health": overlay.get("spread_health"),
                    "support_wall_price": overlay.get("support_wall_price"),
                    "resistance_wall_price": overlay.get("resistance_wall_price"),
                    "fake_bid_wall": overlay.get("fake_bid_wall"),
                    "source": normalized.get("source"),
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #18: RELATIVE STRENGTH ───────────────────────────────────────────
class RelativeStrengthEngine(BaseEngine):
    def __init__(self):
        super().__init__("RelativeStrengthEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = [c["close"] for c in ohlcv]
            ihsg   = kwargs.get("ihsg_data", [])

            # RSI
            rsi = self._calc_rsi(closes)
            rsi_signal = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"

            # RS vs IHSG jika ada
            rs_score = 50.0
            if ihsg and len(ihsg) >= 20:
                stock_ret = (closes[-1] - closes[-20]) / closes[-20]
                ihsg_ret  = (ihsg[-1] - ihsg[-20]) / ihsg[-20]
                rs = stock_ret - ihsg_ret
                rs_score = 50 + rs * 200

            score = rsi * 0.5 + rs_score * 0.5
            score = max(0, min(100, score))

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=72.0,
                rationale=f"RSI: {rsi:.1f} ({rsi_signal}). RS vs IHSG score: {rs_score:.1f}. {'Strong momentum — stock outperforming market.' if score > 65 else 'Weak relative strength — underperforming.' if score < 40 else 'Average relative strength.'}",
                data={"rsi": round(rsi, 2), "rsi_signal": rsi_signal, "rs_score": round(rs_score, 2)}
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _calc_rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))


# ─── ENGINE #19: FIBONACCI ────────────────────────────────────────────────────
class FibonacciEngine(BaseEngine):
    def __init__(self):
        super().__init__("FibonacciEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]
            closes = [c["close"] for c in ohlcv]
            current = closes[-1]

            swing_high = max(highs[-50:]) if len(highs) >= 50 else max(highs)
            swing_low  = min(lows[-50:])  if len(lows)  >= 50 else min(lows)
            diff = swing_high - swing_low

            # Fibonacci levels
            fib_levels = {
                "0": swing_low,
                "0.236": swing_low + diff * 0.236,
                "0.382": swing_low + diff * 0.382,
                "0.5":   swing_low + diff * 0.5,
                "0.618": swing_low + diff * 0.618,
                "0.786": swing_low + diff * 0.786,
                "1.0":   swing_high,
            }

            # Cari level terdekat
            nearest = min(fib_levels.items(), key=lambda x: abs(x[1] - current))
            dist_pct = abs(nearest[1] - current) / current * 100

            # Score: makin dekat ke fib support = bullish
            fib_val = float(nearest[0])
            if dist_pct < 1.0:
                if fib_val in [0.382, 0.5, 0.618]:
                    score = 78.0  # Di level golden ratio
                elif fib_val == 0.236:
                    score = 70.0
                else:
                    score = 55.0
            else:
                score = 50.0

            # Apakah sedang retracement atau extension?
            trend = "retracement" if current < swing_high * 0.95 else "extension"

            kb_context = await query_knowledge_base("carolyn_boroden", f"fibonacci {nearest[0]} retracement level")

            rationale = await ask_claude(
                system="You are a Fibonacci trading expert using Carolyn Boroden methodology.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Swing High: {swing_high:.0f} | Swing Low: {swing_low:.0f}
Current: {current:.0f} | Trend: {trend}
Nearest Fibonacci: {nearest[0]} at {nearest[1]:.0f} (distance: {dist_pct:.2f}%)

Reference (Boroden): {kb_context[:400] if kb_context else 'N/A'}

2-sentence Fibonacci analysis with entry/target implication.
""",
                max_tokens=150
            )

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=75.0,
                rationale=rationale,
                data={
                    "swing_high": swing_high, "swing_low": swing_low,
                    "fib_levels": {k: round(v, 2) for k, v in fib_levels.items()},
                    "nearest_level": nearest[0], "nearest_price": round(nearest[1], 2),
                    "distance_pct": round(dist_pct, 2), "trend": trend,
                }
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #20: AI PATTERN RECOGNITION ──────────────────────────────────────
class AIPatternRecognitionEngine(BaseEngine):
    def __init__(self):
        super().__init__("AIPatternRecognitionEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            last5 = ohlcv[-5:]
            candles = [{
                "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"],
                "body": c["close"] - c["open"],
                "upper_wick": c["high"] - max(c["open"], c["close"]),
                "lower_wick": min(c["open"], c["close"]) - c["low"],
            } for c in last5]

            # Detect patterns
            patterns = self._detect_patterns(candles)
            kb_context = await query_knowledge_base("candlestick_patterns", f"{' '.join(patterns)} candlestick pattern")

            score = 50.0
            bullish_patterns = ["hammer", "bullish_engulfing", "morning_star", "doji_bottom", "piercing"]
            bearish_patterns = ["shooting_star", "bearish_engulfing", "evening_star", "hanging_man"]

            bull_count = sum(1 for p in patterns if p in bullish_patterns)
            bear_count = sum(1 for p in patterns if p in bearish_patterns)

            if bull_count > bear_count:
                score = 65 + bull_count * 8
            elif bear_count > bull_count:
                score = 35 - bear_count * 8
            score = max(5, min(95, score))

            rationale = await ask_claude(
                system="You are a candlestick pattern expert using Bulkowski's Encyclopedia methodology.",
                prompt=f"""
Ticker: {ticker} | Mode: {mode}
Detected patterns: {patterns if patterns else ['no clear pattern']}
Last 5 candles: {[{'body': round(c['body'],0), 'upper': round(c['upper_wick'],0), 'lower': round(c['lower_wick'],0)} for c in candles]}

Reference (Bulkowski): {kb_context[:400] if kb_context else 'N/A'}

2-sentence pattern analysis with historical success rate and trading implication.
""",
                max_tokens=180
            )

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=68.0,
                rationale=rationale,
                data={"patterns_detected": patterns, "bullish_count": bull_count, "bearish_count": bear_count}
            )
        except Exception as e:
            return self._safe_result(str(e))

    def _detect_patterns(self, candles):
        patterns = []
        if not candles:
            return patterns
        last = candles[-1]
        body = abs(last["body"])
        total_range = last["upper_wick"] + last["lower_wick"] + body

        if total_range == 0:
            return patterns

        # Hammer
        if last["lower_wick"] > body * 2 and last["upper_wick"] < body * 0.5:
            patterns.append("hammer")

        # Shooting star
        if last["upper_wick"] > body * 2 and last["lower_wick"] < body * 0.5:
            patterns.append("shooting_star")

        # Doji
        if body < total_range * 0.1:
            patterns.append("doji")

        # Engulfing (perlu 2 candle)
        if len(candles) >= 2:
            prev = candles[-2]
            if (last["body"] > 0 and prev["body"] < 0 and
                    last["close"] > prev["open"] and last["open"] < prev["close"]):
                patterns.append("bullish_engulfing")
            elif (last["body"] < 0 and prev["body"] > 0 and
                    last["close"] < prev["open"] and last["open"] > prev["close"]):
                patterns.append("bearish_engulfing")

        return patterns


# ─── ENGINE #21: SECTOR ROTATION ─────────────────────────────────────────────
class SectorRotationEngine(BaseEngine):
    def __init__(self):
        super().__init__("SectorRotationEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            sector = kwargs.get("sector", "unknown")
            sector_data = kwargs.get("sector_data", {})
            closes = [c["close"] for c in ohlcv]

            # Momentum sektor 1 bulan
            ret_1m = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0
            ret_1w = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0

            score = 50.0
            if ret_1m > 5 and ret_1w > 1:
                score = 72.0
            elif ret_1m > 2:
                score = 62.0
            elif ret_1m < -5:
                score = 28.0
            elif ret_1m < -2:
                score = 38.0

            hot_sectors = sector_data.get("hot_sectors", [])
            if sector in hot_sectors:
                score = min(85, score + 10)

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=60.0,
                rationale=f"Sector: {sector}. 1M return: {ret_1m:.1f}%, 1W return: {ret_1w:.1f}%. {'Sector in strong uptrend — rotation favors this sector.' if score > 65 else 'Sector underperforming — consider rotation out.' if score < 40 else 'Neutral sector momentum.'}",
                data={"sector": sector, "ret_1m_pct": round(ret_1m, 2), "ret_1w_pct": round(ret_1w, 2)}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #22: MACRO MARKET ─────────────────────────────────────────────────
class MacroMarketEngine(BaseEngine):
    def __init__(self):
        super().__init__("MacroMarketEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            ihsg = kwargs.get("ihsg_data", [])
            closes = [c["close"] for c in ohlcv]

            if not ihsg or len(ihsg) < 20:
                ret = (closes[-1] - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 else 0
                score = 55.0 if ret > 0 else 45.0
                return EngineResult(
                    engine_name=self.name, score=score, signal=self._signal_from_score(score),
                    confidence=40.0, rationale="No IHSG data available. Using stock momentum as proxy.",
                    data={"data_source": "proxy"}
                )

            ihsg_ret_1m = (ihsg[-1] - ihsg[-20]) / ihsg[-20] * 100
            ihsg_trend = "bull" if ihsg[-1] > np.mean(ihsg[-20:]) else "bear"

            score = 55.0 if ihsg_trend == "bull" else 45.0
            if ihsg_ret_1m > 3:
                score = 70.0
            elif ihsg_ret_1m < -3:
                score = 30.0

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=65.0,
                rationale=f"IHSG trend: {ihsg_trend}. IHSG 1M return: {ihsg_ret_1m:.1f}%. {'Bullish market condition supports long positions.' if score > 60 else 'Bearish market condition — reduce exposure.' if score < 40 else 'Neutral market.'}",
                data={"ihsg_trend": ihsg_trend, "ihsg_ret_1m": round(ihsg_ret_1m, 2)}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #23: MACRO ECONOMICS ──────────────────────────────────────────────
class MacroEconomicsEngine(BaseEngine):
    def __init__(self):
        super().__init__("MacroEconomicsEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            macro = kwargs.get("macro_data", {})
            bi_rate = macro.get("bi_rate", 6.0)
            inflation = macro.get("inflation", 3.0)
            gdp_growth = macro.get("gdp_growth", 5.0)
            usd_idr = macro.get("usd_idr", 15500)

            # Score macro Indonesia
            score = 50.0
            if bi_rate < 6.0:
                score += 8   # Suku bunga rendah = bullish
            elif bi_rate > 7.0:
                score -= 8

            if inflation < 3.5:
                score += 5
            elif inflation > 5.0:
                score -= 10

            if gdp_growth > 5.0:
                score += 7
            elif gdp_growth < 4.0:
                score -= 7

            if usd_idr < 15000:
                score += 5
            elif usd_idr > 16000:
                score -= 8

            score = max(10, min(90, score))

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=60.0,
                rationale=f"BI Rate: {bi_rate}%, Inflation: {inflation}%, GDP: {gdp_growth}%, USD/IDR: {usd_idr:,.0f}. {'Favorable macro conditions for Indonesian equities.' if score > 60 else 'Challenging macro environment — be selective.' if score < 40 else 'Neutral macro backdrop.'}",
                data={"bi_rate": bi_rate, "inflation": inflation, "gdp_growth": gdp_growth, "usd_idr": usd_idr}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #24: GEOPOLITICS ──────────────────────────────────────────────────
class GeopoliticsEngine(BaseEngine):
    def __init__(self):
        super().__init__("GeopoliticsEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            geo = kwargs.get("geo_data", {})
            risk_level = geo.get("risk_level", "low")
            events = geo.get("events", [])

            score_map = {"low": 65, "medium": 50, "high": 30, "critical": 15}
            score = float(score_map.get(risk_level, 50))

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=50.0,
                rationale=f"Geopolitical risk: {risk_level}. Active events: {len(events)}. {'Low geopolitical risk supports risk-on positioning.' if score > 60 else 'Elevated geopolitical risk — reduce position size.' if score < 40 else 'Moderate geopolitical environment.'}",
                data={"risk_level": risk_level, "events": events[:3]}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #25: NEWS & SENTIMENT ─────────────────────────────────────────────
class NewsSentimentEngine(BaseEngine):
    def __init__(self):
        super().__init__("NewsSentimentEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            news = kwargs.get("news_data", [])
            closes = [c["close"] for c in ohlcv]

            if not news:
                # Proxy: gap up/down sebagai news proxy
                gap = (ohlcv[-1]["open"] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0
                score = 60.0 if gap > 1 else 40.0 if gap < -1 else 50.0
                return EngineResult(
                    engine_name=self.name, score=score, signal=self._signal_from_score(score),
                    confidence=30.0, rationale=f"No news data. Gap proxy: {gap:.2f}%.",
                    data={"gap_proxy": round(gap, 2)}
                )

            pos = sum(1 for n in news if n.get("sentiment") == "positive")
            neg = sum(1 for n in news if n.get("sentiment") == "negative")
            total = len(news)

            sentiment_score = (pos - neg) / total * 50 + 50 if total > 0 else 50
            score = max(10, min(90, sentiment_score))

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=65.0,
                rationale=f"News sentiment: {pos} positive, {neg} negative of {total} articles. {'Positive news flow supports bullish momentum.' if score > 60 else 'Negative sentiment creating headwinds.' if score < 40 else 'Mixed news sentiment.'}",
                data={"positive": pos, "negative": neg, "total": total, "sentiment_score": round(score, 1)}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #26: INSIDER/OWNERSHIP ───────────────────────────────────────────
class InsiderOwnershipEngine(BaseEngine):
    def __init__(self):
        super().__init__("InsiderOwnershipEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            insider = kwargs.get("insider_data", {})
            insider_buy  = insider.get("insider_buy_3m", 0)
            insider_sell = insider.get("insider_sell_3m", 0)
            inst_ownership = insider.get("institutional_ownership_pct", 50)

            score = 50.0
            if insider_buy > insider_sell * 2:
                score = 78.0
            elif insider_buy > insider_sell:
                score = 65.0
            elif insider_sell > insider_buy * 2:
                score = 22.0
            elif insider_sell > insider_buy:
                score = 38.0

            if inst_ownership > 60:
                score = min(85, score + 5)

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=65.0,
                rationale=f"Insider 3M: Buy={insider_buy}, Sell={insider_sell}. Institutional ownership: {inst_ownership}%. {'Insider buying signals confidence in future performance.' if score > 65 else 'Insider selling may indicate concerns — caution warranted.' if score < 40 else 'Neutral insider activity.'}",
                data={"insider_buy": insider_buy, "insider_sell": insider_sell, "institutional_pct": inst_ownership}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #27: PROBABILITY ──────────────────────────────────────────────────
class ProbabilityEngine(BaseEngine):
    def __init__(self):
        super().__init__("ProbabilityEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = np.array([c["close"] for c in ohlcv])
            returns = np.diff(closes) / closes[:-1]

            # Historical win rate per mode
            hold_days = {"swing": 15, "daytrading": 1, "scalping": 1}
            days = hold_days.get(mode, 5)

            wins = sum(1 for i in range(len(closes) - days - 1)
                      if closes[i + days] > closes[i])
            total = len(closes) - days - 1
            hist_win_rate = wins / total if total > 0 else 0.5

            # Volatility-adjusted probability
            vol = np.std(returns[-20:]) * np.sqrt(252)
            vol_penalty = max(0, (vol - 0.3) * 50)

            prob_score = hist_win_rate * 100 - vol_penalty
            score = max(10, min(90, prob_score))

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=70.0,
                rationale=f"Historical win rate ({days}D hold): {hist_win_rate*100:.0f}%. Annual vol: {vol*100:.1f}%. Probability score: {score:.0f}/100. {'High probability setup based on historical patterns.' if score > 65 else 'Low probability — unfavorable historical stats for this setup.' if score < 40 else 'Moderate probability.'}",
                data={"hist_win_rate": round(hist_win_rate, 3), "annual_vol": round(vol, 3), "hold_days": days}
            )
        except Exception as e:
            return self._safe_result(str(e))


# ─── ENGINE #28: TRADING SETUP ────────────────────────────────────────────────
class TradingSetupEngine(BaseEngine):
    def __init__(self):
        super().__init__("TradingSetupEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            closes = [c["close"] for c in ohlcv]
            highs  = [c["high"]  for c in ohlcv]
            lows   = [c["low"]   for c in ohlcv]
            current = closes[-1]

            # Compile scores dari engines lain jika ada
            other_scores = kwargs.get("other_scores", [])
            avg_score = np.mean(other_scores) if other_scores else 50.0

            # Setup quality berdasarkan confluence
            atr = np.mean([max(highs[i] - lows[i],
                              abs(highs[i] - closes[i-1]),
                              abs(lows[i] - closes[i-1]))
                          for i in range(1, min(15, len(ohlcv)))]) if len(ohlcv) > 1 else current * 0.02

            # R:R minimum
            sl = current - atr * 1.5
            tp = current + atr * 2.5
            rr = (tp - current) / (current - sl) if current != sl else 0

            setup_quality = "A+" if avg_score > 75 and rr > 2 else \
                           "A"  if avg_score > 65 and rr > 1.5 else \
                           "B"  if avg_score > 55 else \
                           "C"  if avg_score > 45 else "D"

            score = avg_score

            return EngineResult(
                engine_name=self.name, score=score,
                signal=self._signal_from_score(score), confidence=min(90, avg_score),
                rationale=f"Setup grade: {setup_quality}. Composite score: {avg_score:.1f}/100. R:R ratio: {rr:.2f}. {'Excellent setup — all factors aligned.' if setup_quality in ['A+', 'A'] else 'Decent setup — proceed with normal sizing.' if setup_quality == 'B' else 'Poor setup — skip or reduce size significantly.'}",
                data={"setup_quality": setup_quality, "avg_score": round(avg_score, 2),
                      "suggested_sl": round(sl, 0), "suggested_tp": round(tp, 0), "rr": round(rr, 2)}
            )
        except Exception as e:
            return self._safe_result(str(e))
