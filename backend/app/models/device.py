from sqlalchemy import Column, String, Integer, Numeric, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(UUID(as_uuid=True), primary_key=True)
    device_hash = Column(String(255), nullable=False, unique=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    total_reports = Column(Integer, default=0)
    trusted_reports = Column(Integer, default=0)
    flagged_reports = Column(Integer, default=0)
    device_trust_score = Column(Numeric(5, 2), default=50.00)
