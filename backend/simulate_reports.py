"""
Simulate ~1000 realistic incident reports across Musanze district.

Usage (inside container):
    python simulate_reports.py

- Creates new devices with varied trust profiles
- Distributes reports across all villages with realistic geographic jitter
- Uses the real verification pipeline (AI auto-verification)
- Triggers notifications for flagged/pending reports
- Creates cases for high-severity clusters
- No evidence files — reports rely on description quality for ML scoring
"""

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
from app.models.ml_prediction import MLPrediction
from app.models.notification import Notification
from app.models.case import Case, CaseReport
from app.models.local_leader import LocalLeader

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("simulate")

# ─── Configuration ──────────────────────────────────────────────────────────────

NUM_REPORTS = 1000
NUM_DEVICES = 180          # ~5-6 reports per device on average
DAYS_BACK = 45             # Reports spread over 45 days
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
        "Someone broke into a shop near the market and stole electronic items around midnight. Neighbors heard glass breaking.",
        "A motorcycle was stolen from outside a restaurant while the owner was eating lunch. Security camera may have captured it.",
        "Multiple phones were reported missing from a charging station near the bus park. This is the third time this month.",
        "Agricultural tools taken from a storage shed overnight in the village. The lock was cut with bolt cutters.",
        "A bag was snatched from a woman walking home from the market in the late afternoon. The thief fled on foot towards the hill.",
        "Shopkeeper reported cash stolen from the register during busy hours. Suspects may have used distraction technique.",
        "Bicycle left outside a church during Sunday service was found missing afterwards. Owner had tied it to a fence post.",
        "Small electronics shop was burglarized over the weekend. Glass door was smashed and several items were taken.",
        "Two goats disappeared from a pen near the road overnight. Tracks suggest they were led away, not wandering.",
        "Items were taken from an unlocked vehicle parked at the trading center during market day.",
        "Construction materials were stolen from a building site. Workers noticed missing cement bags in the morning.",
        "Household items stolen from a compound while family attended a community meeting in the evening.",
        "Money was taken from a mobile money agent's booth during a brief moment when the agent stepped away.",
        "Crops were stolen from a field near the main road. Maize and beans harvested by unknown individuals at night.",
        "Water jerrycans and farming equipment stolen from a community water point storage area.",
    ],
    "Assault": [
        "A fight broke out between two groups of young men near the bar. One person was injured with a broken bottle.",
        "A man was attacked while walking home late at night on the path between the two villages. He sustained head injuries.",
        "Dispute between neighbors escalated to physical violence over a land boundary issue. Several witnesses present.",
        "A boda-boda driver was beaten by a passenger who refused to pay the fare. Other drivers intervened.",
        "Physical altercation at a football field after a match dispute. Three people sustained minor injuries.",
        "A vendor was assaulted at the market by someone he accused of stealing from his stall. Both parties needed medical attention.",
        "Group of individuals attacked a man walking near the school compound after dark. Motive unclear.",
        "Bar fight resulted in injuries to three people. One person was taken to Musanze hospital by neighbors.",
        "Road rage incident where a truck driver attacked a cyclist who was blocking the road near the junction.",
        "Person was pushed and hit during an argument at a neighborhood gathering. Witnesses say alcohol was involved.",
    ],
    "Suspicious Activity": [
        "Unknown individuals were seen photographing houses and noting entry points in a residential area during early morning hours.",
        "A vehicle with no license plates was parked near the school for over three hours. No one was seen entering or leaving.",
        "Several strangers were observed walking around the village at unusual hours asking questions about who lives where.",
        "Someone was seen testing door handles of parked cars in the trading center parking area around 2am.",
        "Unfamiliar person was loitering near the ATM for a long time without using it, appearing to watch people enter PINs.",
        "A group was spotted unloading unmarked packages from a vehicle at night near the abandoned warehouse.",
        "Someone keeps returning to the same spot near the bank every day without apparent reason, watching customers.",
        "Unusual vehicle movements late at night on the road leading to the village. Multiple trips back and forth.",
        "Person was seen climbing over a compound wall and then leaving quickly when spotted by a neighbor.",
        "Unfamiliar individuals asking shop owners about their closing times and security arrangements.",
        "A drone was spotted flying over residential areas at night. No one in the community owns one.",
        "Repeated knocking on doors of houses where residents are known to be away during the day.",
        "Unknown person was watching children at the school playground from across the road for extended periods.",
        "Vehicle was seen slowly driving through residential streets multiple times over several days, seemingly surveying.",
    ],
    "Domestic Violence": [
        "Neighbors heard screaming and sounds of fighting from a house. A woman was seen leaving with visible injuries.",
        "A woman sought help at a local leader's home saying her husband had beaten her. She had bruises on her arms.",
        "Children reported that their father regularly beats their mother when he comes home drunk in the evenings.",
        "Community health worker reported a case where a woman showed signs of repeated physical abuse during a home visit.",
        "A woman was locked out of her home by her partner after an argument. She was found sleeping outside by neighbors.",
        "Elderly parent was neglected and physically mistreated by adult children living in the same household.",
        "Neighbor heard a child crying for help. Investigation revealed the child was being physically punished severely.",
        "Woman came to the village office with injuries saying her partner attacked her when she refused to hand over money.",
    ],
    "Drug Activity": [
        "Young people are regularly gathering behind the abandoned building near the market. Strong smell of cannabis in the area.",
        "Suspected drug dealing observed near the school entrance during morning hours. Multiple exchanges of small packages.",
        "Unknown substances found discarded in plastic bags near the community water source. Appears to be drug paraphernalia.",
        "Residents report increased drug use among youth in the area. Needles found near the football field.",
        "A house in the neighborhood is suspected of being used for drug distribution. Frequent visitors at unusual hours.",
        "Cannabis plants found growing in a hidden garden plot near the river. Estimated 20-30 plants.",
        "Young men seen exchanging small packages for money near the bus stop on multiple occasions this week.",
        "Strong chemical smell coming from a residence at night. Neighbors suspect production of illegal substances.",
    ],
    "Vandalism": [
        "Several windows of the local school were broken overnight. Glass and stones found inside classrooms.",
        "Street lights along the main road were deliberately damaged. Three poles had their wiring cut.",
        "A community notice board was torn down and vandalized with graffiti during the night.",
        "Water pipes leading to the public tap were cut, causing flooding and water shortage for the village.",
        "Walls of the health center were spray-painted with offensive messages over the weekend.",
        "Someone deliberately damaged crops in a field near the road, cutting down banana plants with a machete.",
        "Public toilet facility had its door broken and fixtures damaged. Unusable until repaired.",
        "Church windows were smashed and chairs broken inside. Entry through a side door that was forced open.",
        "Road signs were bent and knocked over along the stretch near the junction. Appears intentional.",
        "Community garden fence was torn down and some plants uprooted during the night.",
    ],
    "Fraud/Scam": [
        "Mobile money agent reported customers being scammed by fake mobile money messages asking them to send confirmation codes.",
        "Someone is impersonating a government official collecting fees for a non-existent program door to door.",
        "Fake agricultural cooperative representatives collected membership fees from farmers and disappeared.",
        "Online marketplace scam where a seller collected payment but never delivered the goods. Multiple victims identified.",
        "A person was tricked into sending money for a fake job opportunity abroad. Communication was via WhatsApp.",
        "Residents warned of phone scam where callers claim to be from the bank and request account details.",
        "Someone sold counterfeit medicine at the local market claiming it was from a hospital pharmacy.",
        "Pyramid scheme operating in the area promising high returns on small investments. Several people lost money.",
        "Forged documents being used to claim ownership of land that belongs to another family.",
    ],
    "Harassment": [
        "A woman reported being followed home from work multiple times by an unknown man on a motorcycle.",
        "Students reported verbal harassment from adults near the school gate during morning drop-off times.",
        "A market vendor is being repeatedly intimidated by competitors trying to force them to leave their selling spot.",
        "Someone is sending threatening messages to a business owner demanding protection payments.",
        "A tenant reported ongoing harassment from their landlord trying to force them to move out before lease ends.",
        "Woman reported catcalling and intimidation while walking on the main road. Multiple incidents over weeks.",
        "Street vendor harassed by group of youth demanding free items. Threats were made when vendor refused.",
        "Repeated threatening phone calls received by a community leader regarding their role in resolving disputes.",
    ],
    "Traffic Incident": [
        "Motorcycle collided with a pedestrian at the intersection near the market. Pedestrian sustained leg injuries.",
        "Vehicle lost control on the wet road and hit a roadside vendor's stand. No serious injuries but property damaged.",
        "A truck was driving at excessive speed through the residential area. Nearly hit children playing near the road.",
        "Hit-and-run incident where a car struck a cyclist and fled the scene. Witnesses noted a partial plate number.",
        "Two boda-bodas collided at the roundabout. One driver was thrown off and needed hospital attention.",
        "Vehicle parked illegally blocking emergency access to the health center. Repeated issue with same vehicle.",
    ],
}

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


