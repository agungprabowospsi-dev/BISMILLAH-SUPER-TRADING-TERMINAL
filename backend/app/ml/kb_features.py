"""
KB Features Extractor — Extract insight numerik dari Knowledge Base context
untuk memperkuat ML Engine dengan wisdom dari 10+ buku trading
"""
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def extract_kb_features(kb_context: str) -> Dict[str, float]:
    """
    Extract fitur numerik dari KB context (RAG output)
    Returns dict of features untuk ML model
    """
    if not kb_context:
        return _default_features()
    
    text = kb_context.lower()
    features = {}

    # 1. Win Rate mentions — "win rate 70%", "success rate 65%", "akurasi 75%"
    win_rates = re.findall(r'(?:win rate|success rate|akurasi|accuracy)[:\s]+(\d+(?:\.\d+)?)\s*%', text)
    if win_rates:
        features['kb_win_rate'] = min(95.0, max(5.0, float(win_rates[0]))) / 100.0
    else:
        features['kb_win_rate'] = 0.5

    # 2. Risk Reward mentions — "rr 1:3", "risk reward 2:1", "target 3x risk"
    rr_patterns = re.findall(r'(?:rr|risk.reward|reward.risk)[:\s]+(\d+(?:\.\d+)?)[:\s]+(\d+(?:\.\d+)?)', text)
    if rr_patterns:
        r_val, reward = float(rr_patterns[0][0]), float(rr_patterns[0][1])
        features['kb_rr_ratio'] = min(10.0, reward / r_val if r_val > 0 else 1.0) / 10.0
    else:
        features['kb_rr_ratio'] = 0.2  # default 2:1

    # 3. Volume confirmation signal
    vol_bullish = sum(1 for w in ['volume tinggi', 'high volume', 'volume naik', 'volume besar', 
                                   'accumulation', 'akumulasi', 'volume konfirmasi'] if w in text)
    vol_bearish = sum(1 for w in ['volume rendah', 'low volume', 'distribusi', 'distribution',
                                   'volume turun', 'no volume'] if w in text)
    features['kb_volume_signal'] = min(1.0, max(0.0, 0.5 + (vol_bullish - vol_bearish) * 0.15))

    # 4. Trend confirmation
    trend_bull = sum(1 for w in ['uptrend', 'trend naik', 'bullish trend', 'higher high', 
                                  'momentum positif', 'breakout'] if w in text)
    trend_bear = sum(1 for w in ['downtrend', 'trend turun', 'bearish trend', 'lower low',
                                  'breakdown', 'momentum negatif'] if w in text)
    features['kb_trend_signal'] = min(1.0, max(0.0, 0.5 + (trend_bull - trend_bear) * 0.15))

    # 5. Bandar/Institutional signal (khusus buku Bandarmology)
    bandar_bull = sum(1 for w in ['bandar beli', 'akumulasi bandar', 'institutional buy',
                                   'foreign buy', 'net buy', 'bandar masuk'] if w in text)
    bandar_bear = sum(1 for w in ['bandar jual', 'distribusi bandar', 'institutional sell',
                                   'foreign sell', 'net sell', 'bandar keluar'] if w in text)
    features['kb_bandar_signal'] = min(1.0, max(0.0, 0.5 + (bandar_bull - bandar_bear) * 0.2))

    # 6. Pattern quality (dari Encyclopedia of Chart Patterns - Bulkowski)
    high_quality = sum(1 for w in ['high probability', 'reliable pattern', 'strong setup',
                                    'pola kuat', 'setup bagus', 'konfirmasi kuat'] if w in text)
    low_quality = sum(1 for w in ['low probability', 'weak setup', 'false signal',
                                   'pola lemah', 'sinyal palsu', 'risky'] if w in text)
    features['kb_pattern_quality'] = min(1.0, max(0.0, 0.5 + (high_quality - low_quality) * 0.2))

    # 7. KB consensus — berapa banyak KB bagian yang support setup
    kb_sections = kb_context.split('---')
    supporting = 0
    for section in kb_sections:
        sec = section.lower()
        bull_words = sum(1 for w in ['buy', 'bullish', 'naik', 'akumulasi', 'breakout'] if w in sec)
        bear_words = sum(1 for w in ['sell', 'bearish', 'turun', 'distribusi', 'breakdown'] if w in sec)
        if bull_words > bear_words:
            supporting += 1
    total_sections = max(1, len(kb_sections))
    features['kb_consensus'] = supporting / total_sections

    # 8. López de Prado — Triple Barrier / Meta-labeling hints
    ml_signals = sum(1 for w in ['triple barrier', 'meta.label', 'purged', 'embargo',
                                   'feature importance', 'fractional', 'bet sizing'] if w in text)
    features['kb_quant_signal'] = min(1.0, ml_signals * 0.2)

    # 9. Fibonacci levels (dari buku Fibonacci Trading - Boroden)
    fib_bull = sum(1 for w in ['fibonacci support', 'fib 0.618', 'fib 0.382', 
                                'golden ratio support', 'fib retracement buy'] if w in text)
    features['kb_fib_signal'] = min(1.0, fib_bull * 0.25)

    # 10. Market Microstructure (Larry Harris — Trading and Exchanges)
    micro_bull = sum(1 for w in [
        'bid ask spread', 'order flow', 'market depth', 'liquidity',
        'price impact', 'informed trader', 'institutional order',
        'buying pressure', 'demand exceeds', 'order imbalance'
    ] if w in text)
    micro_bear = sum(1 for w in [
        'selling pressure', 'supply exceeds', 'thin market',
        'wide spread', 'illiquid', 'adverse selection'
    ] if w in text)
    features['kb_microstructure'] = min(1.0, max(0.0, 0.5 + (micro_bull - micro_bear) * 0.15))

    # 11. Overall KB bullish score — update ke 11 komponen
    all_bull = sum(v for k, v in features.items() if 'signal' in k or 'quality' in k or 'consensus' in k or 'microstructure' in k)
    features['kb_overall'] = all_bull / 7.0  # normalize ke 0-1

    logger.debug(f"KB Features extracted: {features}")
    return features

def _default_features() -> Dict[str, float]:
    """Default features ketika tidak ada KB context"""
    return {
        'kb_win_rate': 0.5,
        'kb_rr_ratio': 0.2,
        'kb_volume_signal': 0.5,
        'kb_trend_signal': 0.5,
        'kb_bandar_signal': 0.5,
        'kb_pattern_quality': 0.5,
        'kb_consensus': 0.5,
        'kb_quant_signal': 0.0,
        'kb_fib_signal': 0.0,
        'kb_microstructure': 0.5,
        'kb_overall': 0.5,
    }

def kb_features_to_array(kb_context: str) -> list:
    """Convert KB context ke array numerik untuk ML feature vector"""
    features = extract_kb_features(kb_context)
    keys = sorted(features.keys())
    return [features[k] for k in keys]
