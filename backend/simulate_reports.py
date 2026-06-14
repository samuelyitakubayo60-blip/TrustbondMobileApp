"""
Reset operational data and seed realistic incident reports for Musanze district.

Usage (inside container / backend folder):
    python simulate_reports.py
    python simulate_reports.py --no-clear          # seed only
    python simulate_reports.py --dry-run-clear     # preview counts

Preserves: police_users, incident_types, locations, stations, local_leaders,
           system_config, special_assignment_units.

Clears: reports (+ related), hotspots, devices, audit_logs, sessions.
Keeps up to 2 reports dated tomorrow (UTC), then seeds 400 new reports through the
real 5-stage verification pipeline (AI summaries, scorecards, ML predictions).
Target mix via description quality: ≥16 rejected, ≥80 pending, remainder verified.
"""

import argparse
from types import SimpleNamespace
import os
import sys
import uuid
import random
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Ensure the app package is importable
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import func, text
from app.database import SessionLocal
from app.models.report import Report
from app.models.device import Device
from app.models.location import Location
from app.models.incident_type import IncidentType
from app.models.notification import Notification
from app.models.case import Case, CaseReport
from app.models.local_leader import LocalLeader
from app.core.operational_data_reset import (
    clear_operational_data,
    find_preserved_report_ids,
)
from app.core.leader_workflow import leader_covered_village_ids

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("simulate")

# ─── Configuration ──────────────────────────────────────────────────────────────

NUM_REPORTS = 400
MIN_REJECTED = 16
MIN_PENDING = 80
NUM_DEVICES = 90
DAYS_BACK = 90
BATCH_SIZE = 50

# Realistic incident type weights (some crimes are more common)
INCIDENT_WEIGHTS = {
    "Theft": 22,
    "Assault": 12,
    "Suspicious Activity": 18,
    "Domestic Violence": 8,
    "Drug Activity": 7,
    "Vandalism": 10,
    "Fraud/Scam": 9,
    "Harassment": 8,
    "Traffic Incident": 6,
}

# Realistic Kinyarwanda/English descriptions per incident type
DESCRIPTIONS = {
    "Theft": [
        "At approximately 11:45 PM last night, three unidentified men forced their way into the electronics shop near the main market by shattering the front glass window with a heavy stone. They made off with several smartphones, two laptops, and the cash register containing roughly 50,000 RWF. Neighbors heard the glass breaking and saw them fleeing down the alleyway towards the bus park.",
        "A red Bajaj Boxer motorcycle (Plate No. RE 342 A) was stolen from outside the 'Good Eats' restaurant between 1:00 PM and 1:30 PM. The owner had locked the steering, but witnesses reported seeing two men load the bike into the back of a white pickup truck before speeding off towards the highway.",
        "Over the past three days, we have noticed systematic theft of copper wire from the electrical poles along the secondary road to the village. The thieves operate between 2:00 AM and 4:00 AM using professional climbing gear, leaving the entire sector without power.",
        "Thieves cut through the chain-link fence of the community agricultural storage shed during a heavy rainstorm last night, making off with 15 bags of fertilizer, 5 hoes, and the newly purchased water pump. Tire tracks indicate a medium-sized truck was used to transport the goods.",
        "While walking home from the market near the hospital junction at 5:30 PM, a woman had her purse violently snatched by two young men riding a motorcycle without license plates. The purse contained her ID card, mobile phone, and business earnings for the week. The suspects wore black helmets obscuring their faces.",
    ],
    "Assault": [
        "A severe physical altercation occurred outside the local bar around 9:00 PM following a dispute over an unpaid debt. A man in his 30s was attacked by two others who used broken beer bottles, resulting in deep lacerations to his arm and face. Bystanders eventually intervened, and the victim was transported to the nearby clinic.",
        "A boda-boda driver was aggressively beaten by a male passenger who refused to pay the agreed 1,000 RWF fare upon arriving at the destination. The passenger pulled the driver off the bike and punched him repeatedly in the face before running into the nearby neighborhood. Other drivers tried to chase him but lost him in the narrow paths.",
        "During a community football match on Sunday afternoon, an argument over a referee's decision escalated into a massive brawl involving players and spectators. Wooden sticks and rocks were thrown, leading to at least four individuals sustaining moderate head and limb injuries. The crowd dispersed before local authorities arrived.",
    ],
    "Suspicious Activity": [
        "For the past three days, a dark blue SUV with tinted windows has been parked near the primary school gates during drop-off and pick-up times. The two occupants never exit the vehicle, but one was seen taking photographs of the children leaving the compound. They drive away quickly if approached.",
        "A group of four unfamiliar men carrying large, heavy backpacks have been seen moving through the forest path behind the village very late at night. They do not use flashlights and avoid the main roads. This path is not normally used for legitimate travel after dark.",
        "Several shop owners at the trading center reported that a well-dressed man has been coming in asking very specific questions about their security camera coverage, the times when cash is transported to the bank, and police patrol schedules. He claims to be doing a research project but refuses to show any identification.",
    ],
    "Domestic Violence": [
        "Frequent and severe screaming has been heard coming from the house at the end of the street for the past three nights. This morning, the wife was seen at the communal water tap with a heavily swollen eye and bruised arms. The children are crying continuously, and the husband was heard threatening further violence if anyone interferes.",
        "An elderly woman living with her adult son is being systematically denied food and subjected to verbal and physical abuse to force her to hand over her pension money. Neighbors report hearing the son shouting and throwing objects inside the house, and the mother appears visibly malnourished and afraid.",
    ],
    "Drug Activity": [
        "A coordinated drug distribution ring appears to be operating out of the abandoned half-built structure behind the old market. Every evening between 6:00 PM and 10:00 PM, dozens of youths arrive, briefly meet with two men standing at the entrance, exchange money for small wrapped packages, and leave immediately. There is a persistent strong smell of cannabis in the immediate vicinity.",
        "We found several discarded syringes and empty small plastic baggies scattered around the children's playground near the community center this morning. Last night, a group of unruly teenagers were seen congregating there, playing loud music and passing around what appeared to be illegal substances.",
    ],
    "Vandalism": [
        "Over the weekend, vandals targeted the newly constructed community health center. They spray-painted offensive symbols on the main entrance doors, smashed five windows in the waiting area, and deliberately broke the external water pipes, causing severe flooding in the courtyard and delaying medical services.",
        "The public solar-powered street lights installed along the main pathway were intentionally destroyed last night. The perpetrators climbed the poles to smash the solar panels and cut the internal wiring, leaving the entire neighborhood in complete darkness and increasing the risk of night-time crimes.",
    ],
    "Fraud/Scam": [
        "A highly organized scam is targeting elderly residents in the district. Two individuals claiming to be government agricultural officers are going door-to-door, requiring a 'mandatory registration fee' of 5,000 RWF to receive subsidized fertilizer for the upcoming planting season. They issue fake receipts with a forged official stamp and disappear with the money.",
        "A fake mobile money agent operating near the bus park is tricking people into initiating transfers to his number, claiming the network is down and he needs to manually process it. He takes the cash, pretends to send the money, but sends a fake SMS confirmation from a regular phone number. Several travelers have already lost their money.",
    ],
    "Harassment": [
        "A young woman is being relentlessly stalked by an older man who waits for her outside her workplace every evening. He follows her all the way to her bus stop, making inappropriate and threatening comments about knowing where she lives. Despite being told to stop by her coworkers, he has escalated to sending her anonymous threatening text messages.",
        "Local market vendors are facing extreme intimidation from a group of youths demanding a weekly 'protection fee' of 2,000 RWF per stall. If a vendor refuses, the group surrounds their stall, harasses their customers, and threatens to destroy their merchandise overnight. The vendors are terrified to report this formally out of fear of retaliation.",
    ],
    "Traffic Incident": [
        "A severe hit-and-run accident occurred at the main intersection near the hospital. A speeding white Toyota Corolla ignored the stop sign and violently struck a pedestrian crossing the road, throwing them several meters. The driver did not stop but accelerated away. The vehicle has significant damage to its right front headlight, and witnesses recorded part of the license plate ending in '45 B'.",
    ],
}

