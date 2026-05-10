from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import backref, relationship

from app.database import Base


class LocalLeaderCoverageLocation(Base):
    __tablename__ = "local_leader_coverage_locations"

    local_leader_coverage_location_id = Column(Integer, primary_key=True, autoincrement=True)
    local_leader_id = Column(
        Integer,
        ForeignKey("local_leaders.local_leader_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False, index=True)

    # passive_deletes: DB has ON DELETE CASCADE; avoid ORM issuing UPDATE ... SET local_leader_id=NULL first.
    local_leader = relationship(
        "LocalLeader",
        backref=backref("coverage_locations", passive_deletes=True),
    )
    location = relationship("Location")

    __table_args__ = (
        UniqueConstraint("local_leader_id", "location_id", name="uq_local_leader_coverage_location"),
    )

