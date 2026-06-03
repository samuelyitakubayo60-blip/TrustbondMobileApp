from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class PoliceUser(Base):
    __tablename__ = "police_users"

    police_user_id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(150), nullable=False)
    middle_name = Column(String(150))
    last_name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    phone_number = Column(String(20))
    password_hash = Column(String(255), nullable=False)
    badge_number = Column(String(50))
    rank = Column(String(80), nullable=False, server_default="Police Constable")
    role = Column(String(20), nullable=False)  # admin, supervisor, officer
    assigned_location_id = Column(Integer, ForeignKey("locations.location_id"))
    station_id = Column(Integer, ForeignKey("stations.station_id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True))
    last_password_change = Column(DateTime(timezone=True))
    mfa_enabled = Column(Boolean, default=False, server_default="false")
    mfa_method = Column(String(20), server_default="email")  # email

    assigned_location = relationship("Location", backref="police_users")
    station = relationship("Station", backref="officers")
