"""
Submission Guidance System - Offline-First Approach
Provides real-time feedback to help users create verifiable reports.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
import math
from collections import Counter
from datetime import datetime

class GuidanceLevel(Enum):
    CRITICAL = "critical"
    WARNING = "warning" 
    INFO = "info"
    SUCCESS = "success"

@dataclass
class GuidanceItem:
    level: GuidanceLevel
    title: str
    message: str
    actionable: bool = True
    suggested_action: Optional[str] = None

@dataclass
class TrustScoreEstimate:
    total_score: float
    trustbond_score: float
    natural_language_score: float
    volo_score: Optional[float]
    base_score: float
    confidence: str
    will_be_verified: bool
    contributing_models: int

class SubmissionGuidance:
    """Offline-first submission guidance system."""
    
    def __init__(self):
        # Offline validation rules
        self.description_rules = self._init_description_rules()
        self.evidence_rules = self._init_evidence_rules()
        self.location_rules = self._init_location_rules()
        self._semantic_model = None
        self._semantic_model_unavailable = False
        
        # Cached model weights (for offline estimation)
        self.model_weights = {
            'trustbond': 0.4,
            'natural_language': 0.3,
            'volo': 0.2,
            'base': 0.1
        }
        
        # Thresholds for offline estimation (aligned with backend decision policy)
        self.thresholds = {
            'min_description_length': 20,
            'ideal_description_length': 50,
            'min_evidence_count': 1,
            'ideal_evidence_count': 3,
            'min_gps_accuracy': 50,  # meters
            'min_words_for_detail': 15,
            # Text-only reports (no evidence)
            'text_confirmed_min': 85.0,
            'text_under_review_min': 60.0,
            # Evidence-backed reports
            'evidence_confirmed_min': 80.0,
            'evidence_under_review_min': 55.0,
        }
    
    def analyze_submission_quality(
        self,
        description: str,
        incident_type: str,
        evidence_count: int = 0,
        file_types: Optional[List[str]] = None,
        gps_accuracy: Optional[float] = None,
        movement_speed: Optional[float] = None,
        device_trust_score: Optional[float] = None,
        has_live_capture: bool = False,
        is_offline: bool = True
    ) -> Tuple[List[GuidanceItem], TrustScoreEstimate]:
        """
        Analyze submission quality and provide guidance.
        Works offline and online.
        """
        guidance_items = []
        
        # Description analysis
        desc_guidance = self._analyze_description(description, incident_type, evidence_count)
        guidance_items.extend(desc_guidance)
        
        # Evidence analysis
        evidence_guidance = self._analyze_evidence(
            evidence_count,
            has_live_capture,
            is_offline,
            file_types=file_types,
            incident_type=incident_type,
        )
        guidance_items.extend(evidence_guidance)
        
        # Location analysis
        location_guidance = self._analyze_location(
            gps_accuracy, movement_speed, is_offline
        )
        guidance_items.extend(location_guidance)
        
        # Device trust analysis
        if device_trust_score is not None:
            device_guidance = self._analyze_device_trust(device_trust_score)
            guidance_items.extend(device_guidance)
        
        # Estimate trust score
        trust_estimate = self._estimate_trust_score(
            description, incident_type, evidence_count, 
            gps_accuracy, device_trust_score, has_live_capture, is_offline
        )
        
        # Add trust score guidance
        score_guidance = self._generate_trust_score_guidance(trust_estimate)
        guidance_items.extend(score_guidance)
        
        return guidance_items, trust_estimate
    
    def _analyze_description(self, description: str, incident_type: str, evidence_count: int = 0) -> List[GuidanceItem]:
        """Analyze description quality."""
        guidance = []
        text = (description or "").strip()
        word_count = len(text.split())
        char_count = len(text)
        quality_metrics = self.evaluate_description_quality(text, incident_type)
        
        # Length analysis
        if word_count < self.thresholds['min_words_for_detail']:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Description Too Brief",
                message=f"Add {self.thresholds['min_words_for_detail'] - word_count} more words for better verification.",
                suggested_action="Include details about location, time, people involved, and specific actions."
            ))
        elif word_count < self.thresholds['ideal_description_length']:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Add More Detail",
                message="Good start, but more details will increase verification chances.",
                suggested_action="Add specific information about weapons, clothing, vehicle descriptions, or exact location."
            ))
        else:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.SUCCESS,
                title="Good Description Length",
                message="Description has sufficient detail for verification."
            ))
        
        # Incident type relevance - enhanced with specific missing words
        incident_data = self._get_incident_keywords(incident_type)
        required_keywords = incident_data["required"]
        recommended_keywords = incident_data["recommended"]
        evidence_hints = incident_data["evidence_hints"]
        
        found_required = [kw for kw in required_keywords if kw.lower() in text.lower()]
        found_recommended = [kw for kw in recommended_keywords if kw.lower() in text.lower()]
        missing_required = [kw for kw in required_keywords if kw.lower() not in text.lower()]
        missing_recommended = [kw for kw in recommended_keywords if kw.lower() not in text.lower()]
        
        # Check for people mentioned (for evidence suggestions)
        people_mentioned = self._extract_people_count(text)
        has_people = people_mentioned > 0 or any(word in text.lower() for word in ['people', 'person', 'man', 'woman', 'child', 'men', 'women', 'children', 'group', 'crowd'])
        
        # Generate specific missing words guidance
        if missing_required:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Missing Required Details",
                message=f"Add these essential words: {', '.join(missing_required)}",
                suggested_action=f"Include: {self._format_missing_words_suggestion(missing_required, incident_type)}"
            ))
        
        if missing_recommended:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Add Recommended Details",
                message=f"Add these words for better verification: {', '.join(missing_recommended[:3])}",
                suggested_action=f"Include details about: {', '.join(missing_recommended[:3])}"
            ))
        
        # Evidence suggestions based on content
        if has_people and evidence_count == 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Add Evidence of People",
                message="You mentioned people - add photos/videos to support this.",
                suggested_action="Take photos of the people involved, location, or any visible evidence."
            ))
        
        # Specific evidence hints based on mentioned keywords
        mentioned_evidence_keywords = [hint for hint in evidence_hints if hint.lower() in text.lower()]
        if mentioned_evidence_keywords and evidence_count == 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Add Evidence for Mentioned Details",
                message=f"You mentioned: {', '.join(mentioned_evidence_keywords)}. Add photos/videos.",
                suggested_action=f"Take clear photos of: {', '.join(mentioned_evidence_keywords)} to verify your report."
            ))
        
        # Quality checks
        if not re.search(r'\d', text):
            guidance.append(GuidanceItem(
                level=GuidanceLevel.INFO,
                title="Add Numbers",
                message="Include counts, times, or quantities for better verification.",
                suggested_action="How many people? What time did it happen? How many items?"
            ))
        
        # Check for vague language
        vague_patterns = ['someone', 'something', 'somehow', 'somewhere', 'a person', 'a thing']
        vague_found = [pattern for pattern in vague_patterns if pattern in text.lower()]
        
        if len(vague_found) > 2:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Be More Specific",
                message="Replace vague terms with specific descriptions.",
                suggested_action="Instead of 'someone', describe the person (gender, clothing, height, etc.)"
            ))

        if quality_metrics["authenticity_score"] < 45:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Text Looks Repetitive or Random",
                message="Description appears repetitive/noisy and may be rejected by language validation.",
                suggested_action="Use plain sentences: who did what, where, when, and visible evidence."
            ))
        elif quality_metrics["authenticity_score"] < 65:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Improve Text Clarity",
                message="Description has weak language quality signals.",
                suggested_action="Reduce repeated words/letters and add concrete incident details."
            ))

        if quality_metrics["incident_alignment_score"] < 45:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Incident Mismatch Risk",
                message="Description does not clearly match the selected incident type.",
                suggested_action=f"Add terms specific to {incident_type} and explain the exact event."
            ))
        
        return guidance
    
    def _analyze_evidence(
        self, 
        evidence_count: int, 
        has_live_capture: bool, 
        is_offline: bool,
        file_types: Optional[List[str]] = None,
        incident_type: str = "Default",
    ) -> List[GuidanceItem]:
        """Analyze evidence quality for TrustBond and YOLO evidence pipelines."""
        guidance = []
        metrics = self.evaluate_evidence_quality(
            evidence_count=evidence_count,
            has_live_capture=has_live_capture,
            file_types=file_types,
            incident_type=incident_type,
        )
        incident_data = self._get_incident_keywords(incident_type)
        hints = incident_data.get("evidence_hints", [])
        hint_text = ", ".join(hints[:4]) if hints else "scene, people, key objects"
        
        if evidence_count == 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="No Evidence Added",
                message="Reports with evidence are 5x more likely to be verified.",
                suggested_action=f"For {incident_type}, add media showing: {hint_text}."
            ))
        elif evidence_count < self.thresholds['ideal_evidence_count']:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Add More Evidence",
                message=f"Add {self.thresholds['ideal_evidence_count'] - evidence_count} more photos for better verification.",
                suggested_action="Take photos from different angles and distances."
            ))
        else:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.SUCCESS,
                title="Good Evidence Amount",
                message="Multiple evidence files improve verification chances."
            ))
        
        if not has_live_capture and evidence_count > 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.INFO,
                title="Use Live Camera",
                message="Live photos are more trusted than gallery images.",
                suggested_action="Take new photos instead of using existing images."
            ))

        if metrics["yolo_coverage_score"] < 45 and evidence_count > 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Weak YOLO Coverage",
                message="Current files may not provide clear visual signals for object/scene detection.",
                suggested_action=(
                    f"Add clearer photo/video for {incident_type} showing: {hint_text}. "
                    "Keep lighting good and framing stable."
                )
            ))

        if metrics["trustbond_evidence_score"] < 45 and evidence_count > 0:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Weak TrustBond Evidence Reliability",
                message="Evidence source reliability is low (for example gallery-only evidence).",
                suggested_action="Capture live media at scene and keep GPS/time metadata available."
            ))
        
        return guidance

    def evaluate_evidence_quality(
        self,
        *,
        evidence_count: int,
        has_live_capture: bool,
        file_types: Optional[List[str]] = None,
        incident_type: str = "Default",
    ) -> Dict[str, float]:
        """Estimate evidence quality with separate TrustBond and YOLO support signals."""
        types = [str(t).strip().lower() for t in (file_types or []) if str(t).strip()]
        image_types = {"photo", "image", "jpg", "jpeg", "png", "webp"}
        video_types = {"video", "mp4", "mov", "avi", "mkv", "3gp"}
        audio_types = {"audio", "mp3", "wav", "m4a", "aac", "ogg"}

        images = sum(1 for t in types if t in image_types)
        videos = sum(1 for t in types if t in video_types)
        audios = sum(1 for t in types if t in audio_types)

        if not types and evidence_count > 0:
            # When types are unavailable, assume generic media.
            images = evidence_count

        trustbond_score = min(100.0, evidence_count * 28.0)
        if has_live_capture:
            trustbond_score += 22.0
        trustbond_score = max(0.0, min(100.0, trustbond_score))

        # YOLO is strongest on image/video content; audio contributes little to object/scene detection.
        yolo_score = min(100.0, (images * 35.0) + (videos * 30.0) + (audios * 5.0))
        if images == 0 and videos == 0 and evidence_count > 0:
            yolo_score = min(yolo_score, 30.0)
        yolo_score = max(0.0, min(100.0, yolo_score))

        # Incident-aware media preference: some incidents are usually better supported by specific media mixes.
        incident_lower = (incident_type or "").strip().lower()
        prefers_video = any(k in incident_lower for k in ["traffic", "suspicious", "assault", "harassment"])
        prefers_photo = any(k in incident_lower for k in ["theft", "vandalism", "drug", "fraud"])
        if evidence_count > 0:
            if prefers_video and videos == 0:
                yolo_score = max(0.0, yolo_score - 10.0)
            if prefers_photo and images == 0:
                yolo_score = max(0.0, yolo_score - 10.0)

        overall = max(0.0, min(100.0, (trustbond_score * 0.45) + (yolo_score * 0.55)))
        return {
            "overall_score": round(overall, 2),
            "trustbond_evidence_score": round(trustbond_score, 2),
            "yolo_coverage_score": round(yolo_score, 2),
        }
    
    def _analyze_location(
        self, 
        gps_accuracy: Optional[float], 
        movement_speed: Optional[float],
        is_offline: bool
    ) -> List[GuidanceItem]:
        """Analyze location quality."""
        guidance = []
        
        if gps_accuracy is None:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="No Location Data",
                message="GPS location is required for verification.",
                suggested_action="Enable location services and wait for GPS signal."
            ))
        elif gps_accuracy > self.thresholds['min_gps_accuracy']:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Poor GPS Accuracy",
                message=f"GPS accuracy is {gps_accuracy:.0f}m (target: <{self.thresholds['min_gps_accuracy']}m).",
                suggested_action="Move to open area or wait for better GPS signal."
            ))
        else:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.SUCCESS,
                title="Good GPS Accuracy",
                message=f"GPS accuracy is {gps_accuracy:.0f}m - excellent for verification."
            ))
        
        if movement_speed is not None and movement_speed > 5:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Movement Detected",
                message="Stay still for better GPS accuracy.",
                suggested_action="Stop moving while submitting report for better location data."
            ))
        
        return guidance
    
    def _analyze_device_trust(self, device_trust_score: float) -> List[GuidanceItem]:
        """Analyze device trust score."""
        guidance = []
        
        if device_trust_score < 20:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Device Trust Score Low",
                message=f"Your device trust score is {device_trust_score:.0f}/100.",
                suggested_action="Build trust by submitting accurate reports over time."
            ))
        elif device_trust_score > 70:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.SUCCESS,
                title="Excellent Device Trust",
                message=f"Your device trust score is {device_trust_score:.0f}/100 - reports will be prioritized."
            ))
        
        return guidance
    
    def _estimate_trust_score(
        self,
        description: str,
        incident_type: str,
        evidence_count: int,
        gps_accuracy: Optional[float],
        device_trust_score: Optional[float],
        has_live_capture: bool,
        is_offline: bool
    ) -> TrustScoreEstimate:
        """Estimate trust score (offline capable)."""
        
        # TrustBond estimation (location/device)
        trustbond_score = 50.0  # Base score
        
        if gps_accuracy:
            if gps_accuracy < 20:
                trustbond_score += 20
            elif gps_accuracy < 50:
                trustbond_score += 10
            else:
                trustbond_score -= 10
        
        if device_trust_score:
            trustbond_score = (trustbond_score + device_trust_score) / 2
        
        # Natural Language estimation (advanced quality + incident alignment)
        quality_metrics = self.evaluate_description_quality(description, incident_type)
        nl_score = (
            quality_metrics["authenticity_score"] * 0.55
            + quality_metrics["incident_alignment_score"] * 0.45
        )
        nl_score = max(0.0, min(100.0, nl_score))
        
        # Volo estimation (evidence)
        volo_score = None
        if evidence_count > 0:
            volo_score = min(80.0, evidence_count * 25)
            if has_live_capture:
                volo_score += 10
        else:
            volo_score = 0.0
        
        # Base score
        base_score = 10.0
        
        # Calculate weighted total
        if is_offline and evidence_count == 0:
            # No evidence policy: 50% TrustBond + 50% Natural Language.
            weights = {
                'trustbond': 0.5,
                'natural_language': 0.5,
                'volo': 0.0,
                'base': 0.0
            }
        else:
            weights = self.model_weights
        
        total_score = (
            trustbond_score * weights['trustbond'] +
            (nl_score or 0) * weights['natural_language'] +
            (volo_score or 0) * weights['volo'] +
            base_score * weights['base']
        )
        
        # Determine contributing models
        contributing = 1  # Base always contributes
        if trustbond_score > 20:
            contributing += 1
        if nl_score > 20:
            contributing += 1
        if volo_score and volo_score > 20:
            contributing += 1
        
        has_evidence = evidence_count > 0
        confirm_min = self.thresholds['evidence_confirmed_min'] if has_evidence else self.thresholds['text_confirmed_min']
        review_min = self.thresholds['evidence_under_review_min'] if has_evidence else self.thresholds['text_under_review_min']

        # Determine confidence and verification likelihood using aligned thresholds
        if total_score >= confirm_min:
            confidence = "high_confidence"
            will_be_verified = True
        elif total_score >= review_min:
            confidence = "medium_confidence"
            will_be_verified = False
        elif total_score > 0:
            confidence = "low_confidence"
            will_be_verified = False
        else:
            confidence = "reject"
            will_be_verified = False
        
        return TrustScoreEstimate(
            total_score=total_score,
            trustbond_score=trustbond_score,
            natural_language_score=nl_score,
            volo_score=volo_score,
            base_score=base_score,
            confidence=confidence,
            will_be_verified=will_be_verified,
            contributing_models=contributing
        )
    
    def _generate_trust_score_guidance(self, estimate: TrustScoreEstimate) -> List[GuidanceItem]:
        """Generate guidance based on trust score estimate."""
        guidance = []
        
        if estimate.will_be_verified:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.SUCCESS,
                title="High Verification Probability",
                message=f"Estimated trust score {estimate.total_score:.0f}/100 - likely to be auto-verified.",
                actionable=False
            ))
        elif estimate.confidence == "medium_confidence":
            guidance.append(GuidanceItem(
                level=GuidanceLevel.WARNING,
                title="Medium Verification Chance",
                message=f"Estimated trust score {estimate.total_score:.0f}/100 - may require human review.",
                suggested_action="Add more evidence or description details to increase verification chances."
            ))
        elif estimate.confidence == "low_confidence":
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="Low Verification Chance",
                message=f"Estimated trust score {estimate.total_score:.0f}/100 - likely to be rejected.",
                suggested_action="Significantly improve description, add more evidence, and ensure good GPS accuracy."
            ))
        else:
            guidance.append(GuidanceItem(
                level=GuidanceLevel.CRITICAL,
                title="High Rejection Risk",
                message=f"Estimated trust score {estimate.total_score:.0f}/100 - very likely to be rejected.",
                suggested_action="Report needs major improvements in all areas to be considered."
            ))
        
        return guidance
    
    def _get_incident_keywords(self, incident_type: str) -> Dict[str, List[str]]:
        """Get relevant keywords for incident type."""
        keyword_map = {
            # Exact DB incident types
            "Assault": {
                "required": ["person", "location", "time"],
                "recommended": ["weapon", "attacked", "injured", "description"],
                "evidence_hints": ["weapon", "injury", "location", "people"]
            },
            "Domestic Violence": {
                "required": ["person", "location", "time"],
                "recommended": ["partner", "family", "threat", "injury", "weapon"],
                "evidence_hints": ["injury", "damage", "location", "people"]
            },
            "Drug Activity": {
                "required": ["drugs", "location", "time"],
                "recommended": ["selling", "using", "packaging", "person", "vehicle"],
                "evidence_hints": ["drugs", "packaging", "location", "people"]
            },
            "Fraud/Scam": {
                "required": ["person", "location", "time"],
                "recommended": ["money", "phone", "transfer", "message", "account"],
                "evidence_hints": ["phone", "message", "receipt", "location"]
            },
            "Harassment": {
                "required": ["person", "location", "time"],
                "recommended": ["threat", "stalk", "message", "witness", "description"],
                "evidence_hints": ["messages", "audio", "location", "people"]
            },
            "Suspicious Activity": {
                "required": ["person", "location", "time"],
                "recommended": ["behavior", "vehicle", "object", "movement", "description"],
                "evidence_hints": ["person", "vehicle", "object", "location"]
            },
            "Theft": {
                "required": ["stolen", "property", "location", "time"],
                "recommended": ["thief", "value", "belongings", "description"],
                "evidence_hints": ["stolen", "property", "thief", "location"]
            },
            "Traffic Incident": {
                "required": ["vehicle", "location", "time"],
                "recommended": ["collision", "plate", "injury", "road", "damage"],
                "evidence_hints": ["vehicle", "road", "damage", "location"]
            },
            "Vandalism": {
                "required": ["damaged", "property", "location", "time"],
                "recommended": ["broken", "destroyed", "graffiti", "description"],
                "evidence_hints": ["damage", "property", "vandalism", "location"]
            },
            # Compatibility aliases for old labels
            "Drugs": {
                "required": ["drugs", "location", "time"],
                "recommended": ["using", "selling", "packaging", "people", "description"],
                "evidence_hints": ["drugs", "packaging", "location", "people"]
            },
            "Accident": {
                "required": ["accident", "location", "time"],
                "recommended": ["injured", "vehicle", "collision", "damage", "description"],
                "evidence_hints": ["accident", "damage", "vehicle", "injuries"]
            },
            "Default": {
                "required": ["person", "location", "time"],
                "recommended": ["description", "happened", "details"],
                "evidence_hints": ["location", "people", "evidence"]
            }
        }

        raw = (incident_type or "").strip()
        if raw in keyword_map:
            return keyword_map[raw]

        lowered = raw.lower()
        alias_map = {
            "domestic violence": "Domestic Violence",
            "drug activity": "Drug Activity",
            "fraud/scam": "Fraud/Scam",
            "fraud": "Fraud/Scam",
            "scam": "Fraud/Scam",
            "harassment": "Harassment",
            "suspicious activity": "Suspicious Activity",
            "traffic incident": "Traffic Incident",
            "theft": "Theft",
            "vandalism": "Vandalism",
            "assault": "Assault",
            "drugs": "Drug Activity",
            "accident": "Traffic Incident",
        }
        canonical = alias_map.get(lowered)
        if canonical and canonical in keyword_map:
            return keyword_map[canonical]

        return keyword_map["Default"]

    def evaluate_description_quality(self, description: str, incident_type: str) -> Dict[str, float]:
        """
        Advanced text-quality estimate for guidance:
        - authenticity_score: repetition/noise/gibberish resistance
        - incident_alignment_score: semantic or keyword alignment to incident type
        """
        text = (description or "").strip()
        if not text:
            return {
                "quality_score": 0.0,
                "authenticity_score": 0.0,
                "incident_alignment_score": 0.0,
            }

        tokens = re.findall(r"[a-zA-Z]{2,}", text.lower())
        token_count = len(tokens)
        unique_ratio = (len(set(tokens)) / token_count) if token_count else 0.0
        max_repeat_ratio = (max(Counter(tokens).values()) / token_count) if token_count else 1.0
        repeated_char_runs = len(re.findall(r"(.)\1{3,}", text.lower()))
        vowel_light_tokens = sum(1 for t in tokens if not re.search(r"[aeiou]", t))
        vowel_light_ratio = (vowel_light_tokens / token_count) if token_count else 1.0
        long_token_ratio = (sum(1 for t in tokens if len(t) > 12) / token_count) if token_count else 1.0

        length_score = min(1.0, max(0.0, len(text) / 180.0))
        structure_score = min(1.0, max(0.0, token_count / 35.0))
        diversity_score = min(1.0, unique_ratio / 0.75) if unique_ratio < 0.75 else 1.0

        penalty = 0.0
        penalty += min(0.45, max(0.0, max_repeat_ratio - 0.14) * 2.4)
        penalty += min(0.25, repeated_char_runs * 0.06)
        penalty += min(0.30, max(0.0, vowel_light_ratio - 0.40) * 0.8)
        penalty += min(0.20, max(0.0, long_token_ratio - 0.35) * 0.7)

        authenticity = ((length_score * 0.3) + (structure_score * 0.35) + (diversity_score * 0.35) - penalty) * 100.0
        authenticity = max(0.0, min(100.0, authenticity))

        incident_alignment = self._incident_alignment_score(text, incident_type)
        quality_score = max(0.0, min(100.0, (authenticity * 0.6) + (incident_alignment * 0.4)))

        return {
            "quality_score": round(quality_score, 2),
            "authenticity_score": round(authenticity, 2),
            "incident_alignment_score": round(incident_alignment, 2),
        }

    def _incident_alignment_score(self, description: str, incident_type: str) -> float:
        incident_data = self._get_incident_keywords(incident_type)
        required = incident_data.get("required", [])
        recommended = incident_data.get("recommended", [])
        desc_lower = (description or "").lower()

        if not required and not recommended:
            return 50.0

        required_hits = sum(1 for kw in required if kw.lower() in desc_lower)
        recommended_hits = sum(1 for kw in recommended if kw.lower() in desc_lower)
        required_ratio = (required_hits / len(required)) if required else 0.0
        recommended_ratio = (recommended_hits / len(recommended)) if recommended else 0.0
        keyword_score = ((required_ratio * 0.7) + (recommended_ratio * 0.3)) * 100.0

        model = self._get_semantic_model()
        if model is None:
            return max(0.0, min(100.0, keyword_score))

        try:
            from sentence_transformers import util
            incident_text = " ".join([incident_type] + required + recommended).strip()
            emb = model.encode([description, incident_text], convert_to_tensor=True, normalize_embeddings=True)
            semantic_score = float(util.cos_sim(emb[0], emb[1]).item()) * 100.0
            return max(0.0, min(100.0, (keyword_score * 0.45) + (semantic_score * 0.55)))
        except Exception:
            return max(0.0, min(100.0, keyword_score))

    def _get_semantic_model(self):
        if self._semantic_model is not None:
            return self._semantic_model
        if self._semantic_model_unavailable:
            return None
        try:
            from app.core.model_manager import ensure_sentence_transformer_model
            self._semantic_model = ensure_sentence_transformer_model("all-MiniLM-L6-v2")
            return self._semantic_model
        except Exception:
            self._semantic_model_unavailable = True
            return None
    
    def _init_description_rules(self) -> Dict[str, Any]:
        """Initialize description validation rules."""
        return {
            'min_length': 10,
            'ideal_length': 50,
            'max_length': 500,
            'required_patterns': [r'\w+', r'[a-zA-Z]'],
            'forbidden_patterns': [r'^.{0,5}$'],  # Too short
        }
    
    def _init_evidence_rules(self) -> Dict[str, Any]:
        """Initialize evidence validation rules."""
        return {
            'min_count': 0,
            'ideal_count': 3,
            'max_count': 10,
            'supported_formats': ['jpg', 'jpeg', 'png', 'mp4', 'mov'],
            'max_file_size': 50 * 1024 * 1024,  # 50MB
        }
    
    def _init_location_rules(self) -> Dict[str, Any]:
        """Initialize location validation rules."""
        return {
            'min_gps_accuracy': 10,  # meters
            'ideal_gps_accuracy': 20,
            'max_movement_speed': 2.0,  # m/s while submitting
        }
    
    def _extract_people_count(self, description: str) -> int:
        """Extract number of people mentioned in description."""
        # Look for number + people patterns
        people_patterns = [
            r'(\d+)\s*(?:people|person|man|men|woman|women|child|children)',
            r'(?:people|person|man|men|woman|women|child|children):\s*(\d+)',
        ]
        
        for pattern in people_patterns:
            matches = re.findall(pattern, description.lower())
            if matches:
                return int(matches[0])
        
        # Count individual people words
        people_words = ['man', 'woman', 'child', 'person', 'people']
        count = sum(1 for word in people_words if word in description.lower())
        
        return count
    
    def _format_missing_words_suggestion(self, missing_words: List[str], incident_type: str) -> str:
        """Format specific suggestions for missing words."""
        suggestions = []
        
        for word in missing_words:
            if word == "person":
                suggestions.append("who was involved (man, woman, child, how many)")
            elif word == "location":
                suggestions.append("where it happened (street name, landmark, building)")
            elif word == "time":
                suggestions.append("when it happened (exact time, morning/evening)")
            elif word == "weapon":
                suggestions.append("what weapon was used (knife, gun, panga, object)")
            elif word == "attacked":
                suggestions.append("how the attack happened (punched, stabbed, threatened)")
            elif word == "injured":
                suggestions.append("injuries sustained (cuts, bruises, serious injuries)")
            elif word == "stolen":
                suggestions.append("what was taken (phone, wallet, bag, valuables)")
            elif word == "property":
                suggestions.append("what property was affected (car, house, window, sign)")
            elif word == "damaged":
                suggestions.append("type of damage (broken, burned, spray-painted, destroyed)")
            elif word == "drugs":
                suggestions.append("drug details (type, packaging, amount, appearance)")
            elif word == "fire":
                suggestions.append("fire details (what's burning, smoke color, flames size)")
            elif word == "accident":
                suggestions.append("accident details (vehicles involved, collision type, damage)")
            else:
                suggestions.append(f"details about {word}")
        
        return "; ".join(suggestions)

# Global instance
submission_guidance = SubmissionGuidance()
