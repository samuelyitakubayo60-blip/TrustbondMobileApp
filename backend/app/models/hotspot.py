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

    # ── Improvement 1: Corroboration ─────────────────────────────────────────
    # Require multiple independent reporters before a cluster becomes a hotspot.
    # unique_reporter_count: distinct submitter IDs contributing to this cluster.
    # corroboration_score:   0.0–1.0 composite (reporter diversity × trust
    #                        consistency × temporal spread).
    unique_reporter_count = Column(Integer, nullable=True)
    corroboration_score = Column(Numeric(5, 4), nullable=True)

    # ── Improvement 2: Multi-crime zone ──────────────────────────────────────
    # Post-clustering pass marks hotspots that spatially overlap with hotspots
    # of a different crime group — composite risk zone for law enforcement.
    is_multi_crime_zone = Column(Boolean, nullable=True, default=False)
    multi_crime_groups = Column(Text, nullable=True)    # JSON: ["violent","drug"]

    # ── Improvement 8: Prediction tracking ───────────────────────────────────
    # Rule-based prediction of next lifecycle state, verified on the following
    # clustering run so prediction accuracy can be measured over time.
    predicted_next_state = Column(String(30), nullable=True)
    predicted_at = Column(DateTime(timezone=True), nullable=True)
    prediction_verified_at = Column(DateTime(timezone=True), nullable=True)
    prediction_was_accurate = Column(Boolean, nullable=True)

    # ── Improvement 9: Explainability ────────────────────────────────────────
    # JSON blob with human-readable reasoning for every numeric score:
    # severity, trend, lifecycle, confidence, classification.
    explanation_json = Column(Text, nullable=True)

    # ── Improvement 10: Cache management ─────────────────────────────────────
    # Incremented whenever any input that invalidates cached LLM text changes
    # (trust score update, re-verification, cluster composition change).
    cache_version = Column(Integer, nullable=True, default=0)

    # ── Improvement 11: Abuse/anomaly detection ───────────────────────────────
    # Coordinated false-report detection.
    # abuse_flag:    True when anomaly_score exceeds the configured threshold.
    # anomaly_score: 0.0–1.0 (time-burst, GPS copy-paste, single-reporter
    #                dominance, uniform trust pattern).
    abuse_flag = Column(Boolean, nullable=True, default=False)
    anomaly_score = Column(Numeric(5, 4), nullable=True)

    # Computed geographic scope label (e.g. "Muhoza Cell", "Covers Musanze, Kinigi Stations")
    area_label = Column(String(300), nullable=True)

    controlled_by = relationship("PoliceUser", foreign_keys=[controlled_by_user_id])
    reports = relationship(
        "Report",
        secondary=hotspot_reports_table,
        backref="hotspots",
    )
    incident_type = relationship("IncidentType", backref="hotspots")
