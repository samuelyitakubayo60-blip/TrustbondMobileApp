from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class MLPrediction(Base):
    __tablename__ = "ml_predictions"

    prediction_id = Column(UUID(as_uuid=True), primary_key=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id"), nullable=False)
    trust_score = Column(Numeric(5, 2))
    prediction_label = Column(String(20))  # likely_real, suspicious, fake
    model_version = Column(String(50))
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now())
    confidence = Column(Numeric(5, 2))
    explanation = Column(JSONB)
    processing_time = Column(Integer)
    model_type = Column(String(50))
    is_final = Column(Boolean, default=False)

    report = relationship("Report", backref="ml_predictions")
