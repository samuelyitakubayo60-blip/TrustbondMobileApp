from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.location import Location
from app.models.report import Report
from app.models.local_leader import LocalLeader
from app.api.v1.leader_auth import get_current_local_leader
from app.core.leader_workflow import leader_covered_village_ids as _leader_covered_village_ids
from app.core.report_credibility_summary import build_credibility_summary


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
    trust_score: Optional[float] = None
    verification_status: Optional[str] = None
    flag_reason: Optional[str] = None
    evidence_count: int = 0
    credibility_summary: Optional[str] = None


class LeaderReportListResponse(BaseModel):
    items: list[LeaderReportResponse]
    total: int


class LeaderVerifyRequest(BaseModel):
    decision: str  # confirmed | rejected
    note: Optional[str] = None


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
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.evidence_files),
            joinedload(Report.village_location)
            .joinedload(Location.parent)
            .joinedload(Location.parent),
        )
        .filter(Report.village_location_id.in_(covered_villages))
        .order_by(Report.reported_at.desc())
    )
    if only_pending:
        q = q.filter((Report.leader_verification_status.is_(None)) | (Report.leader_verification_status == "pending"))

    total = q.count()
    rows = q.offset(offset).limit(limit).all()

    items: list[LeaderReportResponse] = []
    for r in rows:
        vname = getattr(r.village_location, "location_name", None) if r.village_location else None
        cell_name = None
        sector_name = None
        if r.village_location and r.village_location.parent:
            cell_name = r.village_location.parent.location_name
            if r.village_location.parent.parent:
                sector_name = r.village_location.parent.parent.location_name

        evidence_count = len(getattr(r, "evidence_files", None) or [])
        trust_val = float(r.trust_score) if getattr(r, "trust_score", None) is not None else None
        credibility_summary = build_credibility_summary(
            report=r,
            trust_score=trust_val,
            flag_reason=r.flag_reason,
            evidence_count=evidence_count,
        )

        items.append(
            LeaderReportResponse(
                report_id=str(r.report_id),
                incident_type_id=int(r.incident_type_id),
                incident_type_name=getattr(r.incident_type, "type_name", None) if r.incident_type else None,
                description=r.description,
                latitude=float(r.latitude),
                longitude=float(r.longitude),
                reported_at=r.reported_at,
                status=r.status,
                verification_status=r.verification_status,
                village_location_id=r.village_location_id,
                village_name=vname,
                cell_name=cell_name,
                sector_name=sector_name,
                leader_verification_status=getattr(r, "leader_verification_status", None),
                leader_verified_at=getattr(r, "leader_verified_at", None),
                trust_score=trust_val,
                flag_reason=r.flag_reason,
                evidence_count=evidence_count,
                credibility_summary=credibility_summary,
            )
        )

    return LeaderReportListResponse(items=items, total=total)


@router.post("/reports/{report_id}/verify", status_code=200)
def verify_report(
    report_id: str,
    payload: LeaderVerifyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
):
    decision = (payload.decision or "").strip().lower()
    if decision not in {"confirmed", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be confirmed or rejected")

    covered_villages = _leader_covered_village_ids(db, current_leader.local_leader_id)
    if not covered_villages:
        raise HTTPException(status_code=403, detail="Leader coverage is not configured")

    try:
        rid = UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Report not found")
    r = db.query(Report).filter(Report.report_id == rid).first()
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

    if decision == "confirmed":
        from app.api.v1.reports import run_auto_case_for_report

        background_tasks.add_task(run_auto_case_for_report, str(r.report_id))
    from app.api.v1.reports import run_hotspot_auto

    background_tasks.add_task(run_hotspot_auto)

    return {"message": "OK", "leader_verification_status": decision, "leader_verified_at": now.isoformat()}
