from sqlalchemy import Column, String, SmallInteger, Integer, Text, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    report_id = Column(UUID(as_uuid=True), primary_key=True)
    report_number = Column(String(20), unique=True, index=True, nullable=True)  # RPT-YYYY-NNNN, backfilled by migration
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.device_id"), nullable=False)
    incident_type_id = Column(SmallInteger, ForeignKey("incident_types.incident_type_id"), nullable=False)
    description = Column(Text)
    latitude = Column(Numeric(10, 7), nullable=False)
    longitude = Column(Numeric(10, 7), nullable=False)
    gps_accuracy = Column(Numeric(8, 2))
    motion_level = Column(String(20))  # low, medium, high
    movement_speed = Column(Numeric(6, 2))
    was_stationary = Column(Boolean)
    location_id = Column(Integer, ForeignKey("locations.location_id"))  # optional sector/cell-level location
    handling_station_id = Column(Integer, ForeignKey("stations.station_id"))  # set when assigned to a station
    village_location_id = Column(Integer, ForeignKey("locations.location_id"))
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    # report_status enum: pending, verified, flagged, rejected (lifecycle / police confirmation)
    status = Column(String(20), default="pending")
    rule_status = Column(String(20), default="pending")  # passed, flagged, rejected (rule engine)
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(Text)  # set when is_flagged or when police flags
    priority = Column(String(20), default="medium")  # low, medium, high, urgent - auto-calculated
    # verification_status enum: pending, under_review, verified, rejected
    verification_status = Column(String(20), default="pending")
    verified_by = Column(Integer, ForeignKey("police_users.police_user_id"))
    verified_at = Column(DateTime(timezone=True))
    feature_vector = Column(JSONB)
    ai_ready = Column(Boolean, default=False)
    features_extracted = Column(DateTime(timezone=True))
    features_extracted_at = Column(DateTime(timezone=True))  # when ML features were last extracted
    app_version = Column(String(50))  # from mobile at submit
    network_type = Column(String(20))  # from mobile at submit
    battery_level = Column(Numeric(5, 2))  # from mobile at submit (optional)
    context_tags = Column(ARRAY(String), default=lambda: [])  # e.g. Night-time, Weapons involved

    device = relationship("Device", backref="reports")
    incident_type = relationship("IncidentType", backref="reports")
    village_location = relationship("Location", backref="reports", foreign_keys=[village_location_id])
    location = relationship("Location", foreign_keys=[location_id])
    handling_station = relationship("Station", backref="reports", foreign_keys=[handling_station_id])
    evidence_files = relationship("EvidenceFile", back_populates="report", cascade="all, delete-orphan")
