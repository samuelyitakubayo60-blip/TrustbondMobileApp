"""
Volo Model Scorer
Analyzes evidence content authenticity using YOLO object detection.
Outputs only scores - no decision making.
"""

from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
import logging
import numpy as np
from datetime import datetime, timezone

from .trust_thresholds import trust_thresholds

logger = logging.getLogger(__name__)

@dataclass
class VoloAnalysisResult:
    """Result of Volo evidence analysis."""
    evidence_authenticity_score: float  # 0-100
    object_detection_score: float  # 0-100
    image_quality_score: float  # 0-100
    overall_score: float  # 0-100 weighted combination
    confidence: float  # 0.0-1.0
    metadata: Dict[str, Any]

class VoloScorer:
    """Volo model scorer for evidence analysis."""
    
    def __init__(self):
        self.thresholds = trust_thresholds
        self.yolo_model = None
        self.yolo_unavailable = False
    
    def _get_yolo_model(self):
        """Lazy-load YOLO model."""
        if self.yolo_model is not None:
            return self.yolo_model
        if self.yolo_unavailable:
            return None
        
        try:
            from .model_manager import ensure_yolo_model
            self.yolo_model = ensure_yolo_model('yolov8n.pt')
            return self.yolo_model
        except Exception as exc:
            logger.warning(f"YOLO model unavailable: {exc}")
            self.yolo_unavailable = True
            return None
    
    def analyze_evidence(
        self,
        image_url: str,
        incident_type_name: str = "",
        expected_objects: Optional[List[str]] = None
    ) -> VoloAnalysisResult:
        """
        Analyze evidence image for authenticity and content.
        
        Args:
            image_url: URL of the evidence image
            incident_type_name: Name of the incident type for context
            expected_objects: List of objects expected for this incident type
            
        Returns:
            VoloAnalysisResult with scores and metadata
        """
        try:
            # Download and analyze image
            image_analysis = self._analyze_image_from_url(image_url)
            
            # 1. Evidence Authenticity Analysis
            authenticity_score, authenticity_metadata = self._analyze_evidence_authenticity(
                image_analysis, incident_type_name
            )
            
            # 2. Object Detection Analysis
            detection_score, detection_metadata = self._analyze_object_detection(
                image_analysis, expected_objects
            )
            
            # 3. Image Quality Analysis
            quality_score, quality_metadata = self._analyze_image_quality(image_analysis)
            
            # 4. Calculate overall score (weighted combination)
            overall_score = (
                authenticity_score * 0.4 +
                detection_score * 0.4 +
                quality_score * 0.2
            )
            
            # 5. Calculate confidence
            confidence = self._calculate_confidence(
                authenticity_metadata, detection_metadata, quality_metadata
            )
            
            # 6. Create result
            metadata = {
                "image_url": image_url,
                "incident_type": incident_type_name,
                "authenticity_analysis": authenticity_metadata,
                "detection_analysis": detection_metadata,
                "quality_analysis": quality_metadata,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }
            
            return VoloAnalysisResult(
                evidence_authenticity_score=authenticity_score,
                object_detection_score=detection_score,
                image_quality_score=quality_score,
                overall_score=overall_score,
                confidence=confidence,
                metadata=metadata
            )
            
        except Exception as exc:
            logger.error(f"Evidence analysis failed: {exc}")
            return self._create_empty_result(f"Analysis failed: {exc}")
    
    def _analyze_image_from_url(self, image_url: str) -> Dict[str, Any]:
        """Download and analyze image from URL."""
        import requests
        import cv2
        from PIL import Image
        import io
        
        # Download image
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        
        # Convert to numpy array for OpenCV
        image_array = np.frombuffer(response.content, np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        
        if image is None:
            raise ValueError("Could not decode image")
        
        pil_image = Image.open(io.BytesIO(response.content))
        
        # Basic analysis
        analysis = {
            "width": image.shape[1],
            "height": image.shape[0],
            "channels": image.shape[2] if len(image.shape) > 2 else 1,
            "file_size": len(response.content),
            "pil_image": pil_image,
            "cv_image": image
        }
        
        # Blur detection
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        analysis["blur_score"] = float(laplacian_var)
        analysis["is_blurry"] = laplacian_var < self.thresholds.config.EVIDENCE_MIN_BLUR_SCORE
        
        # Brightness analysis
        brightness = np.mean(gray) / 255.0
        analysis["brightness"] = float(brightness)
        analysis["brightness_valid"] = (
            self.thresholds.config.EVIDENCE_MIN_BRIGHTNESS <= brightness <= 
            self.thresholds.config.EVIDENCE_MAX_BRIGHTNESS
        )
        
        # Object detection
        analysis["detected_objects"] = self._detect_objects(image)
        
        return analysis
    
    def _detect_objects(self, image: np.ndarray) -> List[str]:
        """Detect objects using YOLO model."""
        model = self._get_yolo_model()
        if model is None:
            return []
        
        try:
            results = model(image, verbose=False)
            
            # Map COCO classes to TrustBond relevant objects
            relevant_classes = {
                0: 'person',
                67: 'cell phone',
                24: 'handbag',
                28: 'backpack',
                39: 'bottle',
                42: 'knife',
                76: 'scissors',
                91: 'baseball bat',
                101: 'knife',
                62: 'laptop',
                84: 'handbag',
                3: 'motorcycle',
                1: 'bicycle'
            }
            
            detected_objects = []
            for result in results:
                if hasattr(result, 'boxes') and result.boxes is not None:
                    boxes = result.boxes
                    if hasattr(boxes, 'cls'):
                        for cls in boxes.cls:
                            class_id = int(cls.item())
                            if class_id in relevant_classes:
                                detected_objects.append(relevant_classes[class_id])
            
            return list(set(detected_objects))  # Remove duplicates
            
        except Exception as exc:
            logger.warning(f"Object detection failed: {exc}")
            return []
    
    def _analyze_evidence_authenticity(
        self,
        image_analysis: Dict[str, Any],
        incident_type_name: str
    ) -> Tuple[float, Dict[str, Any]]:
        """Analyze evidence authenticity."""
        score = 50.0  # Base score
        metadata = {}
        
        # Image quality checks
        if image_analysis.get("is_blurry", True):
            score -= 20
            metadata["blur_penalty"] = 20
        else:
            metadata["blur_penalty"] = 0
        
        if not image_analysis.get("brightness_valid", False):
            score -= 15
            metadata["brightness_penalty"] = 15
        else:
            metadata["brightness_penalty"] = 0
        
        # Resolution check
        width = image_analysis.get("width", 0)
        height = image_analysis.get("height", 0)
        if width >= 1920 and height >= 1080:
            score += 15
            metadata["resolution_bonus"] = 15
        elif width >= 1280 and height >= 720:
            score += 10
            metadata["resolution_bonus"] = 10
        else:
            metadata["resolution_bonus"] = 0
        
        # File size check (reasonable range)
        file_size = image_analysis.get("file_size", 0)
        if 50000 <= file_size <= 5000000:  # 50KB to 5MB
            score += 10
            metadata["file_size_bonus"] = 10
        else:
            metadata["file_size_penalty"] = 10
            score -= 10
        
        # Contextual relevance (basic check)
        detected_objects = image_analysis.get("detected_objects", [])
        if self._objects_relevant_to_incident(detected_objects, incident_type_name):
            score += 15
            metadata["context_relevance_bonus"] = 15
        else:
            metadata["context_relevance_bonus"] = 0
        
        # Clamp to 0-100
        score = max(0.0, min(100.0, score))
        metadata["final_authenticity_score"] = score
        
        return score, metadata
    
    def _analyze_object_detection(
        self,
        image_analysis: Dict[str, Any],
        expected_objects: Optional[List[str]]
    ) -> Tuple[float, Dict[str, Any]]:
        """Analyze object detection results."""
        detected_objects = image_analysis.get("detected_objects", [])
        metadata = {
            "detected_objects": detected_objects,
            "expected_objects": expected_objects or []
        }
        
        # Base score depends on number of objects detected
        object_count = len(detected_objects)
        if object_count >= 5:
            score = 70.0
        elif object_count >= 3:
            score = 55.0
        elif object_count >= 1:
            score = 40.0
        else:
            score = 25.0
        
        metadata["object_count_score"] = score
        
        # Bonus for relevant objects
        if expected_objects:
            matches = len(set(detected_objects) & set(expected_objects))
            if matches >= 3:
                score += 20
            elif matches >= 2:
                score += 15
            elif matches >= 1:
                score += 10
            
            metadata["expected_object_matches"] = matches
            metadata["match_bonus"] = min(matches * 7, 20)
        
        # Penalty for suspicious objects (if any)
        suspicious_objects = ['knife', 'scissors', 'baseball bat']
        suspicious_found = [obj for obj in detected_objects if obj in suspicious_objects]
        if suspicious_found:
            score -= 5
            metadata["suspicious_object_penalty"] = 5
        else:
            metadata["suspicious_object_penalty"] = 0
        
        # Clamp to 0-100
        score = max(0.0, min(100.0, score))
        metadata["final_detection_score"] = score
        
        return score, metadata
    
    def _analyze_image_quality(self, image_analysis: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """Analyze image quality metrics."""
        score = 50.0  # Base score
        metadata = {}
        
        # Blur score
        blur_score = image_analysis.get("blur_score", 0)
        if blur_score >= 200:
            score += 25
            metadata["blur_quality"] = "excellent"
        elif blur_score >= 150:
            score += 15
            metadata["blur_quality"] = "good"
        elif blur_score >= 100:
            score += 5
            metadata["blur_quality"] = "acceptable"
        else:
            score -= 10
            metadata["blur_quality"] = "poor"
        
        # Brightness score
        brightness = image_analysis.get("brightness", 0.5)
        if 0.3 <= brightness <= 0.7:
            score += 15
            metadata["brightness_quality"] = "optimal"
        elif 0.2 <= brightness <= 0.8:
            score += 5
            metadata["brightness_quality"] = "acceptable"
        else:
            score -= 10
            metadata["brightness_quality"] = "poor"
        
        # Resolution score
        width = image_analysis.get("width", 0)
        height = image_analysis.get("height", 0)
        total_pixels = width * height
        
        if total_pixels >= 2073600:  # 1920x1080
            score += 10
            metadata["resolution_quality"] = "high"
        elif total_pixels >= 921600:  # 1280x720
            score += 5
            metadata["resolution_quality"] = "medium"
        else:
            metadata["resolution_quality"] = "low"
        
        # Clamp to 0-100
        score = max(0.0, min(100.0, score))
        metadata["final_quality_score"] = score
        
        return score, metadata
    
    def _objects_relevant_to_incident(self, objects: List[str], incident_type: str) -> bool:
        """Check if detected objects are relevant to the incident type."""
        incident_type = incident_type.lower()
        
        relevance_map = {
            "theft": ["person", "cell phone", "handbag", "backpack", "laptop"],
            "assault": ["person", "knife", "baseball bat"],
            "vandalism": ["person"],
            "fraud/scam": ["cell phone", "laptop"],
            "drug activity": ["person", "bottle"],
            "traffic incident": ["motorcycle", "bicycle", "person"]
        }
        
        for incident, relevant_objects in relevance_map.items():
            if incident in incident_type:
                return any(obj in objects for obj in relevant_objects)
        
        # Default: if objects detected, assume some relevance
        return len(objects) > 0
    
    def _calculate_confidence(
        self,
        authenticity_metadata: Dict[str, Any],
        detection_metadata: Dict[str, Any],
        quality_metadata: Dict[str, Any]
    ) -> float:
        """Calculate confidence in the analysis."""
        confidence = 0.6  # Base confidence
        
        # Boost confidence if quality is good
        if quality_metadata.get("blur_quality") in ["excellent", "good"]:
            confidence += 0.15
        
        if quality_metadata.get("brightness_quality") == "optimal":
            confidence += 0.1
        
        # Reduce confidence if penalties were applied
        total_penalties = (
            authenticity_metadata.get("blur_penalty", 0) +
            authenticity_metadata.get("brightness_penalty", 0) +
            authenticity_metadata.get("file_size_penalty", 0)
        )
        
        if total_penalties > 20:
            confidence -= 0.2
        elif total_penalties > 10:
            confidence -= 0.1
        
        # Adjust based on object detection
        object_count = len(detection_metadata.get("detected_objects", []))
        if object_count >= 3:
            confidence += 0.1
        elif object_count == 0:
            confidence -= 0.1
        
        return max(0.3, min(1.0, confidence))
    
    def _create_empty_result(self, reason: str) -> VoloAnalysisResult:
        """Create empty result for cases where analysis cannot be performed."""
        return VoloAnalysisResult(
            evidence_authenticity_score=0.0,
            object_detection_score=0.0,
            image_quality_score=0.0,
            overall_score=0.0,
            confidence=0.0,
            metadata={
                "error": reason,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }
        )

# Global instance
volo_scorer = VoloScorer()

# Export main function for easy access
def analyze_evidence_content(
    image_url: str,
    incident_type_name: str = "",
    expected_objects: Optional[List[str]] = None
) -> VoloAnalysisResult:
    """Convenience function for evidence analysis."""
    return volo_scorer.analyze_evidence(
        image_url=image_url,
        incident_type_name=incident_type_name,
        expected_objects=expected_objects
    )
