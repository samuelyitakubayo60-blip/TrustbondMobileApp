"""
Seed 300+ realistic incident reports into TrustBond database.

Reports span April 27, 2026 → June 14, 2026 with:
  - Realistic Android devices (Samsung, Tecno, Infinix, Itel, Xiaomi, Huawei, Oppo)
  - Trust scores & statuses consistent with verification system rules:
      ≥70 → verified/likely_real, 40-69 → under_review/suspicious, <40 → rejected/fake
  - Leader verification aligned with AI decision
  - Realistic feature_vectors with scorecard, stage scores, NL analysis
  - GPS coordinates jittered around real Musanze village centroids
  - Time-of-day crime distribution (peaks at evening/night)
  - Incident type weighting (theft/suspicious activity more common)

Usage:
    cd backend
    python seed_300_reports.py
    python seed_300_reports.py --count 500
    python seed_300_reports.py --no-clear          # add without clearing existing
"""

import argparse
import hashlib
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import SessionLocal
from app.models.report import Report
from app.models.device import Device
from app.models.location import Location
from app.models.incident_type import IncidentType
from app.models.local_leader import LocalLeader

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("seed300")

# ── Date range ───────────────────────────────────────────────────────────────
START_DATE = datetime(2026, 4, 27, tzinfo=timezone.utc)
END_DATE   = datetime(2026, 6, 14, 23, 59, 59, tzinfo=timezone.utc)

# ── Realistic Android devices ────────────────────────────────────────────────
PHONE_MODELS = [
    # Samsung (most popular in Rwanda)
    {"brand": "Samsung", "model": "SM-A145F",   "name": "Galaxy A14",     "os": "Android 13", "ram": "4GB",  "screen": "6.6"},
    {"brand": "Samsung", "model": "SM-A245F",   "name": "Galaxy A24",     "os": "Android 13", "ram": "4GB",  "screen": "6.5"},
    {"brand": "Samsung", "model": "SM-A346B",   "name": "Galaxy A34 5G",  "os": "Android 13", "ram": "6GB",  "screen": "6.6"},
    {"brand": "Samsung", "model": "SM-A546B",   "name": "Galaxy A54 5G",  "os": "Android 14", "ram": "8GB",  "screen": "6.4"},
    {"brand": "Samsung", "model": "SM-A057F",   "name": "Galaxy A05s",    "os": "Android 13", "ram": "4GB",  "screen": "6.7"},
    {"brand": "Samsung", "model": "SM-A156B",   "name": "Galaxy A15",     "os": "Android 14", "ram": "4GB",  "screen": "6.5"},
    {"brand": "Samsung", "model": "SM-G991B",   "name": "Galaxy S21",     "os": "Android 14", "ram": "8GB",  "screen": "6.2"},
    {"brand": "Samsung", "model": "SM-S911B",   "name": "Galaxy S23",     "os": "Android 14", "ram": "8GB",  "screen": "6.1"},
    # Tecno (very popular in East Africa)
    {"brand": "Tecno",   "model": "KJ7",        "name": "Spark 20",       "os": "Android 14", "ram": "8GB",  "screen": "6.56"},
    {"brand": "Tecno",   "model": "KI5q",       "name": "Spark 10C",      "os": "Android 13", "ram": "4GB",  "screen": "6.6"},
    {"brand": "Tecno",   "model": "KJ5",        "name": "Spark 20C",      "os": "Android 14", "ram": "4GB",  "screen": "6.56"},
    {"brand": "Tecno",   "model": "CK7n",       "name": "Camon 20",       "os": "Android 13", "ram": "8GB",  "screen": "6.67"},
    {"brand": "Tecno",   "model": "CK8n",       "name": "Camon 30",       "os": "Android 14", "ram": "8GB",  "screen": "6.78"},
    {"brand": "Tecno",   "model": "AD8",        "name": "Pop 8",          "os": "Android 14", "ram": "3GB",  "screen": "6.56"},
    {"brand": "Tecno",   "model": "BG7",        "name": "Pova 5",         "os": "Android 13", "ram": "8GB",  "screen": "6.78"},
    # Infinix (popular budget brand)
    {"brand": "Infinix", "model": "X6833B",     "name": "Hot 40i",        "os": "Android 14", "ram": "8GB",  "screen": "6.56"},
    {"brand": "Infinix", "model": "X6711",      "name": "Smart 8",        "os": "Android 13", "ram": "3GB",  "screen": "6.6"},
    {"brand": "Infinix", "model": "X6837",      "name": "Hot 40 Pro",     "os": "Android 14", "ram": "8GB",  "screen": "6.78"},
    {"brand": "Infinix", "model": "X6710",      "name": "Note 30",        "os": "Android 13", "ram": "8GB",  "screen": "6.78"},
    # Itel (entry-level)
    {"brand": "itel",    "model": "A665L",       "name": "A70",            "os": "Android 14", "ram": "4GB",  "screen": "6.6"},
    {"brand": "itel",    "model": "S666LN",      "name": "S24",            "os": "Android 14", "ram": "8GB",  "screen": "6.6"},
    {"brand": "itel",    "model": "P662L",       "name": "P55+",           "os": "Android 13", "ram": "8GB",  "screen": "6.6"},
    # Xiaomi
    {"brand": "Xiaomi",  "model": "23129RAA4G",  "name": "Redmi 13C",     "os": "Android 13", "ram": "4GB",  "screen": "6.74"},
    {"brand": "Xiaomi",  "model": "2312DRA50G",  "name": "Redmi Note 13", "os": "Android 14", "ram": "6GB",  "screen": "6.67"},
    # Huawei
    {"brand": "Huawei",  "model": "MGA-LX9",     "name": "Nova Y91",      "os": "EMUI 13",   "ram": "8GB",  "screen": "6.95"},
    {"brand": "Huawei",  "model": "STG-LX1",     "name": "Nova Y61",      "os": "EMUI 12",   "ram": "4GB",  "screen": "6.52"},
    # Oppo
    {"brand": "OPPO",    "model": "CPH2565",     "name": "A18",           "os": "Android 14", "ram": "4GB",  "screen": "6.56"},
    {"brand": "OPPO",    "model": "CPH2581",     "name": "A38",           "os": "Android 13", "ram": "4GB",  "screen": "6.56"},
]