def build_village_pools(db):
    """Load all villages with coordinates and build weighted sampling pools."""
    villages = db.query(Location).filter(
        Location.location_type == "village",
        Location.is_active == True,
        Location.centroid_lat.isnot(None),
        Location.centroid_long.isnot(None),
    ).all()

    if not villages:
        raise RuntimeError("No villages with coordinates found in DB")

    # Pick hotspot villages (will get more reports)
    hotspot_villages = random.sample(villages, min(NUM_HOTSPOT_VILLAGES, len(villages)))
    hotspot_ids = {v.location_id for v in hotspot_villages}

    logger.info("Loaded %d villages, %d designated as hotspot villages", len(villages), len(hotspot_ids))
    return villages, hotspot_villages, hotspot_ids


def pick_village(villages, hotspot_villages, hotspot_ids):
    """Weighted village selection — hotspot villages get ~4x more reports."""
    if random.random() < 0.45:  # 45% of reports go to hotspot villages
        return random.choice(hotspot_villages)
    return random.choice(villages)


def get_sector_cell_for_village(db, village):
    """Walk up the location hierarchy to find cell and sector IDs."""
    cell_id = village.parent_location_id
    if cell_id:
        cell = db.query(Location).get(cell_id)
        if cell:
            sector_id = cell.parent_location_id
            return sector_id, cell_id
    return None, None


