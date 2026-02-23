from sqlalchemy import Column, Integer, String, Numeric, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database import Base


class Location(Base):
    __tablename__ = "locations"

    location_id = Column(Integer, primary_key=True, autoincrement=True)
    location_type = Column(String(20), nullable=False)  # sector, cell, village
    location_name = Column(String(100), nullable=False)
    parent_location_id = Column(Integer, ForeignKey("locations.location_id"))
    # Some villages are MultiPolygon; store as MULTIPOLYGON to support both.
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326))  # PostGIS GEOMETRY (WGS84)
    centroid_lat = Column(Numeric(10, 7))
    centroid_long = Column(Numeric(10, 7))
    is_active = Column(Boolean, default=True)

    parent = relationship("Location", remote_side=[location_id])