# Brand distribution matching East African market share
BRAND_WEIGHTS = {
    "Samsung": 30, "Tecno": 28, "Infinix": 15, "itel": 10,
    "Xiaomi": 8, "Huawei": 5, "OPPO": 4,
}

APP_VERSIONS = ["1.2.4", "1.2.4", "1.2.3", "1.2.3", "1.2.2", "1.2.1"]
NETWORK_TYPES = ["4g", "3g", "wifi", "2g"]
NETWORK_WEIGHTS = [40, 30, 20, 10]
MOTION_LEVELS = ["low", "medium", "high"]

# Hour-of-day crime distribution (evening/night peaks)
HOUR_WEIGHTS = [
    3, 2, 2, 1, 1, 2, 5, 8, 6, 5, 4, 5,
    6, 5, 5, 6, 7, 9, 12, 14, 15, 12, 8, 5,
]

# Incident type weights (frequency)
INCIDENT_WEIGHTS = {
    "Theft": 24, "Suspicious Activity": 18, "Assault": 12,
    "Vandalism": 10, "Fraud/Scam": 9, "Domestic Violence": 8,
    "Harassment": 8, "Drug Activity": 7, "Traffic Incident": 4,
}

# ── Realistic descriptions per type ──────────────────────────────────────────

GOOD_DESCRIPTIONS = {
    "Theft": [
        "At approximately 11:45 PM last night, three unidentified men forced their way into the electronics shop near the main market by shattering the front glass window with a heavy stone. They made off with several smartphones, two laptops, and the cash register containing roughly 50,000 RWF. Neighbors heard the glass breaking and saw them fleeing towards the bus park.",
        "A red Bajaj Boxer motorcycle (Plate No. RE 342 A) was stolen from outside the restaurant between 1:00 PM and 1:30 PM. The owner had locked the steering, but witnesses saw two men load the bike into a white pickup truck before speeding off towards the highway.",
        "Over the past three days, systematic theft of copper wire from electrical poles along the secondary road. Thieves operate between 2:00 AM and 4:00 AM using professional climbing gear, leaving the sector without power each morning.",
        "Thieves cut through the chain-link fence of the community agricultural storage shed during a heavy rainstorm last night, taking 15 bags of fertilizer, 5 hoes, and the water pump. Tire tracks indicate a medium-sized truck was used.",
        "While walking from the market near the hospital junction at 5:30 PM, a woman had her purse snatched by two young men on a motorcycle without plates. The purse contained her ID card, mobile phone, and weekly business earnings of approximately 35,000 RWF.",
        "Between 9 PM and midnight, someone broke the padlock on the village cooperative storage room and stole approximately 200 kg of harvested beans, 3 watering cans, and a coil of irrigation pipe. Fresh footprints leading towards the valley were found in the morning.",
        "A trader at the Musanze central market noticed 8 bundles of dried fish missing from her stall after a group of young men caused a commotion near the entrance around 2 PM. Security camera footage from the adjacent pharmacy may have captured the theft.",
        "Two solar panels from the community health post were removed overnight. The mounting brackets were cut with a hacksaw. This is the third time solar equipment has been stolen from this area in two months.",
    ],
    "Assault": [
        "A severe physical altercation occurred outside the local bar around 9:00 PM after a dispute over an unpaid debt. A man in his 30s was attacked by two others using broken bottles, resulting in deep lacerations to his arm and face. Bystanders intervened, and the victim was taken to the clinic.",
        "A boda-boda driver was beaten by a male passenger who refused to pay the agreed 1,000 RWF fare. The passenger pulled the driver off the bike and punched him repeatedly before fleeing into the neighborhood. Other drivers tried to chase him without success.",
        "During a community football match, an argument over a referee's decision escalated into a brawl involving players and spectators. Wooden sticks and rocks were thrown, causing at least four head and limb injuries. The crowd dispersed before authorities arrived.",
        "A shop owner on the main road was attacked by two men demanding repayment of a disputed loan. They struck him with a metal rod, breaking his left arm. The attackers fled on foot towards the forest path behind the trading center.",
        "An elderly farmer returning from the evening market was assaulted by three unknown men near the bridge at approximately 7:30 PM. They took his bag containing 12,000 RWF and a torch. He sustained bruises to his ribs and forehead.",
    ],
    "Suspicious Activity": [
        "For three days, a dark blue SUV with tinted windows has been parked near the primary school during drop-off and pick-up times. The occupants never exit but were seen photographing children leaving the compound. They drive away if approached.",
        "Four unfamiliar men carrying heavy backpacks have been moving through the forest path behind the village late at night. They avoid flashlights and main roads. This path is not normally used after dark for legitimate travel.",
        "Several shop owners reported a well-dressed man asking specific questions about security camera coverage, cash transport times, and police patrol schedules. He claims to be doing research but refuses to show identification or affiliation.",
        "Neighbors noticed a rented room in the trading center being used for brief late-night meetings. Groups of 3-4 men arrive on motorbikes around 11 PM, stay for 20 minutes, and leave with small packages. The tenant is not a known local resident.",
        "Two men in military-style clothing were seen measuring distances along the perimeter wall of the district fuel depot early this morning. When a guard approached them, they said they were surveyors but had no equipment or documentation.",
    ],
    "Domestic Violence": [
        "Frequent screaming from the house at the end of the street for three nights. This morning, the wife was seen at the communal water tap with a swollen eye and bruised arms. The children are crying continuously, and the husband was heard threatening further violence.",
        "An elderly woman living with her adult son is being denied food and subjected to verbal and physical abuse to force her to hand over her pension money. Neighbors hear the son shouting and throwing objects. The mother appears malnourished and afraid.",
        "A young mother with two children was seen fleeing her home barefoot last night. Neighbors say her husband was drunk and threatening to burn her belongings. He has been arrested before for a similar incident but was released after paying a fine.",
    ],
    "Drug Activity": [
        "A drug distribution ring operates out of the abandoned structure behind the old market. Every evening between 6-10 PM, dozens of youths arrive, exchange money for small packages, and leave. A strong smell of cannabis is persistent in the area.",
        "Several discarded syringes and small plastic baggies were found around the playground near the community center. Last night, a group of teenagers was seen congregating there, playing loud music and passing around substances.",
        "A new kiosk near the secondary school has been selling energy drinks but also appears to be distributing small sachets of white powder to older youth. Three parents reported their children coming home in an altered state after visiting the kiosk.",
    ],
    "Vandalism": [
        "Vandals targeted the newly constructed community health center over the weekend. They spray-painted offensive symbols on the entrance, smashed five waiting-area windows, and broke the external water pipes, causing flooding and delaying medical services.",
        "Public solar-powered street lights along the main pathway were intentionally destroyed last night. Perpetrators climbed the poles to smash solar panels and cut wiring, leaving the neighborhood in darkness and increasing night-crime risk.",
        "The boundary wall of the primary school was partially demolished overnight using what appear to be sledgehammers. Graffiti threatening the headmaster was painted on the remaining sections. The school gate lock was also broken.",
    ],
    "Fraud/Scam": [
        "An organized scam targets elderly residents. Two individuals claiming to be government agricultural officers go door-to-door requiring a 'mandatory registration fee' of 5,000 RWF for subsidized fertilizer. They issue fake receipts with forged stamps.",
        "A fake mobile money agent near the bus park tricks people into initiating transfers, claiming the network is down. He takes cash, pretends to process it, then sends fake SMS confirmations from a regular phone number. Several travelers have lost money.",
        "A man posing as a water utility inspector is collecting 'reconnection fees' of 3,000 RWF from residents whose water supply was interrupted. He wears a uniform and carries a clipboard, but the water authority confirmed no inspectors were deployed.",
    ],
    "Harassment": [
        "A young woman is being stalked by an older man who waits outside her workplace every evening. He follows her to the bus stop with threatening comments about knowing where she lives. Despite warnings from coworkers, he has escalated to anonymous threatening texts.",
        "Market vendors face intimidation from a group demanding weekly 'protection fees' of 2,000 RWF per stall. If a vendor refuses, the group surrounds their stall, harasses customers, and threatens to destroy merchandise overnight.",
        "A schoolteacher reports that a parent has been sending her threatening voice messages on WhatsApp after she disciplined the parent's child for fighting. The messages include threats of physical harm and mention knowing her home address.",
    ],
    "Traffic Incident": [
        "A severe hit-and-run at the main intersection near the hospital. A speeding white Toyota Corolla ignored the stop sign and struck a pedestrian, throwing them several meters. The driver accelerated away. The vehicle had right front headlight damage, plate ending in '45 B'.",
        "A fully loaded cargo truck lost its brakes coming down the hill towards the trading center and crashed into three parked motorcycles and a fruit stand. The driver survived but two boda-boda riders were taken to hospital. Diesel is leaking on the road.",
    ],
}