def create_ml_prediction(db, report, trust_score):
    """Create a realistic ML prediction for a report."""
    if trust_score >= 70:
        label = "likely_real"
        confidence = round(random.uniform(72, 98), 2)
    elif trust_score >= 45:
        label = random.choice(["likely_real", "suspicious"])
        confidence = round(random.uniform(50, 78), 2)
    elif trust_score >= 20:
        label = "suspicious"
        confidence = round(random.uniform(30, 55), 2)
    else:
        label = "fake"
        confidence = round(random.uniform(60, 90), 2)

    pred = MLPrediction(
        prediction_id=uuid.uuid4(),
        report_id=report.report_id,
        trust_score=Decimal(str(trust_score)),
        prediction_label=label,
        model_version="unified_v3.2",
        confidence=Decimal(str(confidence)),
        explanation={
            "description_quality": round(random.uniform(0.4, 0.95), 3),
            "device_credibility": round(random.uniform(0.3, 0.9), 3),
            "location_consistency": round(random.uniform(0.5, 1.0), 3),
            "temporal_pattern": round(random.uniform(0.3, 0.9), 3),
        },
        model_type="unified_aggregation",
        is_final=True,
        processing_time=random.randint(80, 2500),
    )
    db.add(pred)
    return pred


def apply_verification(report, trust_score, device_trust):
    """Apply verification logic matching the real pipeline thresholds."""
    # Combine report trust + device trust for overall score
    combined = trust_score * 0.7 + device_trust * 0.3

    reported_at = report.reported_at

    if combined >= 70:
        # High confidence — auto-verify + leader confirmed
        report.rule_status = "passed"
        report.verification_status = "verified"
        report.status = "verified"
        report.is_flagged = False
        report.ai_verification_reason = "AI auto-verified: high trust score with consistent indicators"
        report.leader_verification_status = "confirmed"
        report.leader_verified_at = reported_at + timedelta(hours=random.randint(1, 24))
        report.leader_verification_note = random.choice([
            "Confirmed by community leader. Incident is known in the area.",
            "Verified through community channels. Details consistent.",
            "Community confirms this incident occurred as described.",
            "Local leader confirmed after speaking with witnesses.",
            None,
        ])
    elif combined >= 45:
        # Medium — some verified, some under review
        if random.random() < 0.65:
            report.rule_status = "passed"
            report.verification_status = "verified"
            report.status = "verified"
            report.is_flagged = False
            report.ai_verification_reason = "AI verified: adequate trust indicators meet threshold"
            # ~70% of medium-verified also get leader confirmation
            if random.random() < 0.7:
                report.leader_verification_status = "confirmed"
                report.leader_verified_at = reported_at + timedelta(hours=random.randint(2, 48))
            else:
                report.leader_verification_status = "pending"
        else:
            report.rule_status = "flagged"
            report.verification_status = "under_review"
            report.status = "pending"
            report.is_flagged = True
            report.flag_reason = "threshold_low_score"
            report.ai_verification_reason = "AI flagged for review: borderline trust score requires human verification"
            report.leader_verification_status = "pending"
    elif combined >= 20:
        # Low confidence — mostly flagged
        if random.random() < 0.15:
            report.rule_status = "passed"
            report.verification_status = "verified"
            report.status = "verified"
            report.ai_verification_reason = "AI verified with caution: marginal indicators but no hard gate violations"
            report.leader_verification_status = "pending"
        else:
            report.rule_status = "flagged"
            report.verification_status = "under_review"
            report.status = "pending"
            report.is_flagged = True
            report.flag_reason = "threshold_low_score"
            report.ai_verification_reason = "AI flagged: low trust indicators require community leader confirmation"
            report.leader_verification_status = "pending"
    else:
        # Very low — rejected
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = "threshold_low_score"
        report.ai_verification_reason = "AI rejected: trust score below minimum threshold"
        report.leader_verification_status = "rejected"
        report.leader_verified_at = reported_at + timedelta(hours=random.randint(1, 12))


