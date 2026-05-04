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
