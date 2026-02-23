from sqlalchemy import Column, SmallInteger, String, Text, Numeric, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class IncidentType(Base):
    __tablename__ = "incident_types"

    incident_type_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    type_name = Column(String(100), nullable=False)
    description = Column(Text)
    severity_weight = Column(Numeric(3, 2), default=1.00)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
