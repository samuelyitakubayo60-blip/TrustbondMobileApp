from uuid import uuid4, UUID
from typing import Annotated, Optional, List, Any
import time

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, or_, func

from app.database import get_db
from app.core.websocket import manager
from app.models.case import Case, CaseReport
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.location import Location
from app.models.ml_prediction import MLPrediction
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_admin_or_supervisor, get_current_user
from app.schemas.case import CaseCreate, CaseUpdate, CaseResponse, CaseListResponse, CaseAddReports
from app.schemas.report import ReportResponse

router = APIRouter(prefix="/cases", tags=["cases"])


def _require_supervisor_station_id(current_user: PoliceUser) -> int:
    station_id = getattr(current_user, "station_id", None)
    if station_id is None:
        raise HTTPException(status_code=403, detail="Supervisor station is not configured")
    return station_id


def _all_location_ids_for_scope(db: Session, location_id: Optional[int]) -> set[int]:
    if location_id is None:
        return set()
    query = db.query(Location.location_id).filter(
        or_(
            Location.location_id == location_id,
            Location.parent_location_id == location_id,
            Location.location_id.in_(
                db.query(Location.location_id).filter(
                    Location.parent_location_id.in_(
                        db.query(Location.location_id).filter(
                            Location.parent_location_id == location_id
                        )
                    )
                )
            )
        )
    )
    return {r[0] for r in query.all()}


def _supervisor_scope(current_user: PoliceUser, db: Session) -> tuple[int, set[int]]:
    # Use the same logic as the reports API
    supervisor_station_id = getattr(current_user, "station_id", None)
    
    location_ids = set()
    if supervisor_station_id is not None:
        # Get station to find configured coverage cells (or legacy sectors)
        from app.models.station import Station
        from app.models.station_coverage import StationCoverageCell
        station = db.query(Station).filter(Station.station_id == supervisor_station_id).first()
        
        if station:
            covered_cell_ids = {
                int(row[0])
                for row in db.query(StationCoverageCell.cell_location_id)
                .filter(StationCoverageCell.station_id == station.station_id)
                .all()
            }
            if covered_cell_ids:
                village_rows = db.query(Location.location_id).filter(
                    Location.location_type == "village",
                    Location.parent_location_id.in_(covered_cell_ids),
                ).all()
                location_ids.update(int(row[0]) for row in village_rows)
    else:
        # Fallback to assigned_location_id if station_id is None
        assigned_location_id = getattr(current_user, "assigned_location_id", None)
        if assigned_location_id:
            location_ids = _all_location_ids_for_scope(db, assigned_location_id)
    
    return supervisor_station_id, location_ids


def _report_in_supervisor_scope(report: Report, station_id: int, location_ids: set[int], db: Session) -> bool:
    if report.handling_station_id == station_id:
        return True
    in_station_assignment = (
        db.query(ReportAssignment.assignment_id)
        .join(PoliceUser, PoliceUser.police_user_id == ReportAssignment.police_user_id)
        .filter(
            ReportAssignment.report_id == report.report_id,
            PoliceUser.station_id == station_id,
        )
        .first()
        is not None
    )
    if in_station_assignment:
        return True
    if location_ids and report.village_location_id in location_ids:
        return True
    return False


def _role_uses_station_scope(role: Optional[str]) -> bool:
    return role in ("supervisor", "officer")


