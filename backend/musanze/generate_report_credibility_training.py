"""
Generate a synthetic training dataset for the report-credibility ML model.

It uses the real Musanze location samples from `musanze_training_data.csv`
to provide realistic lat/long + sector/cell/village distributions, and then
simulates report features plus ground-truth labels.

Output:
    report_credibility_training.csv in the same folder.

Columns (all included, even if some are "optional" for the first model):

    # Geo and admin info
    latitude
    longitude
    sector
    cell
    village
    sector_id
    cell_id
    village_id

    # Incident and report-level features
    incident_type_id          (1–8, aligned with seeded incident_types)
    incident_type_name
    gps_accuracy              (meters)
    motion_level              (low / medium / high)
    movement_speed            (m/s)
    was_stationary            (0/1)
    evidence_count
    has_live_capture          (0/1)
    time_of_day               (night / morning / day / evening)
    reported_at               (ISO timestamp)
    description_length        (synthetic length of description text)
    network_type              (wifi / mobile / offline)

    # Device history features
    device_total_reports
    device_trusted_reports
    device_flagged_reports
    device_trust_score        (0–100)
    confirmation_rate         (trusted / total, 0–1)
    spam_flag_count           (alias of device_flagged_reports)

    # Rule engine outputs (synthetic)
    rule_status               (passed / pending / flagged / rejected)
    is_flagged                (0/1)
    gps_speed_check           (km/h, derived from movement_speed)
    gps_anomaly_flag          (0/1, based on impossible speed / bad GPS)
    future_timestamp_flag     (0/1, timestamp in the future)

    # Ground-truth labels for ML
    ground_truth_label        (real / fake)
    decision                  (confirmed / rejected / investigation)
    confidence_level          (0.0–1.0)
    used_for_training         (0/1) – mark a subset as usable
"""

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "musanze_training_data.csv"
OUTPUT_PATH = ROOT / "report_credibility_training.csv"


INCIDENT_TYPES = {
    1: "Domestic Violence",
    2: "Assault",
    3: "Drug Activity",
    4: "Fraud / Scam",
    5: "Harassment",
    6: "Theft",
    7: "Vandalism",
    8: "Suspicious Activity",
}

MOTION_LEVELS = ["low", "medium", "high"]
TIMES_OF_DAY = ["night", "morning", "day", "evening"]
NETWORK_TYPES = ["wifi", "mobile", "offline"]


def pick_time_of_day() -> str:
    # Slightly more incidents in evening/night
    r = random.random()
    if r < 0.25:
        return "night"
    if r < 0.45:
        return "morning"
    if r < 0.75:
        return "day"
    return "evening"


def generate_reported_at(time_of_day: str) -> datetime:
    """
    Generate a realistic timestamp (as datetime), roughly within the last 6 months,
    and aligned with the chosen time_of_day bucket. A very small fraction will be
    in the near future to simulate timestamp anomalies.
    """
    now = datetime.now()

    # With small probability, create a future timestamp anomaly within 7 days
    if random.random() < 0.01:
        future_dt = now + timedelta(days=random.randint(1, 7))
        return future_dt.replace(
            hour=random.randint(0, 23),
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            microsecond=0,
        )

    # Random day within last ~180 days
    base_date = now - timedelta(days=random.randint(0, 180))

    if time_of_day == "night":
        hour = random.randint(0, 5)
    elif time_of_day == "morning":
        hour = random.randint(6, 11)
    elif time_of_day == "day":
        hour = random.randint(12, 17)
    else:  # evening
        hour = random.randint(18, 23)

    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    dt = base_date.replace(hour=hour, minute=minute, second=second, microsecond=0)
    return dt