WEAK_DESCRIPTIONS = [
    "something happened",
    "bad thing",
    "help",
    "problem",
    "incident here",
    "need police",
    "theft maybe",
    "saw something",
    "not sure what",
    "urgent",
    "bad people",
    "trouble",
    "call someone",
    "idk",
    "happened yesterday",
    "weird stuff",
]

# Time-of-day distribution (hour weights — crimes peak in evening/night)
HOUR_WEIGHTS = {
    0: 3, 1: 2, 2: 2, 3: 1, 4: 1, 5: 2, 6: 5, 7: 8, 8: 6, 9: 5,
    10: 4, 11: 5, 12: 6, 13: 5, 14: 5, 15: 6, 16: 7, 17: 9, 18: 12,
    19: 14, 20: 15, 21: 12, 22: 8, 23: 5,
}

# Hotspot bias — some villages should have more reports than others (realistic clustering)
# These indices will be picked from actual villages and get 3-8x more reports
NUM_HOTSPOT_VILLAGES = 15

# Priority weights
PRIORITY_WEIGHTS = {"low": 30, "medium": 45, "high": 20, "urgent": 5}

# Network types
NETWORK_TYPES = ["wifi", "4g", "3g", "2g"]
NETWORK_WEIGHTS = [25, 40, 25, 10]

# Motion levels
MOTION_LEVELS = ["low", "medium", "high"]
MOTION_WEIGHTS = [50, 35, 15]

# App versions
APP_VERSIONS = ["1.2.4", "1.2.3", "1.2.2", "1.2.1", "1.1.9"]

# Context tags per incident type
CONTEXT_TAGS_POOL = {
    "Theft": [["Night-time"], ["Repeated offender area"], ["Near market"], ["Forced entry"], []],
    "Assault": [["Weapons involved"], ["Night-time"], ["Alcohol-related"], ["Group violence"], []],
    "Suspicious Activity": [["Night-time"], ["Near school"], ["Unknown individuals"], ["Repeated sightings"], []],
    "Domestic Violence": [["Repeat incident"], ["Children present"], ["Alcohol-related"], []],
    "Drug Activity": [["Near school"], ["Youth involved"], ["Night-time"], ["Recurring location"], []],
    "Vandalism": [["Night-time"], ["Public property"], ["Repeated damage"], []],
    "Fraud/Scam": [["Phone scam"], ["Door-to-door"], ["Online fraud"], ["Multiple victims"], []],
    "Harassment": [["Repeated incidents"], ["Workplace"], ["Public space"], []],
    "Traffic Incident": [["Speeding"], ["Hit and run"], ["Pedestrian involved"], ["Wet road conditions"], []],
}


