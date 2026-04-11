"""Cluster-level hotspot classification (model-first, DBSCAN-score fallback)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


def compute_dbscan_score(
    incident_count: int,
    avg_trust: float,
    cluster_density: float,
    time_window_hours: int,
) -> float:
    """Compute trust-weighted DBSCAN score in range 0..100."""
    trust_weight = max(0.0, min(1.0, float(avg_trust) / 100.0))
    incident_score = min(40.0, float(incident_count) * 4.0 * trust_weight)
    density_score = min(30.0, float(cluster_density) * 3.0)
    recency_factor = max(0.1, 24.0 / max(1, int(time_window_hours)))
    recency_score = min(30.0, float(incident_count) * recency_factor * trust_weight * 2.0)
    return round(min(100.0, incident_score + density_score + recency_score), 2)


def classify_from_score(score: float) -> str:
    """Map score to TrustBond lifecycle classes."""
    if score >= 80.0:
        return "critical"
    if score >= 60.0:
        return "active"
    if score >= 40.0:
        return "emerging"
    return "low_activity"


def classification_to_risk_level(classification: str) -> str:
    """Map lifecycle class to DB hotspot risk enum."""
    if classification == "critical":
        return "critical"
    if classification == "active":
        return "high"
    if classification == "emerging":
        return "medium"
    return "low"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _load_cluster_model() -> Optional[Any]:
    """Best-effort load of optional cluster classifier model."""
    model_path = _project_root() / "musanze" / "cluster_hotspot_classifier.joblib"
    if not model_path.exists():
        return None
    try:
        import joblib  # type: ignore

        return joblib.load(model_path)
    except Exception:
        return None


def _normalize_label(label: Any) -> Optional[str]:
    if isinstance(label, str):
        l = label.strip().lower()
        if l in {"low_activity", "emerging", "active", "critical"}:
            return l
        return None
    if isinstance(label, (int, float)):
        idx = int(label)
        mapping = ["low_activity", "emerging", "active", "critical"]
        if 0 <= idx < len(mapping):
            return mapping[idx]
    return None


def predict_cluster_classification(
    incident_count: int,
    avg_trust: float,
    cluster_density: float,
    time_window_hours: int,
) -> Dict[str, Any]:
    """Return class, confidence, score, and source for cluster classification.

    Source values:
    - model: optional trained model loaded and used successfully
    - dbscan_fallback: deterministic trust-weighted DBSCAN score thresholds
    """
    score = compute_dbscan_score(
        incident_count=incident_count,
        avg_trust=avg_trust,
        cluster_density=cluster_density,
        time_window_hours=time_window_hours,
    )

    model = _load_cluster_model()
    if model is not None:
        try:
            row = [[
                float(incident_count),
                float(avg_trust),
                float(cluster_density),
                float(time_window_hours),
            ]]
            feature_names = [
                "incident_count",
                "avg_trust",
                "cluster_density",
                "time_window_hours",
            ]
            try:
                import pandas as pd  # type: ignore

                model_input = pd.DataFrame(row, columns=feature_names)
            except Exception:
                model_input = row
            label = None
            confidence = None

            if hasattr(model, "predict"):
                pred = model.predict(model_input)
                if len(pred):
                    label = _normalize_label(pred[0])

            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(model_input)
                if len(probs):
                    p = probs[0]
                    confidence = float(max(p)) if len(p) else None
                    if hasattr(model, "classes_") and confidence is not None:
                        classes = list(getattr(model, "classes_"))
                        top_idx = int(max(range(len(p)), key=lambda i: p[i]))
                        if 0 <= top_idx < len(classes):
                            label = _normalize_label(classes[top_idx]) or label

            if label is not None:
                return {
                    "classification": label,
                    "confidence": round(float(confidence), 4) if confidence is not None else None,
                    "hotspot_score": score,
                    "source": "model",
                }
        except Exception:
            pass

    return {
        "classification": classify_from_score(score),
        "confidence": None,
        "hotspot_score": score,
        "source": "dbscan_fallback",
    }
