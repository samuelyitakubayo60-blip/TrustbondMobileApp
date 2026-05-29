from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.location import Location
from app.models.ml_prediction import MLPrediction
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
    flag_reason: Optional[str] = None
    evidence_count: int = 0
    credibility_summary: Optional[str] = None


class LeaderReportListResponse(BaseModel):
    items: list[LeaderReportResponse]
    total: int


class EvidenceFileInfo(BaseModel):
    evidence_id: str
    file_url: str
    file_type: Optional[str] = None
    is_live_capture: bool = False
    captured_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None


class LeaderReportDetailResponse(LeaderReportResponse):
    priority: Optional[str] = None
    leader_note: Optional[str] = None
    evidence_files: list[EvidenceFileInfo] = []
    verification_summary: Optional[str] = None


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


@router.get("/reports/{report_id}", response_model=LeaderReportDetailResponse)
def get_leader_report_detail(
    report_id: str,
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
):
    covered_villages = _leader_covered_village_ids(db, current_leader.local_leader_id)
    if not covered_villages:
        raise HTTPException(status_code=403, detail="Leader coverage is not configured")

    try:
        rid = UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Report not found")

    r = (
        db.query(Report)
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.evidence_files),
            joinedload(Report.village_location)
            .joinedload(Location.parent)
            .joinedload(Location.parent),
        )
        .filter(Report.report_id == rid)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")

    if r.village_location_id is None or int(r.village_location_id) not in covered_villages:
        raise HTTPException(status_code=403, detail="Not allowed for this location")

    vname = getattr(r.village_location, "location_name", None) if r.village_location else None
    cell_name = None
    sector_name = None
    if r.village_location and r.village_location.parent:
        cell_name = r.village_location.parent.location_name
        if r.village_location.parent.parent:
            sector_name = r.village_location.parent.parent.location_name

    evidence_files_raw = getattr(r, "evidence_files", None) or []
    evidence_count = len(evidence_files_raw)
    trust_val = float(r.trust_score) if getattr(r, "trust_score", None) is not None else None

    credibility_summary = build_credibility_summary(
        report=r,
        trust_score=trust_val,
        flag_reason=r.flag_reason,
        evidence_count=evidence_count,
    )

    # Derive priority from trust score and flags
    is_flagged = bool(getattr(r, "is_flagged", False))
    if trust_val is not None and trust_val < 30 and is_flagged:
        priority = "urgent"
    elif (trust_val is not None and trust_val < 50) or is_flagged:
        priority = "high"
    else:
        priority = "medium"

    # Build verification summary from feature_vector if available
    fv = r.feature_vector if isinstance(getattr(r, "feature_vector", None), dict) else {}
    leader_note = None
    ld = fv.get("leader_decision") or {}
    if isinstance(ld, dict):
        leader_note = ld.get("note")

    evidence_files = [
        EvidenceFileInfo(
            evidence_id=str(ef.evidence_id),
            file_url=str(ef.cloudinary_url or ef.file_url or ""),
            file_type=ef.file_type,
            is_live_capture=bool(ef.is_live_capture),
            captured_at=ef.captured_at,
            uploaded_at=ef.uploaded_at,
        )
        for ef in evidence_files_raw
    ]

    return LeaderReportDetailResponse(
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
        priority=priority,
        leader_note=leader_note,
        evidence_files=evidence_files,
        verification_summary=credibility_summary,
    )


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

    # Leader confirmation is sufficient for map display — no police review needed.
    if decision == "confirmed" and r.verification_status not in ("rejected",):
        r.verification_status = "verified"
        r.status = "verified"
        if r.rule_status not in ("rejected", "passed"):
            r.rule_status = "passed"
    elif decision == "rejected":
        r.verification_status = "rejected"
        r.status = "rejected"
        r.is_flagged = True
        r.flag_reason = r.flag_reason or "rejected_by_local_leader"

    # ── Update ML trust score based on leader decision ──────────────────────
    # confirmed: raise score to at least 80, is_final=False (future evidence can still adjust)
    # rejected:  hard-set score to 10, is_final=True (locks scorecard — prevents any rerun
    #            from restoring the report to verified after leader rejection)
    existing_ml = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == r.report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )

    # Always persist the leader decision in feature_vector so the scorecard
    # is aware of it even if it reruns (e.g. from a community vote).
    fv = r.feature_vector if isinstance(getattr(r, "feature_vector", None), dict) else {}
    fv["leader_decision"] = {
        "decision": decision,
        "leader_id": int(current_leader.local_leader_id),
        "decided_at": now.isoformat(),
        "note": (payload.note or "").strip()[:500] if payload.note else None,
    }
    r.feature_vector = fv

    if decision == "confirmed":
        if existing_ml:
            current_score = float(existing_ml.trust_score or 50.0)
            new_score = max(80.0, current_score)
            existing_ml.trust_score = Decimal(str(round(new_score, 2)))
            existing_ml.prediction_label = "likely_real"
            existing_ml.confidence = Decimal("0.85")
            existing_ml.model_type = "leader_override"
            existing_ml.is_final = False  # community votes can still adjust
        else:
            db.add(MLPrediction(
                prediction_id=uuid4(),
                report_id=r.report_id,
                trust_score=Decimal("80.0"),
                prediction_label="likely_real",
                confidence=Decimal("0.85"),
                model_type="leader_override",
                is_final=False,
                evaluated_at=now,
            ))
        # Reward reporting device slightly
        if getattr(r, "device", None) and hasattr(r.device, "device_trust_score"):
            r.device.device_trust_score = Decimal(
                str(min(100.0, float(r.device.device_trust_score or 50.0) + 1.0))
            )
        if hasattr(r.device, "trusted_reports"):
            r.device.trusted_reports = (r.device.trusted_reports or 0) + 1

    elif decision == "rejected":
        # Hard-lock: score drops to 10, is_final=True prevents any background
        # rerun (community vote, backlog processor) from overwriting this decision.
        if existing_ml:
            existing_ml.trust_score = Decimal("10.0")
            existing_ml.prediction_label = "fake"
            existing_ml.confidence = Decimal("0.90")
            existing_ml.model_type = "leader_override"
            existing_ml.is_final = True
        else:
            db.add(MLPrediction(
                prediction_id=uuid4(),
                report_id=r.report_id,
                trust_score=Decimal("10.0"),
                prediction_label="fake",
                confidence=Decimal("0.90"),
                model_type="leader_override",
                is_final=True,
                evaluated_at=now,
            ))
        # Penalise reporting device
        if getattr(r, "device", None) and hasattr(r.device, "device_trust_score"):
            r.device.device_trust_score = Decimal(
                str(max(0.0, float(r.device.device_trust_score or 50.0) - 5.0))
            )
        if hasattr(r.device, "flagged_reports"):
            r.device.flagged_reports = (r.device.flagged_reports or 0) + 1

    db.add(r)
    db.commit()

    from app.core.leader_verification_notifications import notify_police_leader_verification_task
    from app.core.mobile_push_notifications import notify_citizen_leader_decision_task

    background_tasks.add_task(
        notify_police_leader_verification_task,
        str(r.report_id),
        decision,
        int(current_leader.local_leader_id),
    )
    background_tasks.add_task(notify_citizen_leader_decision_task, str(r.report_id), decision)

    if decision == "confirmed":
        from app.api.v1.reports import run_auto_case_for_report

        background_tasks.add_task(run_auto_case_for_report, str(r.report_id))
    from app.api.v1.reports import run_hotspot_auto

    background_tasks.add_task(run_hotspot_auto)

    return {"message": "OK", "leader_verification_status": decision, "leader_verified_at": now.isoformat()}
