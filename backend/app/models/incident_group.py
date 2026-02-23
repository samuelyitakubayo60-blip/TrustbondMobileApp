from sqlalchemy import Column, SmallInteger, Integer, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class IncidentGroup(Base):
    __tablename__ = "incident_groups"

    group_id = Column(UUID(as_uuid=True), primary_key=True)
    incident_type_id = Column(SmallInteger, ForeignKey("incident_types.incident_type_id"), nullable=False)
    center_lat = Column(Numeric(10, 7), nullable=False)
    center_long = Column(Numeric(10, 7), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    report_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
