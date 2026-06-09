"""
Audio Forensic Analyzer
=======================
Extracts meaningful forensic features from audio evidence for crime reports.

Two-layer analysis:
  A) Signal-level feature extraction (numpy + ffmpeg)
     - Spectral analysis (frequency bands → screaming, speech, impacts)
     - Amplitude spike detection (gunshots, glass breaking, impacts)
     - Voice stress indicators (pitch variance, tremor patterns)
     - Background noise classification (chaotic, quiet, traffic, crowd)
     - Voice activity detection (someone is speaking vs silence)

  B) LLM-enhanced audio reasoning (Groq / Gemini)
     - Interprets extracted features + Whisper transcript together
     - Classifies distress indicators, urgency, relevance to incident
     - Works even with partial / noisy transcripts

The combined output feeds into Stage 4 (description ↔ evidence matching)
and the Volo audio scoring in the verification pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── LLM cache ────────────────────────────────────────────────────────────────
_AUDIO_LLM_CACHE: Dict[str, Dict[str, Any]] = {}
_AUDIO_LLM_CACHE_MAX = 128

# ── Constants ─────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000          # 16 kHz mono — standard for speech/forensic audio
MAX_AUDIO_SECONDS = 300      # Analyze at most 5 minutes
SPIKE_THRESHOLD_DB = 15.0    # dB above mean to count as amplitude spike
FRAME_MS = 25                # Analysis frame length in milliseconds
HOP_MS = 10                  # Frame hop in milliseconds

# Frequency band boundaries (Hz) for spectral classification
FREQ_BANDS = {
    "sub_bass":    (20, 100),     # Rumble, heavy impacts, explosions
    "bass":        (100, 300),    # Vehicle engines, slamming doors
    "low_mid":     (300, 800),    # Male speech fundamental
    "mid":         (800, 2000),   # Female speech, shouting
    "upper_mid":   (2000, 4000),  # Screaming, crying, glass breaking
    "high":        (4000, 8000),  # Sibilants, sharp impacts, whistles
}

# Sound event patterns (energy ratios between bands)
SOUND_SIGNATURES = {
    "scream_or_cry":  {"upper_mid": 0.35, "mid": 0.25, "high": 0.15},
    "impact_or_bang":  {"sub_bass": 0.30, "bass": 0.30, "low_mid": 0.15},
    "glass_breaking":  {"upper_mid": 0.25, "high": 0.40},
    "speech":          {"low_mid": 0.25, "mid": 0.30, "upper_mid": 0.15},
    "siren":           {"mid": 0.30, "upper_mid": 0.35, "high": 0.15},
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AudioFeatures:
    """Signal-level features extracted from audio evidence."""
    duration_seconds: float = 0.0
    sample_rate: int = SAMPLE_RATE

    # Energy & amplitude
    rms_energy: float = 0.0              # Overall RMS energy
    peak_amplitude: float = 0.0          # Maximum absolute amplitude
    dynamic_range_db: float = 0.0        # Difference between loudest and quietest
    amplitude_spikes: int = 0            # Count of sudden loud events
    spike_timestamps: List[float] = field(default_factory=list)  # Seconds

    # Spectral
    spectral_centroid_mean: float = 0.0  # Hz — higher = brighter/sharper sounds
    spectral_centroid_std: float = 0.0   # Variation in spectral centroid
    band_energies: Dict[str, float] = field(default_factory=dict)  # Per-band energy ratios

    # Voice / speech
    voice_activity_ratio: float = 0.0    # Fraction of audio with voice detected
    pitch_mean: float = 0.0             # Hz — estimated fundamental frequency
    pitch_std: float = 0.0             # Pitch variation (stress indicator)
    zero_crossing_rate: float = 0.0     # Higher = noisier / more chaotic

    # Noise & environment
    signal_to_noise_ratio: float = 0.0  # Estimated SNR in dB
    background_noise_level: float = 0.0  # Noise floor energy
    is_noisy: bool = False               # SNR below usable threshold
    is_chaotic: bool = False             # High ZCR + high energy variance

    # Sound event detection
    detected_sound_events: List[str] = field(default_factory=list)
    sound_event_confidences: Dict[str, float] = field(default_factory=dict)

    # Metadata
    has_speech: bool = False
    has_distress_indicators: bool = False
    urgency_indicators: List[str] = field(default_factory=list)
    extraction_error: str = ""


@dataclass
class AudioForensicResult:
    """Combined result of feature extraction + LLM analysis."""
    features: AudioFeatures
    transcript: str = ""

    # LLM analysis
    distress_level: str = "none"        # none | low | moderate | high | critical
    urgency_score: float = 0.0          # 0-100
    detected_sounds: List[str] = field(default_factory=list)
    incident_relevance: str = "unknown"  # strong | moderate | weak | unrelated
    incident_relevance_score: float = 50.0  # 0-100
    llm_reasoning: str = ""
    llm_available: bool = False

    # Composite scores for pipeline integration
    audio_content_score: float = 50.0   # 0-100 — how much useful content
    audio_authenticity_score: float = 50.0  # 0-100 — how authentic/real
    audio_relevance_score: float = 50.0    # 0-100 — relevance to description

    evidence_text_summary: str = ""     # Human-readable summary for Stage 4

    metadata: Dict[str, Any] = field(default_factory=dict)


# ── WAV conversion via ffmpeg ─────────────────────────────────────────────────

def _convert_to_wav_mono(input_path: str, output_path: str) -> bool:
    """Convert any audio file to 16kHz mono WAV using ffmpeg."""
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",           # mono
            "-sample_fmt", "s16", # 16-bit signed
            "-t", str(MAX_AUDIO_SECONDS),
            output_path,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0
    except Exception as exc:
        logger.warning("ffmpeg conversion failed: %s", exc)
        return False


def _load_wav_samples(wav_path: str) -> Optional[np.ndarray]:
    """Load WAV file as float32 numpy array normalized to [-1, 1]."""
    import wave
    import struct

    try:
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return None
            sw = wf.getsampwidth()
            raw = wf.readframes(min(n_frames, SAMPLE_RATE * MAX_AUDIO_SECONDS))

            if sw == 2:
                samples = np.array(
                    struct.unpack(f"<{len(raw) // 2}h", raw),
                    dtype=np.float32,
                )
                samples /= 32768.0
            elif sw == 1:
                samples = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
                samples = (samples - 128.0) / 128.0
            else:
                return None

            return samples
    except Exception as exc:
        logger.warning("WAV load failed: %s", exc)
        return None


# ── Feature extraction functions ──────────────────────────────────────────────

def _compute_rms_frames(samples: np.ndarray, frame_len: int, hop_len: int) -> np.ndarray:
    """Compute RMS energy per frame."""
    n = len(samples)
    n_frames = max(1, (n - frame_len) // hop_len + 1)
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        start = i * hop_len
        end = min(start + frame_len, n)
        frame = samples[start:end]
        rms[i] = np.sqrt(np.mean(frame ** 2) + 1e-10)
    return rms


def _compute_spectral_features(
    samples: np.ndarray, sr: int, frame_len: int, hop_len: int,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """Compute spectral centroid per frame and band energy ratios."""
    n = len(samples)
    n_frames = max(1, (n - frame_len) // hop_len + 1)
    centroids = np.zeros(n_frames, dtype=np.float32)
    band_energies_acc: Dict[str, float] = {b: 0.0 for b in FREQ_BANDS}
    total_spectral_energy = 0.0

    freqs = np.fft.rfftfreq(frame_len, d=1.0 / sr)

    for i in range(n_frames):
        start = i * hop_len
        end = min(start + frame_len, n)
        frame = samples[start:end]
        if len(frame) < frame_len:
            frame = np.pad(frame, (0, frame_len - len(frame)))

        # Apply Hann window
        window = np.hanning(frame_len).astype(np.float32)
        windowed = frame * window

        # FFT
        spectrum = np.abs(np.fft.rfft(windowed))
        power = spectrum ** 2
        total_power = np.sum(power) + 1e-10

        # Spectral centroid
        centroids[i] = np.sum(freqs * power) / total_power

        # Band energies
        for band_name, (low, high) in FREQ_BANDS.items():
            mask = (freqs >= low) & (freqs < high)
            band_power = np.sum(power[mask])
            band_energies_acc[band_name] += band_power
        total_spectral_energy += total_power

    # Normalize band energies to ratios
    if total_spectral_energy > 0:
        band_ratios = {
            b: round(e / total_spectral_energy, 4)
            for b, e in band_energies_acc.items()
        }
    else:
        band_ratios = {b: 0.0 for b in FREQ_BANDS}

    return centroids, band_ratios


def _detect_amplitude_spikes(
    rms_frames: np.ndarray, hop_len: int, sr: int,
) -> Tuple[int, List[float]]:
    """Detect sudden loud events (gunshots, impacts, screams starting)."""
    if len(rms_frames) < 3:
        return 0, []

    # Convert to dB
    rms_db = 20 * np.log10(rms_frames + 1e-10)
    mean_db = np.mean(rms_db)

    spikes = []
    for i in range(1, len(rms_db)):
        if rms_db[i] - mean_db > SPIKE_THRESHOLD_DB:
            # Check it's a real spike (not sustained loud section)
            if i > 0 and rms_db[i] - rms_db[i - 1] > SPIKE_THRESHOLD_DB * 0.5:
                timestamp = round(i * hop_len / sr, 2)
                spikes.append(timestamp)

    return len(spikes), spikes[:20]  # Cap at 20 timestamps


def _estimate_pitch(samples: np.ndarray, sr: int) -> Tuple[float, float]:
    """Simple autocorrelation-based pitch estimation for voiced segments."""
    frame_len = int(sr * 0.03)  # 30ms frames
    hop = int(sr * 0.015)       # 15ms hop
    n = len(samples)
    pitches = []

    min_lag = int(sr / 500)   # 500 Hz max
    max_lag = int(sr / 60)    # 60 Hz min

    for start in range(0, n - frame_len, hop):
        frame = samples[start:start + frame_len]
        energy = np.sum(frame ** 2)
        if energy < 1e-6:
            continue

        # Normalized autocorrelation
        corr = np.correlate(frame, frame, mode='full')
        corr = corr[len(corr) // 2:]
        if len(corr) <= max_lag:
            continue

        corr_segment = corr[min_lag:max_lag]
        if len(corr_segment) == 0:
            continue

        peak_idx = np.argmax(corr_segment) + min_lag
        peak_val = corr[peak_idx]

        # Only count if autocorrelation peak is strong (voiced)
        if peak_val > 0.3 * corr[0]:
            pitch = sr / peak_idx
            if 60 <= pitch <= 500:
                pitches.append(pitch)

    if not pitches:
        return 0.0, 0.0

    return float(np.mean(pitches)), float(np.std(pitches))


def _compute_zero_crossing_rate(samples: np.ndarray) -> float:
    """Zero crossing rate — higher means noisier / more chaotic."""
    if len(samples) < 2:
        return 0.0
    signs = np.sign(samples)
    crossings = np.sum(np.abs(np.diff(signs)) > 0)
    return float(crossings / len(samples))


def _estimate_snr(rms_frames: np.ndarray) -> float:
    """Estimate signal-to-noise ratio from RMS frame distribution."""
    if len(rms_frames) < 10:
        return 0.0

    sorted_rms = np.sort(rms_frames)
    # Bottom 10% as noise floor, top 10% as signal
    n = len(sorted_rms)
    noise_floor = np.mean(sorted_rms[:max(1, n // 10)]) + 1e-10
    signal_level = np.mean(sorted_rms[-(max(1, n // 10)):])

    snr_db = 20 * np.log10(signal_level / noise_floor)
    return round(float(snr_db), 2)


def _voice_activity_detection(rms_frames: np.ndarray) -> float:
    """Simple energy-based VAD. Returns fraction of frames with voice activity."""
    if len(rms_frames) < 5:
        return 0.0

    sorted_rms = np.sort(rms_frames)
    # Noise floor = bottom 15%
    noise_floor = np.mean(sorted_rms[:max(1, len(sorted_rms) // 7)])
    threshold = noise_floor * 3.0 + 1e-6

    active_frames = np.sum(rms_frames > threshold)
    return round(float(active_frames / len(rms_frames)), 3)


def _detect_sound_events(
    band_energies: Dict[str, float],
    rms_frames: np.ndarray,
    zcr: float,
    pitch_mean: float,
    pitch_std: float,
) -> Tuple[List[str], Dict[str, float]]:
    """Detect sound events by matching spectral profile against known signatures."""
    events: List[str] = []
    confidences: Dict[str, float] = {}

    for event_name, signature in SOUND_SIGNATURES.items():
        score = 0.0
        total_weight = 0.0

        for band, expected_ratio in signature.items():
            actual_ratio = band_energies.get(band, 0.0)
            # How close is actual to expected
            diff = abs(actual_ratio - expected_ratio)
            band_score = max(0, 1.0 - diff / max(expected_ratio, 0.01))
            score += band_score * expected_ratio
            total_weight += expected_ratio

        if total_weight > 0:
            confidence = score / total_weight
        else:
            confidence = 0.0

        # Extra heuristics per event type
        if event_name == "scream_or_cry":
            if pitch_mean > 250:
                confidence += 0.15
            if pitch_std > 40:
                confidence += 0.10
        elif event_name == "impact_or_bang":
            rms_std = float(np.std(rms_frames)) if len(rms_frames) > 1 else 0
            if rms_std > 0.1:
                confidence += 0.15
        elif event_name == "speech":
            if 80 < pitch_mean < 350:
                confidence += 0.15

        confidence = round(min(1.0, confidence), 3)
        confidences[event_name] = confidence
        if confidence >= 0.40:
            events.append(event_name)

    return events, confidences


def _identify_distress_indicators(
    features: AudioFeatures,
    transcript: str,
) -> Tuple[bool, List[str]]:
    """Identify indicators of distress from audio features and transcript."""
    indicators: List[str] = []

    # High pitch with high variation = stressed/screaming voice
    if features.pitch_mean > 200 and features.pitch_std > 50:
        indicators.append("stressed_voice_high_pitch_variance")

    # Screaming detected in sound events
    if "scream_or_cry" in features.detected_sound_events:
        indicators.append("screaming_or_crying_detected")

    # Sudden loud events (impacts, gunshots)
    if features.amplitude_spikes >= 2:
        indicators.append(f"sudden_loud_events_detected ({features.amplitude_spikes} spikes)")

    # High energy + chaotic = active incident
    if features.is_chaotic and features.rms_energy > 0.05:
        indicators.append("chaotic_high_energy_environment")

    # Noisy environment with speech = someone trying to communicate in chaos
    if features.is_noisy and features.has_speech:
        indicators.append("speech_in_noisy_environment")

    # Siren detected
    if "siren" in features.detected_sound_events:
        indicators.append("emergency_siren_detected")

    # Transcript-based distress keywords
    if transcript:
        transcript_lower = transcript.lower()
        distress_phrases = [
            "help", "please", "stop", "no", "don't", "fire", "police",
            "ambulance", "emergency", "save", "hurry", "run", "danger",
            "scared", "afraid", "hurt", "pain", "bleeding", "dying",
            "kill", "murder", "thief", "robber", "attack", "fighting",
            # Kinyarwanda distress words
            "ntabara", "mfasha", "fata", "hagarara", "polisi", "umuriro",
            "ndapfa", "ntibikwiye", "igitero", "umujura",
        ]
        found = [p for p in distress_phrases if p in transcript_lower]
        if found:
            indicators.append(f"distress_words_in_transcript: {', '.join(found[:5])}")

    return len(indicators) > 0, indicators


# ── Main feature extraction ──────────────────────────────────────────────────

def extract_audio_features(audio_bytes: bytes, suffix: str = ".m4a") -> AudioFeatures:
    """
    Extract forensic audio features from raw audio bytes.
    Converts to WAV via ffmpeg, then analyzes with numpy.
    """
    features = AudioFeatures()
    tmp_input = None
    tmp_wav = None

    try:
        # Write input to temp file
        fd, tmp_input = tempfile.mkstemp(suffix=suffix)
        os.write(fd, audio_bytes)
        os.close(fd)

        # Convert to 16kHz mono WAV
        fd2, tmp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd2)

        if not _convert_to_wav_mono(tmp_input, tmp_wav):
            features.extraction_error = "ffmpeg conversion failed"
            return features

        # Load samples
        samples = _load_wav_samples(tmp_wav)
        if samples is None or len(samples) < SAMPLE_RATE // 4:  # < 0.25s
            features.extraction_error = "audio too short or unreadable"
            return features

        sr = SAMPLE_RATE
        features.sample_rate = sr
        features.duration_seconds = round(len(samples) / sr, 2)

        frame_len = int(sr * FRAME_MS / 1000)
        hop_len = int(sr * HOP_MS / 1000)

        # 1. RMS energy per frame
        rms_frames = _compute_rms_frames(samples, frame_len, hop_len)
        features.rms_energy = round(float(np.mean(rms_frames)), 6)
        features.peak_amplitude = round(float(np.max(np.abs(samples))), 4)

        rms_db = 20 * np.log10(rms_frames + 1e-10)
        features.dynamic_range_db = round(
            float(np.max(rms_db) - np.min(rms_db)), 2
        )

        # 2. Amplitude spikes
        spikes, timestamps = _detect_amplitude_spikes(rms_frames, hop_len, sr)
        features.amplitude_spikes = spikes
        features.spike_timestamps = timestamps

        # 3. Spectral features
        centroids, band_energies = _compute_spectral_features(
            samples, sr, frame_len, hop_len,
        )
        features.spectral_centroid_mean = round(float(np.mean(centroids)), 1)
        features.spectral_centroid_std = round(float(np.std(centroids)), 1)
        features.band_energies = band_energies

        # 4. Pitch estimation
        pitch_mean, pitch_std = _estimate_pitch(samples, sr)
        features.pitch_mean = round(pitch_mean, 1)
        features.pitch_std = round(pitch_std, 1)

        # 5. Zero crossing rate
        features.zero_crossing_rate = round(
            _compute_zero_crossing_rate(samples), 4
        )

        # 6. SNR estimation
        features.signal_to_noise_ratio = _estimate_snr(rms_frames)
        noise_floor_frames = np.sort(rms_frames)[:max(1, len(rms_frames) // 7)]
        features.background_noise_level = round(float(np.mean(noise_floor_frames)), 6)
        features.is_noisy = features.signal_to_noise_ratio < 10.0

        # 7. Voice activity
        features.voice_activity_ratio = _voice_activity_detection(rms_frames)
        features.has_speech = features.voice_activity_ratio > 0.15

        # 8. Chaotic detection: high ZCR + high energy variance
        rms_cv = float(np.std(rms_frames) / (np.mean(rms_frames) + 1e-10))
        features.is_chaotic = (
            features.zero_crossing_rate > 0.15 and rms_cv > 1.5
        )

        # 9. Sound event detection
        events, confidences = _detect_sound_events(
            band_energies, rms_frames,
            features.zero_crossing_rate,
            features.pitch_mean, features.pitch_std,
        )
        features.detected_sound_events = events
        features.sound_event_confidences = confidences

        logger.info(
            "Audio features extracted: %.1fs, RMS=%.4f, spikes=%d, "
            "voice=%.0f%%, pitch=%.0fHz±%.0f, SNR=%.1fdB, events=%s",
            features.duration_seconds, features.rms_energy,
            features.amplitude_spikes, features.voice_activity_ratio * 100,
            features.pitch_mean, features.pitch_std,
            features.signal_to_noise_ratio,
            features.detected_sound_events,
        )

    except Exception as exc:
        features.extraction_error = str(exc)
        logger.error("Audio feature extraction failed: %s", exc)
    finally:
        for p in (tmp_input, tmp_wav):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return features


# ── LLM audio reasoning ──────────────────────────────────────────────────────

def _build_audio_llm_prompt(
    features: AudioFeatures,
    transcript: str,
    description: str,
    incident_type: str,
) -> str:
    """Build prompt for LLM to interpret audio evidence."""

    feature_summary = (
        f"Duration: {features.duration_seconds}s\n"
        f"Has speech: {features.has_speech} (voice activity: {features.voice_activity_ratio:.0%})\n"
        f"Background: {'noisy' if features.is_noisy else 'relatively clear'}, "
        f"SNR: {features.signal_to_noise_ratio:.1f}dB\n"
        f"Environment: {'chaotic/turbulent' if features.is_chaotic else 'calm/stable'}\n"
        f"Amplitude spikes (sudden loud events): {features.amplitude_spikes}\n"
        f"Pitch: mean={features.pitch_mean:.0f}Hz, variation={features.pitch_std:.0f}Hz "
        f"({'high stress/screaming' if features.pitch_std > 50 else 'normal variation'})\n"
        f"Detected sound patterns: {', '.join(features.detected_sound_events) or 'none identified'}\n"
        f"Distress indicators: {', '.join(features.urgency_indicators) or 'none'}\n"
    )

    transcript_section = ""
    if transcript and transcript.strip():
        transcript_section = (
            f"\nAUDIO TRANSCRIPT (may be partial/noisy):\n"
            f"{transcript[:2000]}\n"
        )
    else:
        transcript_section = (
            "\nAUDIO TRANSCRIPT: Not available (audio may be too noisy, "
            "non-verbal, or the person was whispering/hiding)\n"
        )

    return f"""You are a forensic audio analyst evaluating audio evidence submitted with a crime report.

