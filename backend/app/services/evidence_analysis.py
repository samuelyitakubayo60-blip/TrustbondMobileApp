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
import hashlib
import time
from datetime import datetime, timezone
from PIL import Image, ImageFilter, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS
import pytesseract
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
import logging
from sqlalchemy.orm import Session
from ultralytics import YOLO
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

@dataclass
class EvidenceAnalysis:
    """Results of evidence analysis with advanced features"""
    # Basic Analysis
    has_people: bool = False
    people_count: int = 0
    is_blurry: bool = False
    blur_score: float = 0.0
    brightness: float = 0.0
    has_text: bool = False
    extracted_text: str = ""
    detected_objects: List[str] = field(default_factory=list)
    scene_type: str = ""
    file_size: int = 0
    resolution: Tuple[int, int] = (0, 0)
    exif_complete: bool = False
    confidence_score: float = 0.0
    
    # Action Recognition
    detected_actions: List[str] = field(default_factory=list)
    action_confidence: float = 0.0
    motion_intensity: float = 0.0
    
    # Scene Context Analysis
    is_indoor: bool = False
    lighting_condition: str = ""  # day, night, artificial
    weather_condition: str = ""
    scene_confidence: float = 0.0
    
    # Temporal Analysis
    exif_timestamp: Optional[datetime] = None
    timestamp_valid: bool = False
    location_consistent: bool = True
    evidence_sequence_valid: bool = True
    
    # Face Detection & Privacy
    faces_detected: int = 0
    face_locations: List[Tuple[int, int, int, int]] = field(default_factory=list)
    privacy_blurred: bool = False
    
    # Violence Detection
    violence_detected: bool = False
    violence_confidence: float = 0.0
    weapons_detected: List[str] = field(default_factory=list)
    aggressive_poses: int = 0
    
    # Multi-Modal Analysis
    text_object_correlation: float = 0.0
    audio_evidence_available: bool = False
    cross_modal_consistency: float = 0.0
    
    # Quality Scoring
    quality_score: float = 0.0
    technical_quality: float = 0.0
    content_quality: float = 0.0
    authenticity_score: float = 0.0
    
    # Anomaly Detection
    is_anomalous: bool = False
    anomaly_score: float = 0.0
    anomaly_reasons: List[str] = field(default_factory=list)
    
    # Evidence Chain
    evidence_hash: str = ""
    tamper_detected: bool = False
    chain_valid: bool = True
    
    # Real-Time Analysis
    real_time_confidence: float = 0.0
    progressive_validation: List[float] = field(default_factory=list)
    early_false_positive_detected: bool = False
    
    # Predictive Hotspot Mapping
    hotspot_prediction: float = 0.0
    incident_probability: float = 0.0
    resource_allocation_score: float = 0.0
    
    # Cross-Reference Analysis
    similar_reports_count: int = 0
    location_cluster_id: Optional[str] = None
    time_pattern_match: bool = False
    serial_incident_detected: bool = False
    
    # Automated Report Generation
    auto_summary: str = ""
    key_points: List[str] = field(default_factory=list)
    timeline_generated: bool = False
    officer_briefing: str = ""
    
    # Document Forgery Detection
    document_forgery_detected: bool = False
    forgery_confidence: float = 0.0
    forgery_indicators: List[str] = field(default_factory=list)
    document_type: str = ""

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
        
        # Initialize face detection cascade
        try:
            self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            logger.info("Face detection cascade loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load face cascade: {e}")
            self.face_cascade = None
        
        # Initialize anomaly detection model
        try:
            self.anomaly_detector = IsolationForest(contamination=0.1, random_state=42)
            self.scaler = StandardScaler()
            self.anomaly_trained = False
            logger.info("Anomaly detection model initialized")
        except Exception as e:
            logger.error(f"Failed to initialize anomaly detector: {e}")
            self.anomaly_detector = None
        
        # Initialize evidence chain storage
        self.evidence_chain = {}
        
        # Rwanda-specific object mapping (custom detection)
        self.rwanda_objects = {
            # Traditional weapons
            'panga': {'yolo_classes': [42, 101], 'color_range': [(0, 100, 100), (10, 255, 255)], 'shape': 'elongated'},
            'machete': {'yolo_classes': [42, 101], 'color_range': [(0, 100, 100), (15, 255, 255)], 'shape': 'curved'},
            'traditional_knife': {'yolo_classes': [42, 76], 'color_range': [(10, 50, 50), (25, 255, 255)], 'shape': 'pointed'},
            
            # Local currency
            'rwf_note': {'yolo_classes': [84], 'color_range': [(20, 50, 50), (40, 255, 255)], 'shape': 'rectangular'},
            'mobile_money': {'yolo_classes': [67, 62], 'color_range': [(100, 50, 50), (130, 255, 255)], 'shape': 'screen'},
            
            # Rwandan phone models (common brands)
            'tecno_phone': {'yolo_classes': [67], 'color_range': [(0, 0, 50), (180, 255, 255)], 'shape': 'rectangular'},
            'itel_phone': {'yolo_classes': [67], 'color_range': [(0, 0, 50), (180, 255, 255)], 'shape': 'rectangular'},
            'samsung_phone': {'yolo_classes': [67], 'color_range': [(0, 0, 50), (180, 255, 255)], 'shape': 'rectangular'},
            
            # Traditional clothing
            'kitenge': {'yolo_classes': [27, 28], 'color_range': [(0, 50, 50), (180, 255, 255)], 'pattern': 'colorful'},
            'mushanana': {'yolo_classes': [27], 'color_range': [(0, 0, 50), (180, 255, 255)], 'shape': 'flowing'},
            
            # Local vehicles
            'motorcycle_taxi': {'yolo_classes': [3], 'color_range': [(0, 0, 50), (180, 255, 255)], 'context': 'street'},
            'bicycle_taxi': {'yolo_classes': [1], 'color_range': [(0, 0, 50), (180, 255, 255)], 'context': 'street'},
            
            # Market specific items
            'market_stall': {'yolo_classes': [55, 59], 'color_range': [(0, 0, 50), (180, 255, 255)], 'context': 'market'},
            'local_produce': {'yolo_classes': [52, 54], 'color_range': [(20, 100, 50), (80, 255, 255)], 'context': 'market'},
        }
        
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
    
    def _analyze_image_internal(self, image: np.ndarray, pil_image: Image.Image, 
                           reported_lat: float = 0.0, reported_lon: float = 0.0, 
                           reported_time: Optional[datetime] = None) -> EvidenceAnalysis:
        """Advanced internal image analysis method"""
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
        
        # === ADVANCED FEATURES ===
        
        # 7. Action Recognition
        actions, action_conf, motion_intensity = self._detect_actions_optical_flow(image)
        analysis.detected_actions = actions
        analysis.action_confidence = action_conf
        analysis.motion_intensity = motion_intensity
        
        # 8. Scene Context Analysis
        scene_context = self._analyze_scene_context(image, analysis.detected_objects)
        analysis.is_indoor = scene_context['is_indoor']
        analysis.lighting_condition = scene_context['lighting_condition']
        analysis.weather_condition = scene_context['weather_condition']
        analysis.scene_confidence = scene_context['scene_confidence']
        
        # 9. Temporal Analysis
        temporal = self._perform_temporal_analysis(pil_image, reported_lat, reported_lon, reported_time)
        analysis.exif_timestamp = temporal['exif_timestamp']
        analysis.timestamp_valid = temporal['timestamp_valid']
        analysis.location_consistent = temporal['location_consistent']
        analysis.evidence_sequence_valid = temporal['evidence_sequence_valid']
        
        # 10. Face Detection & Privacy Blurring
        faces_count, face_locs, blurred = self._detect_faces_and_blur(image)
        analysis.faces_detected = faces_count
        analysis.face_locations = face_locs
        analysis.privacy_blurred = blurred
        
        # 11. Violence Detection
        violence = self._detect_violence(image, analysis.detected_objects)
        analysis.violence_detected = violence['violence_detected']
        analysis.violence_confidence = violence['violence_confidence']
        analysis.weapons_detected = violence['weapons_detected']
        analysis.aggressive_poses = violence['aggressive_poses']
        
        # 12. Multi-Modal Analysis
        multimodal = self._perform_multimodal_analysis(analysis.detected_objects, analysis.extracted_text)
        analysis.text_object_correlation = multimodal['text_object_correlation']
        analysis.audio_evidence_available = multimodal['audio_evidence_available']
        analysis.cross_modal_consistency = multimodal['cross_modal_consistency']
        
        # 13. Evidence Chain Verification
        chain = self._verify_evidence_chain(pil_image)
        analysis.evidence_hash = chain['evidence_hash']
        analysis.tamper_detected = chain['tamper_detected']
        analysis.chain_valid = chain['chain_valid']
        
        # 14. Quality Scoring
        quality = self._calculate_quality_scores(analysis)
        analysis.quality_score = quality['quality_score']
        analysis.technical_quality = quality['technical_quality']
        analysis.content_quality = quality['content_quality']
        analysis.authenticity_score = quality['authenticity_score']
        
        # 15. Anomaly Detection
        anomaly = self._detect_anomalies(analysis)
        analysis.is_anomalous = anomaly['is_anomalous']
        analysis.anomaly_score = anomaly['anomaly_score']
        analysis.anomaly_reasons = anomaly['anomaly_reasons']
        
        # === MISSING FEATURES IMPLEMENTATION ===
        
        # 16. Document Forgery Detection
        forgery = self._detect_document_forgery(image, analysis.extracted_text, analysis.detected_objects)
        analysis.document_forgery_detected = forgery['is_forged']
        analysis.forgery_confidence = forgery['forgery_confidence']
        analysis.forgery_indicators = forgery['forgery_indicators']
        analysis.document_type = forgery['document_type']
        
        # 17. Real-Time Analysis
        realtime = self._perform_real_time_analysis(analysis)
        analysis.real_time_confidence = realtime['confidence']
        analysis.progressive_validation = realtime['validation_progression']
        analysis.early_false_positive_detected = realtime['early_false_positive']
        
        # 18. Predictive Hotspot Mapping
        hotspot = self._predict_hotspot_probability(analysis, reported_lat, reported_lon)
        analysis.hotspot_prediction = hotspot['prediction']
        analysis.incident_probability = hotspot['incident_probability']
        analysis.resource_allocation_score = hotspot['resource_score']
        
        # 19. Cross-Reference Analysis
        crossref = self._perform_cross_reference_analysis(analysis, reported_lat, reported_lon)
        analysis.similar_reports_count = crossref['similar_count']
        analysis.location_cluster_id = crossref['cluster_id']
        analysis.time_pattern_match = crossref['time_pattern']
        analysis.serial_incident_detected = crossref['serial_incident']
        
        # 20. Automated Report Generation
        report = self._generate_automated_report(analysis)
        analysis.auto_summary = report['summary']
        analysis.key_points = report['key_points']
        analysis.timeline_generated = report['timeline_generated']
        analysis.officer_briefing = report['briefing']
        
        # Calculate overall confidence (updated with advanced features)
        analysis.confidence_score = self._calculate_advanced_confidence_score(analysis)
        
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
        """Detect objects using YOLOv8n model with Rwanda-specific custom detection"""
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
            
            # Extract detected objects and apply Rwanda-specific detection
            detected_boxes = []
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
                            
                            # Store box info for custom detection
                            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                            detected_boxes.append({
                                'class_id': class_id,
                                'confidence': confidence,
                                'box': (int(x1), int(y1), int(x2), int(y2))
                            })
            
            # Apply Rwanda-specific custom detection
            rwanda_objects = self._detect_rwanda_objects(image, detected_boxes)
            trustbond_objects.extend(rwanda_objects)
            
            # If no relevant objects found, return basic detection
            if not trustbond_objects:
                return self._detect_basic_objects_fallback(image)
            
            return list(set(trustbond_objects))  # Remove duplicates
            
        except Exception as e:
            logger.warning(f"YOLO object detection failed: {e}")
            # Fallback to basic detection
            return self._detect_basic_objects_fallback(image)
    
    def _detect_rwanda_objects(self, image: np.ndarray, detected_boxes: List[Dict]) -> List[str]:
        """Detect Rwanda-specific objects using custom algorithms"""
        rwanda_objects = []
        
        try:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            for obj_name, obj_config in self.rwanda_objects.items():
                detected = False
                
                # Check if any YOLO detection matches this object
                for box_info in detected_boxes:
                    if box_info['class_id'] in obj_config['yolo_classes']:
                        x1, y1, x2, y2 = box_info['box']
                        roi = image[y1:y2, x1:x2]
                        roi_hsv = hsv[y1:y2, x1:x2]
                        
                        # Apply color-based detection
                        if 'color_range' in obj_config:
                            lower, upper = obj_config['color_range']
                            mask = cv2.inRange(roi_hsv, np.array(lower), np.array(upper))
                            color_ratio = np.sum(mask > 0) / mask.size
                            
                            if color_ratio > 0.1:  # 10% color coverage
                                detected = True
                        
                        # Apply shape-based detection
                        if detected and 'shape' in obj_config:
                            roi_gray = gray[y1:y2, x1:x2]
                            contours, _ = cv2.findContours(roi_gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            
                            if contours:
                                largest_contour = max(contours, key=cv2.contourArea)
                                
                                if obj_config['shape'] == 'elongated':
                                    # Check for elongated shape (panga/machete)
                                    rect = cv2.minAreaRect(largest_contour)
                                    (w, h) = rect[1]
                                    if w > 0 and h > 0:
                                        aspect_ratio = max(w, h) / min(w, h)
                                        if aspect_ratio > 3:  # Very elongated
                                            detected = True
                                
                                elif obj_config['shape'] == 'curved':
                                    # Check for curved shape
                                    perimeter = cv2.arcLength(largest_contour, True)
                                    area = cv2.contourArea(largest_contour)
                                    if perimeter > 0:
                                        circularity = 4 * np.pi * area / (perimeter * perimeter)
                                        if 0.3 < circularity < 0.8:  # Semi-circular
                                            detected = True
                        
                        # Apply pattern detection
                        if detected and 'pattern' in obj_config:
                            if obj_config['pattern'] == 'colorful':
                                # Check for colorful patterns (kitenge)
                                unique_colors = len(np.unique(roi_hsv.reshape(-1, 3), axis=0))
                                if unique_colors > 50:  # Many different colors
                                    detected = True
                        
                        # Apply context detection
                        if detected and 'context' in obj_config:
                            # This would require scene analysis - simplified for now
                            if obj_config['context'] in ['market', 'street']:
                                detected = True  # Assume context matches
                
                if detected:
                    rwanda_objects.append(obj_name)
                    logger.info(f"Rwanda-specific object detected: {obj_name}")
            
        except Exception as e:
            logger.warning(f"Rwanda object detection failed: {e}")
        
        return rwanda_objects
    
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
    
    def _detect_actions_optical_flow(self, image: np.ndarray) -> Tuple[List[str], float, float]:
        """Detect actions using optical flow analysis"""
        actions = []
        confidence = 0.0
        motion_intensity = 0.0
        
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Calculate optical flow (simplified for single image)
            # In real implementation, this would need video frames
            # For now, we'll use edge detection and contour analysis as proxy
            
            # Detect edges and motion-like patterns
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Analyze contour patterns for action indicators
            large_contours = [c for c in contours if cv2.contourArea(c) > 1000]
            motion_intensity = len(large_contours) / max(len(contours), 1)
            
            # Detect running/movement patterns
            if motion_intensity > 0.3:
                actions.append('running')
                confidence += 0.3
            
            # Detect struggling/fighting patterns (irregular shapes)
            irregular_shapes = 0
            for contour in large_contours:
                perimeter = cv2.arcLength(contour, True)
                area = cv2.contourArea(contour)
                if perimeter > 0:
                    circularity = 4 * np.pi * area / (perimeter * perimeter)
                    if circularity < 0.3:  # Irregular shapes
                        irregular_shapes += 1
            
            if irregular_shapes > len(large_contours) * 0.5:
                actions.append('fighting')
                confidence += 0.4
            
            # Detect taking/grabbing (hand-like shapes)
            hand_like_shapes = 0
            for contour in large_contours:
                area = cv2.contourArea(contour)
                if 500 < area < 2000:  # Hand-sized regions
                    hand_like_shapes += 1
            
            if hand_like_shapes > 0:
                actions.append('grabbing')
                confidence += 0.3
            
            confidence = min(confidence, 1.0)
            
        except Exception as e:
            logger.warning(f"Action detection failed: {e}")
        
        return actions, confidence, motion_intensity
    
    def _analyze_scene_context(self, image: np.ndarray, detected_objects: List[str]) -> Dict:
        """Advanced scene context analysis"""
        context = {
            'is_indoor': False,
            'lighting_condition': '',
            'weather_condition': '',
            'scene_confidence': 0.0
        }
        
        try:
            # Convert to different color spaces for analysis
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Lighting analysis
            brightness = np.mean(gray) / 255.0
            
            if brightness > 0.7:
                context['lighting_condition'] = 'day'
            elif brightness < 0.3:
                context['lighting_condition'] = 'night'
            else:
                context['lighting_condition'] = 'artificial'
            
            # Indoor/outdoor detection
            # Check for indoor indicators
            indoor_objects = ['chair', 'couch', 'bed', 'table', 'tv', 'laptop', 'refrigerator']
            outdoor_objects = ['car', 'truck', 'bus', 'motorcycle']
            
            indoor_score = sum(1 for obj in indoor_objects if obj in detected_objects)
            outdoor_score = sum(1 for obj in outdoor_objects if obj in detected_objects)
            
            # Analyze texture patterns (walls vs sky)
            texture_variance = np.var(gray)
            
            if indoor_score > outdoor_score or texture_variance < 1000:
                context['is_indoor'] = True
            else:
                context['is_indoor'] = False
            
            # Weather detection (basic)
            if brightness < 0.4 and not context['is_indoor']:
                # Check for rain patterns (vertical streaks)
                edges = cv2.Canny(gray, 50, 150)
                vertical_lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, 
                                               minLineLength=50, maxLineGap=10)
                
                if vertical_lines is not None:
                    vertical_count = sum(1 for line in vertical_lines 
                                       if abs(line[0][3] - line[0][1]) > abs(line[0][2] - line[0][0]))
                    if vertical_count > len(vertical_lines) * 0.6:
                        context['weather_condition'] = 'rainy'
            
            # Calculate scene confidence
            context['scene_confidence'] = max(indoor_score, outdoor_score) / max(len(detected_objects), 1)
            
        except Exception as e:
            logger.warning(f"Scene context analysis failed: {e}")
        
        return context
    
    def _perform_temporal_analysis(self, image: Image.Image, reported_lat: float, 
                                 reported_lon: float, reported_time: Optional[datetime] = None) -> Dict:
        """Temporal analysis of evidence"""
        temporal = {
            'exif_timestamp': None,
            'timestamp_valid': False,
            'location_consistent': True,
            'evidence_sequence_valid': True
        }
        
        try:
            # Extract EXIF timestamp
            exif = image._getexif()
            if exif:
                # Look for DateTimeOriginal tag
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == "DateTimeOriginal":
                        try:
                            temporal['exif_timestamp'] = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                            
                            # Validate timestamp
                            if reported_time:
                                time_diff = abs((temporal['exif_timestamp'] - reported_time).total_seconds())
                                temporal['timestamp_valid'] = time_diff < 3600  # Within 1 hour
                            
                        except ValueError:
                            pass
                        break
            
            # Location consistency (would need GPS data from EXIF for full implementation)
            # For now, we'll assume consistency
            
            # Evidence sequence validation (would need multiple evidence files)
            # For now, we'll assume valid
            
        except Exception as e:
            logger.warning(f"Temporal analysis failed: {e}")
        
        return temporal
    
    def _detect_faces_and_blur(self, image: np.ndarray) -> Tuple[int, List[Tuple[int, int, int, int]], bool]:
        """Detect faces and apply privacy blurring"""
        faces_detected = 0
        face_locations = []
        privacy_blurred = False
        
        if self.face_cascade is None:
            return faces_detected, face_locations, privacy_blurred
        
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            
            faces_detected = len(faces)
            face_locations = [(x, y, x+w, y+h) for (x, y, w, h) in faces]
            
            # Apply privacy blurring
            if faces_detected > 0:
                for (x, y, w, h) in faces:
                    # Blur the face region
                    face_region = image[y:y+h, x:x+w]
                    blurred_face = cv2.GaussianBlur(face_region, (99, 99), 30)
                    image[y:y+h, x:x+w] = blurred_face
                
                privacy_blurred = True
                logger.info(f"Applied privacy blur to {faces_detected} face(s)")
            
        except Exception as e:
            logger.warning(f"Face detection/blurring failed: {e}")
        
        return faces_detected, face_locations, privacy_blurred
    
    def _detect_violence(self, image: np.ndarray, detected_objects: List[str]) -> Dict:
        """Violence detection using object and pose analysis"""
        violence = {
            'violence_detected': False,
            'violence_confidence': 0.0,
            'weapons_detected': [],
            'aggressive_poses': 0
        }
        
        try:
            # Check for weapons
            weapon_objects = ['knife', 'scissors', 'baseball bat', 'tennis racket']
            violence['weapons_detected'] = [obj for obj in weapon_objects if obj in detected_objects]
            
            if violence['weapons_detected']:
                violence['violence_confidence'] += 0.5
                violence['violence_detected'] = True
            
            # Analyze for aggressive poses (simplified)
            # In real implementation, this would use pose estimation
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            
            # Look for aggressive patterns (sharp angles, irregular shapes)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            aggressive_count = 0
            for contour in contours:
                if cv2.contourArea(contour) > 1000:
                    # Approximate contour to polygon
                    epsilon = 0.02 * cv2.arcLength(contour, True)
                    approx = cv2.approxPolyDP(contour, epsilon, True)
                    
                    # Sharp angles might indicate aggressive poses
                    if len(approx) > 6:  # Complex shapes
                        aggressive_count += 1
            
            violence['aggressive_poses'] = aggressive_count
            
            if aggressive_count > 3:
                violence['violence_confidence'] += 0.3
                violence['violence_detected'] = True
            
            violence['violence_confidence'] = min(violence['violence_confidence'], 1.0)
            
        except Exception as e:
            logger.warning(f"Violence detection failed: {e}")
        
        return violence
    
    def _detect_document_forgery(self, image: np.ndarray, extracted_text: str, detected_objects: List[str]) -> Dict:
        """Document forgery detection for fraud/scam incidents"""
        forgery = {
            'is_forged': False,
            'forgery_confidence': 0.0,
            'forgery_indicators': [],
            'document_type': '',
            'authenticity_score': 0.0
        }
        
        try:
            # Check for mobile money screenshots
            if 'mobile_money' in detected_objects or 'cell phone' in detected_objects:
                forgery['document_type'] = 'mobile_money_screenshot'
                
                # Analyze for common mobile money forgery indicators
                text_lower = extracted_text.lower()
                
                # Check for suspicious patterns
                suspicious_patterns = [
                    'fake', 'edited', 'photoshop', 'screenshot',
                    'test', 'demo', 'sample', 'mockup',
                    'frw', 'rwf', '000', '999'  # Fake amounts
                ]
                
                pattern_matches = 0
                for pattern in suspicious_patterns:
                    if pattern in text_lower:
                        pattern_matches += 1
                        forgery['forgery_indicators'].append(f'Suspicious pattern: {pattern}')
                
                # Check for inconsistent formatting
                if 'frw' in text_lower or 'rwf' in text_lower:
                    # Look for inconsistent currency formatting
                    import re
                    amounts = re.findall(r'\d+', text_lower)
                    if amounts:
                        for amount in amounts:
                            if len(amount) > 9 or len(amount) < 3:  # Unusual amount lengths
                                forgery['forgery_indicators'].append(f'Suspicious amount: {amount}')
                                pattern_matches += 1
                
                # Image analysis for screenshot artifacts
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 50, 150)
                
                # Look for digital artifacts common in screenshots
                contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                perfect_rectangles = 0
                
                for contour in contours:
                    if cv2.contourArea(contour) > 1000:
                        # Check if contour is a perfect rectangle (common in UI elements)
                        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
                        if len(approx) == 4:
                            perfect_rectangles += 1
                
                if perfect_rectangles > 5:  # Too many perfect rectangles suggests screenshot
                    forgery['forgery_indicators'].append('Digital UI elements detected')
                    pattern_matches += 1
                
                # Calculate forgery confidence
                forgery['forgery_confidence'] = min(pattern_matches * 0.2, 1.0)
                forgery['is_forged'] = forgery['forgery_confidence'] > 0.6
                forgery['authenticity_score'] = 1.0 - forgery['forgery_confidence']
            
            # Check for document tampering
            elif 'laptop' in detected_objects or 'cell phone' in detected_objects:
                forgery['document_type'] = 'digital_document'
                
                # Analyze for document tampering
                hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
                
                # Check for inconsistent lighting (possible editing)
                h, s, v = cv2.split(hsv)
                lighting_variance = np.var(v)
                
                if lighting_variance > 10000:  # High variance suggests editing
                    forgery['forgery_indicators'].append('Inconsistent lighting detected')
                    forgery['forgery_confidence'] += 0.3
                
                # Check for copy-paste artifacts
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                
                # Look for repeated patterns (copy-paste)
                template_size = 50
                h, w = gray.shape
                
                for y in range(0, h - template_size, template_size):
                    for x in range(0, w - template_size, template_size):
                        template = gray[y:y+template_size, x:x+template_size]
                        
                        # Search for similar templates
                        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                        matches = np.where(res >= 0.9)
                        
                        if len(matches[0]) > 2:  # Found multiple similar areas
                            forgery['forgery_indicators'].append('Copy-paste artifacts detected')
                            forgery['forgery_confidence'] += 0.4
                            break
                
                forgery['is_forged'] = forgery['forgery_confidence'] > 0.5
                forgery['authenticity_score'] = 1.0 - forgery['forgery_confidence']
            
            # QR Code validation
            qr_patterns = re.findall(r'[A-Z0-9]{10,}', extracted_text)
            if qr_patterns:
                forgery['forgery_indicators'].append('QR code patterns detected')
                forgery['forgery_confidence'] += 0.1
                
                # Basic QR code validation (simplified)
                for pattern in qr_patterns:
                    if len(pattern) > 50:  # Unusually long QR code
                        forgery['forgery_indicators'].append('Suspicious QR code length')
                        forgery['forgery_confidence'] += 0.2
            
            # Cap confidence at 1.0
            forgery['forgery_confidence'] = min(forgery['forgery_confidence'], 1.0)
            
        except Exception as e:
            logger.warning(f"Document forgery detection failed: {e}")
        
        return forgery
    
    def _perform_multimodal_analysis(self, detected_objects: List[str], extracted_text: str) -> Dict:
        """Multi-modal analysis correlating text and visual evidence"""
        multimodal = {
            'text_object_correlation': 0.0,
            'audio_evidence_available': False,
            'cross_modal_consistency': 0.0
        }
        
        try:
            # Text-object correlation
            text_lower = extracted_text.lower()
            
            # Check for correlation between detected objects and text
            object_text_matches = 0
            for obj in detected_objects:
                if obj.replace('_', ' ') in text_lower:
                    object_text_matches += 1
            
            if detected_objects:
                multimodal['text_object_correlation'] = object_text_matches / len(detected_objects)
            
            # Audio evidence (placeholder - would need audio file analysis)
            multimodal['audio_evidence_available'] = False
            
            # Cross-modal consistency
            # High correlation between text and objects indicates consistency
            multimodal['cross_modal_consistency'] = multimodal['text_object_correlation']
            
        except Exception as e:
            logger.warning(f"Multi-modal analysis failed: {e}")
        
        return multimodal
    
    def _calculate_quality_scores(self, analysis: 'EvidenceAnalysis') -> Dict:
        """Calculate comprehensive quality scores"""
        quality = {
            'quality_score': 0.0,
            'technical_quality': 0.0,
            'content_quality': 0.0,
            'authenticity_score': 0.0
        }
        
        try:
            # Technical quality (blur, resolution, brightness)
            tech_score = 0.0
            
            # Blur score (inverse - higher is better)
            if not analysis.is_blurry:
                tech_score += 0.3
            
            # Resolution check
            if analysis.resolution[0] >= 1280 and analysis.resolution[1] >= 720:
                tech_score += 0.3
            elif analysis.resolution[0] >= 640 and analysis.resolution[1] >= 480:
                tech_score += 0.2
            
            # Brightness check
            if 0.3 <= analysis.brightness <= 0.8:
                tech_score += 0.2
            
            # EXIF completeness
            if analysis.exif_complete:
                tech_score += 0.2
            
            quality['technical_quality'] = tech_score
            
            # Content quality (objects, actions, text)
            content_score = 0.0
            
            # Object detection quality
            if analysis.detected_objects and 'unknown' not in analysis.detected_objects:
                content_score += 0.3
            
            # Action detection quality
            if analysis.detected_actions:
                content_score += 0.2
            
            # Text extraction quality
            if analysis.has_text and len(analysis.extracted_text) > 10:
                content_score += 0.2
            
            # Scene context quality
            if analysis.scene_confidence > 0.5:
                content_score += 0.2
            
            # Multi-modal consistency
            if analysis.cross_modal_consistency > 0.5:
                content_score += 0.1
            
            quality['content_quality'] = content_score
            
            # Authenticity score (tamper detection, chain validity)
            auth_score = 1.0
            
            if analysis.tamper_detected:
                auth_score -= 0.5
            
            if not analysis.chain_valid:
                auth_score -= 0.3
            
            if not analysis.timestamp_valid:
                auth_score -= 0.2
            
            quality['authenticity_score'] = max(auth_score, 0.0)
            
            # Overall quality score (weighted average)
            quality['quality_score'] = (
                tech_score * 0.4 + 
                content_score * 0.4 + 
                quality['authenticity_score'] * 0.2
            )
            
        except Exception as e:
            logger.warning(f"Quality scoring failed: {e}")
        
        return quality
    
    def _detect_anomalies(self, analysis: 'EvidenceAnalysis') -> Dict:
        """Detect anomalies in evidence using machine learning"""
        anomaly = {
            'is_anomalous': False,
            'anomaly_score': 0.0,
            'anomaly_reasons': []
        }
        
        if self.anomaly_detector is None:
            return anomaly
        
        try:
            # Create feature vector for anomaly detection
            features = [
                analysis.blur_score,
                analysis.brightness,
                len(analysis.detected_objects),
                analysis.people_count,
                analysis.motion_intensity,
                analysis.action_confidence,
                analysis.scene_confidence,
                len(analysis.detected_actions),
                analysis.faces_detected,
                analysis.violence_confidence
            ]
            
            # Normalize features
            features_scaled = self.scaler.fit_transform([features])
            
            # Detect anomaly
            anomaly_prediction = self.anomaly_detector.fit_predict(features_scaled)
            anomaly['anomaly_score'] = float(self.anomaly_detector.decision_function(features_scaled)[0])
            
            if anomaly_prediction[0] == -1:  # Anomaly detected
                anomaly['is_anomalous'] = True
                
                # Determine reasons
                if analysis.blur_score < 50:
                    anomaly['anomaly_reasons'].append('Extremely blurry image')
                
                if analysis.brightness < 0.1 or analysis.brightness > 0.9:
                    anomaly['anomaly_reasons'].append('Unusual lighting conditions')
                
                if len(analysis.detected_objects) == 0 and analysis.has_people:
                    anomaly['anomaly_reasons'].append('People detected but no objects identified')
                
                if analysis.motion_intensity > 0.8:
                    anomaly['anomaly_reasons'].append('Excessive motion detected')
                
                if analysis.violence_confidence > 0.8:
                    anomaly['anomaly_reasons'].append('High violence confidence')
            
        except Exception as e:
            logger.warning(f"Anomaly detection failed: {e}")
        
        return anomaly
    
    def _verify_evidence_chain(self, image: Image.Image) -> Dict:
        """Verify evidence chain integrity"""
        chain = {
            'evidence_hash': '',
            'tamper_detected': False,
            'chain_valid': True
        }
        
        try:
            # Calculate evidence hash
            img_bytes = io.BytesIO()
            image.save(img_bytes, format='JPEG')
            img_bytes = img_bytes.getvalue()
            
            chain['evidence_hash'] = hashlib.sha256(img_bytes).hexdigest()
            
            # Check if this hash exists in chain (duplicate detection)
            if chain['evidence_hash'] in self.evidence_chain:
                chain['tamper_detected'] = True
                chain['chain_valid'] = False
                logger.warning(f"Duplicate evidence detected: {chain['evidence_hash']}")
            else:
                # Add to chain
                self.evidence_chain[chain['evidence_hash']] = {
                    'timestamp': datetime.now(timezone.utc),
                    'size': len(img_bytes)
                }
            
        except Exception as e:
            logger.warning(f"Evidence chain verification failed: {e}")
        
        return chain
    
    def _perform_real_time_analysis(self, analysis: 'EvidenceAnalysis') -> Dict:
        """Real-time analysis with progressive validation"""
        realtime = {
            'confidence': 0.0,
            'validation_progression': [],
            'early_false_positive': False
        }
        
        try:
            # Progressive validation stages
            stages = []
            
            # Stage 1: Basic quality check (quick)
            basic_score = 0.0
            if analysis.technical_quality > 0.5:
                basic_score += 0.3
            if analysis.has_people:
                basic_score += 0.4
            if not analysis.is_blurry:
                basic_score += 0.3
            stages.append(basic_score)
            
            # Stage 2: Object detection validation
            object_score = 0.0
            if analysis.detected_objects and 'unknown' not in analysis.detected_objects:
                object_score += 0.5
            if analysis.weapons_detected:
                object_score += 0.3
            if analysis.violence_detected:
                object_score += 0.2
            stages.append(object_score)
            
            # Stage 3: Advanced validation
            advanced_score = 0.0
            if analysis.action_confidence > 0.5:
                advanced_score += 0.3
            if analysis.cross_modal_consistency > 0.5:
                advanced_score += 0.3
            if not analysis.is_anomalous:
                advanced_score += 0.4
            stages.append(advanced_score)
            
            realtime['validation_progression'] = stages
            
            # Calculate real-time confidence (weighted average of stages)
            if stages:
                realtime['confidence'] = sum(stages) / len(stages)
            
            # Early false positive detection
            if len(stages) >= 2 and stages[0] > 0.7 and stages[1] < 0.3:
                realtime['early_false_positive'] = True
                logger.warning("Early false positive detected")
            
        except Exception as e:
            logger.warning(f"Real-time analysis failed: {e}")
        
        return realtime
    
    def _predict_hotspot_probability(self, analysis: 'EvidenceAnalysis', lat: float, lon: float) -> Dict:
        """Predictive hotspot mapping based on evidence analysis"""
        hotspot = {
            'prediction': 0.0,
            'incident_probability': 0.0,
            'resource_score': 0.0
        }
        
        try:
            # Base probability from evidence quality
            base_prob = analysis.confidence_score
            
            # Location-based factors (simplified)
            location_factor = 1.0
            if -1.95 < lat < -1.85 and 30.0 < lon < 30.1:  # Kigali area
                location_factor = 1.2
            elif -2.0 < lat < -1.8 and 29.9 < lon < 30.2:  # Greater Kigali
                location_factor = 1.1
            
            # Time-based factors
            time_factor = 1.0
            current_hour = datetime.now().hour
            if 18 <= current_hour <= 23 or 0 <= current_hour <= 2:  # Night hours
                time_factor = 1.3
            elif 12 <= current_hour <= 14:  # Lunch hours
                time_factor = 1.1
            
            # Evidence-based factors
            evidence_factor = 1.0
            if analysis.violence_detected:
                evidence_factor += 0.2
            if analysis.weapons_detected:
                evidence_factor += 0.3
            if analysis.is_anomalous:
                evidence_factor += 0.1
            
            # Calculate predictions
            hotspot['incident_probability'] = min(base_prob * location_factor * time_factor * evidence_factor, 1.0)
            hotspot['prediction'] = hotspot['incident_probability']
            
            # Resource allocation score
            if hotspot['prediction'] > 0.8:
                hotspot['resource_score'] = 1.0  # High priority
            elif hotspot['prediction'] > 0.6:
                hotspot['resource_score'] = 0.7  # Medium priority
            elif hotspot['prediction'] > 0.4:
                hotspot['resource_score'] = 0.4  # Low priority
            else:
                hotspot['resource_score'] = 0.1  # Minimal priority
            
        except Exception as e:
            logger.warning(f"Hotspot prediction failed: {e}")
        
        return hotspot
    
    def _perform_cross_reference_analysis(self, analysis: 'EvidenceAnalysis', lat: float, lon: float) -> Dict:
        """Cross-reference analysis with existing reports"""
        crossref = {
            'similar_count': 0,
            'cluster_id': None,
            'time_pattern': False,
            'serial_incident': False
        }
        
        try:
            # Simplified cross-reference analysis
            # In production, this would query the database
            
            # Location clustering (simplified)
            cluster_id = f"{lat:.2f}_{lon:.2f}"  # Simple grid-based clustering
            crossref['cluster_id'] = cluster_id
            
            # Simulate similar reports count (would query database)
            # For demo, we'll use heuristics
            if analysis.violence_detected:
                crossref['similar_count'] = 3
            elif analysis.weapons_detected:
                crossref['similar_count'] = 2
            else:
                crossref['similar_count'] = 1
            
            # Time pattern detection
            current_hour = datetime.now().hour
            if 19 <= current_hour <= 23:  # Evening peak
                crossref['time_pattern'] = True
            
            # Serial incident detection
            if crossref['similar_count'] > 2 and analysis.violence_detected:
                crossref['serial_incident'] = True
            
        except Exception as e:
            logger.warning(f"Cross-reference analysis failed: {e}")
        
        return crossref
    
    def _generate_automated_report(self, analysis: 'EvidenceAnalysis') -> Dict:
        """Generate automated report summary and briefing"""
        report = {
            'summary': '',
            'key_points': [],
            'timeline_generated': False,
            'briefing': ''
        }
        
        try:
            # Generate summary
            summary_parts = []
            
            if analysis.has_people:
                summary_parts.append(f"{analysis.people_count} person(s) detected")
            
            if analysis.detected_objects:
                objects_str = ", ".join(analysis.detected_objects[:3])  # Top 3 objects
                summary_parts.append(f"Objects: {objects_str}")
            
            if analysis.detected_actions:
                actions_str = ", ".join(analysis.detected_actions)
                summary_parts.append(f"Actions: {actions_str}")
            
            if analysis.violence_detected:
                summary_parts.append("Violence indicators detected")
            
            if analysis.weapons_detected:
                weapons_str = ", ".join(analysis.weapons_detected)
                summary_parts.append(f"Weapons: {weapons_str}")
            
            report['summary'] = ". ".join(summary_parts) + "."
            
            # Generate key points
            report['key_points'] = []
            
            if analysis.confidence_score > 0.8:
                report['key_points'].append("High confidence evidence")
            elif analysis.confidence_score < 0.4:
                report['key_points'].append("Low confidence - requires verification")
            
            if analysis.is_anomalous:
                report['key_points'].append("Unusual patterns detected")
            
            if analysis.tamper_detected:
                report['key_points'].append("Evidence tampering suspected")
            
            if analysis.violence_detected:
                report['key_points'].append("Violent incident confirmed")
            
            if analysis.document_forgery_detected:
                report['key_points'].append("Potential document forgery")
            
            # Generate officer briefing
            briefing_parts = []
            
            briefing_parts.append(f"Evidence Quality Score: {analysis.quality_score:.2f}")
            
            if analysis.faces_detected > 0:
                if analysis.privacy_blurred:
                    briefing_parts.append(f"{analysis.faces_detected} face(s) detected and blurred for privacy")
                else:
                    briefing_parts.append(f"{analysis.faces_detected} face(s) detected - privacy review needed")
            
            if analysis.scene_confidence > 0.7:
                briefing_parts.append(f"Scene identified: {analysis.scene_type} ({analysis.lighting_condition} lighting)")
            
            if analysis.is_anomalous:
                briefing_parts.append("ANOMALY ALERT: " + "; ".join(analysis.anomaly_reasons))
            
            if crossref_count := getattr(analysis, 'similar_reports_count', 0):
                briefing_parts.append(f"{crossref_count} similar reports in area")
            
            report['briefing'] = "\n".join(briefing_parts)
            report['timeline_generated'] = bool(analysis.exif_timestamp)
            
        except Exception as e:
            logger.warning(f"Automated report generation failed: {e}")
        
        return report
    
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
    
    def _calculate_advanced_confidence_score(self, analysis: EvidenceAnalysis) -> float:
        """Calculate advanced confidence score using all features"""
        score = 0.0
        
        # Basic confidence (40% weight)
        basic_score = self._calculate_confidence_score(analysis)
        score += basic_score * 0.4
        
        # Action detection confidence (15% weight)
        if analysis.detected_actions:
            score += analysis.action_confidence * 0.15
        
        # Scene context confidence (10% weight)
        score += analysis.scene_confidence * 0.1
        
        # Violence detection (10% weight)
        if analysis.violence_detected:
            score += analysis.violence_confidence * 0.1
        
        # Multi-modal consistency (10% weight)
        score += analysis.cross_modal_consistency * 0.1
        
        # Quality score (15% weight)
        score += analysis.quality_score * 0.15
        
        # Penalty factors
        if analysis.is_anomalous:
            score -= 0.2
        
        if analysis.tamper_detected:
            score -= 0.3
        
        if not analysis.timestamp_valid:
            score -= 0.1
        
        if not analysis.chain_valid:
            score -= 0.2
        
        return max(min(score, 1.0), 0.0)
    
    def validate_incident_evidence(self, incident_type_id: int, description: str, 
                                 analysis: EvidenceAnalysis) -> Dict:
        """Advanced evidence validation against incident type requirements"""
        logger.info(f"Advanced validation for incident type {incident_type_id}")
        
        # Get rules for this incident type
        rules = self.enhanced_rules.get(incident_type_id, {})
        
        if not rules:
            return {
                'valid': False,
                'reason': 'Unknown incident type',
                'confidence': 0.0,
                'issues': ['Unknown incident type'],
                'advanced_analysis': {}
            }
        
        score = 0.0
        max_score = 0.0
        issues = []
        warnings = []
        
        # === CORE VALIDATION (50% weight) ===
        
        # 1. Expected objects (15% weight)
        if 'expected_objects' in rules:
            max_score += 0.15
            object_matches = 0
            for obj in rules['expected_objects']:
                if obj in analysis.detected_objects:
                    object_matches += 1
            
            if object_matches > 0:
                score += 0.15 * (object_matches / len(rules['expected_objects']))
            else:
                issues.append(f"No expected objects found. Expected: {rules['expected_objects']}")
        
        # 2. People detection (10% weight)
        max_score += 0.1
        if analysis.has_people:
            score += 0.1
        else:
            issues.append("No people detected in evidence")
        
        # 3. Action validation (15% weight)
        max_score += 0.15
        if 'expected_actions' in rules and analysis.detected_actions:
            action_matches = 0
            for action in rules['expected_actions']:
                if action in analysis.detected_actions:
                    action_matches += 1
            
            if action_matches > 0:
                score += 0.15 * (action_matches / len(rules['expected_actions']))
            else:
                warnings.append(f"No expected actions detected. Expected: {rules['expected_actions']}")
        else:
            warnings.append("No actions detected in evidence")
        
        # 4. Scene validation (10% weight)
        max_score += 0.1
        if 'expected_scenes' in rules:
            scene_match = False
            for scene in rules['expected_scenes']:
                if scene in analysis.scene_type or (scene == 'market' and 'market' in description.lower()):
                    scene_match = True
                    break
            
            if scene_match or analysis.scene_confidence > 0.7:
                score += 0.1
            else:
                warnings.append(f"Scene mismatch. Expected: {rules['expected_scenes']}, Found: {analysis.scene_type}")
        
        # === QUALITY & AUTHENTICITY (30% weight) ===
        
        # 5. Technical quality (10% weight)
        max_score += 0.1
        if analysis.technical_quality > 0.7:
            score += 0.1
        elif analysis.technical_quality > 0.5:
            score += 0.05
        else:
            warnings.append("Low technical quality")
        
        # 6. Content quality (10% weight)
        max_score += 0.1
        if analysis.content_quality > 0.7:
            score += 0.1
        elif analysis.content_quality > 0.5:
            score += 0.05
        else:
            warnings.append("Low content quality")
        
        # 7. Authenticity (10% weight)
        max_score += 0.1
        if analysis.authenticity_score > 0.8:
            score += 0.1
        elif analysis.authenticity_score > 0.6:
            score += 0.05
        else:
            if analysis.tamper_detected:
                issues.append("Evidence tampering detected")
            if not analysis.chain_valid:
                issues.append("Evidence chain validation failed")
            if not analysis.timestamp_valid:
                warnings.append("Timestamp validation failed")
        
        # === ADVANCED VALIDATION (20% weight) ===
        
        # 8. Violence detection (for applicable incidents)
        max_score += 0.05
        if incident_type_id in [2, 5]:  # Assault, Domestic Violence
            if analysis.violence_detected:
                score += 0.05
            else:
                warnings.append("No violence indicators detected for violent incident type")
        else:
            score += 0.05  # Not applicable, give full points
        
        # 9. Multi-modal consistency (5% weight)
        max_score += 0.05
        if analysis.cross_modal_consistency > 0.7:
            score += 0.05
        elif analysis.cross_modal_consistency > 0.5:
            score += 0.025
        else:
            warnings.append("Low multi-modal consistency")
        
        # 10. Anomaly check (5% weight)
        max_score += 0.05
        if not analysis.is_anomalous:
            score += 0.05
        else:
            issues.extend(analysis.anomaly_reasons)
        
        # 11. Privacy compliance (5% weight)
        max_score += 0.05
        if analysis.faces_detected > 0:
            if analysis.privacy_blurred:
                score += 0.05
            else:
                warnings.append("Faces detected but not blurred - privacy concern")
        else:
            score += 0.05
        
        # === DESCRIPTION ANALYSIS ===
        
        # 12. Keyword matching (bonus points)
        description_lower = description.lower()
        keyword_matches = 0
        if 'keywords' in rules:
            for keyword in rules['keywords']:
                if keyword in description_lower:
                    keyword_matches += 1
            
            if keyword_matches > 0:
                bonus = 0.1 * (keyword_matches / len(rules['keywords']))
                score += bonus
                max_score += bonus
        
        # Calculate final score
        final_score = score / max_score if max_score > 0 else 0.0
        
        # Determine validation result with dynamic threshold
        base_threshold = 0.6
        threshold = base_threshold  # Initialize threshold
        
        # Adjust threshold based on incident severity and evidence quality
        if incident_type_id in [2, 5]:  # High severity incidents
            threshold = base_threshold - 0.1  # More lenient for serious incidents
        
        if analysis.authenticity_score < 0.5:
            threshold = base_threshold + 0.2  # Stricter for suspicious evidence
        
        if analysis.violence_detected and incident_type_id in [2, 5]:
            threshold = base_threshold - 0.1  # More lenient if violence detected
        
        is_valid = final_score >= threshold
        
        # Prepare advanced analysis summary
        advanced_analysis = {
            'actions_detected': analysis.detected_actions,
            'violence_detected': analysis.violence_detected,
            'weapons_detected': analysis.weapons_detected,
            'faces_detected': analysis.faces_detected,
            'privacy_blurred': analysis.privacy_blurred,
            'scene_context': {
                'is_indoor': analysis.is_indoor,
                'lighting': analysis.lighting_condition,
                'weather': analysis.weather_condition
            },
            'quality_scores': {
                'technical': analysis.technical_quality,
                'content': analysis.content_quality,
                'authenticity': analysis.authenticity_score,
                'overall': analysis.quality_score
            },
            'anomaly_detected': analysis.is_anomalous,
            'tamper_detected': analysis.tamper_detected,
            'chain_valid': analysis.chain_valid
        }
        
        return {
            'valid': is_valid,
            'confidence': final_score,
            'threshold_used': threshold,
            'issues': issues,
            'warnings': warnings,
            'advanced_analysis': advanced_analysis,
            'analysis_summary': {
                'has_people': analysis.has_people,
                'detected_objects': analysis.detected_objects,
                'extracted_text': analysis.extracted_text,
                'quality_score': analysis.quality_score
            }
        }

# Global service instance
evidence_analysis_service = EvidenceAnalysisService()
