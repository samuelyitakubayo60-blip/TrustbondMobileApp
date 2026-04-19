import secrets
from typing import Annotated, List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.websocket import manager
import asyncio

from app.api.v1.auth import get_current_admin, get_current_admin_or_supervisor, get_current_user
from app.core.security import get_password_hash
from app.core.email import is_smtp_configured, send_new_user_credentials
from app.database import get_db
from app.models.police_user import PoliceUser
from app.models.station import Station
from app.models.police_review import PoliceReview
from app.models.report import Report
from app.models.location import Location
from app.schemas.police_user import (
    PoliceUserCreate,
    PoliceUserResponse,
    PoliceUserUpdate,
)
from app.models.user_session import UserSession
from app.models.report_assignment import ReportAssignment
from app.models.notification import Notification
from app.models.case import Case
from app.models.system_config import SystemConfig

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

    if current_user.role == "supervisor":
        if current_user.station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
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
    location_id: Optional[int] = Query(
        None,
        description="Optional sector/cell/village location_id to filter officers by assigned location.",
    ),
    report_id: Optional[UUID] = Query(
        None,
        description="Optional report_id; derives report sector and filters officers by that location.",
    ),
):
    """
    Minimal list of active officers (for assignment dropdown).

    - Admin: all active officers.
    - Supervisor: only active officers in their station.
    - Officer: only themselves.
    """
    query = db.query(PoliceUser).filter(PoliceUser.is_active == True)

    if current_user.role == "supervisor":
        if current_user.station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
        query = query.filter(PoliceUser.station_id == current_user.station_id)
        # Don't filter by assigned_location_id for supervisors - they should see all officers in their station
    elif current_user.role == "officer":
        query = query.filter(PoliceUser.police_user_id == current_user.police_user_id)

    derived_location_id = location_id
    if report_id is not None:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        if report.village_location_id is not None:
            loc = db.query(Location).filter(Location.location_id == report.village_location_id).first()
            # Traverse up the location hierarchy to find the sector
            while loc is not None and loc.location_type != "sector" and loc.parent_location_id:
                loc = db.query(Location).filter(Location.location_id == loc.parent_location_id).first()
            
            # Officers must be assigned at SECTOR level, not village or cell
            if loc is not None and loc.location_type == "sector":
                derived_location_id = loc.location_id
            else:
                # If we can't find a sector, don't assign to this officer
                # This ensures officers only get sector-level assignments
                derived_location_id = None

    if derived_location_id is not None:
        query = query.filter(PoliceUser.assigned_location_id == derived_location_id)
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
    station_id: Optional[int] = Query(
        None,
        description="Optional station_id to filter officers by assigned station. Admins only.",
    ),
):
    query = db.query(PoliceUser)

    # If station_id is provided, admins can filter any station, supervisors only their own
    if station_id is not None:
        if current_user.role == "admin":
            query = query.filter(PoliceUser.station_id == station_id)
        elif current_user.role == "supervisor":
            if current_user.station_id is None:
                raise HTTPException(status_code=403, detail="Supervisor station is not configured")
            if station_id != current_user.station_id:
                raise HTTPException(status_code=403, detail="Supervisors can only view their own station")
            query = query.filter(PoliceUser.station_id == station_id)
        else:
            raise HTTPException(status_code=403, detail="Only admins and supervisors can filter by station_id")
    # Supervisors see only officers in their own station/area.
    elif current_user.role == "supervisor":
        if current_user.station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
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
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    """
    Return per-officer review counts (number of police_reviews per police_user_id).
    Used by the Users screen to show Reviews column.
    """
    q = db.query(PoliceReview.police_user_id, func.count(PoliceReview.review_id)).group_by(
        PoliceReview.police_user_id
    )
    if current_user.role == "supervisor":
        if current_user.station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
        q = q.join(
            PoliceUser,
            PoliceUser.police_user_id == PoliceReview.police_user_id,
        ).filter(PoliceUser.station_id == current_user.station_id)
    rows = q.all()
    return {user_id: int(count) for user_id, count in rows}


