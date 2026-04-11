from uuid import uuid4
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.websocket import manager
from app.api.v1.ws import notification_manager
import asyncio

from app.database import get_db
from app.models.notification import Notification
from app.api.v1.auth import get_current_user
from app.models.police_user import PoliceUser
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _run_async_now_or_schedule(coro) -> None:
    """
    Run a coroutine from either sync or async context.
    - If an event loop exists, schedule it.
    - Otherwise, run it to completion synchronously.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


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
    db.commit()
    db.refresh(n)
    
    # Send real-time notification update for the target user.
    _run_async_now_or_schedule(
        notification_manager.increment_notification_count(str(police_user_id))
    )
    
    return n


def create_role_notifications(
    db: Session,
    title: str,
    message: str | None = None,
    notif_type: str = "system",
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    target_roles: List[str] | None = None,
    target_location_id: int | None = None,
    target_station_id: int | None = None,
    exclude_user_id: int | None = None,
) -> List[Notification]:
    """
    Create notifications for users based on roles, location, or station.
    
    Args:
        db: Database session
        title: Notification title
        message: Notification message
        notif_type: Type of notification
        related_entity_type: Type of related entity
        related_entity_id: ID of related entity
        target_roles: List of roles to notify (admin, supervisor, officer)
        target_location_id: Specific location ID to notify
        target_station_id: Specific station ID to notify
        exclude_user_id: User ID to exclude from notifications
    
    Returns:
        List of created notifications
    """
    from app.models.police_user import PoliceUser
    
    query = db.query(PoliceUser).filter(PoliceUser.is_active == True)
    
    if exclude_user_id:
        query = query.filter(PoliceUser.police_user_id != exclude_user_id)
    
    if target_roles:
        query = query.filter(PoliceUser.role.in_(target_roles))
    
    if target_location_id:
        query = query.filter(PoliceUser.assigned_location_id == target_location_id)
    
    if target_station_id:
        query = query.filter(PoliceUser.station_id == target_station_id)
    
    users = query.all()
    notifications = []
    
    for user in users:
        notif = Notification(
            notification_id=uuid4(),
            police_user_id=user.police_user_id,
            title=title,
            message=message,
            type=notif_type,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(notif)
        notifications.append(notif)
    
    db.commit()
    
    # Send real-time notification updates for affected users.
    for user in users:
        _run_async_now_or_schedule(
            notification_manager.increment_notification_count(str(user.police_user_id))
        )
    
    return notifications


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
    background_tasks: BackgroundTasks,
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
    
    # Only update if it was previously unread
    was_unread = not notif.is_read
    notif.is_read = True
    db.add(notif)
    db.commit()
    db.refresh(notif)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            # Send general refresh for any connected clients
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "notification"}))
            
            # If this was unread, send updated count to user
            if was_unread:
                loop.create_task(notification_manager.send_to_user(
                    str(current_user.police_user_id),
                    {"type": "notification_count_updated"}
                ))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "notification"}))
            if was_unread:
                asyncio.run(notification_manager.send_to_user(
                    str(current_user.police_user_id),
                    {"type": "notification_count_updated"}
                ))
    background_tasks.add_task(notify)

    return notif


@router.get("/mobile/{device_id}")
def get_device_notifications(
    device_id: str,
    db: Session = Depends(get_db),
    limit: int = 50,
    unread_only: bool = False,
):
    """
    Get notifications for a device (mobile app).
    This returns system notifications relevant to the device user.
    """
    from app.models.device import Device
    
    try:
        # Find the device - only search by device_hash for mobile API
        device = db.query(Device).filter(
            Device.device_hash == device_id
        ).first()
        
        # For testing, if device not found, return empty list instead of 404
        if not device:
            return []
        
        # For mobile devices, we return system-wide notifications
        # In a real implementation, you might want location-based filtering
        query = db.query(Notification).filter(
            Notification.is_read == False if unread_only else True
        )
        
        # Get the most recent notifications
        notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
        
        # Return a simplified response format for mobile devices
        return [
            {
                "id": str(notification.notification_id),
                "title": notification.title,
                "message": notification.message,
                "type": notification.type,
                "created_at": notification.created_at.isoformat(),
                "related_entity_type": notification.related_entity_type,
                "related_entity_id": notification.related_entity_id,
            }
            for notification in notifications
        ]
    except Exception as e:
        # Return error details for debugging
        return {"error": str(e), "device_id": device_id}


@router.post("/mobile/{device_id}/register-token")
def register_mobile_token(
    device_id: str,
    token_data: dict,
    db: Session = Depends(get_db),
):
    """
    Register a mobile device token for push notifications.
    This would integrate with Firebase Cloud Messaging or similar service.
    """
    try:
        from app.models.device import Device
        
        token = token_data.get("token")
        if not token:
            raise HTTPException(status_code=400, detail="Token is required")
        
        device = db.query(Device).filter(
            Device.device_hash == device_id
        ).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        # Store the token
        device.mobile_token = token
        db.add(device)
        db.commit()
        
        return {"message": "Token registered successfully", "device_id": device_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
