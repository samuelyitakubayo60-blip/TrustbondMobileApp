from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class SpecialAssignmentUnit(Base):
    __tablename__ = "special_assignment_units"

    unit_id = Column(Integer, primary_key=True, autoincrement=True)
    unit_code = Column(String(50), nullable=False, unique=True)
    unit_name = Column(String(100), nullable=False)
    description = Column(String(500))
    is_active = Column(Boolean, default=True)
    requires_commander_approval = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