MEDIUM_DESCRIPTIONS = {
    "Theft": [
        "Someone stole from the shop near the market last night. Several items were taken. The owner reported it this morning.",
        "My bicycle was taken from outside the church during the Sunday service. It was locked with a chain but the chain was cut.",
        "Tools are missing from the construction site. Workers noticed when they arrived at 6 AM. No fence was broken.",
        "A phone was snatched from a woman near the bus stop around 4 PM yesterday. She could not see the face clearly.",
    ],
    "Assault": [
        "A fight broke out near the bar last night. One person was hurt and went to the health center.",
        "Two men argued over money and one was hit with a stick. He has injuries on his arm.",
        "Someone was beaten near the market. People called for help. The attacker ran away.",
    ],
    "Suspicious Activity": [
        "Strange car has been parked near the school for two days. Nobody knows who owns it.",
        "People moving around at night near the storage area. Could not see them clearly.",
        "Someone keeps asking about bank delivery times at the trading center. Looks suspicious.",
    ],
    "Domestic Violence": [
        "Shouting and crying heard from the house down the road most evenings. Neighbors are worried.",
        "A woman came to the health center with bruises. She said she fell but the nurse is not convinced.",
    ],
    "Drug Activity": [
        "Young people gathering behind the market every evening. Something is being exchanged.",
        "Smell of marijuana near the abandoned building most nights. Groups come and go.",
    ],
    "Vandalism": [
        "Street lights along the path were broken. Happened sometime last night.",
        "Someone damaged the water tank. It is leaking now. May have been intentional.",
    ],
    "Fraud/Scam": [
        "A man collected money from neighbors claiming to be from the cooperative. Nobody authorized him.",
        "Fake mobile money messages being sent. Two people already lost money.",
    ],
    "Harassment": [
        "A vendor is being threatened by a group demanding money every week at the market.",
        "A woman says someone follows her from work regularly. She is scared.",
    ],
    "Traffic Incident": [
        "A motorbike hit a pedestrian near the junction. The rider did not stop. Pedestrian was taken to hospital.",
    ],
}

