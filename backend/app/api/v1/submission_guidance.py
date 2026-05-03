"""
Submission Guidance API - Offline-First Approach
Provides real-time feedback for report submission.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.submission_guidance import submission_guidance, GuidanceLevel, TrustScoreEstimate
from app.core.draft_report_evaluation import preview_trust_estimate_online
from app.models.device import Device

router = APIRouter(prefix="/submission-guidance", tags=["submission-guidance"])

# Pydantic models for API
class GuidanceRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)
    incident_type: str = Field(..., min_length=1, max_length=100)
    evidence_count: int = Field(default=0, ge=0, le=10)
    file_types: List[str] = Field(default_factory=list)
    gps_accuracy: Optional[float] = Field(default=None, ge=0, le=1000)
    movement_speed: Optional[float] = Field(default=None, ge=0, le=100)
    device_id: Optional[str] = Field(default=None)
    has_live_capture: bool = Field(default=False)
    is_offline: bool = Field(default=True)

class GuidanceItemResponse(BaseModel):
    level: str
    title: str
    message: str
    actionable: bool = True
    suggested_action: Optional[str] = None

class TrustScoreResponse(BaseModel):
    total_score: float
    trustbond_score: float
    natural_language_score: float
    volo_score: Optional[float]
    base_score: float
    confidence: str
    will_be_verified: bool
    contributing_models: int

class GuidanceResponse(BaseModel):
    guidance_items: List[GuidanceItemResponse]
    trust_estimate: TrustScoreResponse
    summary: str
    priority_actions: List[str]

class DescriptionValidationRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)
    incident_type: str = Field(..., min_length=1, max_length=100)

class DescriptionValidationResponse(BaseModel):
    is_valid: bool
    word_count: int
    quality_score: float
    suggestions: List[str]
    missing_keywords: List[str]

class EvidenceValidationRequest(BaseModel):
    evidence_count: int = Field(default=0, ge=0, le=10)
    incident_type: str = Field(default="Default", min_length=1, max_length=100)
    has_live_capture: bool = Field(default=False)
    file_types: List[str] = Field(default_factory=list)

class EvidenceValidationResponse(BaseModel):
    is_sufficient: bool
    quality_score: float
    suggestions: List[str]
    ideal_count: int

@router.post("/analyze", response_model=GuidanceResponse)
def analyze_submission(
    request: GuidanceRequest,
    db: Session = Depends(get_db)
):
    """
    Analyze submission quality and provide comprehensive guidance.
    Works offline and online.
    """
    try:
        # Get device trust score if device_id provided
        device_trust_score = None
        if request.device_id:
            device = db.query(Device).filter(Device.device_id == request.device_id).first()
            if device:
                device_trust_score = float(device.device_trust_score)

        trust_preview: Optional[TrustScoreEstimate] = None
        if not request.is_offline:
            trust_preview = preview_trust_estimate_online(
                db,
                description=request.description,
                incident_type=request.incident_type,
                evidence_count=request.evidence_count,
                file_types=request.file_types,
                gps_accuracy=request.gps_accuracy,
                movement_speed=request.movement_speed,
                device_id=request.device_id,
                has_live_capture=request.has_live_capture,
            )

        # Analyze submission (online: trust band matches unified aggregator + XGBoost inference)
        guidance_items, trust_estimate = submission_guidance.analyze_submission_quality(
            description=request.description,
            incident_type=request.incident_type,
            evidence_count=request.evidence_count,
            file_types=request.file_types,
            gps_accuracy=request.gps_accuracy,
            movement_speed=request.movement_speed,
            device_trust_score=device_trust_score,
            has_live_capture=request.has_live_capture,
            is_offline=request.is_offline,
            trust_estimate_override=trust_preview,
        )
        
        # Convert to response format
        guidance_response = [
            GuidanceItemResponse(
                level=item.level.value,
                title=item.title,
                message=item.message,
                actionable=item.actionable,
                suggested_action=item.suggested_action
            )
            for item in guidance_items
        ]
        
        trust_response = TrustScoreResponse(
            total_score=trust_estimate.total_score,
            trustbond_score=trust_estimate.trustbond_score,
            natural_language_score=trust_estimate.natural_language_score,
            volo_score=trust_estimate.volo_score,
            base_score=trust_estimate.base_score,
            confidence=trust_estimate.confidence,
            will_be_verified=trust_estimate.will_be_verified,
            contributing_models=trust_estimate.contributing_models
        )
        
        # Generate summary and priority actions
        summary = _generate_summary(trust_estimate, len(guidance_items))
        priority_actions = _get_priority_actions(guidance_items)
        
        return GuidanceResponse(
            guidance_items=guidance_response,
            trust_estimate=trust_response,
            summary=summary,
            priority_actions=priority_actions
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@router.post("/validate-description", response_model=DescriptionValidationResponse)
def validate_description(request: DescriptionValidationRequest):
    """
    Validate description quality and provide specific suggestions.
    Lightweight for offline use.
    """
    try:
        guidance_items, _ = submission_guidance.analyze_submission_quality(
            description=request.description,
            incident_type=request.incident_type,
            is_offline=True
        )
        
        # Extract description-specific guidance
        desc_guidance = [item for item in guidance_items if "description" in item.title.lower() or "detail" in item.title.lower()]
        
        word_count = len(request.description.split())
        quality_metrics = submission_guidance.evaluate_description_quality(
            request.description,
            request.incident_type,
        )
        quality_score = float(quality_metrics.get("quality_score", 0.0))
        hard_gates = quality_metrics.get("hard_gates", []) if isinstance(quality_metrics.get("hard_gates"), list) else []
        reason_codes = quality_metrics.get("reason_codes", []) if isinstance(quality_metrics.get("reason_codes"), list) else []
        
        # Check for incident-specific keywords
        incident_keywords = submission_guidance._get_incident_keywords(request.incident_type)
        required_keywords = incident_keywords.get("required", [])
        recommended_keywords = incident_keywords.get("recommended", [])
        found_keywords = [
            kw for kw in (required_keywords + recommended_keywords)
            if kw.lower() in request.description.lower()
        ]
        missing_keywords = [
            kw for kw in required_keywords if kw.lower() not in request.description.lower()
        ]
        
        suggestions = []
        for item in desc_guidance:
            if item.suggested_action:
                suggestions.append(item.suggested_action)
        
        is_valid = (
            word_count >= 15
            and quality_metrics.get("authenticity_score", 0.0) >= 45.0
            and quality_metrics.get("incident_alignment_score", 0.0) >= 40.0
            and len(found_keywords) >= 1
            and not hard_gates
            and quality_metrics.get("quality_score", 0.0) >= 70.0
            and str(quality_metrics.get("quality_band", "")) == "pass_quality"
        )
        if reason_codes:
            suggestions.extend([f"Validation signal: {code}" for code in reason_codes[:3]])
        
        return DescriptionValidationResponse(
            is_valid=is_valid,
            word_count=word_count,
            quality_score=quality_score,
            suggestions=suggestions,
            missing_keywords=missing_keywords
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Description validation failed: {str(e)}")

@router.post("/validate-evidence", response_model=EvidenceValidationResponse)
def validate_evidence(request: EvidenceValidationRequest):
    """
    Validate evidence quality and provide suggestions.
    Lightweight for offline use.
    """
    try:
        metrics = submission_guidance.evaluate_evidence_quality(
            evidence_count=request.evidence_count,
            has_live_capture=request.has_live_capture,
            file_types=request.file_types,
            incident_type=request.incident_type,
        )
        guidance_items, _ = submission_guidance.analyze_submission_quality(
            description="evidence provided",
            incident_type=request.incident_type,
            evidence_count=request.evidence_count,
            file_types=request.file_types,
            has_live_capture=request.has_live_capture,
            is_offline=True
        )
        
        # Extract evidence-specific guidance
        evidence_guidance = [
            item for item in guidance_items
            if any(
                token in item.title.lower()
                for token in ["evidence", "photo", "yolo", "trustbond", "camera", "coverage"]
            )
        ]
        
        ideal_count = 3
        quality_score = float(metrics.get("overall_score", 0.0))
        
        is_sufficient = request.evidence_count >= 1
        
        suggestions = []
        for item in evidence_guidance:
            if item.suggested_action:
                suggestions.append(item.suggested_action)
        
        return EvidenceValidationResponse(
            is_sufficient=is_sufficient,
            quality_score=quality_score,
            suggestions=suggestions,
            ideal_count=ideal_count
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evidence validation failed: {str(e)}")

@router.get("/incident-keywords/{incident_type}")
def get_incident_keywords(incident_type: str):
    """
    Get relevant keywords for incident type to help users.
    """
    try:
        keywords = submission_guidance._get_incident_keywords(incident_type)
        return {"keywords": keywords, "incident_type": incident_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get keywords: {str(e)}")

@router.get("/thresholds")
def get_guidance_thresholds():
    """
    Get guidance thresholds for mobile app offline use.
    """
    try:
        return {
            "description": {
                "min_length": submission_guidance.thresholds['min_words_for_detail'],
                "ideal_length": submission_guidance.thresholds['ideal_description_length']
            },
            "evidence": {
                "min_count": submission_guidance.thresholds['min_evidence_count'],
                "ideal_count": submission_guidance.thresholds['ideal_evidence_count']
            },
            "location": {
                "min_gps_accuracy": submission_guidance.thresholds['min_gps_accuracy']
            },
            "model_weights": submission_guidance.model_weights
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thresholds: {str(e)}")

def _generate_summary(trust_estimate: TrustScoreEstimate, guidance_count: int) -> str:
    """Generate a summary of the submission analysis."""
    if trust_estimate.will_be_verified:
        return f"Excellent submission! Estimated trust score {trust_estimate.total_score:.0f}/100 with {trust_estimate.contributing_models} contributing models. Likely to be auto-verified."
    elif trust_estimate.confidence == "medium_confidence":
        return f"Good submission with {trust_estimate.total_score:.0f}/100 estimated score. {guidance_count} suggestions available to improve verification chances."
    else:
        return f"Submission needs improvement. Current score {trust_estimate.total_score:.0f}/100. Follow the guidance to increase verification probability."

def _get_priority_actions(guidance_items: List) -> List[str]:
    """Get priority actions from guidance items."""
    critical_items = [item for item in guidance_items if item.level == GuidanceLevel.CRITICAL and item.actionable]
    warning_items = [item for item in guidance_items if item.level == GuidanceLevel.WARNING and item.actionable]
    
    priority_actions = []
    
    # Add critical actions first
    for item in critical_items[:3]:  # Max 3 critical actions
        if item.suggested_action:
            priority_actions.append(item.suggested_action)
    
    # Add warning actions if space
    if len(priority_actions) < 5:
        for item in warning_items[:5 - len(priority_actions)]:
            if item.suggested_action:
                priority_actions.append(item.suggested_action)
    
    return priority_actions