def _incident_case_title(type_name: str) -> str:
    name = (type_name or "Incident").strip()
    if not name:
        return "Incident case"
    if name.lower().endswith(" case"):
        return name
    if name.lower().endswith(" cases"):
        return f"{name[:-6].strip()} case"
    return f"{name} case"


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
    # Compute average ML trust score across reports linked to this case, if predictions exist.
    avg_trust = None
    scores: list[float] = []
    for cr in getattr(c, "case_reports", []):
        r = getattr(cr, "report", None)
        if not r:
            continue
        preds = getattr(r, "ml_predictions", None) or []
        if not preds:
            continue
        finals = [p for p in preds if getattr(p, "is_final", False)]
        source = finals or preds
        source.sort(
            key=lambda p: getattr(p, "evaluated_at", None) or 0,
            reverse=True,
        )
        latest: MLPrediction = source[0]
        try:
            ts = float(latest.trust_score) if latest.trust_score is not None else None
        except Exception:
            ts = None
        if ts is not None:
            scores.append(ts)
    if scores:
        avg_trust = sum(scores) / len(scores)

    # Get location information
    location_name = None
    if c.location:
        location_name = c.location.location_name
    elif c.latitude and c.longitude:
        # If case has coordinates but no location, create a descriptive name
        location_name = f"Case Location ({float(c.latitude):.4f}, {float(c.longitude):.4f})"
    else:
        # Try to get location from the first report in the case
        case_reports = getattr(c, "case_reports", [])
        if case_reports:
            first_report = getattr(case_reports[0], "report", None)
            if first_report and first_report.village_location:
                location_name = first_report.village_location.location_name
            elif first_report and first_report.latitude and first_report.longitude:
                location_name = f"Report Location ({float(first_report.latitude):.4f}, {float(first_report.longitude):.4f})"

    return CaseResponse(
        case_id=c.case_id,
        case_number=c.case_number,
        status=c.status,
        priority=c.priority,
        title=c.title,
        description=c.description,
        location_id=c.location_id,
        location_name=location_name,
        incident_type_id=c.incident_type_id,
        incident_type_name=c.incident_type.type_name if c.incident_type else None,
        assigned_to_id=c.assigned_to_id,
        assigned_to_name=f"{c.assigned_to.first_name} {c.assigned_to.last_name}".strip() if c.assigned_to else None,
        assigned_to_station_id=c.assigned_to.station_id if c.assigned_to else None,
        created_by=c.created_by,
        report_count=c.report_count or 0,
        opened_at=c.opened_at,
        closed_at=c.closed_at,
        outcome=c.outcome,
        special_assignment_unit=getattr(c, "special_assignment_unit", None),
        rib_handed_over_at=getattr(c, "rib_handed_over_at", None),
        rib_handover_summary=getattr(c, "rib_handover_summary", None),
        rib_handover_prerequisites_acknowledged=bool(
            getattr(c, "rib_handover_prerequisites_acknowledged", False)
        ),
        created_at=c.created_at,
        average_trust_score=avg_trust,
    )


