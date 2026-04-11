from typing import List, Dict, Any
import json
from fastapi import WebSocket

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
