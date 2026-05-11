from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.special_assignment_unit import SpecialAssignmentUnit
from app.models.deployment_decision import DeploymentDecision
from app.api.v1.auth import get_current_user

router = APIRouter()


@router.get("/", response_model=List[dict])
def get_special_assignment_units(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get all special assignment units"""
    query = db.query(SpecialAssignmentUnit)
    
    if active_only:
        query = query.filter(SpecialAssignmentUnit.is_active == True)
    
    units = query.offset(skip).limit(limit).all()
    
    return [
        {
            "unit_id": unit.unit_id,
            "unit_code": unit.unit_code,
            "unit_name": unit.unit_name,
            "description": unit.description,
            "is_active": unit.is_active,
            "requires_commander_approval": unit.requires_commander_approval
        }
        for unit in units
    ]


@router.post("/", response_model=dict)
def create_special_assignment_unit(
    unit_data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new special assignment unit (admin only)"""
    if current_user.role not in ["admin"]:
        raise HTTPException(status_code=403, detail="Only admins can create special assignment units")
    
    unit = SpecialAssignmentUnit(
        unit_code=unit_data["unit_code"],
        unit_name=unit_data["unit_name"],
        description=unit_data.get("description"),
        requires_commander_approval=unit_data.get("requires_commander_approval", True)
    )
    
    db.add(unit)
    db.commit()
    db.refresh(unit)
    
    return {
        "unit_id": unit.unit_id,
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "description": unit.description,
        "is_active": unit.is_active,
        "requires_commander_approval": unit.requires_commander_approval
    }


@router.get("/deployment-stats", response_model=dict)
def get_deployment_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get deployment statistics by unit"""
    # Count deployments by unit
    stats = db.query(
        DeploymentDecision.assigned_unit,
        db.func.count(DeploymentDecision.decision_id).label('deployment_count')
    ).filter(
        DeploymentDecision.assigned_unit.isnot(None)
    ).group_by(DeploymentDecision.assigned_unit).all()
    
    return {
        "deployment_stats": [
            {
                "unit_code": stat.assigned_unit,
                "deployment_count": stat.deployment_count
            }
            for stat in stats
        ]
    }
