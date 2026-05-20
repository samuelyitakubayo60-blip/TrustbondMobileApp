from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.deployment_decision import DeploymentDecision, SuspectVictimTracking
from app.models.report import Report
from app.models.case import Case
from app.models.police_user import PoliceUser
from app.models.local_leader import LocalLeader
from app.schemas.deployment_decision import (
    DeploymentDecisionCreate, DeploymentDecisionUpdate, DeploymentDecisionResponse,
    SuspectVictimCreate, SuspectVictimUpdate, SuspectVictimResponse,
    CommanderDashboardIncident, LeaderMobileIncident
)
from app.api.v1.auth import get_current_user, get_current_admin_or_supervisor
from app.api.v1.leader_auth import get_current_local_leader
from app.core.leader_workflow import report_meets_leader_confirmation
from app.api.v1.notifications import create_role_notifications, create_notification

router = APIRouter()


@router.get("/commander-dashboard", response_model=List[CommanderDashboardIncident])
def get_commander_dashboard(
    skip: int = 0,
    limit: int = 50,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Get incidents ready for commander deployment decisions"""
    # Only supervisors and admins (acting as station commanders) can access
    if current_user.role not in ["supervisor", "admin"]:
        raise HTTPException(status_code=403, detail="Only commanders can access deployment dashboard")
    
    # Incidents cleared for commander ops: police verified and community confirmed
    query = db.query(Report).filter(
        Report.leader_verification_status == "confirmed",
        Report.verification_status == "verified",
    )
    
    if status_filter == "pending_deployment":
        query = query.outerjoin(DeploymentDecision).filter(DeploymentDecision.decision_id.is_(None))
    elif status_filter == "deployed":
        query = query.join(DeploymentDecision).filter(DeploymentDecision.deployment_status == "deployed")
    
    reports = query.offset(skip).limit(limit).all()
    
    incidents = []
    for report in reports:
        # Get leader info
        leader_info = None
        if report.leader_verified_by:
            leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == report.leader_verified_by).first()
            if leader:
                leader_info = {"name": leader.full_name, "role": leader.role}
        
        # Get deployment decision if exists
        deployment_decision = None
        if hasattr(report, 'deployment_decisions') and report.deployment_decisions:
            decision = report.deployment_decisions[0]
            deployment_decision = DeploymentDecisionResponse(
                decision_id=decision.decision_id,
                report_id=decision.report_id,
                case_id=decision.case_id,
                decided_by=decision.decided_by,
                decided_by_name=decision.decided_by_user.first_name + " " + decision.decided_by_user.last_name if decision.decided_by_user else None,
                decided_by_role=decision.decided_by_user.role if decision.decided_by_user else None,
                deployment_status=decision.deployment_status,
                assigned_unit=decision.assigned_unit,
                deployment_priority=decision.deployment_priority,
                decision_note=decision.decision_note,
                leader_confirmation_weight=decision.leader_confirmation_weight,
                deployed_at=decision.deployed_at,
                estimated_arrival=decision.estimated_arrival,
                actual_arrival=decision.actual_arrival,
                deployment_outcome=decision.deployment_outcome,
                outcome_note=decision.outcome_note,
                created_at=decision.created_at,
                updated_at=decision.updated_at
            )
        
        incident = CommanderDashboardIncident(
            report_id=str(report.report_id),
            report_number=report.report_number,
            incident_type=report.incident_type.type_name if report.incident_type else "Unknown",
            location_description=getattr(report, 'location_description', 'Unknown location'),
            latitude=float(report.latitude),
            longitude=float(report.longitude),
            leader_verification_status=report.leader_verification_status,
            leader_verified_at=report.leader_verified_at,
            leader_name=leader_info["name"] if leader_info else None,
            leader_role=leader_info["role"] if leader_info else None,
            priority=report.priority,
            submitted_at=report.reported_at,
            deployment_decision=deployment_decision
        )
        incidents.append(incident)
    
    return incidents


@router.post("/", response_model=DeploymentDecisionResponse)
def create_deployment_decision(
    decision: DeploymentDecisionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Create a deployment decision for a leader-confirmed incident"""
    # Only supervisors and admins can make deployment decisions
    if current_user.role not in ["supervisor", "admin"]:
        raise HTTPException(status_code=403, detail="Only commanders can make deployment decisions")
    
    # Verify the report exists and is leader-confirmed
    report = db.query(Report).filter(Report.report_id == decision.report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    if report.leader_verification_status != "confirmed":
        raise HTTPException(status_code=400, detail="Report must be leader-confirmed before deployment decision")
    
    # Check if decision already exists
    existing = db.query(DeploymentDecision).filter(DeploymentDecision.report_id == decision.report_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Deployment decision already exists for this report")
    
    # Create deployment decision
    deployment_decision = DeploymentDecision(
        report_id=decision.report_id,
        case_id=decision.case_id,
        decided_by=current_user.police_user_id,
        deployment_status=decision.deployment_status,
        assigned_unit=decision.assigned_unit,
        deployment_priority=decision.deployment_priority,
        decision_note=decision.decision_note,
        leader_confirmation_weight=decision.leader_confirmation_weight
    )
    
    db.add(deployment_decision)
    db.commit()
    db.refresh(deployment_decision)
    
    # Create notifications
    if decision.deployment_status == "deployed":
        create_role_notifications(
            db=db,
            title=f"Team Deployed: {report.report_number}",
            message=f"Special unit ({decision.assigned_unit}) deployed to incident {report.report_number}",
            notif_type="deployment",
            send_email=True
        )
    
    return DeploymentDecisionResponse(
        decision_id=deployment_decision.decision_id,
        report_id=deployment_decision.report_id,
        case_id=deployment_decision.case_id,
        decided_by=deployment_decision.decided_by,
        decided_by_name=current_user.first_name + " " + current_user.last_name,
        decided_by_role=current_user.role,
        deployment_status=deployment_decision.deployment_status,
        assigned_unit=deployment_decision.assigned_unit,
        deployment_priority=deployment_decision.deployment_priority,
        decision_note=deployment_decision.decision_note,
        leader_confirmation_weight=deployment_decision.leader_confirmation_weight,
        deployed_at=deployment_decision.deployed_at,
        estimated_arrival=deployment_decision.estimated_arrival,
        actual_arrival=deployment_decision.actual_arrival,
        deployment_outcome=deployment_decision.deployment_outcome,
        outcome_note=deployment_decision.outcome_note,
        created_at=deployment_decision.created_at,
        updated_at=deployment_decision.updated_at
    )


@router.put("/{decision_id}", response_model=DeploymentDecisionResponse)
def update_deployment_decision(
    decision_id: int,
    update: DeploymentDecisionUpdate,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Update deployment decision status and outcome"""
    decision = db.query(DeploymentDecision).filter(DeploymentDecision.decision_id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Deployment decision not found")
    
    # Update fields
    if update.deployment_status is not None:
        decision.deployment_status = update.deployment_status
        if update.deployment_status == "deployed" and not decision.deployed_at:
            decision.deployed_at = datetime.now(timezone.utc)
    
    if update.assigned_unit is not None:
        decision.assigned_unit = update.assigned_unit
    if update.deployment_priority is not None:
        decision.deployment_priority = update.deployment_priority
    if update.decision_note is not None:
        decision.decision_note = update.decision_note
    if update.deployment_outcome is not None:
        decision.deployment_outcome = update.deployment_outcome
    if update.outcome_note is not None:
        decision.outcome_note = update.outcome_note
    if update.deployed_at is not None:
        decision.deployed_at = update.deployed_at
    if update.estimated_arrival is not None:
        decision.estimated_arrival = update.estimated_arrival
    if update.actual_arrival is not None:
        decision.actual_arrival = update.actual_arrival
    
    db.commit()
    db.refresh(decision)
    
    return DeploymentDecisionResponse(
        decision_id=decision.decision_id,
        report_id=decision.report_id,
        case_id=decision.case_id,
        decided_by=decision.decided_by,
        decided_by_name=decision.decided_by_user.first_name + " " + decision.decided_by_user.last_name if decision.decided_by_user else None,
        decided_by_role=decision.decided_by_user.role if decision.decided_by_user else None,
        deployment_status=decision.deployment_status,
        assigned_unit=decision.assigned_unit,
        deployment_priority=decision.deployment_priority,
        decision_note=decision.decision_note,
        leader_confirmation_weight=decision.leader_confirmation_weight,
        deployed_at=decision.deployed_at,
        estimated_arrival=decision.estimated_arrival,
        actual_arrival=decision.actual_arrival,
        deployment_outcome=decision.deployment_outcome,
        outcome_note=decision.outcome_note,
        created_at=decision.created_at,
        updated_at=decision.updated_at
    )


@router.get("/leader-mobile/{leader_id}", response_model=List[LeaderMobileIncident])
def get_leader_mobile_incidents(
    leader_id: int,
    only_pending: bool = False,
    db: Session = Depends(get_db),
    current_leader: LocalLeader = Depends(get_current_local_leader)
):
    """Get incidents for leader mobile interface"""
    # Leaders can only see their own incidents
    if current_leader.local_leader_id != leader_id:
        raise HTTPException(status_code=403, detail="Can only view your own incidents")
    
    from app.core.leader_workflow import leader_covered_village_ids, local_leader_ids_covering_village
    
    # Get incidents in leader's coverage area
    covered_villages = leader_covered_village_ids(db, leader_id)
    
    query = db.query(Report).filter(Report.village_location_id.in_(covered_villages))
    
    if only_pending:
        query = query.filter(
            (Report.leader_verification_status.is_(None)) | 
            (Report.leader_verification_status == "pending")
        )
    
    reports = query.order_by(Report.reported_at.desc()).limit(50).all()
    
    incidents = []
    for report in reports:
        incident = LeaderMobileIncident(
            report_id=str(report.report_id),
            report_number=report.report_number,
            incident_type=report.incident_type.type_name if report.incident_type else "Unknown",
            location_description=getattr(report, 'location_description', 'Unknown location'),
            latitude=float(report.latitude),
            longitude=float(report.longitude),
            description=report.description or "",
            priority=report.priority,
            submitted_at=report.reported_at,
            leader_verification_status=report.leader_verification_status or "pending",
            needs_verification=(report.leader_verification_status or "pending") == "pending"
        )
        incidents.append(incident)
    
    return incidents


# Suspect/Victim Tracking Endpoints

@router.post("/suspect-victim/", response_model=SuspectVictimResponse)
def create_suspect_victim(
    tracking: SuspectVictimCreate,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Add suspect/victim tracking to a case"""
    # Verify case exists
    case = db.query(Case).filter(Case.case_id == tracking.case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    suspect_victim = SuspectVictimTracking(
        case_id=tracking.case_id,
        person_type=tracking.person_type,
        full_name=tracking.full_name,
        national_id=tracking.national_id,
        phone_number=tracking.phone_number,
        age=tracking.age,
        gender=tracking.gender,
        status=tracking.status,
        status_note=tracking.status_note
    )
    
    db.add(suspect_victim)
    db.commit()
    db.refresh(suspect_victim)
    
    return SuspectVictimResponse(
        tracking_id=suspect_victim.tracking_id,
        case_id=suspect_victim.case_id,
        person_type=suspect_victim.person_type,
        full_name=suspect_victim.full_name,
        national_id=suspect_victim.national_id,
        phone_number=suspect_victim.phone_number,
        age=suspect_victim.age,
        gender=suspect_victim.gender,
        status=suspect_victim.status,
        status_note=suspect_victim.status_note,
        rib_case_number=suspect_victim.rib_case_number,
        rib_handover_date=suspect_victim.rib_handover_date,
        rib_officer_name=suspect_victim.rib_officer_name,
        created_at=suspect_victim.created_at,
        updated_at=suspect_victim.updated_at
    )


@router.put("/suspect-victim/{tracking_id}", response_model=SuspectVictimResponse)
def update_suspect_victim(
    tracking_id: int,
    update: SuspectVictimUpdate,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Update suspect/victim tracking (including RIB handover)"""
    tracking = db.query(SuspectVictimTracking).filter(SuspectVictimTracking.tracking_id == tracking_id).first()
    if not tracking:
        raise HTTPException(status_code=404, detail="Tracking record not found")
    
    # Update fields
    if update.person_type is not None:
        tracking.person_type = update.person_type
    if update.full_name is not None:
        tracking.full_name = update.full_name
    if update.national_id is not None:
        tracking.national_id = update.national_id
    if update.phone_number is not None:
        tracking.phone_number = update.phone_number
    if update.age is not None:
        tracking.age = update.age
    if update.gender is not None:
        tracking.gender = update.gender
    if update.status is not None:
        tracking.status = update.status
    if update.status_note is not None:
        tracking.status_note = update.status_note
    if update.rib_case_number is not None:
        tracking.rib_case_number = update.rib_case_number
    if update.rib_handover_date is not None:
        tracking.rib_handover_date = update.rib_handover_date
    if update.rib_officer_name is not None:
        tracking.rib_officer_name = update.rib_officer_name
    
    db.commit()
    db.refresh(tracking)
    
    return SuspectVictimResponse(
        tracking_id=tracking.tracking_id,
        case_id=tracking.case_id,
        person_type=tracking.person_type,
        full_name=tracking.full_name,
        national_id=tracking.national_id,
        phone_number=tracking.phone_number,
        age=tracking.age,
        gender=tracking.gender,
        status=tracking.status,
        status_note=tracking.status_note,
        rib_case_number=tracking.rib_case_number,
        rib_handover_date=tracking.rib_handover_date,
        rib_officer_name=tracking.rib_officer_name,
        created_at=tracking.created_at,
        updated_at=tracking.updated_at
    )


@router.get("/case/{case_id}/suspect-victims", response_model=List[SuspectVictimResponse])
def get_case_suspect_victims(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: PoliceUser = Depends(get_current_admin_or_supervisor)
):
    """Get all suspect/victim tracking for a case"""
    tracking_records = db.query(SuspectVictimTracking).filter(
        SuspectVictimTracking.case_id == case_id
    ).all()
    
    return [
        SuspectVictimResponse(
            tracking_id=record.tracking_id,
            case_id=record.case_id,
            person_type=record.person_type,
            full_name=record.full_name,
            national_id=record.national_id,
            phone_number=record.phone_number,
            age=record.age,
            gender=record.gender,
            status=record.status,
            status_note=record.status_note,
            rib_case_number=record.rib_case_number,
            rib_handover_date=record.rib_handover_date,
            rib_officer_name=record.rib_officer_name,
            created_at=record.created_at,
            updated_at=record.updated_at
        )
        for record in tracking_records
    ]