IMPORTANT CONTEXT: Crime scene audio is often unclear. Reporters may be:
- Hiding and whispering
- Recording from a distance
- In a chaotic/noisy environment
- Capturing sounds of an ongoing incident (screams, impacts, arguments)
- Too afraid to speak clearly

Even unclear audio with background sounds of distress, fighting, or emergency IS valuable evidence.

INCIDENT TYPE: {incident_type}

REPORT DESCRIPTION:
{description[:1500]}

AUDIO SIGNAL ANALYSIS:
{feature_summary}
{transcript_section}

Analyze this audio evidence and return JSON only:
{{
  "distress_level": "<none|low|moderate|high|critical>",
  "urgency_score": <integer 0-100>,
  "detected_sounds": ["<list of sounds you can infer from the features and transcript>"],
  "incident_relevance": "<strong|moderate|weak|unrelated>",
  "incident_relevance_score": <integer 0-100>,
  "audio_content_value": <integer 0-100>,
  "reasoning": "<2-3 sentences explaining your assessment>"
}}

Guidelines:
- Audio with screaming, crying, or distress speech in a crime report = high relevance
- Chaotic background noise during a reported assault/robbery = relevant evidence
- Someone whispering while hiding during a reported break-in = strong relevance
- Clear speech describing an incident = valuable even if audio quality is poor
- Very short audio (<2s) with no identifiable content = weak
- Completely silent audio = weak relevance
- Audio of normal conversation unrelated to any incident = unrelated"""


def _call_audio_llm(prompt: str) -> Optional[Dict[str, Any]]:
    """Call Groq or Gemini for audio analysis."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.warning("Groq audio analysis call failed: %s", exc)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from app.core.llm_recommendations import (
                _gemini_model_candidates,
                gemini_generate_json,
            )
            for model_name in _gemini_model_candidates():
                parsed = gemini_generate_json(
                    prompt, gemini_key, model_name,
                    max_tokens=300, temperature=0.2,
                )
                if parsed:
                    return parsed
        except Exception as exc:
            logger.warning("Gemini audio analysis call failed: %s", exc)

    return None