def simulate_row(base: dict) -> dict:
    # Base location/admin fields copied from musanze_training_data.csv
    lat = float(base["latitude"])
    lon = float(base["longitude"])
    sector = base["sector"]
    cell = base["cell"]
    village = base["village"]
    sector_id = int(base["sector_id"])
    cell_id = int(base["cell_id"])
    village_id = int(base["village_id"])

    incident_type_id = random.randint(1, 8)
    incident_type_name = INCIDENT_TYPES[incident_type_id]

    # GPS accuracy: cluster around 5–20m with some noise
    gps_accuracy = max(1.0, random.gauss(10.0, 4.0))

    # Motion level and speed
    motion_level = random.choices(
        MOTION_LEVELS, weights=[0.4, 0.4, 0.2], k=1
    )[0]
    if motion_level == "low":
        movement_speed = abs(random.gauss(0.3, 0.2))
    elif motion_level == "medium":
        movement_speed = abs(random.gauss(1.4, 0.6))
    else:
        movement_speed = abs(random.gauss(3.0, 1.0))

    was_stationary = 1 if movement_speed < 0.3 else 0

    # Evidence
    evidence_count = max(0, int(random.gauss(2.0, 1.2)))
    has_live_capture = 1 if evidence_count > 0 and random.random() < 0.7 else 0

    time_of_day = pick_time_of_day()
    reported_at_dt = generate_reported_at(time_of_day)
    reported_at = reported_at_dt.isoformat()

    # Description length (synthetic proxy for text length)
    # Center around 120 chars, with some variation and clipping.
    description_length = max(0, min(1200, int(abs(random.gauss(120, 80)))))

    # Network type at submission
    network_type = random.choices(
        NETWORK_TYPES, weights=[0.4, 0.5, 0.1], k=1
    )[0]

    # Device history
    device_total_reports = max(1, int(abs(random.gauss(10, 8))))
    device_trusted_reports = max(
        0, min(device_total_reports, int(random.gauss(device_total_reports * 0.7, 3)))
    )
    device_flagged_reports = max(
        0, min(device_total_reports - device_trusted_reports, int(random.gauss(1, 1)))
    )

    # Simple trust score heuristic (0–100)
    trust_ratio = device_trusted_reports / device_total_reports
    penalty = min(device_flagged_reports * 8, 40)
    device_trust_score = max(
        0.0,
        min(100.0, trust_ratio * 80 + (device_total_reports / 50.0) * 10 - penalty),
    )

    # Higher-level device trust / spam metrics
    confirmation_rate = trust_ratio
    spam_flag_count = device_flagged_reports

    # Ground-truth label heuristic:
    # - many trusted reports, some evidence, decent motion → likely real
    # - poor device history, no evidence, weird GPS → likely fake
    score = (
        device_trust_score
        + evidence_count * 8
        + (10 if has_live_capture else 0)
        - (0 if gps_accuracy <= 25 else (gps_accuracy - 25) * 0.8)
    )
    # Add small random noise
    score += random.gauss(0, 10)

    is_real = score >= 50
    ground_truth_label = "real" if is_real else "fake"

    # Decision + confidence
    if ground_truth_label == "real":
        if random.random() < 0.8:
            decision = "confirmed"
        else:
            decision = "investigation"
    else:
        if random.random() < 0.8:
            decision = "rejected"
        else:
            decision = "investigation"

    if decision == "investigation":
        confidence_level = max(0.4, min(0.8, random.gauss(0.6, 0.1)))
    else:
        confidence_level = max(0.6, min(1.0, random.gauss(0.85, 0.08)))

    # Simulated rule engine outputs
    if ground_truth_label == "real":
        if gps_accuracy <= 25 and evidence_count >= 1:
            rule_status = "passed"
            is_flagged = 0
        elif evidence_count == 0:
            rule_status = "pending"
            is_flagged = 0
        else:
            rule_status = "pending"
            is_flagged = 0
    else:
        if evidence_count == 0 or gps_accuracy > 40:
            rule_status = "flagged"
            is_flagged = 1
        else:
            rule_status = "rejected"
            is_flagged = 1

    # Derived GPS/anomaly features
    gps_speed_check = movement_speed * 3.6  # m/s -> km/h
    gps_anomaly_flag = 1 if gps_speed_check > 200 or gps_accuracy > 200 else 0
    future_timestamp_flag = 1 if reported_at_dt > datetime.now() else 0

    # Only a subset of rows will be marked as used_for_training to mimic real systems
    used_for_training = 1 if random.random() < 0.8 else 0

    return {
        "latitude": lat,
        "longitude": lon,
        "sector": sector,
        "cell": cell,
        "village": village,
        "sector_id": sector_id,
        "cell_id": cell_id,
        "village_id": village_id,
        "incident_type_id": incident_type_id,
        "incident_type_name": incident_type_name,
        "gps_accuracy": round(gps_accuracy, 2),
        "motion_level": motion_level,
        "movement_speed": round(movement_speed, 3),
        "was_stationary": was_stationary,
        "evidence_count": evidence_count,
        "has_live_capture": has_live_capture,
        "time_of_day": time_of_day,
        "reported_at": reported_at,
        "description_length": description_length,
        "network_type": network_type,
        "device_total_reports": device_total_reports,
        "device_trusted_reports": device_trusted_reports,
        "device_flagged_reports": device_flagged_reports,
        "device_trust_score": round(device_trust_score, 2),
        "confirmation_rate": round(confirmation_rate, 3),
        "spam_flag_count": spam_flag_count,
        "rule_status": rule_status,
        "is_flagged": is_flagged,
        "gps_speed_check": round(gps_speed_check, 2),
        "gps_anomaly_flag": gps_anomaly_flag,
        "future_timestamp_flag": future_timestamp_flag,
        "ground_truth_label": ground_truth_label,
        "decision": decision,
        "confidence_level": round(confidence_level, 3),
        "used_for_training": used_for_training,
    }


def main():
    if not INPUT_PATH.exists():
        raise SystemExit(f"Input file not found: {INPUT_PATH}")

    rows: list[dict] = []
    with INPUT_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        base_rows = list(reader)

    # Sample up to N examples; if file is smaller, just use all.
    target_n = 8000
    if len(base_rows) <= target_n:
        sampled = base_rows
    else:
        sampled = random.sample(base_rows, target_n)

    for base in sampled:
        rows.append(simulate_row(base))

    fieldnames = [
        "latitude",
        "longitude",
        "sector",
        "cell",
        "village",
        "sector_id",
        "cell_id",
        "village_id",
        "incident_type_id",
        "incident_type_name",
        "gps_accuracy",
        "motion_level",
        "movement_speed",
        "was_stationary",
        "evidence_count",
        "has_live_capture",
        "time_of_day",
        "reported_at",
        "description_length",
        "network_type",
        "device_total_reports",
        "device_trusted_reports",
        "device_flagged_reports",
        "device_trust_score",
        "confirmation_rate",
        "spam_flag_count",
        "rule_status",
        "is_flagged",
        "gps_speed_check",
        "gps_anomaly_flag",
        "future_timestamp_flag",
        "ground_truth_label",
        "decision",
        "confidence_level",
        "used_for_training",
    ]

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

