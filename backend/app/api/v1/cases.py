from uuid import uuid4
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.case import Case, CaseReport
from app.models.report import Report
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_admin_or_supervisor, get_current_user
from app.schemas.case import CaseCreate, CaseUpdate, CaseResponse, CaseListResponse, CaseAddReports

router = APIRouter(prefix="/cases", tags=["cases"])


def _generate_case_number(db: Session) -> str:
    from datetime import datetime, timezone
    from sqlalchemy import text
    year = datetime.now(timezone.utc).strftime("%Y")
    row = db.execute(
        text("""
            SELECT COALESCE(MAX(
                NULLIF(SUBSTRING(case_number FROM 'CASE-[0-9]{4}-([0-9]+)'), '')::INT
            ), 0) + 1 AS next_num
            FROM cases WHERE case_number LIKE :prefix
        """),
        {"prefix": f"CASE-{year}-%"},
    ).fetchone()
    next_num = row[0] if row else 1
    return f"CASE-{year}-{next_num:04d}"


def _case_to_response(c: Case) -> CaseResponse:
    return CaseResponse(
        case_id=c.case_id,
        case_number=c.case_number,
        status=c.status,
        priority=c.priority,
        title=c.title,
        description=c.description,
        location_id=c.location_id,
        location_name=c.location.location_name if c.location else None,
        incident_type_id=c.incident_type_id,
        incident_type_name=c.incident_type.type_name if c.incident_type else None,
        assigned_to_id=c.assigned_to_id,
        assigned_to_name=f"{c.assigned_to.first_name} {c.assigned_to.last_name}".strip() if c.assigned_to else None,
        created_by=c.created_by,
        report_count=c.report_count or 0,
        opened_at=c.opened_at,
        closed_at=c.closed_at,
        outcome=c.outcome,
        created_at=c.created_at,
    )


