from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


class BandarType(str, Enum):
    INSTITUTIONAL = "INSTITUTIONAL"
    FOREIGN       = "FOREIGN"
    RETAIL_BIG    = "RETAIL_BIG"
    RETAIL_CROWD  = "RETAIL_CROWD"
    UNCLEAR       = "UNCLEAR"

class BandarPhase(str, Enum):
    ACCUMULATION   = "ACCUMULATION"
    MARKUP         = "MARKUP"
    DISTRIBUTION   = "DISTRIBUTION"
    MARKDOWN       = "MARKDOWN"
    REACCUMULATION = "REACCUMULATION"
    UNKNOWN        = "UNKNOWN"

class MomentumLabel(str, Enum):
    VERY_STRONG = "VERY_STRONG"
    STRONG      = "STRONG"
    MODERATE    = "MODERATE"
    WEAK        = "WEAK"
    EXHAUSTED   = "EXHAUSTED"

class RetestClassification(str, Enum):
    VERY_SHALLOW       = "VERY_SHALLOW"
    NORMAL_RETEST      = "NORMAL_RETEST"
    MEDIUM_RETEST      = "MEDIUM_RETEST"
    DEEP_BUT_VALID     = "DEEP_BUT_VALID"
    REVERSAL_WARNING   = "REVERSAL_WARNING"
    REVERSAL_CONFIRMED = "REVERSAL_CONFIRMED"

class FinalAction(str, Enum):
    HOLD_TP2  = "HOLD_TP2"
    HOLD_TP1  = "HOLD_TP1"
    REDUCE_50 = "REDUCE_50"
    EXIT_ALL  = "EXIT_ALL"

class AlertType(str, Enum):
    SL_HIT  = "SL_HIT"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"
    NONE    = "NONE"

class EnrichmentVerdict(str, Enum):
    PROCEED = "PROCEED"
    CAUTION = "CAUTION"
    SKIP    = "SKIP"

class RAGTrigger(str, Enum):
    BANDAR_TYPE_UNCLEAR   = "BANDAR_TYPE_UNCLEAR"
    DISTRIBUTION_DETECTED = "DISTRIBUTION_DETECTED"
    RETEST_UNCLEAR        = "RETEST_UNCLEAR"
    RETEST_DEEP_BUT_VALID = "RETEST_DEEP_BUT_VALID"
    MOMENTUM_DROP         = "MOMENTUM_DROP"
    TP_PROB_DROP          = "TP_PROB_DROP"
    NONE                  = "NONE"


class PriceFeedResult(BaseModel):
    ticker:       str
    last_price:   float
    prev_close:   float
    change_pct:   float
    volume_today: int
    timestamp:    str

class AlertResult(BaseModel):
    alert_type:    AlertType       = AlertType.NONE
    triggered:     bool            = False
    trigger_price: Optional[float] = None
    sl_price:      float
    tp1_price:     float
    tp2_price:     float
    tp3_price:     float
    message:       Optional[str]   = None

class BandarTypeSignal(BaseModel):
    large_lot_spread:   bool            = False
    peak_hour_trading:  bool            = False
    low_price_impact:   bool            = False
    lq45_member:        bool            = False
    net_foreign_buy:    Optional[int]   = None
    usd_idr_corr:       Optional[float] = None
    single_large_lot:   bool            = False
    random_hour:        bool            = False
    high_price_impact:  bool            = False
    small_cap:          bool            = False
    many_small_lots:    bool            = False
    social_media_spike: bool            = False
    spread_widening:    bool            = False
    pump_pattern:       bool            = False

class BandarTypeResult(BaseModel):
    bandar_type:     BandarType
    confidence:      float
    signals:         BandarTypeSignal
    net_foreign_lot: int  = 0
    score_breakdown: dict = Field(default_factory=dict)
    rag_triggered:   bool = False

class DistributionSignal(BaseModel):
    upthrust:         bool = False
    no_demand:        bool = False
    effort_vs_result: bool = False
    top_volume:       bool = False
    count:            int  = 0

class BandarmologiMonitorResult(BaseModel):
    current_score:         float
    score_delta:           float
    current_phase:         BandarPhase
    phase_changed:         bool = False
    distribution_detected: bool = False
    distribution_signals:  DistributionSignal
    obv_trend:             Literal["UP", "FLAT", "DOWN"] = "FLAT"
    ad_line_trend:         Literal["UP", "FLAT", "DOWN"] = "FLAT"
    institutional_flow:    Literal["ACCUMULATING", "NEUTRAL", "DISTRIBUTING"] = "NEUTRAL"
    net_foreign_lot:       int  = 0
    inventory_position:    Literal["ACCUMULATION", "NEUTRAL", "DISTRIBUTION"] = "NEUTRAL"
    rag_triggered:         bool = False
    status_message:        str  = ""

class MomentumResult(BaseModel):
    score:            float
    label:            MomentumLabel
    roc_pct:          float
    roc_acceleration: float
    volume_confirming: bool           = False
    candle_quality:   float
    prev_score:       Optional[float] = None
    score_drop:       float           = 0.0
    rag_triggered:    bool            = False

