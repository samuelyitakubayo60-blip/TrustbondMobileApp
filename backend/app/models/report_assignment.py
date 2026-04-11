from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class ReportAssignment(Base):
    __tablename__ = "report_assignments"

    assignment_id = Column(UUID(as_uuid=True), primary_key=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id"), nullable=False)
    police_user_id = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=False)
    status = Column(String(20), nullable=False)  # assigned, investigating, resolved, closed
    priority = Column(String(20), nullable=False)  # low, medium, high, urgent
    assignment_note = Column(Text)  # Notes from supervisor explaining why assignment is needed
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    report = relationship("Report", backref="assignments")
    police_user = relationship("PoliceUser", backref="assignments")
