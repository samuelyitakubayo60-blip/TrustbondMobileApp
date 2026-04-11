from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key = Column(String(100), primary_key=True)
    config_value = Column(JSONB, nullable=False)
    description = Column(String)
    updated_by = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

