from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Annotated, List

from app.database import get_db
from app.models.special_assignment_unit import SpecialAssignmentUnit
from app.models.deployment_decision import DeploymentDecision
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_user
from app.schemas.special_assignment_unit import (
    SpecialAssignmentUnitCreate,
    SpecialAssignmentUnitUpdate,
)

router = APIRouter()


def _unit_dict(unit: SpecialAssignmentUnit) -> dict:
    return {
        "unit_id": unit.unit_id,
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "description": unit.description,
        "is_active": unit.is_active,
        "requires_commander_approval": unit.requires_commander_approval,
    }


def _require_admin(current_user: PoliceUser) -> None:
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage special assignment units")


@router.get("/", response_model=List[dict])
def get_special_assignment_units(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """List special assignment units (used by case edit, incident types, deployments)."""
    query = db.query(SpecialAssignmentUnit)
    if active_only:
        query = query.filter(SpecialAssignmentUnit.is_active.is_(True))
    units = query.order_by(SpecialAssignmentUnit.unit_name).offset(skip).limit(limit).all()
    return [_unit_dict(u) for u in units]


@router.post("/", response_model=dict, status_code=201)
def create_special_assignment_unit(
    payload: SpecialAssignmentUnitCreate,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Create a new special assignment unit (admin only)."""
    _require_admin(current_user)
    code = payload.unit_code.strip().upper().replace(" ", "_")
    existing = (
        db.query(SpecialAssignmentUnit)
        .filter(SpecialAssignmentUnit.unit_code == code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Unit code '{code}' already exists")

    unit = SpecialAssignmentUnit(
        unit_code=code,
        unit_name=payload.unit_name.strip(),
        description=(payload.description or "").strip() or None,
        requires_commander_approval=payload.requires_commander_approval,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return _unit_dict(unit)


@router.patch("/{unit_id}", response_model=dict)
def update_special_assignment_unit(
    unit_id: int,
    payload: SpecialAssignmentUnitUpdate,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Update unit metadata or active flag (admin only)."""
    _require_admin(current_user)
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

    db.commit()
    db.refresh(unit)
    return _unit_dict(unit)


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
