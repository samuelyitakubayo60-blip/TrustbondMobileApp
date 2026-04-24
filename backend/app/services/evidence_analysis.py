"""
Evidence Analysis Service for TrustBond
Integrates with report submission to validate evidence content
"""

import os
import json
import cv2
import numpy as np
import io
import requests
from PIL import Image, ImageFilter, ImageEnhance
import pytesseract
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging
from sqlalchemy.orm import Session
from ultralytics import YOLO

logger = logging.getLogger(__name__)

@dataclass
class EvidenceAnalysis:
    """Results of evidence analysis"""
    has_people: bool = False
    people_count: int = 0
    is_blurry: bool = False
    blur_score: float = 0.0
    brightness: float = 0.0
    has_text: bool = False
    extracted_text: str = ""
    detected_objects: List[str] = None
    scene_type: str = ""
    file_size: int = 0
    resolution: Tuple[int, int] = (0, 0)
    exif_complete: bool = False
    confidence_score: float = 0.0

    def __post_init__(self):
        if self.detected_objects is None:
            self.detected_objects = []

class EvidenceAnalysisService:
    """Evidence analysis service for validating incident evidence"""
    
    def __init__(self):
        # Load validation rules from JSON file if it exists
        self.validation_rules = self._load_validation_rules()
        
        # Initialize YOLOv8n model (smallest model - 6MB)
        try:
            self.yolo_model = YOLO('yolov8n.pt')  # Nano version - smallest, fastest
            logger.info("YOLOv8n model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            self.yolo_model = None
        
        # Enhanced rules based on TrustBond incident types
        self.enhanced_rules = {
            1: {  # Theft
                'expected_objects': ['person', 'people', 'bag', 'phone', 'money', 'wallet'],
                'expected_actions': ['running', 'struggling', 'taking', 'grabbing'],
                'expected_scenes': ['market', 'street', 'shop'],
                'keywords': ['robbery', 'smart', 'phone', 'stole', 'thief'],
                'weight': 1.2
            },
            2: {  # Assault
                'expected_objects': ['person', 'people', 'weapon', 'blood', 'injury'],
                'expected_actions': ['fighting', 'hitting', 'attacking', 'struggling'],
                'expected_scenes': ['street', 'public', 'building'],
                'keywords': ['panga', 'attacked', 'fight', 'assault', 'violent'],
                'weight': 1.6
            },
            3: {  # Vandalism
                'expected_objects': ['broken', 'damaged', 'graffiti', 'property'],
                'expected_actions': ['breaking', 'destroying', 'painting'],
                'expected_scenes': ['wall', 'building', 'vehicle'],
                'keywords': ['vandalism', 'broken', 'damaged', 'destroyed'],
                'weight': 1.1
            },
            4: {  # Suspicious Activity
                'expected_objects': ['person', 'people', 'group', 'vehicle'],
                'expected_actions': ['lurking', 'watching', 'hiding', 'crossing'],
                'expected_scenes': ['street', 'region', 'night'],
                'keywords': ['unusual', 'suspicious', 'strange', 'movements'],
                'weight': 1.0
            },
            5: {  # Domestic Violence
                'expected_objects': ['person', 'people', 'child', 'woman', 'man'],
                'expected_actions': ['abuse', 'violence', 'threatening'],
                'expected_scenes': ['home', 'household', 'inside'],
                'keywords': ['abuse', 'child', 'wife', 'husband', 'domestic'],
                'weight': 1.7
            },
            6: {  # Drug Activity
                'expected_objects': ['person', 'people', 'drugs', 'paraphernalia'],
                'expected_actions': ['using', 'selling', 'spreading'],
                'expected_scenes': ['street', 'youth', 'group'],
                'keywords': ['drugs', 'spreading', 'youth', 'using'],
                'weight': 1.4
            },
            7: {  # Fraud/Scam
                'expected_objects': ['person', 'people', 'phone', 'money', 'document'],
                'expected_actions': ['deceiving', 'scamming', 'tricking'],
                'expected_scenes': ['public', 'market', 'shop'],
                'keywords': ['fraud', 'scam', 'deception', 'mobile money'],
                'weight': 1.3
            },
            8: {  # Harassment
                'expected_objects': ['person', 'people', 'group'],
                'expected_actions': ['threatening', 'stalking', 'intimidating'],
                'expected_scenes': ['public', 'street', 'repeated'],
                'keywords': ['threatening', 'harassment', 'stalking', 'words'],
                'weight': 1.2
            },
            9: {  # Traffic Incident
                'expected_objects': ['vehicle', 'car', 'person', 'people'],
                'expected_actions': ['accident', 'collision', 'blocking'],
                'expected_scenes': ['road', 'street', 'intersection'],
                'keywords': ['traffic', 'accident', 'road', 'vehicle'],
                'weight': 1.0
            }
        }
    
    def _load_validation_rules(self) -> Dict:
        """Load validation rules from JSON file if available"""
        try:
            rules_path = os.path.join(os.path.dirname(__file__), '..', '..', 'evidence_validation_rules.json')
            if os.path.exists(rules_path):
                with open(rules_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load validation rules: {e}")
        return {}
    
    def analyze_image_from_url(self, image_url: str) -> EvidenceAnalysis:
        """Analyze image from Cloudinary URL"""
        try:
            # Download image from URL
            import requests
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            # Load image
            image_array = np.frombuffer(response.content, np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            if image is None:
                raise ValueError("Could not decode image")
            
            pil_image = Image.open(io.BytesIO(response.content))
            
            # Perform analysis
            return self._analyze_image_internal(image, pil_image)
            
        except Exception as e:
            logger.error(f"Error analyzing image from URL {image_url}: {e}")
            return EvidenceAnalysis()
    
    def _analyze_image_internal(self, image: np.ndarray, pil_image: Image.Image) -> EvidenceAnalysis:
        """Internal image analysis method"""
        analysis = EvidenceAnalysis()
        
        # Basic image properties
        analysis.file_size = len(pil_image.tobytes())
        analysis.resolution = pil_image.size
        analysis.exif_complete = self._check_exif_data(pil_image)
        
        # 1. People detection
        analysis.has_people, analysis.people_count = self._detect_people(image)
        
        # 2. Blur detection
        analysis.is_blurry, analysis.blur_score = self._detect_blur(image)
        
        # 3. Brightness analysis
        analysis.brightness = self._analyze_brightness(image)
        
        # 4. Text extraction (OCR)
        analysis.has_text, analysis.extracted_text = self._extract_text(pil_image)
        
        # 5. Object detection (YOLO-powered)
        analysis.detected_objects = self._detect_objects_with_yolo(image)
        
        # 6. Scene classification
        analysis.scene_type = self._classify_scene(image, analysis.detected_objects)
        
        # Calculate overall confidence
        analysis.confidence_score = self._calculate_confidence_score(analysis)
        
        return analysis
    
    def _detect_people(self, image: np.ndarray) -> Tuple[bool, int]:
        """Detect people in image using OpenCV"""
        try:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            
            boxes, weights = hog.detectMultiScale(image, winStride=(8, 8))
            people_count = len(boxes)
            has_people = people_count > 0
            
            return has_people, people_count
            
        except Exception as e:
            logger.warning(f"People detection failed: {e}")
            return False, 0
    
    def _detect_blur(self, image: np.ndarray) -> Tuple[bool, float]:
        """Detect if image is blurry using Laplacian variance"""
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            blur_threshold = 100.0
            is_blurry = laplacian_var < blur_threshold
            
            return is_blurry, laplacian_var
            
        except Exception as e:
            logger.warning(f"Blur detection failed: {e}")
            return True, 0.0
    
    def _analyze_brightness(self, image: np.ndarray) -> float:
        """Analyze image brightness"""
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray) / 255.0
            return brightness
        except Exception as e:
            logger.warning(f"Brightness analysis failed: {e}")
            return 0.5
    
    def _extract_text(self, image: Image.Image) -> Tuple[bool, str]:
        """Extract text from image using OCR"""
        try:
            gray = image.convert('L')
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(2.0)
            
            text = pytesseract.image_to_string(enhanced)
            text = text.strip()
            
            has_text = len(text) > 5
            return has_text, text
            
        except Exception as e:
            logger.warning(f"Text extraction failed: {e}")
            return False, ""
    
    def _detect_objects_with_yolo(self, image: np.ndarray) -> List[str]:
        """Detect objects using YOLOv8n model"""
        if self.yolo_model is None:
            # Fallback to basic detection if YOLO fails
            return self._detect_basic_objects_fallback(image)
        
        try:
            # Run YOLO inference
            results = self.yolo_model(image, verbose=False)
            
            # Map COCO classes to TrustBond relevant objects
            trustbond_objects = []
            
            # COCO classes relevant to TrustBond incidents
            relevant_classes = {
                0: 'person',           # People detection
                67: 'cell phone',      # Theft evidence
                24: 'handbag',         # Theft evidence  
                28: 'backpack',        # Theft evidence
                39: 'bottle',          # Drug paraphernalia
                42: 'knife',           # Weapon
                43: 'spoon',           # Drug paraphernalia
                44: 'bowl',            # Drug paraphernalia
                45: 'banana',          # Can look like weapons
                46: 'apple',           # Can look like objects
                47: 'sandwich',        # Can look like objects
                48: 'orange',          # Can look like objects
                49: 'broccoli',        # Can look like objects
                50: 'carrot',          # Can look like objects
                51: 'hot dog',         # Can look like objects
                52: 'pizza',           # Can look like objects
                53: 'donut',           # Can look like objects
                54: 'cake',            # Can look like objects
                55: 'chair',           # Domestic violence
                56: 'couch',           # Domestic violence
                57: 'potted plant',    # Indoor objects
                58: 'bed',             # Domestic violence
                59: 'dining table',    # Domestic violence
                60: 'toilet',          # Indoor objects
                61: 'tv',              # Indoor objects
                62: 'laptop',          # Fraud evidence
                63: 'mouse',           # Can look like objects
                64: 'remote',          # Can look like objects
                65: 'keyboard',        # Can look like objects
                66: 'cell phone',      # Theft evidence
                68: 'microwave',       # Indoor objects
                69: 'oven',            # Indoor objects
                70: 'toaster',         # Indoor objects
                71: 'sink',            # Indoor objects
                72: 'refrigerator',    # Indoor objects
                73: 'book',            # Can look like objects
                74: 'clock',           # Indoor objects
                75: 'vase',            # Vandalism target
                76: 'scissors',        # Weapon
                77: 'teddy bear',      # Domestic violence
                78: 'hair drier',      # Can look like weapons
                79: 'toothbrush',      # Can look like objects
                80: 'hair brush',      # Can look like weapons
                81: 'tie',             # Clothing
                82: 'backpack',        # Theft evidence
                84: 'handbag',         # Theft evidence
                85: 'suitcase',        # Theft evidence
                86: 'frisbee',         # Can look like objects
                87: 'skis',            # Can look like weapons
                88: 'snowboard',       # Can look like objects
                89: 'sports ball',     # Can look like objects
                90: 'kite',            # Can look like objects
                91: 'baseball bat',    # Weapon
                92: 'baseball glove',  # Can look like objects
                93: 'skateboard',      # Can look like objects
                94: 'surfboard',       # Can look like objects
                95: 'tennis racket',   # Can look like weapons
                96: 'bottle',          # Drug paraphernalia
                97: 'plate',           # Domestic violence
                98: 'wine glass',      # Domestic violence
                99: 'cup',             # Domestic violence
                100: 'fork',           # Can look like weapons
                101: 'knife',          # Weapon
                102: 'spoon',          # Drug paraphernalia
                103: 'bowl',           # Drug paraphernalia
                104: 'banana',         # Can look like objects
                105: 'apple',          # Can look like objects
                106: 'sandwich',       # Can look like objects
                107: 'orange',         # Can look like objects
                108: 'broccoli',       # Can look like objects
                109: 'carrot',         # Can look like objects
                110: 'hot dog',        # Can look like objects
                111: 'pizza',          # Can look like objects
                112: 'donut',          # Can look like objects
                113: 'cake',           # Can look like objects
                114: 'chair',          # Domestic violence
                115: 'couch',          # Domestic violence
                116: 'potted plant',   # Indoor objects
                117: 'bed',            # Domestic violence
                118: 'dining table',   # Domestic violence
                119: 'toilet',         # Indoor objects
                120: 'tv',             # Indoor objects
                121: 'laptop',         # Fraud evidence
                122: 'mouse',          # Can look like objects
                123: 'remote',         # Can look like objects
                124: 'keyboard',       # Can look like objects
                125: 'cell phone',     # Theft evidence
                126: 'microwave',      # Indoor objects
                127: 'oven',           # Indoor objects
                128: 'toaster',        # Indoor objects
                129: 'sink',           # Indoor objects
                130: 'refrigerator',   # Indoor objects
                131: 'book',           # Can look like objects
                132: 'clock',          # Indoor objects
                133: 'vase',           # Vandalism target
                134: 'scissors',       # Weapon
                135: 'teddy bear',     # Domestic violence
                136: 'hair drier',     # Can look like weapons
                137: 'toothbrush',     # Can look like objects
                138: 'hair brush',     # Can look like weapons
                139: 'tie',            # Clothing
                140: 'backpack',       # Theft evidence
                141: 'handbag',        # Theft evidence
                142: 'suitcase',       # Theft evidence
                143: 'frisbee',        # Can look like objects
                144: 'skis',           # Can look like weapons
                145: 'snowboard',      # Can look like objects
                146: 'sports ball',    # Can look like objects
                147: 'kite',           # Can look like objects
                148: 'baseball bat',   # Weapon
                149: 'baseball glove', # Can look like objects
                150: 'skateboard',     # Can look like objects
                151: 'surfboard',      # Can look like objects
                152: 'tennis racket',  # Can look like weapons
                153: 'bottle',         # Drug paraphernalia
                154: 'plate',          # Domestic violence
                155: 'wine glass',     # Domestic violence
                156: 'cup',            # Domestic violence
                157: 'fork',           # Can look like weapons
                158: 'knife',          # Weapon
                159: 'spoon',          # Drug paraphernalia
                160: 'bowl',           # Drug paraphernalia
                161: 'banana',         # Can look like objects
                162: 'apple',          # Can look like objects
                163: 'sandwich',       # Can look like objects
                164: 'orange',         # Can look like objects
                165: 'broccoli',       # Can look like objects
                166: 'carrot',         # Can look like objects
                167: 'hot dog',        # Can look like objects
                168: 'pizza',          # Can look like objects
                169: 'donut',          # Can look like objects
                170: 'cake',           # Can look like objects
                171: 'chair',          # Domestic violence
                172: 'couch',          # Domestic violence
                173: 'potted plant',   # Indoor objects
                174: 'bed',            # Domestic violence
                175: 'dining table',   # Domestic violence
                176: 'toilet',         # Indoor objects
                177: 'tv',             # Indoor objects
                178: 'laptop',         # Fraud evidence
                179: 'mouse',          # Can look like objects
                180: 'remote',         # Can look like objects
                181: 'keyboard',       # Can look like objects
                182: 'cell phone',     # Theft evidence
            }
            
            # Extract detected objects
            for result in results:
                if result.boxes is not None:
                    for box in result.boxes:
                        class_id = int(box.cls)
                        confidence = float(box.conf)
                        
                        # Only include high-confidence detections
                        if confidence > 0.5:  # 50% confidence threshold
                            if class_id in relevant_classes:
                                object_name = relevant_classes[class_id]
                                if object_name not in trustbond_objects:
                                    trustbond_objects.append(object_name)
            
            # If no relevant objects found, return basic detection
            if not trustbond_objects:
                return self._detect_basic_objects_fallback(image)
            
            return trustbond_objects
            
        except Exception as e:
            logger.warning(f"YOLO object detection failed: {e}")
            # Fallback to basic detection
            return self._detect_basic_objects_fallback(image)
    
    def _detect_basic_objects_fallback(self, image: np.ndarray) -> List[str]:
        """Fallback basic object detection using OpenCV"""
        objects = []
        
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Simple people detection using OpenCV HOG as fallback
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            boxes, _ = hog.detectMultiScale(image, winStride=(8, 8))
            
            if len(boxes) > 0:
                objects.append('person')
            
            # Basic edge detection for structures
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = np.sum(edges > 0) / edges.size
            
            if edge_ratio > 0.05:
                objects.append('structure')
            
            if len(objects) == 0:
                objects.append('unknown')
                
        except Exception as e:
            logger.warning(f"Fallback object detection failed: {e}")
            objects.append('unknown')
        
        return objects
    
    def _classify_scene(self, image: np.ndarray, detected_objects: List[str]) -> str:
        """Classify scene type based on content"""
        try:
            if 'person' in detected_objects or 'people' in detected_objects:
                if 'structure' in detected_objects:
                    return 'indoor'
                else:
                    return 'outdoor'
            elif 'vehicle' in detected_objects:
                return 'street'
            else:
                return 'unknown'
        except:
            return 'unknown'
    
    def _check_exif_data(self, image: Image.Image) -> bool:
        """Check if EXIF data is complete and valid"""
        try:
            exif = image._getexif()
            if exif is None:
                return False
            
            required_tags = ['DateTimeOriginal', 'Make', 'Model']
            for tag in required_tags:
                if tag not in exif:
                    return False
            
            return True
        except:
            return False
    
    def _calculate_confidence_score(self, analysis: EvidenceAnalysis) -> float:
        """Calculate overall confidence score for evidence quality"""
        score = 0.0
        
        # People detection (important for most incident types)
        if analysis.has_people:
            score += 0.2
        
        # Image quality
        if not analysis.is_blurry:
            score += 0.2
        
        # Brightness (not too dark or too bright)
        if 0.2 <= analysis.brightness <= 0.8:
            score += 0.1
        
        # Text presence (can provide context)
        if analysis.has_text:
            score += 0.1
        
        # EXIF data (authenticity)
        if analysis.exif_complete:
            score += 0.1
        
        # Resolution (minimum quality)
        if analysis.resolution[0] >= 640 and analysis.resolution[1] >= 480:
            score += 0.1
        
        # File size (indicates quality)
        if analysis.file_size > 50000:
            score += 0.1
        
        # Object detection
        if analysis.detected_objects and 'unknown' not in analysis.detected_objects:
            score += 0.1
        
        return min(score, 1.0)
    
    def validate_incident_evidence(self, incident_type_id: int, description: str, 
                                 analysis: EvidenceAnalysis) -> Dict:
        """Validate evidence against incident type requirements"""
        logger.info(f"Validating evidence for incident type {incident_type_id}")
        
        # Get rules for this incident type
        rules = self.enhanced_rules.get(incident_type_id, {})
        
        if not rules:
            return {
                'valid': False,
                'reason': 'Unknown incident type',
                'confidence': 0.0,
                'issues': ['Unknown incident type']
            }
        
        score = 0.0
        max_score = 0.0
        issues = []
        
        # 1. Check expected objects
        if 'expected_objects' in rules:
            max_score += 0.3
            object_matches = 0
            for obj in rules['expected_objects']:
                if obj in analysis.detected_objects:
                    object_matches += 1
            
            if object_matches > 0:
                score += 0.3 * (object_matches / len(rules['expected_objects']))
            else:
                issues.append(f"No expected objects found. Expected: {rules['expected_objects']}")
        
        # 2. Check for people (critical for most incidents)
        max_score += 0.2
        if analysis.has_people:
            score += 0.2
        else:
            issues.append("No people detected in evidence")
        
        # 3. Check image quality
        max_score += 0.2
        if not analysis.is_blurry and analysis.confidence_score > 0.5:
            score += 0.2
        else:
            issues.append("Poor image quality")
        
        # 4. Check description keywords
        max_score += 0.2
        description_lower = description.lower()
        keyword_matches = 0
        if 'keywords' in rules:
            for keyword in rules['keywords']:
                if keyword in description_lower:
                    keyword_matches += 1
            
            if keyword_matches > 0:
                score += 0.2 * (keyword_matches / len(rules['keywords']))
        
        # 5. Check scene relevance
        max_score += 0.1
        if 'expected_scenes' in rules:
            if any(scene in analysis.scene_type for scene in rules['expected_scenes']):
                score += 0.1
        
        # Calculate final score
        final_score = score / max_score if max_score > 0 else 0.0
        
        # Determine validation result
        threshold = 0.6  # 60% threshold for validation
        is_valid = final_score >= threshold
        
        return {
            'valid': is_valid,
            'confidence': final_score,
            'issues': issues,
            'analysis': {
                'has_people': analysis.has_people,
                'is_blurry': analysis.is_blurry,
                'confidence_score': analysis.confidence_score,
                'detected_objects': analysis.detected_objects,
                'extracted_text': analysis.extracted_text
            }
        }

# Global service instance
evidence_analysis_service = EvidenceAnalysisService()
