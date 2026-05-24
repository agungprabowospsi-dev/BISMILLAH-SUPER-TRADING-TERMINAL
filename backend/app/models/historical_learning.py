from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class HistoricalFeature(Base):
    __tablename__ = "historical_features"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    mode = Column(String(20), nullable=False, default="swing")
    pattern_key = Column(String(160), nullable=False, index=True)
    feature_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "date", "mode", name="uq_historical_feature_ticker_date_mode"),
        Index("idx_historical_features_ticker_date", "ticker", "date"),
        Index("idx_historical_features_mode_pattern", "mode", "pattern_key"),
    )


class HistoricalOutcome(Base):
    __tablename__ = "historical_outcomes"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    mode = Column(String(20), nullable=False, default="swing")
    horizon_days = Column(Integer, nullable=False)
    tp_pct = Column(Float, nullable=False)
    sl_pct = Column(Float, nullable=False)
    outcome = Column(String(20), nullable=False)
    bars_to_exit = Column(Integer)
    max_favorable_pct = Column(Float)
    max_drawdown_pct = Column(Float)
    exit_reason = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "date", "mode", "horizon_days", name="uq_historical_outcome_label"),
        Index("idx_historical_outcomes_ticker_date", "ticker", "date"),
        Index("idx_historical_outcomes_mode_outcome", "mode", "outcome"),
    )


class EmpiricalPattern(Base):
    __tablename__ = "empirical_patterns"

    id = Column(Integer, primary_key=True)
    mode = Column(String(20), nullable=False)
    pattern_key = Column(String(160), nullable=False)
    sample_count = Column(Integer, nullable=False, default=0)
    win_count = Column(Integer, nullable=False, default=0)
    loss_count = Column(Integer, nullable=False, default=0)
    timeout_count = Column(Integer, nullable=False, default=0)
    winrate = Column(Float, nullable=False, default=0.0)
    avg_mfe_pct = Column(Float, nullable=False, default=0.0)
    avg_drawdown_pct = Column(Float, nullable=False, default=0.0)
    expectancy_pct = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    literature = Column(Text)
    source = Column(String(50), nullable=False, default="idx_empirical_memory")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("mode", "pattern_key", name="uq_empirical_pattern_mode_key"),
        Index("idx_empirical_patterns_mode_winrate", "mode", "winrate"),
    )
