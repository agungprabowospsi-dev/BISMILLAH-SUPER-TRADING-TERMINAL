from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10))
    alert_type = Column(String(50))
    level = Column(String(10))
    message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