class RetestResult(BaseModel):
    classification:        RetestClassification
    fib_level_pct:         float
    pullback_points:       float
    pullback_pct:          float
    volume_ratio_pullback: float
    swing_high:            float
    swing_low:             float
    fib_levels:            dict
    vsa_signal:            Optional[str] = None
    rag_triggered:         bool          = False

class TPProbResult(BaseModel):
    prob_tp1:         float
    prob_tp2:         float
    prob_tp3:         float
    expected_value:   float
    recommendation:   FinalAction
    multiplier_stack: dict
    prev_prob_tp1:    Optional[float] = None
    prob_tp1_drop:    float           = 0.0
    tp1_price:        float
    tp2_price:        float
    tp3_price:        float
    entry_price:      float
    rag_triggered:    bool            = False

class EnrichmentRealtimeResult(BaseModel):
    mfi_signal:          str
    mfi_value:           float
    kama_zone:           str
    kama_distance_pct:   float
    lele_signal:         str
    divergence_state:    str
    divergence_bars_ago: Optional[int]    = None
    verdict:             EnrichmentVerdict
    warning_count:       int              = 0
    veto_active:         bool             = False

class RAGMonitorResult(BaseModel):
    triggered:        bool            = False
    trigger_reason:   RAGTrigger      = RAGTrigger.NONE
    query_used:       Optional[str]   = None
    kb_insight:       Optional[str]   = None
    books_queried:    list[str]       = Field(default_factory=list)
    confidence_boost: float           = 0.0
    rate_limited:     bool            = False

class FinalRecommendation(BaseModel):
    action:     FinalAction
    reason:     list[str]           = Field(default_factory=list)
    confidence: float
    sl_hit:     bool                = False
    tp_hit:     Optional[AlertType] = None

class MonitoringEnhancementResponse(BaseModel):
    ticker:             str
    trade_mode:         Literal["SWING", "DAYTRADING", "SCALPING"]
    poll_timestamp:     str
    price_feed:         PriceFeedResult
    alert:              AlertResult
    bandar_type:        BandarTypeResult
    bandarmologi:       BandarmologiMonitorResult
    momentum:           MomentumResult
    retest:             RetestResultV2
    tp_probability:     TPProbResult
    enrichment:         EnrichmentRealtimeResult
    rag_monitor:        RAGMonitorResult
    recommendation:     FinalRecommendation
    processing_time_ms: Optional[float] = None
    error:              Optional[str]   = None

class MonitoringEnhancementRequest(BaseModel):
    ticker:      str
    trade_mode:  Literal["SWING", "DAYTRADING", "SCALPING"] = "SWING"
    entry_price: float
    sl_price:    float
    tp1_price:   float
    tp2_price:   float
    tp3_price:   float
    entry_score: float = 0.0
    lots:        int   = 10


class BandarRetestType(str, Enum):
    NORMAL_BANDAR_RETEST   = "NORMAL_BANDAR_RETEST"
    DISTRIBUSI_TERSELUBUNG = "DISTRIBUSI_TERSELUBUNG"
    PARKING                = "PARKING"
    UNCLEAR                = "UNCLEAR"

class PatternName(str, Enum):
    BULL_FLAG       = "BULL_FLAG"
    WYCKOFF_SPRING  = "WYCKOFF_SPRING"
    HIGHER_LOW      = "HIGHER_LOW"
    DEAD_CAT_BOUNCE = "DEAD_CAT_BOUNCE"
    BEAR_FLAG       = "BEAR_FLAG"
    NONE            = "NONE"

class RetestVerdict(str, Enum):
    STRONG_HOLD = "STRONG_HOLD"
    HOLD        = "HOLD"
    REDUCE_50   = "REDUCE_50"
    EXIT_ALL    = "EXIT_ALL"

class RetestResultV2(BaseModel):
    # Layer 1 — Fibonacci
    classification:        RetestClassification
    fib_level_pct:         float
    pullback_points:       float
    pullback_pct:          float
    swing_high:            float
    swing_low:             float
    fib_levels:            dict
    # Layer 2 — VSA
    volume_ratio_pullback: float
    vsa_signal:            Optional[str] = None
    # Layer 3 — Bandar Context RAG
    bandar_retest_type:    BandarRetestType = BandarRetestType.UNCLEAR
    bandar_still_holding:  bool             = False
    kb_insight_bandar:     Optional[str]    = None
    confidence_bandar:     float            = 0.0
    # Layer 4 — Chart Pattern RAG
    pattern_name:          PatternName      = PatternName.NONE
    pattern_win_rate:      float            = 0.0
    pattern_implication:   str              = "NEUTRAL"
    kb_insight_pattern:    Optional[str]    = None
    # Layer 5 — Synthesis
    retest_verdict:        RetestVerdict    = RetestVerdict.HOLD
    retest_confidence:     float            = 0.0
    rag_triggered:         bool             = False
