from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.websocket import manager
import asyncio

from app.api.v1.auth import get_current_admin
from app.database import get_db
from app.models.police_user import PoliceUser
from app.models.system_config import SystemConfig
from app.schemas.system_config import SystemConfigItem, SystemConfigList
from app.core.credibility_model import get_effective_trust_formula


router = APIRouter(prefix="/system-config", tags=["system-config"])


@router.get("/", response_model=SystemConfigList)
def list_system_config(
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    rows = db.query(SystemConfig).order_by(SystemConfig.config_key.asc()).all()
    return SystemConfigList(items=rows)


@router.get("/{config_key}", response_model=SystemConfigItem)
def get_system_config(
    config_key: str,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    row = db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    return row


@router.put("/{config_key}", response_model=SystemConfigItem)
def update_system_config(
    config_key: str,
    payload: SystemConfigItem,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    row = db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    row.config_value = payload.config_value
    row.description = payload.description
    row.updated_by = current_admin.police_user_id
    db.add(row)
    db.commit()
    db.refresh(row)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "system"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "system"}))
    background_tasks.add_task(notify)

    return row


@router.get("/effective/trust-score-formula")
def get_effective_trust_score_formula(
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """
    Return trust_score.formula as currently applied by backend scoring:
    - raw DB JSON
    - validated + normalized weights used in compute_trust_score(...)
    """
    return get_effective_trust_formula(db)

