from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Dict, Any

class MLPredictionResponse(BaseModel):
    prediction_id: str
    report_id: str
    trust_score: float
    prediction_label: str  # likely_real, suspicious, fake
    model_version: str
    confidence: float
    evaluated_at: datetime
    explanation: Optional[Dict[str, Any]] = None
    model_type: Optional[str] = None
    is_final: bool

    class Config:
        from_attributes = True

class MLInsightResponse(BaseModel):
    title: str
    description: str
    type: str  # safety, trust, pattern
    score: Optional[float] = None
    timestamp: datetime

    class Config:
        from_attributes = True

class DeviceMLStatsResponse(BaseModel):
    device_id: str
    total_predictions: int
    average_trust_score: float
    credible_reports: int
    suspicious_reports: int
    fake_reports: int
    model_versions: List[str]
    last_prediction: Optional[datetime] = None

    class Config:
        from_attributes = True
