"""
WebSocket connection manager for real-time alert streaming.

Manages active client connections, broadcasts alerts to all connected
dashboards, and handles graceful disconnects.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from core.engine import ProcessedAlert

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for live alert streaming."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info(
            "WebSocket client connected (total: %d)", len(self._connections)
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.info(
            "WebSocket client disconnected (total: %d)", len(self._connections)
        )

    async def broadcast_alert(self, alert: "ProcessedAlert") -> None:
        """Broadcast a processed alert to all connected WebSocket clients."""
        if not self._connections:
            return

        payload = self._serialize_alert(alert)
        message = json.dumps(payload)

        dead_connections = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_connections.append(ws)

        # Clean up dead connections outside the lock
        for ws in dead_connections:
            await self.disconnect(ws)

    async def broadcast_status(self, status: dict) -> None:
        """Broadcast a status update to all connected clients."""
        message = json.dumps({"type": "status", "data": status})

        dead_connections = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_connections.append(ws)

        for ws in dead_connections:
            await self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @staticmethod
    def _serialize_alert(alert: "ProcessedAlert") -> dict:
        """Convert a ProcessedAlert into a JSON-serializable dict."""
        raw = alert.raw
        intent = alert.intent
        return {
            "type": "alert",
            "data": {
                "platform": raw.platform,
                "source_name": raw.source_name,
                "author": raw.author,
                "text": raw.text,
                "link": raw.link,
                "timestamp": raw.timestamp.isoformat(),
                "language": intent.language,
                "category": intent.category,
                "matched_keywords": intent.matched_keywords,
                "summary": intent.summary_sentence,
            },
        }


# Singleton instance used across the application
ws_manager = ConnectionManager()
