from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class StationCoverageCell(Base):
    __tablename__ = "station_coverage_cells"

    station_coverage_cell_id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(Integer, ForeignKey("stations.station_id", ondelete="CASCADE"), nullable=False, index=True)
    cell_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False, index=True)

    station = relationship("Station", back_populates="coverage_cells")
    cell_location = relationship("Location")

    __table_args__ = (
        UniqueConstraint("station_id", "cell_location_id", name="uq_station_coverage_cell"),
    )
