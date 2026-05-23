from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Annotated, List

from app.database import get_db
from app.models.special_assignment_unit import SpecialAssignmentUnit
from app.models.deployment_decision import DeploymentDecision
from app.models.case import Case
from app.models.incident_type import IncidentType
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_user, get_current_admin_or_supervisor
from app.schemas.special_assignment_unit import (
    SpecialAssignmentUnitCreate,
    SpecialAssignmentUnitUpdate,
)

router = APIRouter()


def _commander_label(user: PoliceUser | None) -> str | None:
    if not user:
        return None
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    badge = (user.badge_number or "").strip()
    if name and badge:
        return f"{name} ({badge})"
    return name or badge or user.email


def _unit_dict(unit: SpecialAssignmentUnit) -> dict:
    commander = getattr(unit, "commander", None)
    return {
        "unit_id": unit.unit_id,
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "description": unit.description,
        "is_active": unit.is_active,
        "requires_commander_approval": unit.requires_commander_approval,
        "commander_user_id": unit.commander_user_id,
        "commander_name": _commander_label(commander),
        "commander_role": getattr(commander, "role", None) if commander else None,
    }


def _require_unit_manager(current_user: PoliceUser) -> None:
    """Admin and supervisors manage units; officers can list only."""
    if getattr(current_user, "role", None) not in ("admin", "supervisor"):
        raise HTTPException(
            status_code=403,
            detail="Only admins and supervisors can manage assignment units",
        )


def _validate_commander(db: Session, commander_user_id: int | None) -> None:
    if commander_user_id is None:
        return
    user = (
        db.query(PoliceUser)
        .filter(
            PoliceUser.police_user_id == commander_user_id,
            PoliceUser.is_active.is_(True),
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=400, detail="Selected commander not found or inactive")
    if user.role not in ("supervisor", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Unit commander must be a supervisor or admin account",
        )


@router.get("/", response_model=List[dict])
def get_special_assignment_units(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """List special assignment units (used by case edit, incident types, deployments)."""
    query = db.query(SpecialAssignmentUnit).options(joinedload(SpecialAssignmentUnit.commander))
    if active_only:
        query = query.filter(SpecialAssignmentUnit.is_active.is_(True))
    units = query.order_by(SpecialAssignmentUnit.unit_name).offset(skip).limit(limit).all()
    return [_unit_dict(u) for u in units]


@router.get("/commander-candidates", response_model=List[dict])
def list_commander_candidates(
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    """Supervisors and admins eligible to be assigned as unit commanders."""
    users = (
        db.query(PoliceUser)
        .filter(
            PoliceUser.is_active.is_(True),
            PoliceUser.role.in_(("supervisor", "admin")),
        )
        .order_by(PoliceUser.first_name, PoliceUser.last_name)
        .all()
    )
    return [
        {
            "police_user_id": u.police_user_id,
            "label": _commander_label(u) or u.email,
            "role": u.role,
            "station_id": u.station_id,
        }
        for u in users
    ]


@router.post("/", response_model=dict, status_code=201)
def create_special_assignment_unit(
    payload: SpecialAssignmentUnitCreate,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Create a new special assignment unit (admin or supervisor)."""
    _require_unit_manager(current_user)
    code = payload.unit_code.strip().upper().replace(" ", "_")
    existing = (
        db.query(SpecialAssignmentUnit)
        .filter(SpecialAssignmentUnit.unit_code == code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Unit code '{code}' already exists")

    _validate_commander(db, payload.commander_user_id)

    unit = SpecialAssignmentUnit(
        unit_code=code,
        unit_name=payload.unit_name.strip(),
        description=(payload.description or "").strip() or None,
        requires_commander_approval=payload.requires_commander_approval,
        commander_user_id=payload.commander_user_id,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    unit = (
        db.query(SpecialAssignmentUnit)
        .options(joinedload(SpecialAssignmentUnit.commander))
        .filter(SpecialAssignmentUnit.unit_id == unit.unit_id)
        .first()
    )
    return _unit_dict(unit)


@router.patch("/{unit_id}", response_model=dict)
def update_special_assignment_unit(
    unit_id: int,
    payload: SpecialAssignmentUnitUpdate,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Update unit metadata or active flag (admin or supervisor)."""
    _require_unit_manager(current_user)
    unit = db.query(SpecialAssignmentUnit).filter(SpecialAssignmentUnit.unit_id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    if payload.unit_name is not None:
        unit.unit_name = payload.unit_name.strip()
    if payload.description is not None:
        unit.description = payload.description.strip() or None
    if payload.is_active is not None:
        unit.is_active = payload.is_active
    if payload.requires_commander_approval is not None:
        unit.requires_commander_approval = payload.requires_commander_approval
    updates = payload.model_dump(exclude_unset=True)
    if "commander_user_id" in updates:
        commander_id = updates["commander_user_id"]
        if commander_id is not None:
            _validate_commander(db, commander_id)
        unit.commander_user_id = commander_id

    db.commit()
    db.refresh(unit)
    unit = (
        db.query(SpecialAssignmentUnit)
        .options(joinedload(SpecialAssignmentUnit.commander))
        .filter(SpecialAssignmentUnit.unit_id == unit.unit_id)
        .first()
    )
    return _unit_dict(unit)


@router.delete("/{unit_id}", status_code=204)
def delete_special_assignment_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Permanently remove a unit when it is not referenced on cases, types, or deployments."""
    _require_unit_manager(current_user)
    unit = db.query(SpecialAssignmentUnit).filter(SpecialAssignmentUnit.unit_id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    code = unit.unit_code
    refs: list[str] = []
    if db.query(Case.case_id).filter(Case.special_assignment_unit == code).first():
        refs.append("cases")
    if (
        db.query(IncidentType.incident_type_id)
        .filter(IncidentType.default_special_assignment_unit == code)
        .first()
    ):
        refs.append("incident types")
    if db.query(DeploymentDecision.decision_id).filter(DeploymentDecision.assigned_unit == code).first():
        refs.append("deployment decisions")

    if refs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete unit '{code}': it is still used on {', '.join(refs)}. "
                "Deactivate the unit instead, or remove it from those records first."
            ),
        )

    db.delete(unit)
    db.commit()
    return None


@router.get("/deployment-stats", response_model=dict)
def get_deployment_stats(
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Deployment counts grouped by assigned unit code."""
    from sqlalchemy import func

    stats = (
        db.query(
            DeploymentDecision.assigned_unit,
            func.count(DeploymentDecision.decision_id).label("deployment_count"),
        )
        .filter(DeploymentDecision.assigned_unit.isnot(None))
        .group_by(DeploymentDecision.assigned_unit)
        .all()
    )
    return {
        "deployment_stats": [
            {"unit_code": stat.assigned_unit, "deployment_count": stat.deployment_count}
            for stat in stats
        ]
    }
