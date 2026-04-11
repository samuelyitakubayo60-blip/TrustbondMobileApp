import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent
REPORTS_CSV = ROOT / "report_credibility_training.csv"
MUSANZE_CSV = ROOT / "musanze_training_data.csv"
MODEL_PATH = ROOT / "cluster_hotspot_classifier.joblib"
META_PATH = ROOT / "cluster_hotspot_classifier.json"

FEATURE_COLUMNS = [
    "incident_count",
    "avg_trust",
    "cluster_density",
    "time_window_hours",
]
LABELS = ["low_activity", "emerging", "active", "critical"]


def _load_data() -> pd.DataFrame:
    if not REPORTS_CSV.exists():
        raise SystemExit(f"Missing dataset: {REPORTS_CSV}")
    df = pd.read_csv(REPORTS_CSV)

    if "used_for_training" in df.columns:
        df = df[df["used_for_training"] == 1].copy()

    required = ["latitude", "longitude", "incident_type_id", "reported_at"]
    for col in required:
        if col not in df.columns:
            raise SystemExit(f"Column '{col}' is required in {REPORTS_CSV.name}")

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])

    df["reported_at"] = pd.to_datetime(df["reported_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["reported_at"])

    # trust proxy from device + confidence columns in existing training data
    trust = pd.to_numeric(df.get("device_trust_score"), errors="coerce").fillna(50.0)
    conf = pd.to_numeric(df.get("confidence_level"), errors="coerce").fillna(0.5) * 100.0
    df["trust_score"] = (0.7 * trust + 0.3 * conf).clip(0, 100)

    return df


def _load_density_factor_by_village() -> dict[str, float]:
    if not MUSANZE_CSV.exists():
        return {}

    mdf = pd.read_csv(MUSANZE_CSV)
    if "village" not in mdf.columns:
        return {}

    counts = mdf["village"].astype(str).value_counts()
    if counts.empty:
        return {}

    # Normalize to a mild multiplier [0.85, 1.15]
    min_v = float(counts.min())
    max_v = float(counts.max())
    if max_v <= min_v:
        return {k: 1.0 for k in counts.index}

    out: dict[str, float] = {}
    for village, c in counts.items():
        ratio = (float(c) - min_v) / (max_v - min_v)
        out[str(village)] = 0.85 + 0.30 * ratio
    return out


def _assign_cluster_label(
    incident_count: int,
    avg_trust: float,
    real_ratio: float,
    confirmed_ratio: float,
) -> str:
    # Pseudo-ground-truth for supervised cluster classifier bootstrapping
    risk_signal = 0.6 * real_ratio + 0.4 * confirmed_ratio

    if incident_count >= 10 and avg_trust >= 75 and risk_signal >= 0.80:
        return "critical"
    if incident_count >= 6 and avg_trust >= 60 and risk_signal >= 0.65:
        return "active"
    if incident_count >= 3 and avg_trust >= 45 and risk_signal >= 0.50:
        return "emerging"
    return "low_activity"


def _build_cluster_dataset(df: pd.DataFrame) -> pd.DataFrame:
    village_factor = _load_density_factor_by_village()

    # DBSCAN settings for generating training clusters from report-level rows
    eps_m = 500.0
    earth_radius_m = 6371000.0
    eps_rad = eps_m / earth_radius_m

    rows = []

    # Cluster separately by incident_type to avoid mixed-type artifacts
    for incident_type_id, g in df.groupby("incident_type_id"):
        if len(g) < 2:
            continue

        coords_rad = np.radians(g[["latitude", "longitude"]].to_numpy())
        labels = DBSCAN(eps=eps_rad, min_samples=2, metric="haversine").fit_predict(coords_rad)

        g2 = g.copy()
        g2["cluster_label"] = labels

        for cl, cg in g2.groupby("cluster_label"):
            if int(cl) < 0:
                continue
            incident_count = int(len(cg))
            if incident_count < 2:
                continue

            avg_trust = float(cg["trust_score"].mean())

            lat_center = float(cg["latitude"].mean())
            lon_center = float(cg["longitude"].mean())

            # Approx area in sq-km from max distance to center (very small-area proxy)
            dlat = (cg["latitude"] - lat_center) * 111.32
            dlon = (cg["longitude"] - lon_center) * 111.32 * np.cos(np.radians(lat_center))
            radial_km = np.sqrt(dlat.pow(2) + dlon.pow(2))
            max_r_km = max(0.05, float(radial_km.max()))
            area_sqkm = max(0.001, np.pi * max_r_km * max_r_km)
            cluster_density = float(incident_count / area_sqkm)

            if "village" in cg.columns:
                dominant_village = str(cg["village"].mode().iloc[0]) if not cg["village"].mode().empty else ""
                cluster_density *= float(village_factor.get(dominant_village, 1.0))

            tmin = cg["reported_at"].min()
            tmax = cg["reported_at"].max()
            span_hours = max(1.0, (tmax - tmin).total_seconds() / 3600.0)
            time_window_hours = int(min(168, max(1, round(span_hours))))

            real_ratio = 0.0
            if "ground_truth_label" in cg.columns:
                gt = cg["ground_truth_label"].astype(str).str.lower()
                real_ratio = float((gt == "real").mean())

            confirmed_ratio = 0.0
            if "decision" in cg.columns:
                dec = cg["decision"].astype(str).str.lower()
                confirmed_ratio = float((dec == "confirmed").mean())

            label = _assign_cluster_label(
                incident_count=incident_count,
                avg_trust=avg_trust,
                real_ratio=real_ratio,
                confirmed_ratio=confirmed_ratio,
            )

            rows.append(
                {
                    "incident_count": incident_count,
                    "avg_trust": round(avg_trust, 3),
                    "cluster_density": round(cluster_density, 3),
                    "time_window_hours": time_window_hours,
                    "label": label,
                    "incident_type_id": int(incident_type_id),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        raise SystemExit("No cluster samples could be built from the datasets.")

    # Keep all classes and ensure each class has at least 2 samples.
    def _synthetic_row(lbl: str) -> dict:
        return {
            "incident_count": 2 if lbl == "low_activity" else (4 if lbl == "emerging" else 7),
            "avg_trust": 42.0 if lbl == "low_activity" else (56.0 if lbl == "emerging" else (68.0 if lbl == "active" else 82.0)),
            "cluster_density": 2.5 if lbl == "low_activity" else (4.5 if lbl == "emerging" else (8.0 if lbl == "active" else 12.0)),
            "time_window_hours": 24,
            "label": lbl,
            "incident_type_id": 0,
        }

    counts = out["label"].value_counts().to_dict()
    for lbl in LABELS:
        current = int(counts.get(lbl, 0))
        need = max(0, 2 - current)
        if need > 0:
            out = pd.concat(
                [out, pd.DataFrame([_synthetic_row(lbl) for _ in range(need)])],
                ignore_index=True,
            )
            counts[lbl] = current + need

    return out


def train() -> None:
    df = _load_data()
    clusters = _build_cluster_dataset(df)

    X = clusters[FEATURE_COLUMNS].copy()
    y = clusters["label"].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=y,
    )

    model = RandomForestClassifier(
        n_estimators=400,
        max_depth=8,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)

    joblib.dump(model, MODEL_PATH)

    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "labels": LABELS,
        "n_report_rows": int(len(df)),
        "n_cluster_rows": int(len(clusters)),
        "train_size": int(len(X_train)),
        "test_size": int(len(X_test)),
        "classification_report": report,
        "source_files": [REPORTS_CSV.name, MUSANZE_CSV.name],
        "model_type": "RandomForestClassifier",
    }

    with META_PATH.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"Saved cluster model to: {MODEL_PATH}")
    print(f"Saved metadata to: {META_PATH}")
    print(f"Cluster samples: {len(clusters)}")
    print("Class distribution:")
    print(clusters["label"].value_counts().to_string())


if __name__ == "__main__":
    train()
