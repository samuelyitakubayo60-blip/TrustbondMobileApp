from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(UUID(as_uuid=True), primary_key=True)
    police_user_id = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=False)
    title = Column(String(150), nullable=False)
    message = Column(Text)
    type = Column(String(20), nullable=False)  # report, hotspot, assignment, system
    related_entity_type = Column(String(50))
    related_entity_id = Column(String(36))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    police_user = relationship("PoliceUser", backref="notifications")