def _llm_analyze_audio(
    features: AudioFeatures,
    transcript: str,
    description: str,
    incident_type: str,
) -> Dict[str, Any]:
    """Run LLM analysis on audio features + transcript."""
    # Cache key
    ck = hashlib.sha256(
        f"{features.duration_seconds}|{features.amplitude_spikes}|"
        f"{features.voice_activity_ratio}|{transcript[:200]}|"
        f"{description[:200]}|{incident_type}".encode()
    ).hexdigest()[:24]

    if ck in _AUDIO_LLM_CACHE:
        return _AUDIO_LLM_CACHE[ck]

    prompt = _build_audio_llm_prompt(features, transcript, description, incident_type)
    result = _call_audio_llm(prompt)

    if not result:
        return {}

    try:
        out = {
            "distress_level": str(result.get("distress_level", "none")).lower(),
            "urgency_score": max(0, min(100, int(float(result.get("urgency_score", 50))))),
            "detected_sounds": list(result.get("detected_sounds", [])),
            "incident_relevance": str(result.get("incident_relevance", "weak")).lower(),
            "incident_relevance_score": max(0, min(100, int(float(result.get("incident_relevance_score", 50))))),
            "audio_content_value": max(0, min(100, int(float(result.get("audio_content_value", 50))))),
            "reasoning": str(result.get("reasoning", ""))[:500],
        }
    except (TypeError, ValueError):
        return {}

    if len(_AUDIO_LLM_CACHE) >= _AUDIO_LLM_CACHE_MAX:
        _AUDIO_LLM_CACHE.clear()
    _AUDIO_LLM_CACHE[ck] = out
    return out