def weighted_choice(items_weights):
    items = list(items_weights.keys())
    weights = list(items_weights.values())
    return random.choices(items, weights=weights, k=1)[0]


def jitter_coord(base, spread=0.003):
    """Add realistic GPS jitter to a coordinate."""
    return float(base) + random.gauss(0, spread)


def random_report_time(now, days_back):
    """Generate a realistic report timestamp with time-of-day bias."""
    day_offset = random.uniform(0, days_back)
    hour = weighted_choice(HOUR_WEIGHTS)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    base = now - timedelta(days=day_offset)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=random.randint(0, 999999))


def resolve_distribution_targets(
    num_reports: int,
    min_rejected: int = MIN_REJECTED,
    min_pending: int = MIN_PENDING,
) -> tuple[int, int]:
    """Scale rejected/pending targets for small test runs (e.g. --count 10)."""
    if num_reports >= min_rejected + min_pending:
        return min_rejected, min_pending

    if num_reports <= 0:
        return 0, 0
    if num_reports == 1:
        return 0, 0

    # Same ratios as full seed: 16/400 rejected, 80/400 pending
    rejected = max(1, round(num_reports * min_rejected / NUM_REPORTS))
    pending = max(1, round(num_reports * min_pending / NUM_REPORTS))

    while rejected + pending >= num_reports:
        if pending >= rejected and pending > 0:
            pending -= 1
        elif rejected > 0:
            rejected -= 1
        else:
            break

    return rejected, pending


def build_trust_score_plan(
    num_reports: int = NUM_REPORTS,
    min_rejected: int = MIN_REJECTED,
    min_pending: int = MIN_PENDING,
) -> list[tuple[str, float]]:
    """Return shuffled (bucket, trust_score) pairs matching planned distribution."""
    min_rejected, min_pending = resolve_distribution_targets(
        num_reports, min_rejected, min_pending
    )
    verified_count = num_reports - min_rejected - min_pending
    if verified_count < 0:
        verified_count = 0

    plan: list[tuple[str, float]] = []
    for _ in range(min_rejected):
        plan.append(("rejected", round(random.uniform(12, 39), 2)))
    for _ in range(min_pending):
        plan.append(("pending", round(random.uniform(40, 69), 2)))
    for _ in range(verified_count):
        plan.append(("verified", round(random.uniform(70, 96), 2)))
    random.shuffle(plan)
    return plan


def build_leader_village_since_map(db, local_leaders) -> dict[int, datetime]:
    """Earliest leader registration time per covered village."""
    village_since: dict[int, datetime] = {}
    for leader in local_leaders:
        if not leader.created_at:
            continue
        for vid in leader_covered_village_ids(db, leader.local_leader_id):
            prev = village_since.get(vid)
            if prev is None or leader.created_at < prev:
                village_since[vid] = leader.created_at
    return village_since


def report_time_for_bucket(
    now: datetime,
    days_back: int,
    bucket: str,
    leader_since: datetime | None,
) -> datetime:
    """Pending reports must post-date local leader registration in that village."""
    if bucket == "pending" and leader_since is not None:
        earliest = leader_since + timedelta(hours=random.randint(2, 48))
        if earliest >= now:
            earliest = now - timedelta(hours=random.randint(6, 72))
        span_seconds = max(3600.0, (now - earliest).total_seconds())
        reported_at = earliest + timedelta(seconds=random.uniform(0, span_seconds))
        hour = weighted_choice(HOUR_WEIGHTS)
        return reported_at.replace(
            hour=hour,
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            microsecond=random.randint(0, 999999),
        )
    return random_report_time(now, days_back)


def enrich_description(base: str, inc_type_name: str) -> str:
    """Add witness/time/location detail so descriptions read like real submissions."""
    extras = [
        " A neighbor witnessed part of the incident and is willing to provide a statement.",
        " The reporting party included specific times and nearby landmarks.",
        " Several residents gathered at the scene and confirmed the sequence of events.",
        " The incident was reported within an hour of occurring.",
        " Details include clothing descriptions and direction of travel for suspects.",
        " The reporter noted prior similar incidents in the same area this month.",
        " Local shop owners confirmed unusual activity matching this description.",
        " Children playing nearby alerted adults, who then called for assistance.",
    ]
    location_hints = [
        " near the trading center",
        " along the main village road",
        " close to the community water point",
        " behind the market stalls",
        " near the school compound",
    ]
    text_out = base.strip()
    if random.random() < 0.75:
        text_out += random.choice(extras)
    if random.random() < 0.5:
        text_out += random.choice(location_hints) + "."
    return text_out


def generate_report_number(db, index):
    """Generate unique report number in RPT-YYYY-NNNN format."""
    max_existing = db.execute(
        text("SELECT MAX(CAST(SUBSTRING(report_number FROM 10) AS INTEGER)) FROM reports WHERE report_number LIKE 'RPT-%-____'")
    ).scalar() or 0
    num = max_existing + index + 1
    return f"RPT-2026-{num:04d}"