def create_notifications(db, report, police_users, local_leaders):
    """Create notifications for flagged/pending reports."""
    if report.status == "pending" or report.verification_status == "under_review":
        # Notify supervisors/officers about reports needing review
        for pu in police_users:
            if pu.role in ("supervisor", "admin"):
                notif = Notification(
                    notification_id=uuid.uuid4(),
                    police_user_id=pu.police_user_id,
                    title=f"Report needs review: {report.incident_type.type_name if report.incident_type else 'Unknown'}",
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
                    title=f"{report.priority.upper()}: {report.incident_type.type_name if report.incident_type else 'Unknown'}",
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


def seed_operational_data(
    db,
    *,
    num_reports: int = 300,
    num_devices: int | None = None,
    days_back: int = DAYS_BACK,
    random_seed: int = 42,
) -> dict:
    """
    Seed devices, reports, ML predictions, notifications, and cases.
    Requires incident types, villages, police users, and stations to already exist.
    """
    random.seed(random_seed)
    num_devices = num_devices or max(50, num_reports // 5)
    now = datetime.now(timezone.utc)
    logger.info(
        "Seeding %d reports (%d devices, %d-day window)",
        num_reports,
        num_devices,
        days_back,
    )

    incident_types = db.query(IncidentType).all()
    if not incident_types:
        raise RuntimeError("No incident types found — seed the database first")
    it_map = {it.incident_type_id: it.type_name for it in incident_types}
    it_by_name = {it.type_name: it for it in incident_types}
    logger.info("Loaded %d incident types", len(incident_types))

    villages, hotspot_villages, hotspot_ids = build_village_pools(db)

    from app.models.police_user import PoliceUser
    from app.models.station import Station
    police_users = db.query(PoliceUser).filter(PoliceUser.is_active == True).all()
    local_leaders = db.query(LocalLeader).all()
    stations = db.query(Station).all()
    logger.info(
        "Police users: %d, Local leaders: %d, Stations: %d",
        len(police_users),
        len(local_leaders),
        len(stations),
    )

    max_num = db.execute(
        text(
            "SELECT MAX(CAST(SUBSTRING(report_number FROM 10) AS INTEGER)) "
            "FROM reports WHERE report_number LIKE 'RPT-2026-%'"
        )
    ).scalar() or 0
    report_counter = max_num + 1

    devices = create_devices(db, num_devices)
    db.flush()

    weighted_types = []
    for tname, weight in INCIDENT_WEIGHTS.items():
        if tname in it_by_name:
            weighted_types.extend([it_by_name[tname]] * weight)

    reports_by_village = {}
    created_count = 0
    verified_count = 0
    flagged_count = 0
    rejected_count = 0

    logger.info("Generating %d reports...", num_reports)

    for i in range(num_reports):
        device = random.choice(devices)
        inc_type = random.choice(weighted_types)
        village = pick_village(villages, hotspot_villages, hotspot_ids)
        sector_id, cell_id = get_sector_cell_for_village(db, village)

        lat = jitter_coord(village.centroid_lat, spread=0.002)
        lng = jitter_coord(village.centroid_long, spread=0.002)
        reported_at = random_report_time(now, days_back)

        type_descs = DESCRIPTIONS.get(inc_type.type_name, ["Incident reported in the area."])
        description = random.choice(type_descs)
        variations = [
            "", " The area was dark at the time.",
            " Happened near the main road.", " Local residents are concerned.",
            " This seems to be a recurring issue.", "",
            " Community members alerted the local leader.",
            " The situation was reported promptly.",
            "", " Weather was clear at the time.",
        ]
        description += random.choice(variations)

        tags_pool = CONTEXT_TAGS_POOL.get(inc_type.type_name, [[]])
        tags = random.choice(tags_pool)

        sev = float(inc_type.severity_weight or 1.0)
        if sev >= 1.6:
            priority = weighted_choice({"high": 40, "urgent": 15, "medium": 35, "low": 10})
        elif sev >= 1.2:
            priority = weighted_choice({"medium": 45, "high": 25, "low": 20, "urgent": 10})
        else:
            priority = weighted_choice({"low": 35, "medium": 45, "high": 15, "urgent": 5})

        device_trust = float(device.device_trust_score or 50)
        base_trust = device_trust * 0.35 + random.uniform(20, 80) * 0.65
        trust_score = max(5, min(98, base_trust + random.gauss(0, 8)))
        trust_score = round(trust_score, 2)

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
            priority=priority,
            app_version=random.choice(APP_VERSIONS),
            network_type=random.choices(NETWORK_TYPES, weights=NETWORK_WEIGHTS, k=1)[0],
            battery_level=Decimal(str(round(random.uniform(10, 100), 1))),
            context_tags=tags,
            ai_ready=True,
            features_extracted=reported_at + timedelta(seconds=random.randint(2, 30)),
            features_extracted_at=reported_at + timedelta(seconds=random.randint(2, 30)),
            feature_vector={
                "description_length": len(description),
                "word_count": len(description.split()),
                "device_trust": device_trust,
                "base_trust": round(base_trust, 2),
                "gps_accuracy": float(round(random.uniform(3, 50), 2)),
            },
        )

        apply_verification(report, trust_score, device_trust)

        if report.status == "verified":
            report.verified_at = reported_at + timedelta(minutes=random.randint(1, 60))
            verified_count += 1
        elif report.status == "pending":
            flagged_count += 1
        else:
            rejected_count += 1

        db.add(report)
        create_ml_prediction(db, report, trust_score)

        device.total_reports += 1
        if report.status == "verified":
            device.trusted_reports += 1
        elif report.is_flagged:
            device.flagged_reports += 1
        device.last_seen_at = reported_at

        if report.status in ("pending",) or report.priority in ("high", "urgent"):
            create_notifications(db, report, police_users, local_leaders)

        vid = village.location_id
        reports_by_village.setdefault(vid, []).append(report)

        report_counter += 1
        created_count += 1

        if created_count % BATCH_SIZE == 0:
            db.flush()
            logger.info("  ... %d/%d reports created", created_count, num_reports)

    db.flush()
    logger.info(
        "Reports created: %d (verified=%d, flagged=%d, rejected=%d)",
        created_count,
        verified_count,
        flagged_count,
        rejected_count,
    )

    cases_created = create_cases_from_clusters(
        db, reports_by_village, it_map, police_users, stations
    )
    db.commit()

    stats = {
        "reports": created_count,
        "devices": num_devices,
        "cases": cases_created,
        "verified": verified_count,
        "flagged": flagged_count,
        "rejected": rejected_count,
    }
    logger.info("Seed complete: %s", stats)
    return stats


def main():
    """Legacy entry point — seeds NUM_REPORTS without clearing existing data."""
    db = SessionLocal()
    try:
        seed_operational_data(
            db,
            num_reports=NUM_REPORTS,
            num_devices=NUM_DEVICES,
            days_back=DAYS_BACK,
        )
    except Exception:
        db.rollback()
        logger.exception("Simulation failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