# ── Composite scoring ─────────────────────────────────────────────────────────

def _compute_audio_content_score(features: AudioFeatures, transcript: str) -> float:
    """Score how much useful content the audio contains (0-100)."""
    score = 30.0  # Base: audio evidence exists at all

    # Duration contributes (longer = more potential content)
    score += min(15.0, features.duration_seconds * 1.0)

    # Voice activity is valuable
    if features.has_speech:
        score += 15.0
        score += min(10.0, features.voice_activity_ratio * 15.0)

    # Transcript is very valuable
    if transcript and transcript.strip():
        words = len(transcript.strip().split())
        score += min(20.0, words * 0.8)

    # Sound events are content
    score += min(10.0, len(features.detected_sound_events) * 3.0)

    # Distress indicators are strong content
    if features.has_distress_indicators:
        score += 10.0

    return round(max(0.0, min(100.0, score)), 2)


def _compute_audio_authenticity_score(features: AudioFeatures) -> float:
    """Score how authentic/genuine the audio seems (0-100)."""
    score = 50.0  # Neutral start

    # Longer recordings are harder to fake
    if features.duration_seconds >= 3.0:
        score += 10.0
    if features.duration_seconds >= 10.0:
        score += 5.0

    # Natural dynamic range suggests real recording
    if 15.0 < features.dynamic_range_db < 60.0:
        score += 10.0

    # Background noise is actually a good sign (real environment)
    if features.is_noisy:
        score += 5.0

    # Voice activity with pitch variation = real person
    if features.has_speech and features.pitch_std > 10:
        score += 10.0

    # Amplitude spikes = real events happening
    if features.amplitude_spikes >= 1:
        score += min(10.0, features.amplitude_spikes * 3.0)

    # Too-perfect audio is suspicious (studio quality in crime scene?)
    if features.signal_to_noise_ratio > 40 and not features.is_noisy:
        score -= 10.0

    return round(max(0.0, min(100.0, score)), 2)