def _report_to_response(r: Report, linked_case_id: Optional[UUID] = None) -> ReportResponse:
    case_id = linked_case_id
    if case_id is None:
        cr_links = list(getattr(r, "case_reports", None) or [])
        if cr_links:
            case_id = cr_links[0].case_id
    return ReportResponse(
        report_id=r.report_id,
        report_number=getattr(r, "report_number", None),
        case_id=case_id,
        device_id=r.device_id,
        incident_type_id=r.incident_type_id,
        description=r.description,
        latitude=r.latitude,
        longitude=r.longitude,
        reported_at=r.reported_at,
        rule_status=r.rule_status,
        status=r.status,
        verification_status=r.verification_status,
        village_location_id=r.village_location_id,
        village_name=getattr(r.village_location, "location_name", None)
        if getattr(r, "village_location", None)
        else None,
        incident_type_name=r.incident_type.type_name if r.incident_type else None,
        evidence_count=len(r.evidence_files) if r.evidence_files else 0,
        evidence_preview=[],
        trust_score=None,
        hotspot_id=None,
        hotspot_risk_level=None,
        hotspot_incident_count=None,
        hotspot_label=None,
        is_flagged=r.is_flagged,
        flag_reason=r.flag_reason,
        verified_at=r.verified_at,
        verified_by=getattr(r, "verified_by", None),
        verified_by_name=(
            f"{getattr(getattr(r, 'verified_by_user', None), 'first_name', '')} {getattr(getattr(r, 'verified_by_user', None), 'last_name', '')}".strip()
            or None
        )
        if getattr(r, "verified_by_user", None) is not None
        else None,
        verified_by_role=getattr(getattr(r, "verified_by_user", None), "role", None)
        if getattr(r, "verified_by_user", None) is not None
        else None,
        leader_verification_status=getattr(r, "leader_verification_status", None),
        leader_verified_at=getattr(r, "leader_verified_at", None),
        submitted_by_local_leader_id=getattr(r, "submitted_by_local_leader_id", None),
        context_tags=r.context_tags or [],
        app_version=r.app_version,
        network_type=r.network_type,
        battery_level=r.battery_level,
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
    - Supervisor / Officer: cases in their station coverage (same scope).
    """
    query = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
        selectinload(Case.case_reports)
        .selectinload(CaseReport.report)
        .selectinload(Report.ml_predictions),
    )

    if _role_uses_station_scope(current_user.role):
        station_id, location_ids = _supervisor_scope(current_user, db)
        if location_ids:
            query = query.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id.in_(location_ids),
                )
            )
        else:
            query = query.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))

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


@router.get("/available-reports", response_model=List[ReportResponse])
def list_available_reports_for_case(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    sector_location_id: Optional[int] = Query(
        None,
        description="Sector location_id; returns reports in that sector not yet linked to any case.",
    ),
    incident_type_id: Optional[int] = Query(
        None,
        description="Filter by incident type id.",
    ),
    station_id: Optional[int] = Query(
        None,
        description="Filter by station id (alternative to sector).",
    ),
    limit: int = Query(100, ge=1, le=500),
):
    """
    List reports that are **verified/reviewed** and can be grouped into cases, optionally limited to a given sector.

    Used by the Case Management UI to show "available reports" when creating a new case.
    Shows verified reports (not flagged/rejected) that are NOT already linked to a case.
    """
    from app.models.case import CaseReport

    # Base query: verified reports not already in a case
    q = (
        db.query(Report)
        .outerjoin(CaseReport, CaseReport.report_id == Report.report_id)
        .filter(
            Report.verification_status == 'verified',
            Report.rule_status != 'flagged',  # Not rejected/flagged
            CaseReport.case_id == None  # Not already in a case
        )
    )

    if _role_uses_station_scope(current_user.role):
        supervisor_station_id, sector_location_ids = _supervisor_scope(current_user, db)
        # Use the same logic as the reports API - geographic filtering
        if sector_location_ids:
            q = q.filter(
                or_(
                    Report.handling_station_id == supervisor_station_id,
                    Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                    ),
                    Report.village_location_id.in_(sector_location_ids)
                )
            )
        else:
            # Fallback: only station-based filtering
            station_filter = or_(
                Report.handling_station_id == supervisor_station_id,
                Report.assignments.any(
                    ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                ),
            )
            q = q.filter(station_filter)

    # Optionally restrict to a sector by resolving all villages under that sector
    if sector_location_id is not None:
        # Cells directly under sector
        cell_ids_subq = (
            db.query(Location.location_id)
            .filter(
                Location.location_type == "cell",
                Location.parent_location_id == sector_location_id,
            )
            .subquery()
        )
        # Villages whose parent is the sector OR whose parent is a cell under the sector
        village_ids_subq = (
            db.query(Location.location_id)
            .filter(
                Location.location_type == "village",
                (
                    (Location.parent_location_id == sector_location_id)
                    | (Location.parent_location_id.in_(cell_ids_subq))
                ),
            )
            .subquery()
        )
        q = q.filter(Report.village_location_id.in_(village_ids_subq))

    # Add station-based filtering as alternative to sector
    # IMPORTANT: Don't override supervisor geographic filtering - work with it
    if station_id is not None:
        # If user is supervisor, they should see all reports in their sector
        # The station_id parameter should just be an additional filter, not a replacement
        if current_user.role == "supervisor":
            # For supervisors, station_id acts as an additional geographic filter
            # Get the station's location to filter within the supervisor's sector
            from app.models.station import Station
            station = db.query(Station).filter(Station.station_id == station_id).first()
            if station:
                from app.models.station_coverage import StationCoverageCell
                covered_cell_ids = {
                    int(r[0])
                    for r in db.query(StationCoverageCell.cell_location_id)
                    .filter(StationCoverageCell.station_id == station.station_id)
                    .all()
                }
                covered_village_ids = set()
                if covered_cell_ids:
                    covered_village_ids = {
                        int(r[0])
                        for r in db.query(Location.location_id)
                        .filter(
                            Location.location_type == "village",
                            Location.parent_location_id.in_(covered_cell_ids),
                        )
                        .all()
                    }
                if covered_village_ids:
                    q = q.filter(Report.village_location_id.in_(covered_village_ids))
                else:
                    q = q.filter(Report.handling_station_id == station_id)
            else:
                q = q.filter(Report.handling_station_id == station_id)
        else:
            # For non-supervisors, use direct station filtering
            station_filter = or_(
                Report.handling_station_id == station_id,
                Report.assignments.any(
                    ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
                ),
            )
            q = q.filter(station_filter)

    # Add incident type filtering
    if incident_type_id is not None:
        q = q.filter(Report.incident_type_id == incident_type_id)

    reports = (
        q.options(
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
        )
        .order_by(Report.reported_at.desc())
        .limit(limit)
        .all()
    )

    return [_report_to_response(r) for r in reports]


@router.post("/", response_model=CaseResponse, status_code=201)
def create_case(
    payload: CaseCreate,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a new case, optionally linking reports and assigning an officer."""
    supervisor_station_id = None
    supervisor_location_ids: set[int] = set()
    if _role_uses_station_scope(current_user.role):
        supervisor_station_id, supervisor_location_ids = _supervisor_scope(current_user, db)
        # Allow case creation if:
        # 1. No location specified (will be inferred from reports)
        # 2. Location is in supervisor's geographic scope
        # 3. Station ID matches supervisor's station
        if payload.location_id is not None:
            if payload.location_id not in supervisor_location_ids:
                # Check if it's a station ID that matches supervisor's station
                if payload.location_id != supervisor_station_id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only create cases in your assigned location",
                    )

    from app.models.incident_type import IncidentType

    resolved_title = (payload.title or "").strip()
    if not resolved_title and payload.incident_type_id:
        itype_row = (
            db.query(IncidentType)
            .filter(IncidentType.incident_type_id == payload.incident_type_id)
            .first()
        )
        if itype_row and itype_row.type_name:
            resolved_title = _incident_case_title(itype_row.type_name)

    case_id = uuid4()
    case_number = _generate_case_number(db)
    case = Case(
        case_id=case_id,
        case_number=case_number,
        status="open",
        priority=payload.priority or "medium",
        title=resolved_title or None,
        description=payload.description,
        location_id=payload.location_id,
        incident_type_id=payload.incident_type_id,
        created_by=current_user.police_user_id,
    )
    db.add(case)
    db.flush()

    attached_reports: list[Report] = []
    for rid in payload.report_ids or []:
        r = db.query(Report).filter(Report.report_id == rid).first()
        if r:
            if _role_uses_station_scope(current_user.role):
                if not _report_in_supervisor_scope(
                    r, supervisor_station_id, supervisor_location_ids, db
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="You can only link reports from your station/location",
                    )
            cr = CaseReport(case_id=case_id, report_id=rid)
            db.add(cr)
            attached_reports.append(r)
    case.report_count = len(attached_reports)

    if not case.title and attached_reports:
        first = attached_reports[0]
        if getattr(first, "incident_type", None) and first.incident_type.type_name:
            case.title = _incident_case_title(first.incident_type.type_name)
            case.incident_type_id = case.incident_type_id or first.incident_type_id

    # If location_id not provided, try to infer sector from the first report's village_location.
    if case.location_id is None and attached_reports:
        first = attached_reports[0]
        if getattr(first, "village_location_id", None):
            loc = db.query(Location).get(first.village_location_id)
            while loc is not None and loc.location_type != "sector" and loc.parent_location_id:
                loc = db.query(Location).get(loc.parent_location_id)
            if loc is not None and loc.location_type == "sector":
                case.location_id = loc.location_id

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
        if _role_uses_station_scope(current_user.role):
            if officer.station_id != supervisor_station_id:
                raise HTTPException(
                    status_code=403,
                    detail="You can only assign cases to officers in your station",
                )
            # For supervisors, don't check assigned_location_id - they can assign to any officer in their station
            # The officer's location assignment doesn't matter for supervisors
        case.assigned_to_id = payload.assigned_to_id
    db.commit()
    db.refresh(case)
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "case", "action": "created"})
    
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == case_id).first()
    return _case_to_response(case)


@router.get("/stats")
def get_case_stats(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return case counts by status for dashboard."""
    from sqlalchemy import func

    # Apply scope
    base_q = db.query(Case)
    if _role_uses_station_scope(current_user.role):
        station_id, location_ids = _supervisor_scope(current_user, db)
        if location_ids:
            base_q = base_q.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id.in_(location_ids),
                )
            )
        else:
            base_q = base_q.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))

    def _count(q_filter):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return base_q.filter(q_filter).with_entities(func.count(Case.case_id)).scalar() or 0
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Failed to count cases after {max_retries} attempts: {e}")
                    return 0
                print(f"Database error in count attempt {attempt + 1}, retrying...")
                db.rollback()
                time.sleep(0.5)

    open_c = _count(Case.status == "open")
    in_progress = _count(Case.status == "investigating")
    closed = _count(Case.status == "closed")
    
    # Get total reports with retry
    total_reports = 0
    max_retries = 3
    for attempt in range(max_retries):
        try:
            total_reports = base_q.with_entities(func.sum(Case.report_count)).scalar() or 0
            break
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Failed to get total reports after {max_retries} attempts: {e}")
                total_reports = 0
            else:
                print(f"Database error in total reports attempt {attempt + 1}, retrying...")
                db.rollback()
                time.sleep(0.5)
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
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    query = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
        joinedload(Case.case_reports).joinedload(CaseReport.report).joinedload(Report.village_location),
    ).filter(Case.case_id == cid)

    if _role_uses_station_scope(current_user.role):
        station_id, location_ids = _supervisor_scope(current_user, db)
        if location_ids:
            query = query.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id.in_(location_ids),
                )
            )
        else:
            query = query.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))

    case = query.first()
    if not case:
        raise HTTPException(404, "Case not found")
    return _case_to_response(case)


@router.get("/{case_id}/reports", response_model=List[ReportResponse])
def get_case_reports(
    case_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """List reports linked to a case with same access rules as get_case."""
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")

    case_query = db.query(Case).filter(Case.case_id == cid)
    if _role_uses_station_scope(current_user.role):
        station_id, location_ids = _supervisor_scope(current_user, db)
        if location_ids:
            case_query = case_query.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id.in_(location_ids),
                )
            )
        else:
            case_query = case_query.filter(
                Case.assigned_to.has(PoliceUser.station_id == station_id)
            )

    case = case_query.first()
    if not case:
        raise HTTPException(404, "Case not found")

    reports = (
        db.query(Report)
        .join(CaseReport, CaseReport.report_id == Report.report_id)
        .filter(CaseReport.case_id == cid)
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.evidence_files),
        )
        .order_by(Report.reported_at.desc())
        .all()
    )
    return [_report_to_response(r, linked_case_id=cid) for r in reports]


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: str,
    payload: CaseUpdate,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Update case status, assignment, etc.

    - Admin: unrestricted.
    - Supervisor: only for cases in their location; assignment only to officers in their station.
    - Supervisor / Officer: cases in station coverage; same update fields as IO.
    """
    from uuid import UUID
    from datetime import datetime, timezone
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    query = db.query(Case).filter(Case.case_id == cid)
    if _role_uses_station_scope(current_user.role):
        station_id, location_ids = _supervisor_scope(current_user, db)
        if location_ids:
            query = query.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id.in_(location_ids),
                )
            )
        else:
            query = query.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))
    case = query.first()
    if not case:
        raise HTTPException(404, "Case not found")
    if payload.status is not None:
        case.status = payload.status
        if payload.status == "closed":
            case.closed_at = datetime.now(timezone.utc)
    if payload.priority is not None:
        case.priority = payload.priority
    if payload.assigned_to_id is not None:
        if _role_uses_station_scope(current_user.role):
            station_id = _require_supervisor_station_id(current_user)
            officer = (
                db.query(PoliceUser)
                .filter(
                    PoliceUser.police_user_id == payload.assigned_to_id,
                    PoliceUser.is_active == True,
                )
                .first()
            )
            if not officer or officer.station_id != station_id:
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
    if payload.special_assignment_unit is not None:
        case.special_assignment_unit = (payload.special_assignment_unit or "").strip() or None
    if payload.rib_handover_summary is not None:
        case.rib_handover_summary = (payload.rib_handover_summary or "").strip() or None
    if payload.rib_handed_over_at is not None:
        case.rib_handed_over_at = payload.rib_handed_over_at
    if payload.rib_handover_prerequisites_acknowledged is not None:
        case.rib_handover_prerequisites_acknowledged = bool(
            payload.rib_handover_prerequisites_acknowledged
        )
    db.add(case)
    db.commit()
    db.refresh(case)
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "case", "action": "updated"})
    
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == cid).first()
    return _case_to_response(case)


