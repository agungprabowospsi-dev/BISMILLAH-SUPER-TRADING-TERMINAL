"""
Signal Quality Predictor — ML Engine #1
Prediksi win probability (0-100%) dari 34 engine scores + market regime
"""
import numpy as np
import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from app.ml.kb_features import kb_features_to_array, extract_kb_features

logger = logging.getLogger(__name__)

# Model disimpan di memory (tidak perlu file)
_model = None
_model_meta = {}
_training_data = []  # Buffer training data dari forward test

def _build_features(engine_scores: Dict, market_regime: str, lq45_change: float, breadth_ratio: float, kb_context: str = "") -> np.ndarray:
    """Convert engine scores + market context ke feature vector"""
    
    # Regime encoding
    regime_map = {
        'STRONG BULL': 1.0,
        'BULL': 0.75,
        'SIDEWAYS': 0.5,
        'BEAR': 0.25,
        'STRONG BEAR': 0.0
    }
    regime_score = regime_map.get(market_regime, 0.5)
    
    # Engine scores — ambil nilai numerik
    score_values = []
    engine_keys = sorted(engine_scores.keys()) if engine_scores else []
    for k in engine_keys:
        v = engine_scores.get(k, 0)
        if isinstance(v, (int, float)):
            score_values.append(float(v))
        elif isinstance(v, dict):
            score_values.append(float(v.get('score', 0)))
    
    # Pad atau trim ke 34 features
    while len(score_values) < 34:
        score_values.append(0.0)
    score_values = score_values[:34]
    
    # Composite features
    avg_score = np.mean(score_values) if score_values else 0
    max_score = np.max(score_values) if score_values else 0
    min_score = np.min(score_values) if score_values else 0
    std_score = np.std(score_values) if score_values else 0
    high_count = sum(1 for s in score_values if s >= 70)
    
    features = score_values + [
        regime_score,
        float(lq45_change),
        float(breadth_ratio) / 100.0,
        avg_score / 100.0,
        max_score / 100.0,
        min_score / 100.0,
        std_score / 100.0,
        float(high_count) / 34.0,
    ]
    
    # KB Features — wisdom dari 10+ buku trading
    kb_feats = kb_features_to_array(kb_context)
    features = features + kb_feats

    return np.array(features, dtype=np.float32)

def _rule_based_probability(engine_scores: Dict, market_regime: str, lq45_change: float, final_score: float) -> float:
    """
    Rule-based win probability ketika belum ada training data
    Berdasarkan logika dari 12 buku trading di KB
    """
    prob = 50.0  # Base probability
    
    # Final score contribution (40%)
    if final_score >= 85:
        prob += 20
    elif final_score >= 75:
        prob += 12
    elif final_score >= 65:
        prob += 5
    elif final_score < 50:
        prob -= 15
    
    # Market regime contribution (30%)
    regime_bonus = {
        'STRONG BULL': 15,
        'BULL': 8,
        'SIDEWAYS': 0,
        'BEAR': -10,
        'STRONG BEAR': -20
    }
    prob += regime_bonus.get(market_regime, 0)
    
    # LQ45 change contribution (15%)
    if lq45_change > 1:
        prob += 8
    elif lq45_change > 0:
        prob += 4
    elif lq45_change < -1:
        prob -= 8
    elif lq45_change < 0:
        prob -= 4
    
    # Engine consensus (15%)
    scores = [v if isinstance(v, (int,float)) else v.get('score',0) 
              for v in engine_scores.values() if v]
    if scores:
        high_engines = sum(1 for s in scores if s >= 70)
        consensus = high_engines / len(scores)
        prob += (consensus - 0.5) * 20
    
    return max(5.0, min(95.0, prob))

