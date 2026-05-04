from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

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
    updated_at = Column(DateTime, server_default=func.now())