WEAK_DESCRIPTIONS = [
    "something happened", "bad thing", "help", "problem", "incident here",
    "need police", "theft maybe", "saw something", "not sure what", "urgent",
    "bad people", "trouble", "call someone", "happened yesterday", "weird stuff",
    "idk what happened", "come quick", "there was an issue near us",
]

CONTEXT_TAGS = {
    "Theft": [["Night-time"], ["Near market"], ["Forced entry"], ["Repeated offender area"], []],
    "Assault": [["Weapons involved"], ["Night-time"], ["Alcohol-related"], ["Group violence"], []],
    "Suspicious Activity": [["Night-time"], ["Near school"], ["Unknown individuals"], ["Repeated sightings"], []],
    "Domestic Violence": [["Repeat incident"], ["Children present"], ["Alcohol-related"], []],
    "Drug Activity": [["Near school"], ["Youth involved"], ["Night-time"], ["Recurring location"], []],
    "Vandalism": [["Night-time"], ["Public property"], ["Repeated damage"], []],
    "Fraud/Scam": [["Phone scam"], ["Door-to-door"], ["Multiple victims"], []],
    "Harassment": [["Repeated incidents"], ["Workplace"], ["Public space"], []],
    "Traffic Incident": [["Speeding"], ["Hit and run"], ["Pedestrian involved"], []],
}

LEADER_CONFIRM_NOTES = [
    "Confirmed by community leader. Incident is known in the area.",
    "Verified through community channels. Details match local accounts.",
    "Community confirms this incident occurred as described.",
    "Neighbors and local residents corroborate the reported events.",
    "Village meeting discussed this incident. Report is accurate.",
    "Multiple witnesses spoke to the leader about this. Confirmed.",
    "Leader personally visited the scene and confirms the report.",
]

LEADER_REJECT_NOTES = [
    "No evidence of this incident in the community. Could not verify.",
    "Details do not match what residents reported. Possibly exaggerated.",
    "Community members dispute the account given in this report.",
]


# ── Helper functions ─────────────────────────────────────────────────────────

def pick_hour():
    return random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]