def create_devices(db, count):
    """Create realistic devices with varied trust profiles."""
    logger.info("Creating %d devices...", count)
    devices = []
    for i in range(count):
        device_id = uuid.uuid4()
        # Simulate realistic device fingerprints
        fingerprint = f"android-{uuid.uuid4().hex[:16]}-{random.choice(['samsung', 'tecno', 'infinix', 'itel', 'huawei', 'oppo', 'xiaomi'])}"
        device_hash = hashlib.sha256(fingerprint.encode()).hexdigest()

        # Varied trust profiles: most are medium-high, some low
        trust_profile = random.choices(
            ["high", "medium", "low", "new"],
            weights=[30, 40, 10, 20],
            k=1
        )[0]

        if trust_profile == "high":
            trust_score = round(random.uniform(70, 95), 2)
            total_reports = random.randint(5, 25)
            trusted = int(total_reports * random.uniform(0.75, 0.95))
        elif trust_profile == "medium":
            trust_score = round(random.uniform(45, 70), 2)
            total_reports = random.randint(2, 12)
            trusted = int(total_reports * random.uniform(0.5, 0.8))
        elif trust_profile == "low":
            trust_score = round(random.uniform(15, 45), 2)
            total_reports = random.randint(1, 5)
            trusted = int(total_reports * random.uniform(0.1, 0.4))
        else:  # new device
            trust_score = 50.0
            total_reports = 0
            trusted = 0

        first_seen = datetime.now(timezone.utc) - timedelta(
            days=random.randint(1, 90)
        )

        device = Device(
            device_id=device_id,
            device_hash=device_hash,
            first_seen_at=first_seen,
            last_seen_at=first_seen + timedelta(days=random.randint(0, 30)),
            total_reports=total_reports,
            trusted_reports=trusted,
            flagged_reports=random.randint(0, max(0, total_reports - trusted)),
            spam_flags=0,
            device_trust_score=Decimal(str(trust_score)),
            is_blacklisted=False,
            is_banned=False,
        )
        db.add(device)
        devices.append(device)

    db.flush()
    logger.info("Created %d devices", len(devices))
    return devices


def load_incident_types(db):
    """Load incident types; raw SQL fallback when ORM columns lag migrations."""
    try:
        rows = (
            db.query(IncidentType)
            .filter(IncidentType.is_active.is_(True))
            .all()
        )
        if rows:
            return rows
    except Exception:
        db.rollback()
        logger.warning("ORM incident_types query failed — using raw SQL fallback")

    raw = db.execute(
        text(
            """
            SELECT incident_type_id, type_name, COALESCE(severity_weight, 1.0) AS severity_weight
            FROM incident_types
            WHERE is_active IS NOT FALSE
            """
        )
    ).fetchall()
    return [
        SimpleNamespace(
            incident_type_id=int(r[0]),
            type_name=str(r[1]),
            severity_weight=r[2],
        )
        for r in raw
    ]


def build_village_pools(db):
    """Load villages via raw SQL (avoids heavy PostGIS geometry on remote DB)."""
    rows = db.execute(
        text(
            """
            SELECT location_id, parent_location_id, centroid_lat, centroid_long
            FROM locations
            WHERE location_type = 'village'
              AND is_active IS NOT FALSE
              AND centroid_lat IS NOT NULL
              AND centroid_long IS NOT NULL
            """
        )
    ).fetchall()

    villages = [
        SimpleNamespace(
            location_id=int(r[0]),
            parent_location_id=r[1],
            centroid_lat=r[2],
            centroid_long=r[3],
        )
        for r in rows
    ]

    if not villages:
        raise RuntimeError("No villages with coordinates found in DB")

    today_target_rows = db.execute(
        text(
            """
            SELECT location_id FROM locations WHERE location_type = 'village' AND parent_location_id IN (
                SELECT location_id FROM locations WHERE location_type = 'cell' AND parent_location_id IN (
                    SELECT location_id FROM locations WHERE location_name IN ('Muhoza', 'Cyuve') AND location_type = 'sector'
                )
            )
            """
        )
    ).fetchall()
    today_target_ids = {r[0] for r in today_target_rows}
    today_target_villages = [v for v in villages if v.location_id in today_target_ids]
    if not today_target_villages:
        today_target_villages = villages

    hotspot_villages = random.sample(villages, min(NUM_HOTSPOT_VILLAGES, len(villages)))
    hotspot_ids = {v.location_id for v in hotspot_villages}

    logger.info("Loaded %d villages, %d designated as hotspot villages", len(villages), len(hotspot_ids))
    return villages, hotspot_villages, hotspot_ids, today_target_villages


def pick_village(villages, hotspot_villages, hotspot_ids):
    """Weighted village selection — hotspot villages get ~4x more reports."""
    if random.random() < 0.45:  # 45% of reports go to hotspot villages
        return random.choice(hotspot_villages)
    return random.choice(villages)


def get_sector_cell_for_village(db, village):
    """Walk up the location hierarchy to find cell and sector IDs."""
    cell_id = village.parent_location_id
    if cell_id:
        row = db.execute(
            text("SELECT parent_location_id FROM locations WHERE location_id = :cid"),
            {"cid": int(cell_id)},
        ).first()
        if row:
            return row[0], cell_id
    return None, None


def description_for_bucket(bucket: str, inc_type_name: str) -> str:
    """Pick description quality to steer the real verification pipeline."""
    if bucket == "rejected":
        return random.choice(WEAK_DESCRIPTIONS)
    type_descs = DESCRIPTIONS.get(
        inc_type_name, ["Incident reported in the area with limited detail."]
    )
    base = random.choice(type_descs)
    if bucket == "verified":
        return enrich_description(base, inc_type_name)
    return base


