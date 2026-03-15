import secrets
from typing import Annotated, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.v1.auth import get_current_admin, get_current_admin_or_supervisor, get_current_user
from app.core.security import get_password_hash
from app.core.email import is_smtp_configured, send_new_user_credentials
from app.database import get_db
from app.models.police_user import PoliceUser
from app.models.station import Station
from app.models.police_review import PoliceReview
from app.schemas.police_user import PoliceUserCreate, PoliceUserResponse, PoliceUserUpdate
from app.models.user_session import UserSession

# Badge prefix per role: ADMIN-001, Officer-001, Supervisor-001
ROLE_BADGE_PREFIX = {"admin": "ADMIN", "officer": "Officer", "supervisor": "Supervisor"}

router = APIRouter(prefix="/police-users", tags=["police-users"])


class OfficerOption(BaseModel):
    police_user_id: int
    first_name: str
    last_name: str
    email: str

    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    session_id: str
    police_user_id: int
    user_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    limit: int = Query(100, le=500),
):
    """
    List recent user sessions for security review.

    - Admin: all users' sessions.
    - Supervisor: only sessions for users in their own station (plus themselves).
    """
    q = db.query(UserSession, PoliceUser).join(
        PoliceUser, PoliceUser.police_user_id == UserSession.police_user_id
    )

    if current_user.role == "supervisor" and current_user.station_id is not None:
        q = q.filter(
            (PoliceUser.station_id == current_user.station_id)
            | (PoliceUser.police_user_id == current_user.police_user_id)
        )

    rows = (
        q.order_by(UserSession.created_at.desc())
        .limit(limit)
        .all()
    )
    results: List[SessionResponse] = []
    for sess, user in rows:
        results.append(
            SessionResponse(
                session_id=str(sess.session_id),
                police_user_id=sess.police_user_id,
                user_name=f"{user.first_name} {user.last_name}" if user else None,
                ip_address=sess.ip_address,
                user_agent=sess.user_agent,
                created_at=sess.created_at,
                expires_at=sess.expires_at,
                revoked_at=sess.revoked_at,
            )
        )
    return results