def _build_evidence_text_summary(
    features: AudioFeatures,
    transcript: str,
    llm_result: Dict[str, Any],
) -> str:
    """Build human-readable text summary for Stage 4 evidence matching."""
    parts: List[str] = []

    # Audio characteristics
    env_desc = []
    if features.is_chaotic:
        env_desc.append("chaotic/turbulent environment")
    elif features.is_noisy:
        env_desc.append("noisy environment")
    else:
        env_desc.append("relatively clear environment")

    if features.has_speech:
        env_desc.append(f"voice activity detected ({features.voice_activity_ratio:.0%} of audio)")

    parts.append(f"Audio recording ({features.duration_seconds:.1f}s): {', '.join(env_desc)}")

    # Sound events
    if features.detected_sound_events:
        parts.append(f"Sound patterns detected: {', '.join(features.detected_sound_events)}")

    # Distress
    if features.urgency_indicators:
        clean = [i.split("(")[0].strip() for i in features.urgency_indicators]
        parts.append(f"Distress indicators: {', '.join(clean)}")

    # LLM-detected sounds
    llm_sounds = llm_result.get("detected_sounds", [])
    if llm_sounds:
        parts.append(f"Audio contains: {', '.join(str(s) for s in llm_sounds[:8])}")

    # Transcript
    if transcript and transcript.strip():
        parts.append(f"Speech transcript: {transcript.strip()[:400]}")
    else:
        if features.has_speech:
            parts.append("Speech detected but too unclear to transcribe (possible whispering or background noise)")
        else:
            parts.append("No clear speech detected — audio contains environmental sounds only")

    # LLM reasoning
    reasoning = llm_result.get("reasoning", "")
    if reasoning:
        parts.append(f"Analysis: {reasoning}")

    return " | ".join(parts)


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze_audio_forensic(
    audio_bytes: bytes,
    suffix: str = ".m4a",
    transcript: str = "",
    description: str = "",
    incident_type: str = "",
) -> AudioForensicResult:
    """
    Complete audio forensic analysis: feature extraction + LLM reasoning.

    Args:
        audio_bytes: Raw audio file bytes
        suffix: File extension for format detection
        transcript: Whisper transcript (if already available)
        description: Report description for relevance matching
        incident_type: Incident type name

    Returns:
        AudioForensicResult with features, scores, and evidence text summary
    """
    # Step 1: Extract signal-level features
    features = extract_audio_features(audio_bytes, suffix)

    if features.extraction_error:
        logger.warning("Audio feature extraction failed: %s", features.extraction_error)
        return AudioForensicResult(
            features=features,
            transcript=transcript,
            audio_content_score=30.0,     # Audio exists, just can't analyze
            audio_authenticity_score=50.0, # Unknown
            audio_relevance_score=50.0,    # Unknown
            evidence_text_summary=f"Audio evidence ({len(audio_bytes)} bytes) — analysis failed: {features.extraction_error}",
            metadata={"error": features.extraction_error},
        )

    # Step 2: Identify distress indicators (signal + transcript)
    has_distress, urgency_indicators = _identify_distress_indicators(features, transcript)
    features.has_distress_indicators = has_distress
    features.urgency_indicators = urgency_indicators

    # Step 3: Compute signal-based scores
    content_score = _compute_audio_content_score(features, transcript)
    authenticity_score = _compute_audio_authenticity_score(features)

    # Step 4: LLM analysis (if available)
    llm_result: Dict[str, Any] = {}
    llm_available = False
    distress_level = "none"
    urgency_score = 0.0
    detected_sounds: List[str] = []
    relevance = "unknown"
    relevance_score = 50.0
    reasoning = ""

    if os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip():
        llm_result = _llm_analyze_audio(features, transcript, description, incident_type)
        if llm_result:
            llm_available = True
            distress_level = llm_result.get("distress_level", "none")
            urgency_score = float(llm_result.get("urgency_score", 0))
            detected_sounds = llm_result.get("detected_sounds", [])
            relevance = llm_result.get("incident_relevance", "weak")
            relevance_score = float(llm_result.get("incident_relevance_score", 50))
            reasoning = llm_result.get("reasoning", "")

            # LLM content value can boost/adjust content score
            llm_content = float(llm_result.get("audio_content_value", 50))
            content_score = content_score * 0.4 + llm_content * 0.6
    else:
        # No LLM — estimate relevance from features alone
        if has_distress:
            relevance = "moderate"
            relevance_score = 60.0
            urgency_score = 55.0
        elif features.has_speech and transcript:
            relevance = "moderate"
            relevance_score = 55.0
        elif features.has_speech:
            relevance = "weak"
            relevance_score = 45.0
        else:
            relevance = "weak"
            relevance_score = 40.0

        if features.amplitude_spikes >= 3:
            relevance_score = min(100, relevance_score + 15)
        if features.is_chaotic:
            relevance_score = min(100, relevance_score + 10)

        # Distress level from features
        distress_count = len(urgency_indicators)
        if distress_count >= 4:
            distress_level = "critical"
        elif distress_count >= 3:
            distress_level = "high"
        elif distress_count >= 2:
            distress_level = "moderate"
        elif distress_count >= 1:
            distress_level = "low"

    # Step 5: Build evidence text summary for Stage 4
    evidence_summary = _build_evidence_text_summary(features, transcript, llm_result)

    result = AudioForensicResult(
        features=features,
        transcript=transcript,
        distress_level=distress_level,
        urgency_score=round(urgency_score, 1),
        detected_sounds=detected_sounds,
        incident_relevance=relevance,
        incident_relevance_score=round(relevance_score, 1),
        llm_reasoning=reasoning,
        llm_available=llm_available,
        audio_content_score=round(content_score, 2),
        audio_authenticity_score=round(authenticity_score, 2),
        audio_relevance_score=round(relevance_score, 2),
        evidence_text_summary=evidence_summary,
        metadata={
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "llm_available": llm_available,
            "feature_extraction_ok": not bool(features.extraction_error),
            "has_transcript": bool(transcript and transcript.strip()),
            "distress_indicators": urgency_indicators,
            "sound_event_confidences": features.sound_event_confidences,
            "band_energies": features.band_energies,
        },
    )

    logger.info(
        "Audio forensic analysis complete: content=%.1f auth=%.1f rel=%.1f "
        "distress=%s urgency=%.0f events=%s llm=%s",
        result.audio_content_score, result.audio_authenticity_score,
        result.audio_relevance_score, result.distress_level,
        result.urgency_score, result.detected_sounds,
        result.llm_available,
    )

    return result
