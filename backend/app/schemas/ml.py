from typing import Optional, Any, Dict, List
from pydantic import BaseModel

class MLPredictionResponse(BaseModel):
    prediction_id: str
    report_id: str
    prediction_label: str  # likely_real, suspicious, fake
    trust_score: Optional[float] = None
    confidence: Optional[float] = None
    model_version: Optional[str] = None
    evaluated_at: Optional[str] = None
    is_final: Optional[bool] = None
    explanation: Optional[dict] = None
    processing_time: Optional[int] = None

class MLInsightResponse(BaseModel):
    total_reports: int
    likely_real_count: int
    suspicious_count: int
    fake_count: int
    average_trust_score: Optional[float] = None
    processing_time_avg_ms: Optional[float] = None

class DeviceMLStatsResponse(BaseModel):
    device_id: str
    total_reports: int
    trust_score: Optional[float] = None
    prediction_distribution: Dict[str, int]
    last_prediction_at: Optional[str] = None
    ml: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None