@router.get("/", response_model=CaseListResponse)
def list_cases(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List cases with optional status filter.

    - Admin: all cases.
    - Supervisor: cases in their assigned location (if set).
    - Officer: cases assigned to them.
    """
    query = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    )

    if current_user.role == "supervisor" and getattr(current_user, "assigned_location_id", None):
        query = query.filter(Case.location_id == current_user.assigned_location_id)
    elif current_user.role == "officer":
        query = query.filter(Case.assigned_to_id == current_user.police_user_id)

    if status:
        query = query.filter(Case.status == status)
    total = query.count()
    cases = query.order_by(Case.opened_at.desc()).offset(offset).limit(limit).all()
    return CaseListResponse(
        items=[_case_to_response(c) for c in cases],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=CaseResponse, status_code=201)
def create_case(
    payload: CaseCreate,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
):
    """Create a new case, optionally linking reports and assigning an officer."""
    case_id = uuid4()
    case_number = _generate_case_number(db)
    case = Case(
        case_id=case_id,
        case_number=case_number,
        status="open",
        priority=payload.priority or "medium",
        title=payload.title,
        description=payload.description,
        location_id=payload.location_id,
        incident_type_id=payload.incident_type_id,
        created_by=current_user.police_user_id,
    )
    db.add(case)
    db.flush()
    for rid in payload.report_ids or []:
        r = db.query(Report).filter(Report.report_id == rid).first()
        if r:
            cr = CaseReport(case_id=case_id, report_id=rid)
            db.add(cr)
    case.report_count = len(payload.report_ids or [])

    # Optional initial assignment
    if payload.assigned_to_id is not None:
        officer = (
            db.query(PoliceUser)
            .filter(
                PoliceUser.police_user_id == payload.assigned_to_id,
                PoliceUser.is_active == True,
            )
            .first()
        )
        if not officer:
            raise HTTPException(status_code=400, detail="Assigned officer not found or inactive")
        if current_user.role == "supervisor" and getattr(current_user, "station_id", None):
            if officer.station_id != current_user.station_id:
                raise HTTPException(
                    status_code=403,
                    detail="You can only assign cases to officers in your station",
                )
        case.assigned_to_id = payload.assigned_to_id
    db.commit()
    db.refresh(case)
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == case_id).first()
    return _case_to_response(case)


@router.get("/stats")
def get_case_stats(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
):
    """Return case counts by status for dashboard."""
    from sqlalchemy import func
    open_c = db.query(func.count(Case.case_id)).filter(Case.status == "open").scalar() or 0
    in_progress = db.query(func.count(Case.case_id)).filter(Case.status == "investigating").scalar() or 0
    closed = db.query(func.count(Case.case_id)).filter(Case.status == "closed").scalar() or 0
    total_reports = db.query(func.sum(Case.report_count)).scalar() or 0
    return {
        "open": open_c,
        "in_progress": in_progress,
        "closed": closed,
        "reports_merged": total_reports,
    }


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(
    case_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get one case by ID.

    - Admin: any case.
    - Supervisor: only cases in their location.
    - Officer: only cases assigned to them.
    """
    from uuid import UUID
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    query = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == cid)

    if current_user.role == "supervisor" and getattr(current_user, "assigned_location_id", None):
        query = query.filter(Case.location_id == current_user.assigned_location_id)
    elif current_user.role == "officer":
        query = query.filter(Case.assigned_to_id == current_user.police_user_id)

    case = query.first()
    if not case:
        raise HTTPException(404, "Case not found")
    return _case_to_response(case)


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: str,
    payload: CaseUpdate,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Update case status, assignment, etc.

    - Admin: unrestricted.
    - Supervisor: only for cases in their location; assignment only to officers in their station.
    - Officer: only for cases assigned to them; can update status/description/outcome.
    """
    from uuid import UUID
    from datetime import datetime, timezone
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    query = db.query(Case).filter(Case.case_id == cid)
    if current_user.role == "supervisor" and getattr(current_user, "assigned_location_id", None):
        query = query.filter(Case.location_id == current_user.assigned_location_id)
    elif current_user.role == "officer":
        query = query.filter(Case.assigned_to_id == current_user.police_user_id)
    case = query.first()
    if not case:
        raise HTTPException(404, "Case not found")
    # Role-specific update rules
    if current_user.role == "officer":
        # Officers: can move between investigating/closed and update notes/outcome.
        if payload.status is not None:
            if payload.status not in ("investigating", "closed"):
                raise HTTPException(
                    status_code=403,
                    detail="Officers can only set status to investigating or closed",
                )
            case.status = payload.status
            if payload.status == "closed":
                case.closed_at = datetime.now(timezone.utc)
        if payload.description is not None:
            case.description = payload.description
        if payload.outcome is not None:
            case.outcome = payload.outcome
    else:
        # Admin / Supervisor logic
        if payload.status is not None:
            case.status = payload.status
            if payload.status == "closed":
                case.closed_at = datetime.now(timezone.utc)
        if payload.priority is not None:
            case.priority = payload.priority
        if payload.assigned_to_id is not None:
            # Supervisors may only assign to officers in their station (if they have one)
            if current_user.role == "supervisor" and getattr(current_user, "station_id", None):
                officer = (
                    db.query(PoliceUser)
                    .filter(
                        PoliceUser.police_user_id == payload.assigned_to_id,
                        PoliceUser.is_active == True,
                    )
                    .first()
                )
                if not officer or officer.station_id != current_user.station_id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only assign cases to officers in your station",
                    )
            case.assigned_to_id = payload.assigned_to_id
        if payload.title is not None:
            case.title = payload.title
        if payload.description is not None:
            case.description = payload.description
        if payload.outcome is not None:
            case.outcome = payload.outcome
    db.add(case)
    db.commit()
    db.refresh(case)
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == cid).first()
    return _case_to_response(case)


@router.post("/{case_id}/reports", response_model=CaseResponse)
def add_reports_to_case(
    case_id: str,
    payload: CaseAddReports,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """
    Link one or more existing reports to an existing case.

    - Admin: any case.
    - Supervisor: only cases in their location.
    - Officer: only cases assigned to them.
    """
    from uuid import UUID

    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")

    # Reuse same access rules as get_case/update_case
    query = db.query(Case).filter(Case.case_id == cid)
    if current_user.role == "supervisor" and getattr(current_user, "assigned_location_id", None):
        query = query.filter(Case.location_id == current_user.assigned_location_id)
    elif current_user.role == "officer":
        query = query.filter(Case.assigned_to_id == current_user.police_user_id)

    case = query.first()
    if not case:
        raise HTTPException(404, "Case not found")

    # Add new links, avoiding duplicates
    if payload.report_ids:
        existing_links = {
            cr.report_id for cr in db.query(CaseReport).filter(CaseReport.case_id == cid).all()
        }
        added = 0
        for rid in payload.report_ids:
            if rid in existing_links:
                continue
            report = db.query(Report).filter(Report.report_id == rid).first()
            if not report:
                continue
            cr = CaseReport(case_id=cid, report_id=rid)
            db.add(cr)
            added += 1
        if added:
            # Recompute report_count to stay accurate
            case.report_count = (
                db.query(CaseReport).filter(CaseReport.case_id == cid).count()
            )
    db.add(case)
    db.commit()
    db.refresh(case)
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == cid).first()
    return _case_to_response(case)