def random_datetime_in_range(start: datetime, end: datetime) -> datetime:
    """Random datetime between start and end, with crime hour-of-day bias."""
    span = (end - start).total_seconds()
    offset = random.uniform(0, span)
    dt = start + timedelta(seconds=offset)
    # Apply hour-of-day bias
    hour = pick_hour()
    return dt.replace(hour=hour, minute=random.randint(0, 59),
                      second=random.randint(0, 59),
                      microsecond=random.randint(0, 999999))


def jitter(coord, spread=0.002):
    return float(coord) + random.gauss(0, spread)


def make_device_hash(brand, model, idx):
    raw = f"{brand}-{model}-{uuid.uuid4().hex[:12]}-{idx}"
    return hashlib.sha256(raw.encode()).hexdigest()


def build_ai_reason(score, band, inc_type, desc_len, has_evidence=False):
    """Build a realistic ai_verification_reason string."""
    if band == "verified":
        base = (
            f"AI credibility scoring completed. Trust score: {score:.1f}/100 "
            f"(threshold: ≥70 for auto-verification). "
            f"Incident type: {inc_type}. "
            f"Description quality is sufficient ({desc_len} characters, "
            f"includes specific details and context). "
        )
        if has_evidence:
            base += "Evidence files provided and analyzed. "
        base += "Report auto-verified by AI pipeline."
        return base
    elif band == "pending":
        return (
            f"AI credibility scoring completed. Trust score: {score:.1f}/100 "
            f"(below auto-verification threshold of 70, above rejection at 40). "
            f"Incident type: {inc_type}. "
            f"Report placed under review pending community leader confirmation. "
            f"Description analysis indicates moderate quality."
        )
    else:  # rejected
        return (
            f"AI credibility scoring completed. Trust score: {score:.1f}/100 "
            f"(below rejection threshold of 40). "
            f"Incident type: {inc_type}. "
            f"Description quality is insufficient — too vague or too short "
            f"({desc_len} characters). "
            f"Report rejected by automated screening."
        )


def build_scorecard(score, band, desc_quality, nl_score, semantic_score):
    """Build a realistic threshold_scorecard dict."""
    return {
        "total_score": round(score, 2),
        "threshold_band": {
            "verified": "confirmed_candidate",
            "pending": "under_review",
            "rejected": "low_confidence",
        }[band],
        "hard_gates": [],
        "breakdown": {
            "description_quality": round(desc_quality, 2),
            "nl_overall": round(nl_score, 2),
            "semantic_similarity": round(semantic_score, 2),
            "location_consistency": round(random.uniform(0.7, 1.0), 2),
            "device_trust_factor": round(random.uniform(0.4, 0.9), 2),
        },
        "flags_metadata": [],
    }


def build_feature_vector(score, band, desc, desc_quality, nl_score, semantic_score):
    """Build a realistic feature_vector JSONB."""
    scorecard = build_scorecard(score, band, desc_quality, nl_score, semantic_score)
    return {
        "description_length": len(desc),
        "word_count": len(desc.split()),
        "gps_accuracy": round(random.uniform(3, 40), 2),
        "threshold_scorecard": scorecard,
        "stage_5_trust_score": {
            "trust_score": round(score, 2),
            "label": {"verified": "likely_real", "pending": "suspicious", "rejected": "fake"}[band],
        },
        "text_only_nl": {
            "overall_score": round(nl_score, 2),
            "confidence": round(random.uniform(0.5, 0.95), 2),
            "semantic_similarity": round(semantic_score, 2),
            "description_quality": round(desc_quality, 2),
        },
        "verification_path": "citizen_submission",
    }


# ── Main seeding logic ───────────────────────────────────────────────────────

def load_reference_data(db):
    """Load incident types, villages, stations, leaders from DB."""
    # Incident types
    rows = db.execute(text(
        "SELECT incident_type_id, type_name FROM incident_types WHERE is_active IS NOT FALSE"
    )).fetchall()
    inc_types = {r[1]: int(r[0]) for r in rows}
    log.info("Loaded %d incident types: %s", len(inc_types), list(inc_types.keys()))

    # Villages with coordinates (Musanze district)
    vrows = db.execute(text(
        "SELECT location_id, parent_location_id, centroid_lat, centroid_long "
        "FROM locations WHERE location_type = 'village' AND is_active IS NOT FALSE "
        "AND centroid_lat IS NOT NULL AND centroid_long IS NOT NULL"
    )).fetchall()
    villages = [
        {"id": int(r[0]), "parent_id": r[1],
         "lat": float(r[2]), "lng": float(r[3])}
        for r in vrows
    ]
    log.info("Loaded %d villages with coordinates", len(villages))

    # Stations
    srows = db.execute(text(
        "SELECT station_id FROM stations WHERE is_active IS NOT FALSE"
    )).fetchall()
    station_ids = [int(r[0]) for r in srows]
    log.info("Loaded %d stations", len(station_ids))

    # Leaders for confirmed/rejected decisions
    lrows = db.execute(text(
        "SELECT local_leader_id FROM local_leaders WHERE is_active IS NOT FALSE"
    )).fetchall()
    leader_ids = [int(r[0]) for r in lrows]
    log.info("Loaded %d active leaders", len(leader_ids))

    # Sector lookup for villages
    sector_map = {}
    for v in villages:
        cell_id = v["parent_id"]
        if cell_id:
            srow = db.execute(text(
                "SELECT parent_location_id FROM locations WHERE location_id = :cid"
            ), {"cid": int(cell_id)}).first()
            if srow:
                sector_map[v["id"]] = int(srow[0])

    return inc_types, villages, station_ids, leader_ids, sector_map


