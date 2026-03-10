from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    # Let SQLAlchemy generate a UUID in Python so the PK is never NULL
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    police_user_id = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=False)
    refresh_token = Column(String(512))
    user_agent = Column(String)
    ip_address = Column(String)  # store as text for simplicity
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True))

