from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Numeric, Integer, UUID, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ENUM
import enum

from app.database import Base


class EvidenceQuality(enum.Enum):
    good = "good"
    fair = "fair" 
    poor = "poor"


class EvidenceFile(Base):
    __tablename__ = "evidence_files"

    evidence_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id"), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_type = Column(String(10))  # photo, video
    file_size = Column(Integer)
    duration = Column(Integer)
    media_latitude = Column(Numeric(10, 7))
    media_longitude = Column(Numeric(10, 7))
    captured_at = Column(DateTime)  # timestamp without time zone
    uploaded_at = Column(DateTime, server_default=func.now())  # timestamp without time zone
    is_live_capture = Column(Boolean, default=False)
    perceptual_hash = Column(String(128))
    blur_score = Column(Numeric(6, 3))
    tamper_score = Column(Numeric(6, 3))
    quality_label = Column(ENUM(EvidenceQuality, name="evidence_quality"), default=EvidenceQuality.fair)
    ai_checked_at = Column(DateTime)  # timestamp without time zone
    cloudinary_public_id = Column(String(255))
    cloudinary_url = Column(String(500))

    report = relationship("Report", back_populates="evidence_files")