def create_realistic_devices(db, count=75):
    """Create devices that look like real Android phones in Rwanda."""
    devices = []
    # Build weighted model pool
    model_pool = []
    for phone in PHONE_MODELS:
        w = BRAND_WEIGHTS.get(phone["brand"], 5)
        model_pool.extend([phone] * w)

    for i in range(count):
        phone = random.choice(model_pool)
        did = uuid.uuid4()
        dhash = make_device_hash(phone["brand"], phone["model"], i)

        # Trust profile distribution
        profile = random.choices(
            ["high", "medium", "low", "new"],
            weights=[30, 35, 10, 25], k=1
        )[0]
        if profile == "high":
            trust = round(random.uniform(65, 92), 2)
            total_r = random.randint(5, 30)
            trusted_r = int(total_r * random.uniform(0.7, 0.95))
        elif profile == "medium":
            trust = round(random.uniform(40, 65), 2)
            total_r = random.randint(2, 15)
            trusted_r = int(total_r * random.uniform(0.45, 0.75))
        elif profile == "low":
            trust = round(random.uniform(15, 40), 2)
            total_r = random.randint(1, 6)
            trusted_r = int(total_r * random.uniform(0.1, 0.35))
        else:
            trust = 50.0
            total_r = 0
            trusted_r = 0

        first_seen = START_DATE - timedelta(days=random.randint(1, 120))

        device = Device(
            device_id=did,
            device_hash=dhash,
            first_seen_at=first_seen,
            last_seen_at=first_seen + timedelta(days=random.randint(0, 60)),
            total_reports=total_r,
            trusted_reports=trusted_r,
            flagged_reports=random.randint(0, max(0, total_r - trusted_r)),
            spam_flags=0,
            device_trust_score=Decimal(str(trust)),
            is_blacklisted=False,
            is_banned=False,
            metadata_json={
                "brand": phone["brand"],
                "model": phone["model"],
                "device_name": phone["name"],
                "os_version": phone["os"],
                "ram": phone["ram"],
                "screen_size": phone["screen"],
                "sdk_version": random.choice([33, 34]),
                "locale": random.choice(["rw_RW", "en_RW", "fr_RW"]),
                "timezone": "Africa/Kigali",
            },
        )
        db.add(device)
        devices.append(device)

    db.flush()
    log.info("Created %d realistic devices", len(devices))
    return devices


