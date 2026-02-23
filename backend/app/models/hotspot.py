from sqlalchemy import Column, Integer, Numeric, SmallInteger, String, DateTime, ForeignKey, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

hotspot_reports_table = Table(
    "hotspot_reports",
    Base.metadata,
    Column("hotspot_id", Integer, ForeignKey("hotspots.hotspot_id"), primary_key=True),
    Column("report_id", UUID(as_uuid=True), ForeignKey("reports.report_id"), primary_key=True),
)


class Hotspot(Base):
    __tablename__ = "hotspots"

    hotspot_id = Column(Integer, primary_key=True, autoincrement=True)
    center_lat = Column(Numeric(10, 7), nullable=False)
    center_long = Column(Numeric(10, 7), nullable=False)
    radius_meters = Column(Numeric(8, 2), nullable=False)
    incident_count = Column(Integer, nullable=False)
    risk_level = Column(String(20), nullable=False)  # low, medium, high
    time_window_hours = Column(Integer, nullable=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    incident_type_id = Column(SmallInteger, ForeignKey("incident_types.incident_type_id"), nullable=True)  # same place + same type

    reports = relationship(
        "Report",
        secondary=hotspot_reports_table,
        backref="hotspots",
    )
    incident_type = relationship("IncidentType", backref="hotspots")
