from typing import List, Dict, Any
import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # Store active connections
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """
        Send a JSON message to all active connected clients.
        Example: {"type": "refresh_data", "entity": "case", "action": "created", "id": "123"}
        """
        payload = json.dumps(message)
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                # Connection might be dead/closed unexpectedly
                dead_connections.append(connection)
                
        # Clean up dead connections
        for dead in dead_connections:
            self.disconnect(dead)


# Global singleton instance to be imported across API endpoints
manager = ConnectionManager()


def schedule_broadcast(message: Dict[str, Any]) -> None:
    """
    Broadcast to all /api/v1/ws clients from sync or async route handlers.
  """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast(message))
    except RuntimeError:
        try:
            asyncio.run(manager.broadcast(message))
        except Exception:
            logger.exception("WebSocket broadcast failed: %s", message)
    except Exception:
        logger.exception("WebSocket broadcast schedule failed: %s", message)


def refresh_entity(entity: str, action: str = "updated", **extra: Any) -> None:
    """Convenience wrapper for dashboard refresh pushes."""
    payload: Dict[str, Any] = {
        "type": "refresh_data",
        "entity": entity,
        "action": action,
    }
    payload.update(extra)
    schedule_broadcast(payload)