@router.post("/", response_model=PoliceUserResponse, status_code=status.HTTP_201_CREATED)
def create_police_user(
    payload: PoliceUserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):

    existing = db.query(PoliceUser).filter(PoliceUser.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")


    resolved_location_id = payload.assigned_location_id
    if payload.assigned_location_id is not None:
        assigned_loc = db.query(Location).filter(Location.location_id == payload.assigned_location_id).first()
        if not assigned_loc:
            raise HTTPException(status_code=400, detail="Invalid assigned_location_id")
        if assigned_loc.location_type != "sector":
            raise HTTPException(
                status_code=400,
                detail="Officers must be assigned at sector level, not at village or cell level",
            )


    resolved_station_id = None
    if payload.station_id is not None:
        station = db.query(Station).get(payload.station_id)
        if not station:
            raise HTTPException(status_code=400, detail="Invalid station_id")
        resolved_station_id = station.station_id
        # Derive assigned_location_id from the station's location (must be sector level)
        if station.location_id:
            station_loc = db.query(Location).filter(Location.location_id == station.location_id).first()
            if station_loc and station_loc.location_type == "sector":
                resolved_location_id = station.location_id
            else:
                # Walk up the hierarchy to find the parent sector
                while station_loc is not None and station_loc.location_type != "sector" and station_loc.parent_location_id:
                    station_loc = db.query(Location).filter(Location.location_id == station_loc.parent_location_id).first()
                if station_loc and station_loc.location_type == "sector":
                    resolved_location_id = station_loc.location_id
                else:
                    # Fallback: use station location directly
                    resolved_location_id = station.location_id


    prefix = ROLE_BADGE_PREFIX.get(payload.role, "Officer")
    existing_count = db.query(PoliceUser).filter(PoliceUser.role == payload.role).count()
    badge_number = f"{prefix}-{existing_count + 1:03d}"


    raw_password = secrets.token_urlsafe(12)
    user = PoliceUser(
        first_name=payload.first_name,
        middle_name=payload.middle_name,
        last_name=payload.last_name,
        email=payload.email,
        phone_number=payload.phone_number,
        password_hash=get_password_hash(raw_password),
        badge_number=badge_number,
        role=payload.role,
        assigned_location_id=resolved_location_id,
        station_id=resolved_station_id,
        is_active=payload.is_active,
    )
    db.add(user)
    db.flush()  # assigns user.police_user_id; NOT yet committed

    email_warning: str | None = None
    if is_smtp_configured():
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
    else:
        # SMTP not configured - still create the user, surface a warning in logs.
        email_warning = (
            f"SMTP not configured. Credentials for '{payload.email}' were NOT emailed. "
            "Set SMTP_HOST, SMTP_USER, and SMTP_PASS in .env to enable automatic email delivery."
        )
        print(f"[create_police_user] WARNING: {email_warning}")

    db.commit()
    db.refresh(user)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "user"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "user"}))
    background_tasks.add_task(notify)

    return user


@router.put("/{user_id}", response_model=PoliceUserResponse)
def update_police_user(
    user_id: int,
    payload: PoliceUserUpdate,
    background_tasks: BackgroundTasks,
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

        def notify():
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "user"}))
            except RuntimeError:
                asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "user"}))
        background_tasks.add_task(notify)

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
        # Validate that the assigned location is at SECTOR level
        assigned_loc = db.query(Location).filter(Location.location_id == payload.assigned_location_id).first()
        if not assigned_loc:
            raise HTTPException(status_code=400, detail="Invalid assigned_location_id")
        if assigned_loc.location_type != "sector":
            raise HTTPException(status_code=400, detail="Officers must be assigned at sector level, not at village or cell level")
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
                # Verify that the station location is at sector level
                station_loc = db.query(Location).filter(Location.location_id == station.location_id).first()
                if station_loc and station_loc.location_type == "sector":
                    user.assigned_location_id = station.location_id
                else:
                    # If station location is not sector level, find its parent sector
                    while station_loc is not None and station_loc.location_type != "sector" and station_loc.parent_location_id:
                        station_loc = db.query(Location).filter(Location.location_id == station_loc.parent_location_id).first()
                    if station_loc and station_loc.location_type == "sector":
                        user.assigned_location_id = station_loc.location_id
                    else:
                        # Fallback: use station location but log warning
                        user.assigned_location_id = station.location_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.password_hash = get_password_hash(payload.password)

    db.add(user)
    db.commit()
    db.refresh(user)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "user"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "user"}))
    background_tasks.add_task(notify)

    return user


@router.get("/{user_id}", response_model=PoliceUserResponse)
def get_police_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user.role == "supervisor":
        if current_user.station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
        if user.station_id != current_user.station_id and user.police_user_id != current_user.police_user_id:
            raise HTTPException(status_code=403, detail="You can only view users in your station")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_police_user(
    user_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """Delete a user. Admin only."""
    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Handle cascading deletes / nullifications manually to satisfy DB foreign keys
    try:
        # Nullify references (set to None)
        db.query(Case).filter(Case.assigned_to_id == user_id).update({"assigned_to_id": None}, synchronize_session=False)
        db.query(Case).filter(Case.created_by == user_id).update({"created_by": None}, synchronize_session=False)
        db.query(Report).filter(Report.verified_by == user_id).update({"verified_by": None}, synchronize_session=False)
        db.query(SystemConfig).filter(SystemConfig.updated_by == user_id).update({"updated_by": None}, synchronize_session=False)

        # Delete dependent records (NOT NULL constraints)
        db.query(UserSession).filter(UserSession.police_user_id == user_id).delete(synchronize_session=False)
        db.query(ReportAssignment).filter(ReportAssignment.police_user_id == user_id).delete(synchronize_session=False)
        db.query(PoliceReview).filter(PoliceReview.police_user_id == user_id).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.police_user_id == user_id).delete(synchronize_session=False)

        # Proceed with deleting the user itself
        db.delete(user)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete user because they have strictly associated records in the database. Please deactivate the user instead. Details: {str(e)}"
        )

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "user"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "user"}))
    background_tasks.add_task(notify)


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
    background_tasks: BackgroundTasks,
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

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "session"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "session"}))
    background_tasks.add_task(notify)

    return {"message": "All active sessions for this user have been revoked."}

