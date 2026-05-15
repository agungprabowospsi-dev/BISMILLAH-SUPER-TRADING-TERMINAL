"""
Fase 2B — Bandar Early Detection
Deteksi awal akumulasi bandar sebelum 34 engines dijalankan
Adaptive per mode: swing/intraday/scalping
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from app.core import invesgo

logger = logging.getLogger(__name__)

# Broker institusi asing yang dikenal
FOREIGN_BROKERS = {"YP","BK","RX","ZP","AK","DB","MS","CS","ML","DP","KI"}
# Broker institusi lokal besar
LOCAL_INST_BROKERS = {"CC","OD","HD","IF","PD","KK","LG"}

async def detect_swing_accumulation(ticker: str, ohlcv: List[Dict]) -> Dict[str, Any]:
    """
    Swing: deteksi akumulasi institusi 10-30 hari
    Fokus: broker net buy + RVOL anomaly + quiet accumulation
    """
    score = 50.0
    signals = []
    
    try:
        # 1. Broker summary — net buy institusi
        brokers = await asyncio.wait_for(
            invesgo.get_broker_summary(ticker), timeout=8
        )
        
        foreign_net = 0
        local_net = 0
        foreign_buy_count = 0
        
        for b in brokers:
            code = b.get("code","")
            net = float(b.get("net_value", 0) or 0)
            if code in FOREIGN_BROKERS:
                foreign_net += net
                if net > 0:
                    foreign_buy_count += 1
            elif code in LOCAL_INST_BROKERS:
                local_net += net
        
        # Foreign net buy = strong signal
        if foreign_net > 1_000_000_000:  # > 1 M
            score += 20
            signals.append(f"Foreign net buy: +{foreign_net/1e9:.1f}M")
        elif foreign_net > 500_000_000:
            score += 12
            signals.append(f"Foreign net buy moderate: +{foreign_net/1e9:.1f}M")
        elif foreign_net < -1_000_000_000:
            score -= 15
            signals.append(f"Foreign net sell: {foreign_net/1e9:.1f}M")
        
        # Multiple foreign brokers buying = lebih valid
        if foreign_buy_count >= 3:
            score += 8
            signals.append(f"{foreign_buy_count} foreign brokers buying")
        
        # Local institutional net buy
        if local_net > 500_000_000:
            score += 10
            signals.append(f"Local institutional buy: +{local_net/1e9:.1f}M")
        
    except Exception as e:
        logger.debug(f"Broker summary skip {ticker}: {e}")
        # Fallback ke OHLCV-based detection
        score = _ohlcv_swing_score(ohlcv)
        signals.append("OHLCV-based (broker unavailable)")
    
    # 2. RVOL anomaly check dari OHLCV
    ohlcv_signals = _ohlcv_swing_score(ohlcv, return_dict=True)
    score += ohlcv_signals.get("bonus", 0)
    signals.extend(ohlcv_signals.get("signals", []))
    
    return {
        "akumulasi_score": round(min(95, max(5, score)), 1),
        "mode": "swing",
        "signals": signals,
        "detection_method": "broker_summary + ohlcv"
    }

async def detect_intraday_accumulation(ticker: str, ohlcv: List[Dict]) -> Dict[str, Any]:
    """
    Intraday: deteksi flow hari ini
    Fokus: volume hari ini vs rata-rata + gap + opening strength
    """
    score = 50.0
    signals = []
    
    if len(ohlcv) < 5:
        return {"akumulasi_score": 50.0, "mode": "intraday", "signals": [], "detection_method": "insufficient_data"}
    
    # 1. Volume hari ini vs rata-rata 20 hari
    volumes = [float(c.get("volume", 0) or 0) for c in ohlcv]
    avg_vol_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes) / len(volumes)
    today_vol = volumes[-1]
    rvol = today_vol / avg_vol_20 if avg_vol_20 > 0 else 1
    
    if rvol >= 2.5:
        score += 20
        signals.append(f"Volume spike ekstrem: {rvol:.1f}x")
    elif rvol >= 1.8:
        score += 12
        signals.append(f"Volume spike tinggi: {rvol:.1f}x")
    elif rvol >= 1.3:
        score += 6
        signals.append(f"Volume di atas rata-rata: {rvol:.1f}x")
    elif rvol < 0.7:
        score -= 10
        signals.append(f"Volume sepi: {rvol:.1f}x")
    
    # 2. Gap analysis
    if len(ohlcv) >= 2:
        today = ohlcv[-1]
        yesterday = ohlcv[-2]
        today_open = float(today.get("open", 0) or 0)
        yesterday_close = float(yesterday.get("close", 0) or 0)
        if yesterday_close > 0:
            gap_pct = ((today_open - yesterday_close) / yesterday_close) * 100
            if gap_pct > 2:
                score += 15
                signals.append(f"Gap up: +{gap_pct:.1f}%")
            elif gap_pct > 0.5:
                score += 8
                signals.append(f"Gap up kecil: +{gap_pct:.1f}%")
            elif gap_pct < -2:
                score -= 12
                signals.append(f"Gap down: {gap_pct:.1f}%")
    
    # 3. Price action hari ini
    today = ohlcv[-1]
    close = float(today.get("close", 0) or 0)
    open_ = float(today.get("open", 0) or 0)
    high = float(today.get("high", 0) or 0)
    low = float(today.get("low", 0) or 0)
    
    if close > 0 and open_ > 0:
        body = abs(close - open_)
        range_ = high - low if high > low else 1
        body_ratio = body / range_
        
        # Candle bullish kuat
        if close > open_ and body_ratio > 0.6 and rvol > 1.3:
            score += 10
            signals.append("Candle bullish kuat dengan volume")
    
    return {
        "akumulasi_score": round(min(95, max(5, score)), 1),
        "mode": "intraday",
        "signals": signals,
        "rvol": round(rvol, 2),
        "detection_method": "volume + gap + price_action"
    }

async def detect_scalping_accumulation(ticker: str, ohlcv: List[Dict]) -> Dict[str, Any]:
    """
    Scalping: deteksi momentum burst
    Fokus: momentum 3-5 candle terakhir + volume burst
    """
    score = 50.0
    signals = []
    
    if len(ohlcv) < 5:
        return {"akumulasi_score": 50.0, "mode": "scalping", "signals": [], "detection_method": "insufficient_data"}
    
    # 1. Momentum 5 candle terakhir
    last5 = ohlcv[-5:]
    closes = [float(c.get("close", 0) or 0) for c in last5]
    volumes = [float(c.get("volume", 0) or 0) for c in last5]
    
    up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    down_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])
    
    if up_count >= 4:
        score += 18
        signals.append(f"Momentum kuat: {up_count}/4 candle naik")
    elif up_count >= 3:
        score += 10
        signals.append(f"Momentum moderat: {up_count}/4 candle naik")
    elif down_count >= 4:
        score -= 15
        signals.append(f"Momentum bearish: {down_count}/4 candle turun")
    
    # 2. Volume burst
    avg_vol = sum(volumes[:-1]) / max(1, len(volumes)-1)
    last_vol = volumes[-1]
    if avg_vol > 0:
        vol_ratio = last_vol / avg_vol
        if vol_ratio >= 2.0:
            score += 15
            signals.append(f"Volume burst: {vol_ratio:.1f}x")
        elif vol_ratio >= 1.5:
            score += 8
            signals.append(f"Volume naik: {vol_ratio:.1f}x")
    
    # 3. Price momentum
    if len(closes) >= 2 and closes[0] > 0:
        momentum_pct = ((closes[-1] - closes[0]) / closes[0]) * 100
        if momentum_pct > 1.5:
            score += 12
            signals.append(f"Price momentum: +{momentum_pct:.1f}%")
        elif momentum_pct > 0.5:
            score += 6
        elif momentum_pct < -1.5:
            score -= 12
    
    return {
        "akumulasi_score": round(min(95, max(5, score)), 1),
        "mode": "scalping",
        "signals": signals,
        "detection_method": "momentum + volume_burst"
    }

def _ohlcv_swing_score(ohlcv: List[Dict], return_dict: bool = False):
    """OHLCV-based swing score sebagai fallback"""
    if len(ohlcv) < 20:
        if return_dict:
            return {"bonus": 0, "signals": []}
        return 50.0
    
    bonus = 0
    signals = []
    
    volumes = [float(c.get("volume", 0) or 0) for c in ohlcv[-20:]]
    closes = [float(c.get("close", 0) or 0) for c in ohlcv[-20:]]
    
    avg_vol = sum(volumes[:-5]) / max(1, len(volumes)-5)
    recent_vol = sum(volumes[-5:]) / 5
    
    # Quiet accumulation: harga sideways tapi volume naik
    price_range = ((max(closes) - min(closes)) / min(closes)) * 100 if min(closes) > 0 else 100
    rvol_recent = recent_vol / avg_vol if avg_vol > 0 else 1
    
    if price_range < 10 and rvol_recent > 1.3:
        bonus += 15
        signals.append(f"Quiet accumulation: range {price_range:.1f}%, vol {rvol_recent:.1f}x")
    elif price_range < 15 and rvol_recent > 1.5:
        bonus += 10
        signals.append(f"Possible accumulation: range {price_range:.1f}%")
    
    if return_dict:
        return {"bonus": bonus, "signals": signals}
    return 50.0 + bonus

async def get_bandar_early_score(ticker: str, mode: str, ohlcv: List[Dict]) -> Dict[str, Any]:
    """
    Main function — panggil ini dari screener Fase 2B
    Returns akumulasi_score + signals per mode
    """
    try:
        if mode == "swing":
            result = await detect_swing_accumulation(ticker, ohlcv)
        elif mode == "intraday":
            result = await detect_intraday_accumulation(ticker, ohlcv)
        elif mode == "scalping":
            result = await detect_scalping_accumulation(ticker, ohlcv)
        else:
            result = await detect_swing_accumulation(ticker, ohlcv)
        
        return result
    except Exception as e:
        logger.error(f"Bandar early detection error {ticker}: {e}")
        return {
            "akumulasi_score": 50.0,
            "mode": mode,
            "signals": ["detection_failed"],
            "detection_method": "fallback"
        }

def apply_akumulasi_multiplier(
    composite_score: float,
    akumulasi_score: float,
    mode: str
) -> float:
    """
    Terapkan akumulasi multiplier ke composite score
    Weight berbeda per mode sesuai diskusi
    """
    weights = {
        "swing":    0.25,  # 25% dari final score
        "intraday": 0.15,  # 15%
        "scalping": 0.05,  # 5%
    }
    weight = weights.get(mode, 0.15)
    
    # Blend: composite score + akumulasi boost
    akumulasi_boost = (akumulasi_score - 50) * weight
    final = composite_score + akumulasi_boost
    
    return round(min(100, max(0, final)), 2)
