from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class PoliceReview(Base):
    __tablename__ = "police_reviews"

    review_id = Column(UUID(as_uuid=True), primary_key=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id"), nullable=False)
    police_user_id = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=False)
    decision = Column(String(20), nullable=False)  # confirmed, rejected, investigation
    review_note = Column(Text)
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now())
    ground_truth_label = Column(String(10))  # real, fake
    confidence_level = Column(Numeric(5, 2))
    used_for_training = Column(Boolean, default=False)

    report = relationship("Report", backref="police_reviews")
    police_user = relationship("PoliceUser", backref="police_reviews")