@router.get("/options", response_model=List[OfficerOption])
def list_officer_options(
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """
    Minimal list of active officers (for assignment dropdown).

    - Admin: all active officers.
    - Supervisor: only active officers in their station.
    - Officer: only themselves.
    """
    query = db.query(PoliceUser).filter(PoliceUser.is_active == True)

    if current_user.role == "supervisor":
        if current_user.station_id is not None:
            query = query.filter(PoliceUser.station_id == current_user.station_id)
    elif current_user.role == "officer":
        query = query.filter(PoliceUser.police_user_id == current_user.police_user_id)

    users = query.order_by(PoliceUser.first_name, PoliceUser.last_name).all()
    return [
        OfficerOption(
            police_user_id=u.police_user_id,
            first_name=u.first_name,
            last_name=u.last_name,
            email=u.email,
        )
        for u in users
    ]


@router.get("/", response_model=List[PoliceUserResponse])
def list_police_users(
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    skip: int = 0,
    limit: int = Query(50, le=200),
):
    query = db.query(PoliceUser)

    # Supervisors see only officers in their own station/area.
    if current_user.role == "supervisor" and current_user.station_id is not None:
        query = query.filter(PoliceUser.station_id == current_user.station_id)

    users = (
        query.order_by(PoliceUser.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return users


@router.get("/review-stats")
def get_officer_review_stats(
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    """
    Return per-officer review counts (number of police_reviews per police_user_id).
    Used by the Users screen to show Reviews column.
    """
    rows = (
        db.query(PoliceReview.police_user_id, func.count(PoliceReview.review_id))
        .group_by(PoliceReview.police_user_id)
        .all()
    )
    return {user_id: int(count) for user_id, count in rows}


@router.post("/", response_model=PoliceUserResponse, status_code=status.HTTP_201_CREATED)
def create_police_user(
    payload: PoliceUserCreate,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    # Require SMTP so credentials email is never skipped
    if not is_smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP is not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASS in .env to create users and send credentials by email.",
        )

    # Ensure email uniqueness
    existing = db.query(PoliceUser).filter(PoliceUser.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")

    raw_password = secrets.token_urlsafe(12)

    user = PoliceUser(
        first_name=payload.first_name,
        middle_name=payload.middle_name,
        last_name=payload.last_name,
        email=payload.email,
        phone_number=payload.phone_number,
        password_hash=get_password_hash(raw_password),
        badge_number=None,  # set after flush (sequential)
        role=payload.role,
        assigned_location_id=payload.assigned_location_id,
        is_active=payload.is_active,
    )
    db.add(user)
    db.flush()
    # Badge by role: ADMIN-001, Officer-001, Supervisor-001 (per-role sequence)
    prefix = ROLE_BADGE_PREFIX.get(payload.role, "Officer")
    count = db.query(PoliceUser).filter(PoliceUser.role == payload.role).count()
    user.badge_number = f"{prefix}-{count:03d}"

    # Send credentials email before committing; do not create user if email fails
    sent, email_error = send_new_user_credentials(
        to_email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        login_email=payload.email,
        temporary_password=raw_password,
        role=payload.role,
        badge_number=user.badge_number,
    )
    if not sent:
        db.rollback()
        detail = "Failed to send credentials email. User was not created."
        if email_error:
            detail += f" SMTP error: {email_error}"
        else:
            detail += " Check SMTP_HOST, SMTP_PORT (587 or 465), SMTP_USER, SMTP_PASS in .env."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

    # If station_id is provided, link station and derive assigned_location_id from it.
    if payload.station_id is not None:
        station = db.query(Station).get(payload.station_id)
        if not station:
            db.rollback()
            raise HTTPException(status_code=400, detail="Invalid station_id")
        user.station_id = station.station_id
        if station.location_id:
            user.assigned_location_id = station.location_id

    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=PoliceUserResponse)
def update_police_user(
    user_id: int,
    payload: PoliceUserUpdate,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Supervisor: limited management, only within their own station.
    if current_user.role == "supervisor":
        # Cannot modify admins at all.
        if user.role == "admin":
            raise HTTPException(status_code=403, detail="Cannot modify admin users")

        # Can only manage users in their own station (if they have one).
        if current_user.station_id is not None and user.station_id != current_user.station_id:
            raise HTTPException(status_code=403, detail="You can only manage users in your station")

        # Allowed fields: first/last name, phone, active flag. No role / station / badge / email changes.
        if payload.first_name is not None:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        if payload.phone_number is not None:
            user.phone_number = payload.phone_number
        if payload.is_active is not None:
            user.is_active = payload.is_active

        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    # Admin: full update
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin or supervisor access required")

    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.middle_name is not None:
        user.middle_name = payload.middle_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    if payload.phone_number is not None:
        user.phone_number = payload.phone_number
    if payload.badge_number is not None:
        user.badge_number = payload.badge_number
    if payload.role is not None:
        user.role = payload.role
    if payload.assigned_location_id is not None:
        user.assigned_location_id = payload.assigned_location_id
    if payload.station_id is not None:
        if payload.station_id is None:
            user.station_id = None
        else:
            station = db.query(Station).get(payload.station_id)
            if not station:
                raise HTTPException(status_code=400, detail="Invalid station_id")
            user.station_id = station.station_id
            if station.location_id:
                user.assigned_location_id = station.location_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.password_hash = get_password_hash(payload.password)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=PoliceUserResponse)
def get_police_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_police_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """Delete a user. Admin only."""
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
def admin_reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """
    Admin-only: reset a user's password to a new random value and email it.
    """
    if not is_smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP is not configured. Cannot reset passwords from the admin panel.",
        )

    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    raw_password = secrets.token_urlsafe(12)
    user.password_hash = get_password_hash(raw_password)
    db.add(user)

    sent, email_error = send_new_user_credentials(
        to_email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        login_email=user.email,
        temporary_password=raw_password,
        role=user.role,
        badge_number=user.badge_number or "",
    )
    if not sent:
        db.rollback()
        detail = "Failed to send reset password email."
        if email_error:
            detail += f" SMTP error: {email_error}"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

    db.commit()
    return {"message": "Temporary password sent to user's email."}


@router.post("/{user_id}/revoke-sessions", status_code=status.HTTP_200_OK)
def admin_revoke_user_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """
    Admin-only: revoke all active sessions for the specified user.
    """
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    (
        db.query(UserSession)
        .filter(
            UserSession.police_user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .update({UserSession.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"message": "All active sessions for this user have been revoked."}

