from uuid import uuid4
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import Notification
from app.api.v1.auth import get_current_user
from app.models.police_user import PoliceUser
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def create_notification(
    db: Session,
    police_user_id: int,
    title: str,
    message: str | None = None,
    notif_type: str = "assignment",
    related_entity_type: str | None = "report",
    related_entity_id: str | None = None,
) -> Notification:
    n = Notification(
        notification_id=uuid4(),
        police_user_id=police_user_id,
        title=title,
        message=message,
        type=notif_type,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    db.add(n)
    return n


@router.get("/", response_model=List[NotificationResponse])
def list_notifications(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = 50,
    unread_only: bool = False,
):
    """List notifications for the current user (unread first)."""
    query = db.query(Notification).filter(Notification.police_user_id == current_user.police_user_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return count of unread notifications (for badge)."""
    from sqlalchemy import func
    count = (
        db.query(func.count(Notification.notification_id))
        .filter(
            Notification.police_user_id == current_user.police_user_id,
            Notification.is_read == False,
        )
        .scalar()
        or 0
    )
    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Mark a notification as read."""
    from uuid import UUID
    try:
        nid = UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")
    notif = (
        db.query(Notification)
        .filter(
            Notification.notification_id == nid,
            Notification.police_user_id == current_user.police_user_id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif
