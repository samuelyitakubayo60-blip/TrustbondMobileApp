from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_admin
from app.core.security import get_password_hash
from app.database import get_db
from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.local_leader_auth_code import LocalLeaderAuthCode
from app.schemas.local_leader import LocalLeaderCreate, LocalLeaderResponse, LocalLeaderUpdate
from app.core.sms import send_esms_sms
import secrets
from datetime import datetime, timezone, timedelta


router = APIRouter(prefix="/local-leaders", tags=["local-leaders"])


def _to_response(db: Session, leader: LocalLeader) -> LocalLeaderResponse:
    loc_rows = (
        db.query(LocalLeaderCoverageLocation.location_id)
        .filter(LocalLeaderCoverageLocation.local_leader_id == leader.local_leader_id)
        .all()
    )
    covered_ids = [int(r[0]) for r in loc_rows if r and r[0] is not None]
    names = []
    if covered_ids:
        name_rows = (
            db.query(Location.location_name)
            .filter(Location.location_id.in_(covered_ids))
            .all()
        )
        names = [str(r[0]) for r in name_rows if r and r[0] is not None]
    return LocalLeaderResponse(
        local_leader_id=leader.local_leader_id,
        full_name=leader.full_name,
        phone_number=leader.phone_number,
        email=leader.email,
        is_active=bool(leader.is_active),
        covered_location_ids=covered_ids,
        covered_location_names=names,
        created_at=leader.created_at,
        last_login_at=leader.last_login_at,
    )


def _replace_coverage(db: Session, leader_id: int, location_ids: list[int]) -> None:
    deduped = sorted({int(x) for x in location_ids if x is not None})
    # validate locations exist and are active
    if deduped:
        valid = {
            int(r[0])
            for r in db.query(Location.location_id)
            .filter(Location.location_id.in_(deduped), Location.is_active.is_(True))
            .all()
        }
    else:
        valid = set()

    db.query(LocalLeaderCoverageLocation).filter(
        LocalLeaderCoverageLocation.local_leader_id == leader_id
    ).delete()
    for lid in sorted(valid):
        db.add(LocalLeaderCoverageLocation(local_leader_id=leader_id, location_id=lid))


@router.get("/", response_model=list[LocalLeaderResponse])
def list_local_leaders(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
    limit: int = Query(200, ge=1, le=500),
):
    rows = db.query(LocalLeader).order_by(LocalLeader.full_name.asc()).limit(limit).all()
    return [_to_response(db, r) for r in rows]


@router.post("/", response_model=LocalLeaderResponse, status_code=201)
def create_local_leader(
    payload: LocalLeaderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    phone = (payload.phone_number or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number is required")
    if db.query(LocalLeader).filter(LocalLeader.phone_number == phone).first():
        raise HTTPException(status_code=409, detail="phone_number already exists")

    leader = LocalLeader(
        full_name=payload.full_name.strip(),
        phone_number=phone,
        email=(payload.email.strip().lower() if payload.email else None),
        password_hash=get_password_hash(secrets.token_urlsafe(16)),
        is_active=True,
    )
    db.add(leader)
    db.commit()
    db.refresh(leader)

    _replace_coverage(db, leader.local_leader_id, payload.covered_location_ids)
    db.commit()

    return _to_response(db, leader)


@router.put("/{local_leader_id}", response_model=LocalLeaderResponse)
def update_local_leader(
    local_leader_id: int,
    payload: LocalLeaderUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == local_leader_id).first()
    if not leader:
        raise HTTPException(status_code=404, detail="Local leader not found")

    if payload.full_name is not None:
        leader.full_name = payload.full_name.strip()
    if payload.phone_number is not None:
        phone = payload.phone_number.strip()
        if phone and phone != leader.phone_number:
            if db.query(LocalLeader).filter(LocalLeader.phone_number == phone).first():
                raise HTTPException(status_code=409, detail="phone_number already exists")
            leader.phone_number = phone
    if payload.email is not None:
        leader.email = payload.email.strip().lower() if payload.email else None
    if payload.is_active is not None:
        leader.is_active = bool(payload.is_active)
    if payload.password is not None:
        leader.password_hash = get_password_hash(payload.password)
    if payload.covered_location_ids is not None:
        _replace_coverage(db, leader.local_leader_id, payload.covered_location_ids)

    db.add(leader)
    db.commit()
    return _to_response(db, leader)


@router.delete("/{local_leader_id}", status_code=204)
def delete_local_leader(
    local_leader_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == local_leader_id).first()
    if not leader:
        raise HTTPException(status_code=404, detail="Local leader not found")
    db.delete(leader)
    db.commit()
    return None


@router.post("/{local_leader_id}/send-setup-code")
def send_setup_code(
    local_leader_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == local_leader_id).first()
    if not leader:
        raise HTTPException(status_code=404, detail="Local leader not found")
    if not leader.is_active:
        raise HTTPException(status_code=400, detail="Local leader is inactive")

    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
        LocalLeaderAuthCode.purpose == "password_setup",
        LocalLeaderAuthCode.used_at.is_(None),
    ).delete()

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    row = LocalLeaderAuthCode(
        local_leader_id=leader.local_leader_id,
        phone_number=leader.phone_number,
        code=code,
        purpose="password_setup",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()

    ok, err = send_esms_sms(
        leader.phone_number,
        f"TrustBond setup code: {code}. Expires in 10 minutes.",
    )
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Failed to send setup code SMS.")
    return {"message": "Setup code generated and queued for SMS delivery."}

