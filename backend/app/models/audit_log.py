from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_type = Column(String(20), nullable=False)  # system, police_user
    actor_id = Column(Integer)  # nullable when actor_type is system
    action_type = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(String(36))
    action_details = Column(JSONB)
    ip_address = Column(String(45))
    success = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
