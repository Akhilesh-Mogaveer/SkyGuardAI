"""WebSocket Connection Manager for Real-Time SkyGuard AI Observation Telemetry.

Manages active WebSocket connections and broadcasts real-time processed observation payloads,
anomaly alerts, and historical CSV replay streams to connected dashboard clients.
"""

from typing import Any, Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect
import json
import logging

logger = logging.getLogger("skyguard.websocket")


class ConnectionManager:
    """Manages active WebSocket client connections and JSON payload broadcasting."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts an incoming WebSocket connection and registers client."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("New WebSocket client connected. Total active connections: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Removes a client from active connection pool."""
        self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Remaining active connections: %d", len(self.active_connections))

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        """Sends a JSON message to a single specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning("Error sending message to client: %s", e)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcasts a JSON message to all connected clients."""
        if not self.active_connections:
            return
        
        disconnected = set()
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Broadcasting error, dropping client: %s", e)
                disconnected.add(connection)

        for conn in disconnected:
            self.disconnect(conn)


# Singleton connection manager instance
ws_manager = ConnectionManager()
