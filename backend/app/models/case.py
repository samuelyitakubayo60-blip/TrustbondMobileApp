from sqlalchemy import Column, Integer, SmallInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Case(Base):
    __tablename__ = "cases"

    case_id = Column(UUID(as_uuid=True), primary_key=True)
    case_number = Column(String(20), unique=True)
    status = Column(String(20), nullable=False, default="open")
    priority = Column(String(20), nullable=False, default="medium")
    title = Column(String(200))
    description = Column(Text)
    location_id = Column(Integer, ForeignKey("locations.location_id"))
    incident_type_id = Column(SmallInteger, ForeignKey("incident_types.incident_type_id"))
    assigned_to_id = Column(Integer, ForeignKey("police_users.police_user_id"))
    created_by = Column(Integer, ForeignKey("police_users.police_user_id"))
    report_count = Column(Integer, default=0)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    outcome = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    location = relationship("Location", backref="cases")
    incident_type = relationship("IncidentType", backref="cases")
    assigned_to = relationship("PoliceUser", foreign_keys=[assigned_to_id])
    created_by_user = relationship("PoliceUser", foreign_keys=[created_by])


class CaseReport(Base):
    __tablename__ = "case_reports"

    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE"), primary_key=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("Case", backref="case_reports")
    report = relationship("Report", backref="case_reports")
