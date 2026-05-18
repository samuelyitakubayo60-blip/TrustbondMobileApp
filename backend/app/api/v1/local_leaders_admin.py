from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_admin
from app.core.email import is_smtp_configured
from app.core.security import get_password_hash
from app.database import get_db
from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.local_leader_auth_code import LocalLeaderAuthCode
from app.models.report import Report
from app.schemas.local_leader import (
    VALID_LEADER_ROLES,
    LEADER_ROLE_CHIEF_OF_VILLAGE,
    LEADER_ROLE_EXECUTIVE_OF_CELL,
    LeaderCoverageGapItem,
    LeaderCoverageGapsResponse,
    LocalLeaderCreate,
    LocalLeaderResponse,
    LocalLeaderUpdate,
)
from app.core.leader_coverage import find_leader_coverage_gaps


router = APIRouter(prefix="/local-leaders", tags=["local-leaders"])

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_rw_phone(raw: str) -> str:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if not digits:
        raise HTTPException(status_code=400, detail="Invalid phone number.")
    if digits.startswith("250"):
        n = digits
    elif digits.startswith("0"):
        n = "250" + digits[1:]
    else:
        n = "250" + digits
    if len(n) != 12 or not n.startswith("2507"):
        raise HTTPException(status_code=400, detail="Phone must be a valid Rwandan mobile number (e.g. +2507XXXXXXXX).")
    return n


def _validate_role_and_coverage(db: Session, role: str, location_ids: list[int] | None) -> list[int]:
    if role not in VALID_LEADER_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Invalid role. Use chief_of_village (village chief) or executive_of_cell (cell executive).",
        )
    if not location_ids or len(location_ids) != 1:
        raise HTTPException(status_code=400, detail="Select exactly one village or one cell based on the role.")
    lid = int(location_ids[0])
    loc = db.query(Location).filter(Location.location_id == lid, Location.is_active.is_(True)).first()
    if not loc:
        raise HTTPException(status_code=400, detail="Invalid or inactive location.")
    if role == LEADER_ROLE_CHIEF_OF_VILLAGE and loc.location_type != "village":
        raise HTTPException(status_code=400, detail="A village chief must be assigned to a village.")
    if role == LEADER_ROLE_EXECUTIVE_OF_CELL and loc.location_type != "cell":
        raise HTTPException(status_code=400, detail="A cell executive must be assigned to a cell.")
    return [lid]


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
        role=leader.role,
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


@router.get("/coverage-gaps", response_model=LeaderCoverageGapsResponse)
def list_leader_coverage_gaps(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
    limit: int = Query(200, ge=1, le=1000),
):
    """Villages/cells with no active local leader registered (admin warning)."""
    raw = find_leader_coverage_gaps(db, limit=limit)
    items = [LeaderCoverageGapItem(**row) for row in raw]
    return LeaderCoverageGapsResponse(items=items, total=len(items))


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
    role = (payload.role or "").strip()
    email_norm = _norm_email(payload.email)
    if not email_norm or not _EMAIL_RE.match(email_norm):
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if db.query(LocalLeader).filter(func.lower(LocalLeader.email) == email_norm).first():
        raise HTTPException(status_code=409, detail="email already exists")

    phone = None
    if payload.phone_number and str(payload.phone_number).strip():
        phone = _normalize_rw_phone(str(payload.phone_number))
        if db.query(LocalLeader).filter(LocalLeader.phone_number == phone).first():
            raise HTTPException(status_code=409, detail="phone_number already exists")

    covered = _validate_role_and_coverage(db, role, payload.covered_location_ids)

    leader = LocalLeader(
        full_name=payload.full_name.strip(),
        role=role,
        phone_number=phone,
        email=email_norm,
        password_hash=get_password_hash(secrets.token_urlsafe(16)),
        is_active=True,
    )
    db.add(leader)
    db.commit()
    db.refresh(leader)

    _replace_coverage(db, leader.local_leader_id, covered)
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

    eff_role = (payload.role.strip() if payload.role is not None else leader.role)
    if payload.role is not None:
        if eff_role not in VALID_LEADER_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role.")
        leader.role = eff_role

    if payload.phone_number is not None:
        raw = str(payload.phone_number).strip()
        if raw:
            phone = _normalize_rw_phone(raw)
            if phone != leader.phone_number:
                if db.query(LocalLeader).filter(LocalLeader.phone_number == phone).first():
                    raise HTTPException(status_code=409, detail="phone_number already exists")
            leader.phone_number = phone
        else:
            leader.phone_number = None

    if payload.email is not None:
        email_norm = _norm_email(payload.email)
        if not email_norm:
            leader.email = None
        else:
            if not _EMAIL_RE.match(email_norm):
                raise HTTPException(status_code=400, detail="Invalid email address.")
            if email_norm != _norm_email(leader.email or ""):
                if db.query(LocalLeader).filter(func.lower(LocalLeader.email) == email_norm).first():
                    raise HTTPException(status_code=409, detail="email already exists")
            leader.email = email_norm

    if payload.is_active is not None:
        leader.is_active = bool(payload.is_active)
    if payload.password is not None:
        leader.password_hash = get_password_hash(payload.password)

    if payload.covered_location_ids is not None:
        covered = _validate_role_and_coverage(db, eff_role, payload.covered_location_ids)
        _replace_coverage(db, leader.local_leader_id, covered)
    elif payload.role is not None:
        cur = [
            int(r[0])
            for r in db.query(LocalLeaderCoverageLocation.location_id)
            .filter(LocalLeaderCoverageLocation.local_leader_id == leader.local_leader_id)
            .all()
        ]
        if cur:
            _validate_role_and_coverage(db, eff_role, cur)

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
    lid = int(local_leader_id)
    # ORM delete() would nullify child FKs first; coverage uses NOT NULL + we want CASCADE semantics.
    db.query(LocalLeaderCoverageLocation).filter(
        LocalLeaderCoverageLocation.local_leader_id == lid
    ).delete(synchronize_session=False)
    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == lid
    ).delete(synchronize_session=False)
    # Reports reference local leaders with nullable FKs; clear so DELETE is not blocked.
    db.query(Report).filter(Report.leader_verified_by == lid).update(
        {Report.leader_verified_by: None},
        synchronize_session=False,
    )
    db.query(Report).filter(Report.submitted_by_local_leader_id == lid).update(
        {Report.submitted_by_local_leader_id: None},
        synchronize_session=False,
    )
    db.delete(leader)
    db.commit()
    return None


"""
Admin OTP sending removed:
Local leaders must request setup/login codes themselves via /api/v1/leader-auth/request-setup-code
and /api/v1/leader-auth/request-login-code.
"""