def seed_reports(db, *, count=300, no_clear=False):
    """Main seeding function: creates devices + reports."""

    if not no_clear:
        # Clear existing operational data
        log.info("Clearing existing reports, devices, notifications, cases...")
        for tbl in [
            "deployment_decisions", "ml_predictions",
            "case_reports", "cases", "notifications", "evidence_files",
            "report_assignments",
            "audit_logs", "reports", "devices",
        ]:
            try:
                db.execute(text(f"DELETE FROM {tbl}"))
            except Exception:
                db.rollback()
                log.warning("Could not clear %s (may not exist)", tbl)
        # Clear hotspots
        try:
            db.execute(text("DELETE FROM hotspot_reports"))
            db.execute(text("DELETE FROM hotspots"))
        except Exception:
            db.rollback()
        db.commit()
        log.info("Cleared operational tables")

    inc_types, villages, station_ids, leader_ids, sector_map = load_reference_data(db)

    if not villages:
        raise RuntimeError("No villages found in database!")
    if not inc_types:
        raise RuntimeError("No incident types found in database!")

    # Create devices
    devices = create_realistic_devices(db, count=max(60, count // 4))

    # Build weighted incident type pool
    type_pool = []
    for tname, weight in INCIDENT_WEIGHTS.items():
        if tname in inc_types:
            type_pool.extend([tname] * weight)
    if not type_pool:
        type_pool = list(inc_types.keys())

    # Designate hotspot villages (15 villages get ~4x reports)
    hotspot_villages = random.sample(villages, min(15, len(villages)))
    hotspot_ids = {v["id"] for v in hotspot_villages}

    # Plan score distribution: ~60% verified, ~25% pending, ~15% rejected
    plan = []
    n_rejected = max(1, int(count * 0.12))
    n_pending = max(1, int(count * 0.25))
    n_verified = count - n_rejected - n_pending

    for _ in range(n_rejected):
        plan.append(("rejected", round(random.uniform(8, 39), 2)))
    for _ in range(n_pending):
        plan.append(("pending", round(random.uniform(40, 69), 2)))
    for _ in range(n_verified):
        plan.append(("verified", round(random.uniform(70, 97), 2)))
    random.shuffle(plan)

    # Get next report number
    max_num = db.execute(text(
        "SELECT MAX(CAST(SUBSTRING(report_number FROM 10) AS INTEGER)) "
        "FROM reports WHERE report_number LIKE 'RPT-2026-%'"
    )).scalar() or 0
    rpt_counter = int(max_num) + 1

    stats = {"verified": 0, "pending": 0, "rejected": 0}

    for i, (band, score) in enumerate(plan):
        device = random.choice(devices)
        type_name = random.choice(type_pool)
        type_id = inc_types[type_name]

        # Village selection (hotspot bias)
        if random.random() < 0.4:
            village = random.choice(hotspot_villages)
        else:
            village = random.choice(villages)

        sector_id = sector_map.get(village["id"])
        lat = jitter(village["lat"])
        lng = jitter(village["lng"])

        reported_at = random_datetime_in_range(START_DATE, END_DATE)

        # Description quality based on band
        if band == "rejected":
            desc = random.choice(WEAK_DESCRIPTIONS)
        elif band == "pending":
            descs = MEDIUM_DESCRIPTIONS.get(type_name, MEDIUM_DESCRIPTIONS.get("Theft"))
            desc = random.choice(descs) if descs else "An incident was reported in the area."
        else:
            descs = GOOD_DESCRIPTIONS.get(type_name, GOOD_DESCRIPTIONS.get("Theft"))
            desc = random.choice(descs)
            # 60% chance of appending extra witness detail
            if random.random() < 0.6:
                extras = [
                    " A neighbor witnessed part of the incident and is willing to provide a statement.",
                    " The reporting party included specific times and nearby landmarks.",
                    " Several residents confirmed the sequence of events.",
                    " Local shop owners confirmed unusual activity matching this description.",
                    " Details include clothing descriptions and direction of travel for suspects.",
                ]
                desc += random.choice(extras)

        # NL / semantic scores matching band
        if band == "verified":
            desc_quality = round(random.uniform(65, 95), 2)
            nl_score = round(random.uniform(60, 92), 2)
            semantic_score = round(random.uniform(0.55, 0.95), 2)
        elif band == "pending":
            desc_quality = round(random.uniform(35, 65), 2)
            nl_score = round(random.uniform(30, 60), 2)
            semantic_score = round(random.uniform(0.3, 0.6), 2)
        else:
            desc_quality = round(random.uniform(5, 35), 2)
            nl_score = round(random.uniform(5, 30), 2)
            semantic_score = round(random.uniform(0.05, 0.3), 2)

        feature_vector = build_feature_vector(
            score, band, desc, desc_quality, nl_score, semantic_score
        )

        # Status fields consistent with score band
        if band == "verified":
            status = "verified"
            verification_status = "verified"
            rule_status = "passed"
            is_flagged = False
            flag_reason = None
            ml_label = "likely_real"
        elif band == "pending":
            status = "pending"
            verification_status = "under_review"
            rule_status = "passed"
            is_flagged = False
            flag_reason = None
            ml_label = "suspicious"
        else:
            status = "rejected"
            verification_status = "rejected"
            rule_status = "rejected"
            is_flagged = True
            flag_reason = "low_trust_score"
            ml_label = "fake"

        # Leader verification (follows AI for most cases, some overrides)
        leader_status = "pending"
        leader_by = None
        leader_at = None
        leader_note = None

        if band == "verified":
            # 85% confirmed by leader, 5% still pending, 10% no leader yet
            r = random.random()
            if r < 0.85:
                leader_status = "confirmed"
                leader_by = random.choice(leader_ids) if leader_ids else None
                leader_at = reported_at + timedelta(hours=random.randint(1, 48))
                leader_note = random.choice(LEADER_CONFIRM_NOTES)
            else:
                leader_status = "pending"
        elif band == "pending":
            # 40% confirmed (leader override → makes it eligible), 10% rejected, 50% pending
            r = random.random()
            if r < 0.40:
                leader_status = "confirmed"
                leader_by = random.choice(leader_ids) if leader_ids else None
                leader_at = reported_at + timedelta(hours=random.randint(2, 72))
                leader_note = random.choice(LEADER_CONFIRM_NOTES)
                # Leader confirmed → override to verified
                status = "verified"
                verification_status = "verified"
                rule_status = "passed"
                is_flagged = False
                ml_label = "likely_real"
            elif r < 0.50:
                leader_status = "rejected"
                leader_by = random.choice(leader_ids) if leader_ids else None
                leader_at = reported_at + timedelta(hours=random.randint(1, 24))
                leader_note = random.choice(LEADER_REJECT_NOTES)
                status = "rejected"
                verification_status = "rejected"
                is_flagged = True
                ml_label = "fake"
        else:  # rejected
            # 15% leader confirmed (overrides AI rejection), 40% leader also rejected, 45% pending
            r = random.random()
            if r < 0.15:
                leader_status = "confirmed"
                leader_by = random.choice(leader_ids) if leader_ids else None
                leader_at = reported_at + timedelta(hours=random.randint(1, 36))
                leader_note = random.choice(LEADER_CONFIRM_NOTES)
                # Leader override → verified despite low AI score
                status = "verified"
                verification_status = "verified"
                rule_status = "passed"
                is_flagged = False
                ml_label = "likely_real"
            elif r < 0.55:
                leader_status = "rejected"
                leader_by = random.choice(leader_ids) if leader_ids else None
                leader_at = reported_at + timedelta(hours=random.randint(1, 12))
                leader_note = random.choice(LEADER_REJECT_NOTES)

        # Priority
        if band == "verified":
            priority = random.choices(
                ["low", "medium", "high", "urgent"],
                weights=[15, 45, 30, 10], k=1
            )[0]
        elif band == "pending":
            priority = random.choices(
                ["low", "medium", "high", "urgent"],
                weights=[25, 50, 20, 5], k=1
            )[0]
        else:
            priority = random.choices(
                ["low", "medium", "high"],
                weights=[50, 40, 10], k=1
            )[0]

        tags = random.choice(CONTEXT_TAGS.get(type_name, [[]]))

        verified_at = None
        if status == "verified":
            verified_at = reported_at + timedelta(minutes=random.randint(1, 60))

        report = Report(
            report_id=uuid.uuid4(),
            report_number=f"RPT-2026-{rpt_counter:04d}",
            device_id=device.device_id,
            incident_type_id=type_id,
            description=desc,
            latitude=Decimal(str(round(lat, 7))),
            longitude=Decimal(str(round(lng, 7))),
            gps_accuracy=Decimal(str(round(random.uniform(3, 45), 2))),
            motion_level=random.choices(MOTION_LEVELS, weights=[50, 35, 15], k=1)[0],
            movement_speed=Decimal(str(round(random.uniform(0, 2.0), 2))) if random.random() < 0.25 else None,
            was_stationary=random.random() < 0.6,
            location_id=sector_id,
            village_location_id=village["id"],
            handling_station_id=random.choice(station_ids) if station_ids else None,
            reported_at=reported_at,
            status=status,
            rule_status=rule_status,
            verification_status=verification_status,
            is_flagged=is_flagged,
            flag_reason=flag_reason,
            priority=priority,
            leader_verification_status=leader_status,
            leader_verified_by=leader_by,
            leader_verified_at=leader_at,
            leader_verification_note=leader_note,
            verified_at=verified_at,
            ai_ready=True,
            features_extracted_at=reported_at + timedelta(seconds=random.randint(5, 120)),
            ai_verification_reason=build_ai_reason(score, band, type_name, len(desc)),
            feature_vector=feature_vector,
            app_version=random.choice(APP_VERSIONS),
            network_type=random.choices(NETWORK_TYPES, weights=NETWORK_WEIGHTS, k=1)[0],
            battery_level=Decimal(str(round(random.uniform(12, 100), 1))),
            context_tags=tags,
        )
        db.add(report)

        # Update device stats
        device.total_reports += 1
        if status == "verified":
            device.trusted_reports += 1
        elif is_flagged:
            device.flagged_reports += 1
        device.last_seen_at = max(device.last_seen_at or reported_at, reported_at)

        # Track final status (after leader overrides)
        if status == "verified":
            stats["verified"] += 1
        elif status == "rejected":
            stats["rejected"] += 1
        else:
            stats["pending"] += 1

        rpt_counter += 1

        if (i + 1) % 50 == 0:
            db.flush()
            log.info("  ... %d/%d reports (V=%d P=%d R=%d)",
                     i + 1, count, stats["verified"], stats["pending"], stats["rejected"])

    db.commit()
    log.info("=" * 60)
    log.info("DONE — %d reports seeded (April 27 → June 14, 2026)", count)
    log.info("  Verified: %d", stats["verified"])
    log.info("  Pending:  %d", stats["pending"])
    log.info("  Rejected: %d", stats["rejected"])
    log.info("  Devices:  %d", len(devices))
    log.info("=" * 60)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Seed 300+ realistic reports (April 27 – June 14, 2026)")
    parser.add_argument("--count", type=int, default=300, help="Number of reports (default 300)")
    parser.add_argument("--no-clear", action="store_true", help="Don't clear existing data first")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)

    db = SessionLocal()
    try:
        db.execute(text("SET statement_timeout = '600000'"))
        db.execute(text("SET idle_in_transaction_session_timeout = '900000'"))
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("Could not set session timeouts: %s", e)

    try:
        seed_reports(db, count=args.count, no_clear=not args.no_clear)
    except Exception:
        db.rollback()
        log.exception("Seeding failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
