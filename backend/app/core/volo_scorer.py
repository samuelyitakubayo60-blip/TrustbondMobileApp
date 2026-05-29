"""
Volo Model Scorer
Analyzes evidence content authenticity using YOLO object detection.
Outputs only scores - no decision making.
"""

from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
import logging
import os
import tempfile
import numpy as np
from datetime import datetime, timezone

from .trust_thresholds import trust_thresholds

logger = logging.getLogger(__name__)

_WHISPER_MODEL = None
_WHISPER_UNAVAILABLE = False


def _get_whisper_model_optional():
    """Optional speech-to-text (tiny model). Skips cleanly if openai-whisper is not installed."""
    global _WHISPER_MODEL, _WHISPER_UNAVAILABLE
    if _WHISPER_UNAVAILABLE:
        return None
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    try:
        import whisper

        _WHISPER_MODEL = whisper.load_model("tiny")
        return _WHISPER_MODEL
    except Exception as exc:
        logger.info("Whisper optional dependency unavailable: %s", exc)
        _WHISPER_UNAVAILABLE = True
        return None

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
    
    # YOLOv8n is trained on COCO (80 classes, IDs 0-79).
    # Each entry maps a COCO class ID to the label used everywhere in this project.
    _YOLO_RELEVANT_CLASSES = {
        # ── People ──────────────────────────────────────────
        0: "person",
        # ── Vehicles ────────────────────────────────────────
        1: "bicycle",
        2: "car",
        3: "motorcycle",
        5: "bus",
        7: "truck",
        9: "traffic light",
        # ── Bags / containers ───────────────────────────────
        24: "backpack",
        26: "handbag",
        28: "suitcase",
        # ── Weapons / tools ─────────────────────────────────
        34: "baseball bat",
        43: "knife",
        44: "spoon",       # drug paraphernalia context
        76: "scissors",
        # ── Bottles / drinks ────────────────────────────────
        39: "bottle",
        40: "wine glass",
        41: "cup",
        # ── Electronics ─────────────────────────────────────
        63: "laptop",
        67: "cell phone",
        65: "remote",
        # ── Indoor scene objects ─────────────────────────────
        56: "couch",
        57: "chair",
        59: "bed",
        62: "tv",
        73: "book",
        # ── Child-context indicator ───────────────────────────
        77: "teddy bear",
        # ── Miscellaneous ─────────────────────────────────────
        25: "umbrella",
        75: "vase",
    }

    def _detect_objects_list(self, image: np.ndarray) -> List[str]:
        """YOLO labels for each detection (allows counting people per frame)."""
        model = self._get_yolo_model()
        if model is None:
            return []
        try:
            results = model(image, verbose=False)
            detected_objects: List[str] = []
            for result in results:
                if hasattr(result, "boxes") and result.boxes is not None:
                    boxes = result.boxes
                    if hasattr(boxes, "cls"):
                        for cls in boxes.cls:
                            class_id = int(cls.item())
                            if class_id in self._YOLO_RELEVANT_CLASSES:
                                detected_objects.append(self._YOLO_RELEVANT_CLASSES[class_id])
            return detected_objects
        except Exception as exc:
            logger.warning("Object detection failed: %s", exc)
            return []

    def _detect_objects(self, image: np.ndarray) -> List[str]:
        """Detect objects using YOLO model (unique labels)."""
        return list(set(self._detect_objects_list(image)))

    def detect_objects_from_image_bytes(self, image_bytes: bytes) -> List[str]:
        """Run YOLO on raw image bytes (JPEG/PNG) without an HTTP round-trip."""
        import cv2

        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []
        return self._detect_objects(img)

    def analyze_video_bytes(self, video_bytes: bytes, max_frames: int = 12) -> Dict[str, Any]:
        """Sample video frames, run YOLO + motion proxy; works from raw upload bytes."""
        import cv2

        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
            os.write(fd, video_bytes)
            os.close(fd)
            fd = -1

            cap = cv2.VideoCapture(tmp_path)
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                return {"error": "could_not_open_video", "bytes": len(video_bytes)}

            frame_count_raw = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

            # Some codecs report 0 frames; use a large placeholder only for index spacing.
            n_frames = frame_count_raw if frame_count_raw > 0 else 100000

            target = max_frames
            indices: List[int] = []
            if n_frames <= target:
                indices = list(range(min(n_frames, target)))
            else:
                step = max(1, n_frames // target)
                indices = [min(n_frames - 1, i * step) for i in range(target)]

            prev_small: Optional[np.ndarray] = None
            motion_vals: List[float] = []
            blur_vals: List[float] = []
            brightness_vals: List[float] = []
            all_labels: List[str] = []
            max_persons_frame = 0
            frames_read = 0

            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frames_read += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lap = cv2.Laplacian(gray, cv2.CV_64F).var()
                blur_vals.append(float(lap))
                brightness_vals.append(float(np.mean(gray) / 255.0))

                labels = self._detect_objects_list(frame)
                all_labels.extend(labels)
                max_persons_frame = max(max_persons_frame, labels.count("person"))

                small = cv2.resize(gray, (64, 48))
                if prev_small is not None:
                    motion_vals.append(
                        float(np.mean(np.abs(small.astype(np.float64) - prev_small.astype(np.float64))))
                    )
                prev_small = small

            cap.release()

            unique_objects = sorted(set(all_labels))
            duration_guess = None
            if fps > 0 and frame_count_raw > 0:
                duration_guess = frame_count_raw / fps

            return {
                "bytes": len(video_bytes),
                "width": width,
                "height": height,
                "frame_count_reported": frame_count_raw,
                "fps": fps,
                "duration_guess_seconds": duration_guess,
                "frames_sampled": frames_read,
                "blur_score_avg": float(np.mean(blur_vals)) if blur_vals else 0.0,
                "brightness_avg": float(np.mean(brightness_vals)) if brightness_vals else 0.5,
                "motion_mean": float(np.mean(motion_vals)) if motion_vals else 0.0,
                "detected_objects": unique_objects,
                "max_persons_in_frame": max_persons_frame,
                "person_detections_total": all_labels.count("person"),
            }
        except Exception as exc:
            logger.warning("Video analysis failed: %s", exc)
            return {"error": str(exc), "bytes": len(video_bytes)}
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def analyze_audio_bytes(self, audio_bytes: bytes, suffix: str = ".m4a") -> Dict[str, Any]:
        """Duration (ffprobe), optional Whisper transcript, simple WAV energy."""
        import struct
        import subprocess

        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.write(fd, audio_bytes)
            os.close(fd)

            duration_seconds: Optional[float] = None
            try:
                proc = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        tmp_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    duration_seconds = float(proc.stdout.strip())
            except Exception:
                pass

            transcript: Optional[str] = None
            wm = _get_whisper_model_optional()
            if wm is not None:
                try:
                    out = wm.transcribe(tmp_path)
                    transcript = (out.get("text") or "").strip()
                except Exception as exc:
                    logger.warning("Whisper transcribe failed: %s", exc)

            rms_energy: Optional[float] = None
            if suffix.lower().endswith(".wav"):
                try:
                    import wave

                    with wave.open(tmp_path, "rb") as wf:
                        n = wf.getnframes()
                        raw = wf.readframes(min(n, 320_000))
                        if wf.getsampwidth() == 2 and raw:
                            samples = struct.unpack(f"<{len(raw) // 2}h", raw)
                            rms_energy = float(
                                np.sqrt(np.mean(np.square(np.array(samples, dtype=np.float64))))
                            )
                except Exception:
                    pass

            return {
                "bytes": len(audio_bytes),
                "duration_seconds": duration_seconds,
                "transcript": transcript,
                "rms_energy": rms_energy,
            }
        except Exception as exc:
            logger.warning("Audio analysis failed: %s", exc)
            return {"error": str(exc), "bytes": len(audio_bytes)}
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def analyze_evidence_video_from_url(
        self,
        video_url: str,
        incident_type_name: str = "",
        expected_objects: Optional[List[str]] = None,
    ) -> VoloAnalysisResult:
        """Download video from URL (e.g. Cloudinary), analyze sampled frames."""
        try:
            import requests

            resp = requests.get(video_url, timeout=120)
            resp.raise_for_status()
            meta = self.analyze_video_bytes(resp.content)
            if meta.get("error"):
                return self._create_empty_result(str(meta.get("error")))

            blur_avg = float(meta.get("blur_score_avg") or 0.0)
            bright_avg = float(meta.get("brightness_avg") or 0.5)
            min_blur = self.thresholds.config.EVIDENCE_MIN_BLUR_SCORE
            image_analysis: Dict[str, Any] = {
                "width": int(meta.get("width") or 0),
                "height": int(meta.get("height") or 0),
                "channels": 3,
                "file_size": int(meta.get("bytes") or len(resp.content)),
                "blur_score": blur_avg,
                "is_blurry": blur_avg < min_blur,
                "brightness": bright_avg,
                "brightness_valid": 0.15 <= bright_avg <= 0.92,
                "detected_objects": list(meta.get("detected_objects") or []),
                "pil_image": None,
                "cv_image": None,
            }

            authenticity_score, authenticity_metadata = self._analyze_evidence_authenticity(
                image_analysis, incident_type_name
            )
            detection_score, detection_metadata = self._analyze_object_detection(
                image_analysis, expected_objects
            )
            quality_score, quality_metadata = self._analyze_image_quality(image_analysis)

            motion_mean = float(meta.get("motion_mean") or 0.0)
            if motion_mean > 2.0:
                authenticity_score = min(100.0, authenticity_score + 5.0)

            overall_score = (
                authenticity_score * 0.4 + detection_score * 0.4 + quality_score * 0.2
            )
            confidence = self._calculate_confidence(
                authenticity_metadata, detection_metadata, quality_metadata
            )

            metadata = {
                "video_url": video_url,
                "incident_type": incident_type_name,
                "authenticity_analysis": authenticity_metadata,
                "detection_analysis": detection_metadata,
                "quality_analysis": quality_metadata,
                "video_analysis": meta,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "analysis_kind": "video_frames",
            }

            return VoloAnalysisResult(
                evidence_authenticity_score=authenticity_score,
                object_detection_score=detection_score,
                image_quality_score=quality_score,
                overall_score=overall_score,
                confidence=confidence,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Video URL evidence analysis failed: %s", exc)
            return self._create_empty_result(f"Analysis failed: {exc}")

    def analyze_evidence_audio_from_url(
        self,
        audio_url: str,
        incident_type_name: str = "",
        expected_objects: Optional[List[str]] = None,
    ) -> VoloAnalysisResult:
        """Download audio from URL; duration + optional transcript-based scoring."""
        del expected_objects  # reserved for future keyword mapping
        try:
            import requests
            from urllib.parse import urlparse

            path = urlparse(audio_url).path
            ext = ".m4a"
            for candidate in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
                if path.lower().endswith(candidate):
                    ext = candidate
                    break

            resp = requests.get(audio_url, timeout=120)
            resp.raise_for_status()
            meta = self.analyze_audio_bytes(resp.content, suffix=ext)
            if meta.get("error"):
                return self._create_empty_result(str(meta.get("error")))

            transcript = (meta.get("transcript") or "").strip()
            dur = float(meta.get("duration_seconds") or 0.0)

            authenticity = 45.0 + min(25.0, dur * 3.0)
            if transcript:
                authenticity += min(25.0, len(transcript) / 8.0)
            authenticity = max(0.0, min(100.0, authenticity))

            detection_score = 30.0
            if transcript:
                detection_score += min(55.0, len(transcript) / 5.0)
            detection_score = max(0.0, min(100.0, detection_score))

            quality_score = 45.0
            if dur > 0.5:
                quality_score += 20.0
            if meta.get("rms_energy"):
                quality_score += 10.0
            if transcript:
                quality_score += min(15.0, len(transcript) / 20.0)
            quality_score = max(0.0, min(100.0, quality_score))

            overall_score = authenticity * 0.35 + detection_score * 0.35 + quality_score * 0.3
            confidence = 0.55
            if transcript:
                confidence += 0.15
            if dur > 2.0:
                confidence += 0.1
            confidence = max(0.3, min(1.0, confidence))

            detection_metadata = {
                "detected_objects": [],
                "expected_objects": [],
                "final_detection_score": detection_score,
                "transcript_excerpt": transcript[:500],
            }

            metadata = {
                "audio_url": audio_url,
                "incident_type": incident_type_name,
                "authenticity_analysis": {"final_authenticity_score": authenticity},
                "detection_analysis": detection_metadata,
                "quality_analysis": {"final_quality_score": quality_score},
                "audio_analysis": meta,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "analysis_kind": "audio",
            }

            return VoloAnalysisResult(
                evidence_authenticity_score=authenticity,
                object_detection_score=detection_score,
                image_quality_score=quality_score,
                overall_score=overall_score,
                confidence=confidence,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Audio URL evidence analysis failed: %s", exc)
            return self._create_empty_result(f"Analysis failed: {exc}")
    
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
        
        # Contextual relevance — penalty when evidence content is irrelevant to the incident
        detected_objects = image_analysis.get("detected_objects", [])
        if self._objects_relevant_to_incident(detected_objects, incident_type_name):
            score += 15
            metadata["context_relevance_bonus"] = 15
            metadata["context_relevance_penalty"] = 0
        else:
            score -= 30  # Strong penalty: evidence content does not match incident type
            metadata["context_relevance_bonus"] = 0
            metadata["context_relevance_penalty"] = 30
        
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
    
    # Single source of truth for incident → expected YOLO objects.
    # Keys are substrings matched case-insensitively against the incident type name.
    # Values list every YOLO-detectable object that constitutes valid evidence.
    # IMPORTANT: only list objects that _YOLO_RELEVANT_CLASSES can actually detect.
    _INCIDENT_OBJECT_MAP: Dict[str, List[str]] = {
        # ── Property crimes ───────────────────────────────────────────────────────────
        "theft":       ["person", "cell phone", "handbag", "backpack", "laptop", "suitcase"],
        "robbery":     ["person", "cell phone", "handbag", "backpack", "knife", "suitcase"],
        "burglary":    ["person", "backpack", "handbag", "suitcase"],
        "pickpocket":  ["person", "cell phone", "handbag"],
        "stolen":      ["person", "cell phone", "handbag", "backpack", "laptop", "suitcase"],
        "larceny":     ["person", "cell phone", "handbag", "backpack", "laptop", "suitcase"],
        # ── Violent crimes ────────────────────────────────────────────────────────────
        "assault":     ["person", "knife", "baseball bat", "scissors", "bottle"],
        "attack":      ["person", "knife", "baseball bat", "scissors", "bottle"],
        "fight":       ["person", "knife", "baseball bat", "scissors", "bottle"],
        "brawl":       ["person", "knife", "baseball bat", "bottle"],
        "stabbing":    ["person", "knife", "scissors"],
        "beating":     ["person", "baseball bat", "bottle"],
        "violence":    ["person", "knife", "baseball bat", "scissors", "bottle"],
        "harassment":  ["person"],
        "threat":      ["person", "knife"],
        "kidnap":      ["person"],
        "abduction":   ["person"],
        "domestic":    ["person", "knife", "baseball bat", "bottle", "scissors"],
        "murder":      ["person", "knife"],
        "homicide":    ["person", "knife"],
        # ── Sexual crimes (person MUST be visible; teddy bear = child context) ────────
        "rape":        ["person", "bed", "couch", "teddy bear"],
        "defilement":  ["person", "bed", "couch", "teddy bear"],   # rape of a minor
        "sexual":      ["person", "bed", "couch", "teddy bear"],
        "indecent":    ["person"],
        "molest":      ["person", "teddy bear", "bed"],
        # ── Public-order crimes ───────────────────────────────────────────────────────
        "public disorder": ["person", "bottle"],
        "disturbance": ["person", "bottle"],
        "riot":        ["person", "bottle", "bicycle", "motorcycle", "car"],
        "mob":         ["person"],
        # ── Drug-related ─────────────────────────────────────────────────────────────
        # YOLO cannot detect smoke, small packages, or pills directly.
        # Bottle = drug containers / alcohol bottles; cup/wine glass = drinking evidence;
        # spoon = drug paraphernalia; vase = improvised smoking vessel (e.g. bong-like).
        "drug":        ["person", "bottle", "cup", "wine glass", "spoon", "vase", "backpack", "suitcase"],
        "narcotic":    ["person", "bottle", "cup", "spoon", "vase"],
        "cannabis":    ["person", "bottle", "cup", "vase"],          # smoking paraphernalia
        "weed":        ["person", "bottle", "cup", "vase"],
        "smoking":     ["person", "bottle", "cup", "vase"],
        "substance":   ["person", "bottle", "cup", "wine glass", "spoon"],
        "alcohol":     ["person", "bottle", "wine glass", "cup"],
        "drinking":    ["person", "bottle", "wine glass", "cup"],
        # ── Fraud / financial crimes ──────────────────────────────────────────────────
        "fraud":       ["person", "cell phone", "laptop", "book", "remote"],
        "scam":        ["person", "cell phone", "laptop"],
        "forgery":     ["person", "laptop", "cell phone", "book"],
        "extortion":   ["person", "cell phone"],
        "bribery":     ["person", "cell phone", "laptop"],
        "corruption":  ["person", "laptop", "cell phone"],
        # ── Traffic / road ───────────────────────────────────────────────────────────
        "traffic":     ["motorcycle", "bicycle", "person", "car", "truck", "bus", "traffic light"],
        "road":        ["motorcycle", "bicycle", "person", "car", "truck", "bus"],
        "accident":    ["person", "motorcycle", "bicycle", "car", "truck", "bus"],
        "crash":       ["person", "motorcycle", "bicycle", "car", "truck"],
        "collision":   ["person", "motorcycle", "bicycle", "car", "truck"],
        "hit and run": ["person", "motorcycle", "bicycle", "car", "truck"],
        "reckless driv": ["motorcycle", "bicycle", "person", "car"],
        "speeding":    ["motorcycle", "bicycle", "car", "truck"],
        "motorcycle":  ["motorcycle", "person"],
        "bicycle":     ["bicycle", "person"],
        # ── Environmental / disaster ──────────────────────────────────────────────────
        "fire":        ["person"],
        "arson":       ["person", "bottle"],
        "flooding":    ["person"],
        "flood":       ["person"],
        "landslide":   ["person"],
        "disaster":    ["person"],
        "emergency":   ["person"],
        # ── Suspicious / catch-all ────────────────────────────────────────────────────
        "suspicious":  ["person", "backpack", "handbag", "suitcase"],
        "loitering":   ["person", "backpack"],
        "trespassing": ["person", "backpack"],
        "vandalism":   ["person", "bottle", "scissors"],
        "graffiti":    ["person"],
        "damage":      ["person"],
        "illegal":     ["person"],
        "criminal":    ["person"],
        "missing":     ["person"],
    }

    def _objects_relevant_to_incident(self, objects: List[str], incident_type: str) -> bool:
        """Return True when at least one detected object matches the expected list
        for this incident type.  Returns False for unrecognised incident types so
        a wall / landscape never passes as relevant evidence."""
        incident_type = incident_type.lower()
        for key, expected in self._INCIDENT_OBJECT_MAP.items():
            if key in incident_type:
                return any(obj in objects for obj in expected)
        return False

    def get_expected_objects(self, incident_type_name: str) -> List[str]:
        """Return the deduplicated expected-object list for this incident type.
        Uses _INCIDENT_OBJECT_MAP so it is always in sync with relevance checks.
        Returns [] for unrecognised types — no bonus is awarded in that case."""
        incident_type = incident_type_name.lower()
        for key, expected in self._INCIDENT_OBJECT_MAP.items():
            if key in incident_type:
                # deduplicate while preserving order
                seen: set = set()
                out: List[str] = []
                for obj in expected:
                    if obj not in seen:
                        seen.add(obj)
                        out.append(obj)
                return out
        return []

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


def analyze_evidence_video_content(
    video_url: str,
    incident_type_name: str = "",
    expected_objects: Optional[List[str]] = None,
) -> VoloAnalysisResult:
    """Analyze video evidence via sampled frames + YOLO."""
    return volo_scorer.analyze_evidence_video_from_url(
        video_url=video_url,
        incident_type_name=incident_type_name,
        expected_objects=expected_objects,
    )


def analyze_evidence_audio_content(
    audio_url: str,
    incident_type_name: str = "",
    expected_objects: Optional[List[str]] = None,
) -> VoloAnalysisResult:
    """Analyze audio evidence (duration + optional Whisper transcript)."""
    return volo_scorer.analyze_evidence_audio_from_url(
        audio_url=audio_url,
        incident_type_name=incident_type_name,
        expected_objects=expected_objects,
    )