def build_compose_narratives_fn(incident_type_name: str | None = None):
    """Mirror report submit path so seeded rows get full AI verification narratives."""
    from app.api.v1.reports import (
        _build_ai_analysis_snapshot,
        _compose_ai_verification_reason,
        _description_credibility_from_report,
        _human_location_chain_from_report,
        _persist_ai_analysis_snapshot,
        _text_only_reason_codes_from_report,
    )

    def _resolve_incident_type_name(report) -> str | None:
        if incident_type_name:
            return incident_type_name
        rel = getattr(report, "incident_type", None)
        return getattr(rel, "type_name", None) if rel is not None else None

    def compose_narratives(**kwargs):
        r = kwargs["report"]
        uv = kwargs["unified_validation"]
        sc = kwargs["scorecard"]
        ai_ts = kwargs["ai_trust_score"]
        ai_lbl = kwargs["ai_label"]
        ev = kwargs["evidence_validations"]
        type_name = _resolve_incident_type_name(r)
        evidence_files_all = list(getattr(r, "evidence_files", []) or [])
        ec_final = len(evidence_files_all) if evidence_files_all else len(ev or [])
        sem = (
            r.feature_vector.get("semantic_alignment")
            if isinstance(r.feature_vector, dict)
            else None
        )
        r.ai_verification_reason = _compose_ai_verification_reason(
            verification_status=r.verification_status,
            rule_status=r.rule_status,
            is_flagged=r.is_flagged,
            flag_reason=r.flag_reason,
            ml_prediction_label=ai_lbl,
            trust_score=ai_ts,
            semantic_alignment=sem if isinstance(sem, dict) else None,
            incident_type_name=type_name,
            reporter_description=r.description,
            context_tags=list(getattr(r, "context_tags", None) or []),
            unified_validation=uv,
            scorecard=sc,
            evidence_validations=ev,
            evidence_file_count=ec_final,
            latitude=getattr(r, "latitude", None),
            longitude=getattr(r, "longitude", None),
            gps_accuracy=getattr(r, "gps_accuracy", None),
            location_label=_human_location_chain_from_report(r),
            description_credibility=_description_credibility_from_report(r),
            text_only_reason_codes=_text_only_reason_codes_from_report(r),
        )
        r.ai_evidence_description = None
        snapshot = _build_ai_analysis_snapshot(
            verification_status=r.verification_status,
            rule_status=r.rule_status,
            is_flagged=r.is_flagged,
            flag_reason=r.flag_reason,
            ml_prediction_label=ai_lbl,
            trust_score=ai_ts,
            semantic_alignment=sem if isinstance(sem, dict) else None,
            incident_type_name=type_name,
            reporter_description=r.description,
            context_tags=list(getattr(r, "context_tags", None) or []),
            unified_validation=uv,
            scorecard=sc,
            evidence_validations=ev,
            evidence_file_count=ec_final,
            latitude=getattr(r, "latitude", None),
            longitude=getattr(r, "longitude", None),
            gps_accuracy=getattr(r, "gps_accuracy", None),
            location_label=_human_location_chain_from_report(r),
            description_credibility=_description_credibility_from_report(r),
        )
        _persist_ai_analysis_snapshot(r, snapshot)

    return compose_narratives


def run_seed_verification_pipeline(db, report, device, inc_type):
    """
    Run the same 5-stage citizen verification pipeline used on real report submit.
    Populates threshold_scorecard, ML prediction, ai_verification_reason, and AI snapshot.
    """
    from app.api.v1.reports import _compute_threshold_scorecard
    from app.core.credibility_model import _json_safe
    from app.core.natural_language_scorer import analyze_description_quality
    from app.core.report_priority import apply_anti_fraud_rules
    from app.core.verification_orchestrator import (
        build_text_only_validation_from_nl,
        run_citizen_verification_pipeline,
    )

    type_name = inc_type.type_name
    type_description = getattr(inc_type, "description", "") or ""

    try:
        nl = analyze_description_quality(
            report.description or "",
            type_name,
            type_description,
        )
        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        fv["text_only_nl"] = {
            "overall_score": float(getattr(nl, "overall_score", 0.0) or 0.0),
            "confidence": float(getattr(nl, "confidence", 0.0) or 0.0),
            "semantic_similarity": float(getattr(nl, "semantic_similarity_score", 0.0) or 0.0),
            "description_quality": float(getattr(nl, "description_quality_score", 0.0) or 0.0),
        }
        fv["text_only_validation"] = build_text_only_validation_from_nl(nl)
        report.feature_vector = _json_safe(fv)
    except Exception as exc:
        logger.warning("Text-only NL analysis failed for %s: %s", report.report_id, exc)

    pre_rule_status, _pre_flagged, pre_reason = apply_anti_fraud_rules(report, 0, db)
    if pre_rule_status == "rejected":
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = pre_reason or "anti_fraud_rules_violation"
        report.ai_ready = True
        report.features_extracted_at = datetime.now(timezone.utc)
        return None

    compose_narratives = build_compose_narratives_fn(type_name)
    return run_citizen_verification_pipeline(
        db,
        report,
        device,
        evidence_files=[],
        evidence_validations=[],
        evidence_metadata_list=[],
        compute_scorecard_fn=_compute_threshold_scorecard,
        compose_narratives_fn=compose_narratives,
    )


