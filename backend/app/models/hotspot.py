from sqlalchemy import Boolean, Column, Integer, Numeric, SmallInteger, String, DateTime, ForeignKey, Table, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

hotspot_reports_table = Table(
    "hotspot_reports",
    Base.metadata,
    Column("hotspot_id", Integer, ForeignKey("hotspots.hotspot_id"), primary_key=True),
    Column("report_id", UUID(as_uuid=True), ForeignKey("reports.report_id"), primary_key=True),
    Column("is_core", Boolean, nullable=False, server_default="false"),
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
    assigned_unit_code = Column(String(80), nullable=True)
    controlled_by_user_id = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=True)
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    deployment_note = Column(String(500), nullable=True)

    # Clustering enhancement columns
    lifecycle_state = Column(String(30), nullable=True)          # emerging/active/escalating/stable/declining
    composition = Column(Text, nullable=True)                     # JSON: {"Theft": 3, "Assault": 1}
    temporal_intensity = Column(Numeric(10, 4), nullable=True)   # incidents per hour within cluster time span
    severity_score = Column(Numeric(6, 4), nullable=True)        # weighted average severity 1–10
    trend_direction = Column(String(20), nullable=True)           # rising/stable/falling
    cluster_confidence = Column(Numeric(5, 4), nullable=True)    # 0.0–1.0
    polygon_points = Column(Text, nullable=True)                  # JSON [[lat,lon], ...] convex hull
    crime_group = Column(String(30), nullable=True)               # violent/property/drug/fraud/other

    # Persisted LLM briefing (generated once and reused)
    llm_narrative = Column(Text, nullable=True)
    llm_recommendation = Column(Text, nullable=True)
    llm_status = Column(String(60), nullable=True)
    llm_citizen_advisory = Column(Text, nullable=True)
    llm_provider = Column(String(40), nullable=True)  # groq / gemini / template
    llm_generated_at = Column(DateTime(timezone=True), nullable=True)

    controlled_by = relationship("PoliceUser", foreign_keys=[controlled_by_user_id])
    reports = relationship(
        "Report",
        secondary=hotspot_reports_table,
        backref="hotspots",
    )
    incident_type = relationship("IncidentType", backref="hotspots")