def predict_win_probability(
    engine_scores: Dict,
    market_regime: str = 'SIDEWAYS',
    lq45_change: float = 0.0,
    breadth_ratio: float = 50.0,
    final_score: float = 0.0,
    kb_context: str = ""
) -> Dict[str, Any]:
    """
    Prediksi win probability untuk sebuah sinyal trading
    Returns: { probability, confidence, method, grade }
    """
    global _model
    
    # KB boost dari knowledge base
    kb_feats = extract_kb_features(kb_context)
    kb_boost = (kb_feats.get('kb_overall', 0.5) - 0.5) * 20
    kb_win_rate = kb_feats.get('kb_win_rate', 0.5)
    kb_consensus = kb_feats.get('kb_consensus', 0.5)

    prob = _rule_based_probability(engine_scores, market_regime, lq45_change, final_score)
    prob += kb_boost
    prob += (kb_win_rate - 0.5) * 15
    prob += (kb_consensus - 0.5) * 10
    prob = max(5.0, min(95.0, prob))
    method = "Rule-Based + KB (12 buku)"
    confidence = "medium"
    n_samples = len(_training_data)
    
    # Kalau sudah ada ML model (>= 30 sampel forward test)
    if _model is not None and n_samples >= 30:
        try:
            features = _build_features(engine_scores, market_regime, lq45_change, breadth_ratio, kb_context)
            ml_prob = float(_model.predict_proba([features])[0][1]) * 100
            # Blend rule-based + ML
            weight_ml = min(0.8, n_samples / 100)
            prob = (ml_prob * weight_ml) + (prob * (1 - weight_ml))
            method = f"ML + Rule-Based ({n_samples} samples)"
            confidence = "high" if n_samples >= 100 else "medium"
        except Exception as e:
            logger.error(f"ML predict error: {e}")
    
    # Grade
    if prob >= 75:
        grade = "A"
        grade_label = "High Probability"
        color = "#22c55e"
    elif prob >= 60:
        grade = "B"
        grade_label = "Good Probability"
        color = "#86efac"
    elif prob >= 45:
        grade = "C"
        grade_label = "Moderate"
        color = "#fbbf24"
    else:
        grade = "D"
        grade_label = "Low Probability"
        color = "#ef4444"
    
    return {
        "probability": round(prob, 1),
        "grade": grade,
        "grade_label": grade_label,
        "color": color,
        "method": method,
        "confidence": confidence,
        "n_samples": n_samples,
        "market_regime": market_regime,
    }

def add_training_sample(engine_scores: Dict, market_regime: str, lq45_change: float, 
                         breadth_ratio: float, final_score: float, outcome: int, kb_context: str = ""):
    """
    Tambah sampel training dari forward test result
    outcome: 1 = win (TP hit), 0 = loss (SL hit)
    """
    global _model, _training_data
    
    features = _build_features(engine_scores, market_regime, lq45_change, breadth_ratio, kb_context)
    _training_data.append((features, outcome))
    
    logger.info(f"Training sample added: outcome={outcome}, total={len(_training_data)}")
    
    # Auto retrain kalau >= 30 sampel
    if len(_training_data) >= 30:
        _retrain_model()

def _retrain_model():
    """Retrain Random Forest dari training data"""
    global _model, _model_meta
    
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import cross_val_score
        
        X = np.array([s[0] for s in _training_data])
        y = np.array([s[1] for s in _training_data])
        
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            min_samples_leaf=3,
            random_state=42,
            class_weight='balanced'
        )
        model.fit(X, y)
        
        # Cross-validation score
        if len(_training_data) >= 50:
            cv_scores = cross_val_score(model, X, y, cv=5, scoring='roc_auc')
            accuracy = float(cv_scores.mean())
        else:
            accuracy = float(model.score(X, y))
        
        _model = model
        _model_meta = {
            "n_samples": len(_training_data),
            "accuracy": round(accuracy, 3),
            "trained_at": datetime.now().isoformat(),
            "win_rate": round(float(np.mean(y)), 3)
        }
        
        logger.info(f"ML Model retrained: {_model_meta}")
        
    except Exception as e:
        logger.error(f"Retrain error: {e}")

def get_model_status() -> Dict:
    """Status ML model"""
    return {
        "model_ready": _model is not None,
        "n_samples": len(_training_data),
        "min_samples_needed": 30,
        "samples_needed": max(0, 30 - len(_training_data)),
        "meta": _model_meta
    }
