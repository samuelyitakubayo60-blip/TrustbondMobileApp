import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.core.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])

class NotificationManager:
    def __init__(self):
        # Store user-specific connections with their user_id
        self.user_connections: Dict[str, WebSocket] = {}
        # Store notification counts per user
        self.notification_counts: Dict[str, int] = {}

    async def connect_user(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.user_connections[user_id] = websocket
        # Send current notification count to user
        count = self.notification_counts.get(user_id, 0)
        await websocket.send_text(json.dumps({
            "type": "notification_count",
            "count": count
        }))

    def disconnect_user(self, user_id: str):
        if user_id in self.user_connections:
            del self.user_connections[user_id]

    async def send_to_user(self, user_id: str, message: Dict[str, Any]):
        if user_id in self.user_connections:
            try:
                await self.user_connections[user_id].send_text(json.dumps(message))
            except Exception:
                # Connection might be dead, remove it
                self.disconnect_user(user_id)

    async def increment_notification_count(self, user_id: str):
        current = self.notification_counts.get(user_id, 0)
        new_count = current + 1
        self.notification_counts[user_id] = new_count
        await self.send_to_user(user_id, {
            "type": "notification_count",
            "count": new_count
        })

    async def clear_notifications(self, user_id: str):
        self.notification_counts[user_id] = 0
        await self.send_to_user(user_id, {
            "type": "notification_count",
            "count": 0
        })

# Global notification manager
notification_manager = NotificationManager()

@router.websocket("/ws/notifications")
async def websocket_notifications_endpoint(websocket: WebSocket):
    user_id = None
    try:
        # Wait for authentication message
        data = await websocket.receive_text()
        message = json.loads(data)
        
        if message.get("type") == "auth":
            token = message.get("token")
            if token:
                # Decode token to get user_id
                payload = decode_access_token(token)
                if payload:
                    user_id = str(payload.get("sub"))
                    await notification_manager.connect_user(websocket, user_id)
                else:
                    await websocket.close(code=4001, reason="Invalid token")
                    return
            else:
                await websocket.close(code=4001, reason="Token required")
                return
        else:
            await websocket.close(code=4001, reason="Authentication required")
            return

        # Keep connection alive and handle messages
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "get_notification_count":
                count = notification_manager.notification_counts.get(user_id, 0)
                await websocket.send_text(json.dumps({
                    "type": "notification_count",
                    "count": count
                }))
            elif message.get("type") == "clear_notifications":
                await notification_manager.clear_notifications(user_id)
            else:
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        if user_id:
            notification_manager.disconnect_user(user_id)
    except Exception as e:
        logger.warning("WebSocket notifications error: %s", e)
        if user_id:
            notification_manager.disconnect_user(user_id)

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Police portal live refresh channel (maps, reports, audit, hotspots, etc.)."""
    await manager.connect(websocket)
    await websocket.send_text(
        json.dumps({"type": "connected", "channel": "refresh_data"})
    )
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            msg_type = message.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "auth":
                # Optional token on /ws — refresh channel does not require auth today.
                await websocket.send_text(json.dumps({"type": "auth_ok"}))
            else:
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket refresh channel error: %s", e)
        manager.disconnect(websocket)

# Export notification manager for use in other endpoints
__all__ = ["notification_manager"]