@router.delete("/{case_id}", status_code=204)
def delete_case(
    case_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Delete a case (and its links). Admin/supervisor only."""
    from uuid import UUID

    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")

    case = db.query(Case).filter(Case.case_id == cid).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Remove link rows first — CaseReport uses composite PK (case_id, report_id); ORM delete(case)
    # otherwise tries to null FKs and fails on PK columns.
    db.query(CaseReport).filter(CaseReport.case_id == cid).delete(synchronize_session=False)
    db.delete(case)
    db.commit()

    # Re-run auto-case grouping after deletions so eligible verified reports can
    # immediately be regrouped into cases in real time.
    try:
        from app.api.v1.reports import run_auto_case_realtime
        background_tasks.add_task(run_auto_case_realtime)
    except Exception:
        pass

    background_tasks.add_task(
        manager.broadcast,
        {"type": "refresh_data", "entity": "case", "action": "deleted"},
    )
    return {}


@router.delete("/{case_id}/reports/{report_id}", response_model=CaseResponse)
def remove_report_from_case(
    case_id: str,
    report_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Remove a report from a case (unlink but don't delete the report).

    - Admin: any case.
    - Supervisor: only cases in their location.
    - Officer: only cases assigned to them.
    """
    from uuid import UUID

    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")

    try:
        rid = UUID(report_id)
    except ValueError:
        raise HTTPException(404, "Report not found")

    case = db.query(Case).options(
        joinedload(Case.case_reports).joinedload(CaseReport.report),
        joinedload(Case.assigned_to),
        joinedload(Case.created_by_user),
        joinedload(Case.location),
        joinedload(Case.incident_type)
    ).filter(Case.case_id == cid).first()

    if not case:
        raise HTTPException(404, "Case not found")

    # Check permissions
    role = getattr(current_user, "role", None)
    if role == "admin":
        pass  # Admin can access any case
    elif role == "supervisor":
        supervisor_location_ids = _all_location_ids_for_scope(db, getattr(current_user, "station_id", None))
        if case.location_id and case.location_id not in supervisor_location_ids:
            raise HTTPException(403, "Access denied: case outside your jurisdiction")
    elif role == "officer":
        if case.assigned_to_id != current_user.police_user_id:
            raise HTTPException(403, "Access denied: case not assigned to you")
    else:
        raise HTTPException(403, "Access denied")

    # Find and remove the case-report link
    case_report = db.query(CaseReport).filter(
        CaseReport.case_id == cid,
        CaseReport.report_id == rid
    ).first()

    if not case_report:
        raise HTTPException(404, "Report not found in this case")

    db.delete(case_report)
    
    # Update case report count
    case.report_count = max(0, case.report_count - 1)
    
    db.commit()

    # Refresh case data
    db.refresh(case)

    # Broadcast updates
    background_tasks.add_task(
        manager.broadcast,
        {"type": "refresh_data", "entity": "case", "action": "updated"},
    )
    background_tasks.add_task(
        manager.broadcast,
        {"type": "refresh_data", "entity": "report", "action": "updated"},
    )

    return _case_to_response(case)


@router.post("/reports/{report_id}/move", response_model=CaseResponse)
def move_report_to_case(
    report_id: str,
    target_case_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Move a report from its current case to a different case.
    
    - Admin: any case.
    - Supervisor: only cases in their location.
    - Officer: only cases assigned to them.
    """
    from uuid import UUID

    try:
        rid = UUID(report_id)
    except ValueError:
        raise HTTPException(404, "Report not found")

    try:
        target_cid = UUID(target_case_id)
    except ValueError:
        raise HTTPException(404, "Target case not found")

    # Find the report
    report = db.query(Report).filter(Report.report_id == rid).first()
    if not report:
        raise HTTPException(404, "Report not found")

    # Find current case (if any)
    current_case_report = db.query(CaseReport).filter(CaseReport.report_id == rid).first()
    current_case = None
    if current_case_report:
        current_case = db.query(Case).options(
            joinedload(Case.case_reports).joinedload(CaseReport.report),
            joinedload(Case.assigned_to),
            joinedload(Case.created_by_user),
            joinedload(Case.location),
            joinedload(Case.incident_type)
        ).filter(Case.case_id == current_case_report.case_id).first()

    # Find target case
    target_case = db.query(Case).options(
        joinedload(Case.case_reports).joinedload(CaseReport.report),
        joinedload(Case.assigned_to),
        joinedload(Case.created_by_user),
        joinedload(Case.location),
        joinedload(Case.incident_type)
    ).filter(Case.case_id == target_cid).first()

    if not target_case:
        raise HTTPException(404, "Target case not found")

    # Check permissions for both current and target cases
    role = getattr(current_user, "role", None)
    
    def check_case_access(case, case_name):
        if role == "admin":
            return  # Admin can access any case
        elif role == "supervisor":
            supervisor_location_ids = _all_location_ids_for_scope(db, getattr(current_user, "station_id", None))
            if case.location_id and case.location_id not in supervisor_location_ids:
                raise HTTPException(403, f"Access denied: {case_name} outside your jurisdiction")
        elif role == "officer":
            if case.assigned_to_id != current_user.police_user_id:
                raise HTTPException(403, f"Access denied: {case_name} not assigned to you")
        else:
            raise HTTPException(403, "Access denied")

    # Check access to current case (if exists)
    if current_case:
        check_case_access(current_case, "current case")
    
    # Check access to target case
    check_case_access(target_case, "target case")

    # Validate incident type matching
    if report.incident_type_id != target_case.incident_type_id:
        raise HTTPException(
            400, 
            f"Cannot link report to case: incident type mismatch. "
            f"Report incident type ID: {report.incident_type_id}, "
            f"Case incident type ID: {target_case.incident_type_id}"
        )

    # If report is already in target case, do nothing
    if current_case_report and current_case_report.case_id == target_cid:
        return _case_to_response(target_case)

    # Remove from current case (if exists)
    if current_case_report:
        db.delete(current_case_report)
        if current_case:
            current_case.report_count = max(0, current_case.report_count - 1)

    # Add to target case
    new_case_report = CaseReport(case_id=target_cid, report_id=rid)
    db.add(new_case_report)
    target_case.report_count += 1

    db.commit()

    # Refresh target case data
    db.refresh(target_case)

    # Broadcast updates
    background_tasks.add_task(
        manager.broadcast,
        {"type": "refresh_data", "entity": "case", "action": "updated"},
    )
    background_tasks.add_task(
        manager.broadcast,
        {"type": "refresh_data", "entity": "report", "action": "updated"},
    )

    return _case_to_response(target_case)


@router.post("/{case_id}/reports", response_model=CaseResponse)
def add_reports_to_case(
    case_id: str,
    payload: CaseAddReports,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
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
    if current_user.role == "supervisor":
        station_id = _require_supervisor_station_id(current_user)
        assigned_location_id = getattr(current_user, "assigned_location_id", None)
        if assigned_location_id is not None:
            query = query.filter(
                or_(
                    Case.assigned_to.has(PoliceUser.station_id == station_id),
                    Case.location_id == assigned_location_id,
                )
            )
        else:
            query = query.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))
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
            
            # Validate incident type matching
            if report.incident_type_id != case.incident_type_id:
                raise HTTPException(
                    400, 
                    f"Cannot link report to case: incident type mismatch. "
                    f"Report incident type ID: {report.incident_type_id}, "
                    f"Case incident type ID: {case.incident_type_id}"
                )
            
            # Check if report is already assigned to a different case
            existing_case_report = db.query(CaseReport).filter(CaseReport.report_id == rid).first()
            if existing_case_report:
                raise HTTPException(
                    400,
                    f"Report is already linked to another case. Use the move functionality instead."
                )
            
            if current_user.role == "supervisor":
                station_id, location_ids = _supervisor_scope(current_user, db)
                if not _report_in_supervisor_scope(report, station_id, location_ids, db):
                    raise HTTPException(
                        status_code=403,
                        detail="You can only link reports from your station/location",
                    )
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
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "case", "action": "updated"})
    
    case = db.query(Case).options(
        joinedload(Case.location),
        joinedload(Case.incident_type),
        joinedload(Case.assigned_to),
    ).filter(Case.case_id == cid).first()
    return _case_to_response(case)
