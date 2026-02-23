from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class EvidenceFile(Base):
    __tablename__ = "evidence_files"

    evidence_id = Column(UUID(as_uuid=True), primary_key=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id"), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False)  # photo, video
    media_latitude = Column(Numeric(10, 7))
    media_longitude = Column(Numeric(10, 7))
    captured_at = Column(DateTime(timezone=True))
    is_live_capture = Column(Boolean, default=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    perceptual_hash = Column(String(128))
    blur_score = Column(Numeric(6, 3))
    tamper_score = Column(Numeric(6, 3))
    ai_quality_label = Column(String(20))  # good, poor, suspicious
    ai_checked_at = Column(DateTime(timezone=True))

    report = relationship("Report", back_populates="evidence_files")
