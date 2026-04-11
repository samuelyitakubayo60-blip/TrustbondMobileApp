from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(UUID(as_uuid=True), primary_key=True)
    device_hash = Column(String(255), nullable=False, unique=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    total_reports = Column(Integer, default=0)
    trusted_reports = Column(Integer, default=0)
    flagged_reports = Column(Integer, default=0)
    spam_flags = Column(Integer, default=0)
    device_trust_score = Column(Numeric(5, 2), default=50.00)
    is_blacklisted = Column(Boolean, default=False)
    blacklist_reason = Column(String, nullable=True)
    # Column name is "metadata" in Postgres, but "metadata" is reserved by SQLAlchemy.
    metadata_json = Column("metadata", JSONB, nullable=True)
    is_banned = Column(Boolean, default=False)
