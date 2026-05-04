from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class StockAnalysis(Base):
    __tablename__ = "stock_analysis"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), index=True)
    ticker = Column(String(10))
    mode = Column(String(20))
    composite_score = Column(Float)
    market_structure_score = Column(Float)
    smart_money_score = Column(Float)
    execution_score = Column(Float)
    decision_score = Column(Float)
    rationale = Column(Text)
    entry_suggestion = Column(Float)
    created_at = Column(DateTime, server_default=func.now())

class MonitoringPosition(Base):
    __tablename__ = "monitoring_positions"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10))
    mode = Column(String(20))
    entry_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    status = Column(String(20), default="hold")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10))
    alert_type = Column(String(50))
    level = Column(String(10))
    message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

class TradingLog(Base):
    __tablename__ = "trading_log"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10))
    mode = Column(String(20))
    action = Column(String(20))
    price = Column(Float)
    reason = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
