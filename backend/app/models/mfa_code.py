from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class MfaCode(Base):
    __tablename__ = "mfa_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    police_user_id = Column(Integer, ForeignKey("police_users.police_user_id", ondelete="CASCADE"), nullable=False)
    code = Column(String(6), nullable=False)
    purpose = Column(String(20), nullable=False, server_default="login")  # login | enable
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
