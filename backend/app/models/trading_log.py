from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class TradingLog(Base):
    __tablename__ = "trading_log"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10))
    mode = Column(String(20))
    action = Column(String(20))
    price = Column(Float)
    reason = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
