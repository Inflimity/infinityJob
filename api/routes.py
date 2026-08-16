"""
REST API routes for the JobSearchBot dashboard.

Provides endpoints for job alert history, track filtering,
system status, and job actions (save, dismiss, mute, pitch).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])

_db = None
_engine = None
_settings = None


def init_routes(db, engine, settings) -> None:
    """Inject dependencies into the routes module."""
    global _db, _engine, _settings
    _db = db
    _engine = engine
    _settings = settings


# ── Request / Response Models ────────────────────────────────────────


class JobAlertResponse(BaseModel):
    id: int
    platform: str
    source_name: str
    author: str
    text: str
    language: str
    track_id: str
    track_badge: str
    role: str
    company: str
    salary: str
    location: str
    remote_type: str
    score: int
    matched_skills: list[str]
    summary: str
    pitch: str
    link: str
    acknowledged: bool
    saved: bool
    created_at: str


class StatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    stats: dict
    monitors: list[str]
    websocket_clients: int


class ActionResponse(BaseModel):
    success: bool
    message: str


_start_time = datetime.now(timezone.utc)


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/alerts", response_model=list[JobAlertResponse])
async def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    track: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    saved_only: Optional[bool] = Query(None),
):
    """Fetch recent job alerts with optional track/platform filters."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    alerts = await _db.get_recent_alerts(limit=limit, track_id=track)

    results = []
    for a in alerts:
        if platform and a.platform != platform:
            continue
        if saved_only and not a.saved:
            continue

        results.append(
            JobAlertResponse(
                id=a.id,
                platform=a.platform,
                source_name=a.source_name,
                author=a.author,
                text=a.text,
                language=a.language or "en",
                track_id=a.track_id or "GENERAL",
                track_badge=a.track_badge or "💼 Job",
                role=a.role or "Software Role",
                company=a.company or a.author,
                salary=a.salary or "",
                location=a.location or "Remote",
                remote_type=a.remote_type or "worldwide",
                score=a.score or 0,
                matched_skills=json.loads(a.matched_skills) if a.matched_skills else [],
                summary=a.summary or "",
                pitch=a.pitch or "",
                link=a.link or "",
                acknowledged=a.acknowledged,
                saved=a.saved,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
        )

    return results


@router.post("/alerts/{alert_id}/save", response_model=ActionResponse)
async def save_alert(alert_id: int):
    """Bookmark a job alert for later application."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    success = await _db.save_alert_bookmark(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")

    return ActionResponse(success=True, message=f"Job {alert_id} bookmarked")


@router.post("/alerts/{alert_id}/dismiss", response_model=ActionResponse)
async def dismiss_alert(alert_id: int):
    """Acknowledge / dismiss a job alert."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    success = await _db.acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")

    return ActionResponse(success=True, message=f"Job {alert_id} dismissed")


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """System health, uptime, and processing statistics."""
    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
    stats = _engine.stats if _engine else {}

    return StatusResponse(
        status="healthy" if _engine and _engine._running else "stopped",
        uptime_seconds=round(uptime, 1),
        stats=stats,
        monitors=[
            "TwitterMonitor",
            "RedditMonitor",
            "HNMonitor",
            "RemoteBoardsMonitor",
            "GitHubBountiesMonitor",
            "TelegramMonitor",
        ],
        websocket_clients=0,
    )
