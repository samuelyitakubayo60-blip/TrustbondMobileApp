from sqlalchemy import Column, String, SmallInteger, Integer, Text, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    report_id = Column(UUID(as_uuid=True), primary_key=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.device_id"), nullable=False)
    incident_type_id = Column(SmallInteger, ForeignKey("incident_types.incident_type_id"), nullable=False)
    description = Column(Text)
    latitude = Column(Numeric(10, 7), nullable=False)
    longitude = Column(Numeric(10, 7), nullable=False)
    gps_accuracy = Column(Numeric(6, 2))
    motion_level = Column(String(20))  # low, medium, high
    movement_speed = Column(Numeric(6, 2))
    was_stationary = Column(Boolean)
    village_location_id = Column(Integer, ForeignKey("locations.location_id"))
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    rule_status = Column(String(20), default="pending")  # passed, flagged, rejected
    is_flagged = Column(Boolean, default=False)
    feature_vector = Column(JSONB)
    ai_ready = Column(Boolean, default=False)
    features_extracted = Column(DateTime(timezone=True))

    device = relationship("Device", backref="reports")
    incident_type = relationship("IncidentType", backref="reports")
    village_location = relationship("Location", backref="reports")
    evidence_files = relationship("EvidenceFile", back_populates="report", cascade="all, delete-orphan")
