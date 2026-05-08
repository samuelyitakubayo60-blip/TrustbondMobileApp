from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class LocalLeaderAuthCode(Base):
    __tablename__ = "local_leader_auth_codes"

    local_leader_auth_code_id = Column(Integer, primary_key=True, autoincrement=True)
    local_leader_id = Column(Integer, ForeignKey("local_leaders.local_leader_id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number = Column(String(20), nullable=False, index=True)
    code = Column(String(10), nullable=False)
    purpose = Column(String(30), nullable=False, default="password_setup")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    local_leader = relationship("LocalLeader")