def apply_seed_leader_follow_up(report, reported_at: datetime) -> None:
    """Set leader gate fields after the real pipeline has decided AI status."""
    if report.verification_status == "verified" and report.status == "verified":
        report.leader_verification_status = "confirmed"
        report.leader_verified_at = reported_at + timedelta(hours=random.randint(1, 36))
        report.leader_verification_note = random.choice([
            "Confirmed by community leader. Incident is known in the area.",
            "Verified through community channels. Details are consistent with local accounts.",
            "Community confirms this incident occurred as described.",
        ])
        if not report.verified_at:
            report.verified_at = reported_at + timedelta(minutes=random.randint(2, 45))
    elif report.verification_status == "rejected":
        report.leader_verification_status = "rejected"
        report.leader_verified_at = reported_at + timedelta(hours=random.randint(1, 12))
    else:
        report.leader_verification_status = "pending"


def pipeline_trust_score(report) -> float:
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    sc = fv.get("threshold_scorecard") if isinstance(fv.get("threshold_scorecard"), dict) else {}
    if sc.get("total_score") is not None:
        return float(sc["total_score"])
    stage5 = fv.get("stage_5_trust_score") if isinstance(fv.get("stage_5_trust_score"), dict) else {}
    return float(stage5.get("trust_score") or 0.0)


def create_notifications(db, report, police_users, local_leaders, *, incident_type_name: str = "Unknown"):
    """Create notifications for flagged/pending reports."""
    if report.status == "pending" or report.verification_status == "under_review":
        # Notify supervisors/officers about reports needing review
        for pu in police_users:
            if pu.role in ("supervisor", "admin"):
                notif = Notification(
                    notification_id=uuid.uuid4(),
                    police_user_id=pu.police_user_id,
                    title=f"Report needs review: {incident_type_name}",
                    message=f"Report {report.report_number} has been flagged for review. Trust score indicates community verification is needed.",
                    type="report",
                    related_entity_type="report",
                    related_entity_id=str(report.report_id),
                    is_read=random.random() < 0.3,  # 30% already read
                    created_at=report.reported_at + timedelta(minutes=random.randint(1, 15)),
                )
                db.add(notif)

    if report.status == "verified" and report.priority in ("high", "urgent"):
        # Notify about high-priority verified reports
        for pu in police_users:
            if pu.role in ("supervisor", "officer"):
                notif = Notification(
                    notification_id=uuid.uuid4(),
                    police_user_id=pu.police_user_id,
                    title=f"{report.priority.upper()}: {incident_type_name}",
                    message=f"Verified {report.priority}-priority incident reported. Case investigation may be required.",
                    type="report",
                    related_entity_type="report",
                    related_entity_id=str(report.report_id),
                    is_read=random.random() < 0.4,
                    created_at=report.reported_at + timedelta(minutes=random.randint(2, 30)),
                )
                db.add(notif)


def create_cases_from_clusters(db, reports_by_village, incident_types_map, police_users, stations):
    """Create cases when multiple verified reports of the same type cluster in a village."""
    logger.info("Creating cases from report clusters...")
    officers = [pu for pu in police_users if pu.role == "officer"]
    supervisors = [pu for pu in police_users if pu.role in ("supervisor", "admin")]

    # Get existing max case number
    max_case = db.execute(
        text("SELECT MAX(CAST(SUBSTRING(case_number FROM 11) AS INTEGER)) FROM cases WHERE case_number LIKE 'CASE-2026-%'")
    ).scalar() or 0
    case_num = max_case + 1

    cases_created = 0
    for village_id, village_reports in reports_by_village.items():
        # Group by incident type
        type_groups = {}
        for r in village_reports:
            if r.status != "verified":
                continue
            tid = r.incident_type_id
            type_groups.setdefault(tid, []).append(r)

        for tid, group_reports in type_groups.items():
            if len(group_reports) < 2:
                continue
            # Create a case for this cluster
            sample_report = group_reports[0]
            type_name = incident_types_map.get(tid, "Unknown")
            assigned_officer = random.choice(officers) if officers else (random.choice(supervisors) if supervisors else None)
            creator = random.choice(supervisors) if supervisors else None

            station_id = None
            if assigned_officer and hasattr(assigned_officer, 'station_id'):
                station_id = assigned_officer.station_id
            elif stations:
                station_id = random.choice(stations).station_id

            case = Case(
                case_id=uuid.uuid4(),
                case_number=f"CASE-2026-{case_num:04d}",
                status=random.choice(["open", "open", "open", "investigating"]),
                priority=sample_report.priority or "medium",
                title=f"{type_name} cluster in area",
                description=f"Multiple {type_name.lower()} incidents reported in this area. {len(group_reports)} verified reports require coordinated investigation.",
                location_id=sample_report.village_location_id,
                incident_type_id=tid,
                assigned_to_id=assigned_officer.police_user_id if assigned_officer else None,
                station_id=station_id,
                created_by=creator.police_user_id if creator else None,
                report_count=len(group_reports),
                latitude=sample_report.latitude,
                longitude=sample_report.longitude,
                opened_at=max(r.reported_at for r in group_reports) + timedelta(hours=random.randint(1, 12)),
            )
            db.add(case)
            db.flush()

            # Link reports to case
            for r in group_reports:
                cr = CaseReport(
                    case_id=case.case_id,
                    report_id=r.report_id,
                    added_at=case.opened_at,
                )
                db.add(cr)

            # Notify assigned officer
            if assigned_officer:
                notif = Notification(
                    notification_id=uuid.uuid4(),
                    police_user_id=assigned_officer.police_user_id,
                    title=f"New case assigned: {type_name}",
                    message=f"Case {case.case_number} has been assigned to you. {len(group_reports)} related reports in the area require investigation.",
                    type="assignment",
                    related_entity_type="case",
                    related_entity_id=str(case.case_id),
                    is_read=False,
                    created_at=case.opened_at + timedelta(minutes=random.randint(1, 10)),
                )
                db.add(notif)

            case_num += 1
            cases_created += 1

    logger.info("Created %d cases", cases_created)
    return cases_created


