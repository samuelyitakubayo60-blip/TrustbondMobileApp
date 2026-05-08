from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.location import Location
from app.models.report import Report
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.api.v1.leader_auth import get_current_local_leader


router = APIRouter(prefix="/leader", tags=["leader"])


class LeaderReportResponse(BaseModel):
    report_id: str
    incident_type_id: int
    incident_type_name: Optional[str] = None
    description: Optional[str] = None
    latitude: float
    longitude: float
    reported_at: datetime
    status: Optional[str] = None
    verification_status: Optional[str] = None
    village_location_id: Optional[int] = None
    village_name: Optional[str] = None
    cell_name: Optional[str] = None
    sector_name: Optional[str] = None
    leader_verification_status: Optional[str] = None
    leader_verified_at: Optional[datetime] = None


class LeaderReportListResponse(BaseModel):
    items: list[LeaderReportResponse]
    total: int


class LeaderVerifyRequest(BaseModel):
    decision: str  # confirmed | rejected
    note: Optional[str] = None


def _leader_covered_village_ids(db: Session, leader_id: int) -> set[int]:
    # Coverage locations can include villages or cells. We normalize to villages.
    covered_ids = {
        int(r[0])
        for r in db.query(LocalLeaderCoverageLocation.location_id)
        .filter(LocalLeaderCoverageLocation.local_leader_id == leader_id)
        .all()
    }
    if not covered_ids:
        return set()

    rows = db.query(Location.location_id, Location.location_type, Location.parent_location_id).filter(
        Location.location_id.in_(covered_ids)
    ).all()
    village_ids: set[int] = set()
    cell_ids: set[int] = set()
    for loc_id, loc_type, parent_id in rows:
        if loc_type == "village":
            village_ids.add(int(loc_id))
        elif loc_type == "cell":
            cell_ids.add(int(loc_id))

    if cell_ids:
        vrows = db.query(Location.location_id).filter(
            Location.location_type == "village",
            Location.parent_location_id.in_(cell_ids),
        ).all()
        village_ids.update(int(r[0]) for r in vrows)

    return village_ids


@router.get("/reports", response_model=LeaderReportListResponse)
def list_leader_reports(
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    only_pending: bool = Query(True),
):
    covered_villages = _leader_covered_village_ids(db, current_leader.local_leader_id)
    if not covered_villages:
        return LeaderReportListResponse(items=[], total=0)

    q = (
        db.query(Report)
        .options(joinedload(Report.incident_type), joinedload(Report.village_location))
        .filter(Report.village_location_id.in_(covered_villages))
    )

    if only_pending:
        q = q.filter((Report.leader_verification_status.is_(None)) | (Report.leader_verification_status == "pending"))

    total = q.count()
    rows = (
        q.order_by(Report.reported_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items: list[LeaderReportResponse] = []
    for r in rows:
        items.append(
            LeaderReportResponse(
                report_id=str(r.report_id),
                incident_type_id=int(r.incident_type_id),
                incident_type_name=getattr(r.incident_type, "incident_type_name", None),
                description=r.description,
                latitude=float(r.latitude),
                longitude=float(r.longitude),
                reported_at=r.reported_at,
                status=r.status,
                verification_status=r.verification_status,
                village_location_id=r.village_location_id,
                village_name=getattr(r.village_location, "location_name", None) if r.village_location else None,
                leader_verification_status=getattr(r, "leader_verification_status", None),
                leader_verified_at=getattr(r, "leader_verified_at", None),
            )
        )

    return LeaderReportListResponse(items=items, total=total)


@router.post("/reports/{report_id}/verify", status_code=200)
def verify_report(
    report_id: str,
    payload: LeaderVerifyRequest,
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
):
    decision = (payload.decision or "").strip().lower()
    if decision not in {"confirmed", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be confirmed or rejected")

    covered_villages = _leader_covered_village_ids(db, current_leader.local_leader_id)
    if not covered_villages:
        raise HTTPException(status_code=403, detail="Leader coverage is not configured")

    r = db.query(Report).filter(Report.report_id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")

    if r.village_location_id is None or int(r.village_location_id) not in covered_villages:
        raise HTTPException(status_code=403, detail="Not allowed for this location")

    now = datetime.now(timezone.utc)
    r.leader_verification_status = decision
    r.leader_verified_by = current_leader.local_leader_id
    r.leader_verified_at = now
    r.leader_verification_note = (payload.note or "").strip()[:500] if payload.note else None
    db.add(r)
    db.commit()

    return {"message": "OK", "leader_verification_status": decision, "leader_verified_at": now.isoformat()}

