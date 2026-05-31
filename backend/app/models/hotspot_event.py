"""
HotspotEvent — immutable audit log for every lifecycle change a hotspot goes through.

Records: creation, update, merge, split, escalation, stabilization, closure,
abuse-flagging, prediction verification, and manual officer actions.

This table is append-only.  Nothing in this table is ever deleted — it is the
authoritative forensic trail for operational accountability.
"""
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


# Event type catalogue — add new types here as requirements grow.
# Never rename or remove existing types (breaks historical queries).
HOTSPOT_EVENT_TYPES = frozenset(
    {
        "created",           # new hotspot detected by clustering
        "updated",           # existing hotspot refreshed (same geographic area)
        "merged",            # two or more hotspots absorbed into one
        "split",             # one hotspot divided into sub-clusters
        "escalated",         # lifecycle transition to escalating
        "stabilized",        # lifecycle transition to stable
        "declining",         # lifecycle transition to declining
        "closed",            # manually marked resolved / no longer active
        "abuse_flagged",     # anomaly detection raised an abuse flag
        "abuse_cleared",     # abuse flag manually cleared by an officer
        "prediction_set",    # predicted_next_state stored for this hotspot
        "prediction_verified",  # previous prediction compared to actual state
        "unit_deployed",     # officer deployed a unit to this hotspot
        "control_taken",     # IO/DPC took operational control
        "advisory_updated",  # LLM advisory regenerated (cache invalidated)
        "multi_crime_flagged",  # marked as part of a multi-crime zone
        "recomputed",        # full pipeline recompute touched this hotspot
    }
)


class HotspotEvent(Base):
    """
    Immutable lifecycle event for a hotspot.

    Columns
    -------
    event_id          : surrogate primary key
    hotspot_id        : FK to hotspots — never null
    event_type        : one of HOTSPOT_EVENT_TYPES
    previous_state    : lifecycle_state before the event (nullable)
    new_state         : lifecycle_state after the event (nullable)
    event_data        : JSON blob with any additional context
                        (e.g. merged_hotspot_ids, unit_code, anomaly_score)
    created_at        : UTC timestamp (server-side default)
    created_by_user_id: FK to police_users — null for system-generated events
    note              : free-text note (officer comment or system reason)
    """

    __tablename__ = "hotspot_events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)

    hotspot_id = Column(
        Integer,
        ForeignKey("hotspots.hotspot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Lifecycle fields
    event_type = Column(String(40), nullable=False, index=True)
    previous_state = Column(String(30), nullable=True)
    new_state = Column(String(30), nullable=True)

    # Arbitrary JSON payload — event-type-specific
    event_data = Column(Text, nullable=True)

    # Timestamp (immutable)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Actor — null = system (clustering pipeline / scheduler)
    created_by_user_id = Column(
        Integer,
        ForeignKey("police_users.police_user_id", ondelete="SET NULL"),
        nullable=True,
    )

    note = Column(String(500), nullable=True)

    # Relationships (read-only; HotspotEvent is never written via ORM relationship)
    hotspot = relationship("Hotspot", backref="events")
    created_by = relationship("PoliceUser", foreign_keys=[created_by_user_id])