def recompute_hotspots(db):
    """Rebuild hotspot clusters from verified leader-confirmed reports."""
    try:
        from app.core.hotspot_auto import create_hotspots_from_reports

        result = create_hotspots_from_reports(
            db,
            time_window_hours=720,
            min_incidents=3,
            radius_meters=500,
            trust_min=70,
            analyze_all_reports=True,
        )
        db.commit()
        logger.info("Hotspot recompute: %s", result)
        return result
    except Exception:
        logger.exception("Hotspot recompute failed (non-fatal)")
        db.rollback()
        return None


def seed_operational_data(
    db,
    *,
    num_reports: int = NUM_REPORTS,
    num_devices: int | None = None,
    days_back: int = DAYS_BACK,
    min_rejected: int = MIN_REJECTED,
    min_pending: int = MIN_PENDING,
    with_cases: bool = False,
) -> dict:
    """Seed devices and reports with planned trust-score distribution."""
    now = datetime.now(timezone.utc)
    target_rejected, target_pending = resolve_distribution_targets(
        num_reports, min_rejected, min_pending
    )
    target_verified = num_reports - target_rejected - target_pending
    if num_devices is None:
        num_devices = max(3, min(NUM_DEVICES, (num_reports // 3) + 2))

    logger.info(
        "Seeding %d reports (rejected=%d, pending=%d, verified=%d) over %d days, %d devices",
        num_reports,
        target_rejected,
        target_pending,
        target_verified,
        days_back,
        num_devices,
    )

    incident_types = load_incident_types(db)
    if not incident_types:
        raise RuntimeError("No incident types found — seed reference data first")
    it_map = {it.incident_type_id: it.type_name for it in incident_types}
    it_by_name = {it.type_name: it for it in incident_types}

    villages, hotspot_villages, hotspot_ids, today_target_villages = build_village_pools(db)

    from app.models.police_user import PoliceUser
    from app.models.station import Station

    police_users = db.query(PoliceUser).filter(PoliceUser.is_active == True).all()
    local_leaders = db.query(LocalLeader).filter(LocalLeader.is_active == True).all()
    stations = db.query(Station).all()
    leader_village_since = build_leader_village_since_map(db, local_leaders)

    max_num = db.execute(
        text(
            "SELECT MAX(CAST(SUBSTRING(report_number FROM 10) AS INTEGER)) "
            "FROM reports WHERE report_number LIKE 'RPT-2026-%'"
        )
    ).scalar() or 0
    report_counter = int(max_num) + 1

    devices = create_devices(db, num_devices)
    db.flush()

    weighted_types = []
    for tname, weight in INCIDENT_WEIGHTS.items():
        if tname in it_by_name:
            weighted_types.extend([it_by_name[tname]] * weight)

    score_plan = build_trust_score_plan(num_reports, min_rejected, min_pending)
    reports_by_village = {}
    created_count = 0
    verified_count = 0
    flagged_count = 0
    rejected_count = 0

    for bucket, _target_score in score_plan:
        device = random.choice(devices)
        inc_type = random.choice(weighted_types)
        # 20 reports generated for today in Muhoza/Cyuve, rest over the specified period
        is_today_report = i < 20
        if is_today_report:
            village = random.choice(today_target_villages)
        else:
            village = pick_village(villages, hotspot_villages, hotspot_ids)
            
        sector_id, _cell_id = get_sector_cell_for_village(db, village)

        lat = jitter_coord(village.centroid_lat, spread=0.002)
        lng = jitter_coord(village.centroid_long, spread=0.002)

        leader_since = leader_village_since.get(int(village.location_id))
        
        if is_today_report:
            reported_at = now - timedelta(hours=random.uniform(0, 24))
        else:
            reported_at = report_time_for_bucket(now, days_back, bucket, leader_since)
        description = description_for_bucket(bucket, inc_type.type_name)

        tags_pool = CONTEXT_TAGS_POOL.get(inc_type.type_name, [[]])
        tags = random.choice(tags_pool)

        report = Report(
            report_id=uuid.uuid4(),
            report_number=f"RPT-2026-{report_counter:04d}",
            device_id=device.device_id,
            incident_type_id=inc_type.incident_type_id,
            description=description,
            latitude=Decimal(str(round(lat, 7))),
            longitude=Decimal(str(round(lng, 7))),
            gps_accuracy=Decimal(str(round(random.uniform(3, 50), 2))),
            motion_level=random.choices(MOTION_LEVELS, weights=MOTION_WEIGHTS, k=1)[0],
            movement_speed=Decimal(str(round(random.uniform(0, 2.5), 2))) if random.random() < 0.3 else None,
            was_stationary=random.random() < 0.6,
            location_id=sector_id,
            village_location_id=village.location_id,
            handling_station_id=random.choice(stations).station_id if stations else None,
            reported_at=reported_at,
            priority="medium",
            rule_status="pending",
            status="pending",
            verification_status="pending",
            app_version=random.choice(APP_VERSIONS),
            network_type=random.choices(NETWORK_TYPES, weights=NETWORK_WEIGHTS, k=1)[0],
            battery_level=Decimal(str(round(random.uniform(10, 100), 1))),
            context_tags=tags,
            ai_ready=False,
            feature_vector={
                "description_length": len(description),
                "word_count": len(description.split()),
                "gps_accuracy": float(round(random.uniform(3, 50), 2)),
            },
        )

        db.add(report)
        db.flush()

        try:
            with db.begin_nested():
                run_seed_verification_pipeline(db, report, device, inc_type)
                apply_seed_leader_follow_up(report, reported_at)
        except Exception:
            logger.exception(
                "Verification pipeline failed for %s — rolling back report AI state",
                report.report_number,
            )
            raise

        if report.status == "verified":
            verified_count += 1
        elif report.status == "pending" or report.verification_status == "under_review":
            flagged_count += 1
        else:
            rejected_count += 1

        device.total_reports += 1
        if report.status == "verified":
            device.trusted_reports += 1
        elif report.is_flagged:
            device.flagged_reports += 1
        device.last_seen_at = reported_at

        if report.status == "pending" or report.priority in ("high", "urgent"):
            create_notifications(
                db, report, police_users, local_leaders, incident_type_name=inc_type.type_name
            )

        reports_by_village.setdefault(village.location_id, []).append(report)
        report_counter += 1
        created_count += 1

        if created_count % BATCH_SIZE == 0:
            db.commit()
            logger.info(
                "  ... %d/%d reports verified (verified=%d pending=%d rejected=%d)",
                created_count,
                num_reports,
                verified_count,
                flagged_count,
                rejected_count,
            )

    db.flush()
    logger.info(
        "Reports created: %d (verified=%d, pending=%d, rejected=%d)",
        created_count,
        verified_count,
        flagged_count,
        rejected_count,
    )

    cases_created = 0
    if with_cases:
        try:
            cases_created = create_cases_from_clusters(
                db, reports_by_village, it_map, police_users, stations
            )
        except Exception:
            logger.exception("Case creation failed (reports will still be saved)")
    else:
        logger.info("Skipping case creation (reports-only seed)")

    db.commit()

    return {
        "reports": created_count,
        "devices": num_devices,
        "cases": cases_created,
        "verified": verified_count,
        "pending": flagged_count,
        "rejected": rejected_count,
    }


def configure_seed_db_session(db) -> None:
    """Longer timeouts for bulk seed + verification pipeline on remote Postgres."""
    try:
        db.execute(text("SET statement_timeout = '600000'"))  # 10 minutes per statement
        db.execute(text("SET idle_in_transaction_session_timeout = '900000'"))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Could not tune session timeouts: %s", exc)


def refresh_db_session(db):
    """Return a fresh session after clear/long idle (avoids 'server closed connection')."""
    try:
        db.execute(text("SELECT 1"))
        db.commit()
        return db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        logger.info("Refreshing database session after connection drop")
        new_db = SessionLocal()
        configure_seed_db_session(new_db)
        return new_db


def main():
    parser = argparse.ArgumentParser(description="Clear operational data and seed incident reports.")
    parser.add_argument("--no-clear", action="store_true", help="Skip clearing operational tables")
    parser.add_argument("--dry-run-clear", action="store_true", help="Print row counts only")
    parser.add_argument("--count", type=int, default=NUM_REPORTS, help="Number of reports to seed")
    parser.add_argument("--preserve", type=int, default=2, help="Reports to keep (prefer tomorrow's date)")
    parser.add_argument("--with-cases", action="store_true", help="Also create cases from report clusters")
    parser.add_argument("--with-hotspots", action="store_true", help="Also recompute hotspot clusters after seed")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)
    db = SessionLocal()
    configure_seed_db_session(db)

    try:
        from app.database import engine
        from app.core.workflow_schema_extensions import apply_workflow_schema_ddl

        apply_workflow_schema_ddl(engine)
    except Exception as exc:
        logger.warning("Workflow schema DDL skipped: %s", exc)

    try:
        logger.info("=== Operational data reset & seed ===")

        if not args.no_clear:
            preserve_ids = find_preserved_report_ids(db, preserve_count=args.preserve)
            if preserve_ids:
                logger.info("Preserving %d report(s): %s", len(preserve_ids), preserve_ids)
            cleared = clear_operational_data(
                db,
                preserve_report_ids=preserve_ids,
                dry_run=args.dry_run_clear,
            )
            if args.dry_run_clear:
                logger.info("Dry-run clear counts: %s", cleared)
                return
            logger.info("Cleared operational tables: %s", cleared)
            db = refresh_db_session(db)

        result = seed_operational_data(
            db,
            num_reports=args.count,
            with_cases=args.with_cases,
        )
        if args.with_hotspots:
            recompute_hotspots(db)
        else:
            logger.info("Skipping hotspot recompute (reports-only seed)")

        logger.info("=== Complete ===")
        logger.info("  Reports: %d", result["reports"])
        logger.info("  Devices: %d", result["devices"])
        logger.info("  Cases: %d", result["cases"])
        logger.info(
            "  Verified: %d, Pending: %d, Rejected: %d",
            result["verified"],
            result["pending"],
            result["rejected"],
        )

    except Exception:
        db.rollback()
        logger.exception("Simulation failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
