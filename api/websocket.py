"""
WebSocket connection manager for real-time job alert streaming.

Manages active client connections and broadcasts scored job alerts.
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
    """Manages WebSocket connections for live job alert streaming."""

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
        """Broadcast a processed job alert to all connected WebSocket clients."""
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

            for ws in dead_connections:
                if ws in self._connections:
                    self._connections.remove(ws)

    @staticmethod
    def _serialize_alert(alert: "ProcessedAlert") -> dict:
        """Serialize a ProcessedAlert into a JSON-compatible dict for dashboard clients."""
        raw = alert.raw
        job = alert.job
        return {
            "type": "job_alert",
            "data": {
                "id": alert.db_id,
                "platform": raw.platform,
                "source_name": raw.source_name,
                "author": raw.author,
                "text": raw.text,
                "track_id": getattr(job, "track_id", "GENERAL"),
                "track_badge": getattr(job, "track_badge", "💼 Job"),
                "role": getattr(job, "role", "Software Role"),
                "company": getattr(job, "company", raw.author),
                "salary": getattr(job, "salary", ""),
                "location": getattr(job, "location", "Remote"),
                "remote_type": getattr(job, "remote_type", "worldwide"),
                "score": getattr(job, "score", 0),
                "matched_skills": getattr(job, "matched_skills", []),
                "summary": getattr(job, "summary", ""),
                "pitch": getattr(job, "pitch", ""),
                "link": raw.link,
                "timestamp": raw.timestamp.isoformat(),
            },
        }


# Global singleton instance
ws_manager = ConnectionManager()
