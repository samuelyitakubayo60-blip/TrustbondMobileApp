from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Station(Base):
    __tablename__ = "stations"

    station_id = Column(Integer, primary_key=True, autoincrement=True)
    station_code = Column(String(50), unique=True, nullable=False)
    station_name = Column(String(150), nullable=False)
    station_type = Column(String(30), nullable=False)  # headquarters, station, post
    location_id = Column(Integer, ForeignKey("locations.location_id"))  # Primary sector
    sector2_id = Column(Integer, ForeignKey("locations.location_id"))  # Secondary sector (optional)
    latitude = Column(Numeric(10, 7))
    longitude = Column(Numeric(10, 7))
    address_text = Column(String)
    phone_number = Column(String(50))
    email = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    location = relationship("Location", backref="stations", foreign_keys=[location_id])
    sector2 = relationship("Location", foreign_keys=[sector2_id])

