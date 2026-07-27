"""
REST API routes for the ginNews dashboard.

Provides endpoints for alert history, configuration management,
system status, and alert actions (dismiss/mute/save).
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

# ── These get injected at server startup ─────────────────────────────
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


class AlertResponse(BaseModel):
    id: int
    platform: str
    source_name: str
    author: str
    text: str
    language: str
    category: str
    matched_keywords: list[str]
    summary: str
    link: str
    acknowledged: bool
    saved: bool
    created_at: str


class ConfigUpdate(BaseModel):
    coins: Optional[list[str]] = None
    keywords: Optional[list[str]] = None


class StatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    stats: dict
    monitors: list[str]
    websocket_clients: int


class ActionResponse(BaseModel):
    success: bool
    message: str


# ── Track server start time ─────────────────────────────────────────
_start_time = datetime.now(timezone.utc)


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/alerts", response_model=list[AlertResponse])
async def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    platform: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
):
    """Fetch recent alerts with optional filters."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    alerts = await _db.get_recent_alerts(limit=limit)

    results = []
    for a in alerts:
        # Apply optional filters
        if platform and a.platform != platform:
            continue
        if acknowledged is not None and a.acknowledged != acknowledged:
            continue

        results.append(
            AlertResponse(
                id=a.id,
                platform=a.platform,
                source_name=a.source_name,
                author=a.author,
                text=a.text,
                language=a.language or "en",
                category=a.category or "other",
                matched_keywords=json.loads(a.matched_keywords) if a.matched_keywords else [],
                summary=a.summary or "",
                link=a.link,
                acknowledged=a.acknowledged,
                saved=a.saved,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
        )

    return results


@router.post("/alerts/{alert_id}/dismiss", response_model=ActionResponse)
async def dismiss_alert(alert_id: int):
    """Mark an alert as acknowledged/dismissed."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    success = await _db.acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")

    return ActionResponse(success=True, message=f"Alert {alert_id} dismissed")


@router.post("/alerts/{alert_id}/save", response_model=ActionResponse)
async def save_alert(alert_id: int):
    """Bookmark an alert for later review."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    success = await _db.save_alert_bookmark(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")

    return ActionResponse(success=True, message=f"Alert {alert_id} saved")


@router.post("/alerts/{alert_id}/mute", response_model=ActionResponse)
async def mute_source(alert_id: int, hours: int = Query(1, ge=1, le=24)):
    """Mute the alert's source for the specified number of hours."""
    if _db is None:
        raise HTTPException(503, "Database not initialized")

    # Fetch the alert to get source info
    alerts = await _db.get_recent_alerts(limit=500)
    target = None
    for a in alerts:
        if a.id == alert_id:
            target = a
            break

    if target is None:
        raise HTTPException(404, f"Alert {alert_id} not found")

    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    await _db.mute_source(target.platform, target.source_name, until)

    return ActionResponse(
        success=True,
        message=f"Muted {target.source_name} for {hours}h",
    )


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Get system health and monitor status."""
    from api.websocket import ws_manager

    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()

    stats = _engine.stats if _engine else {}

    monitor_names = []
    if _settings:
        monitor_names.append("telegram")
        if getattr(_settings, "discord_user_token", None):
            monitor_names.append("discord")
        if _settings.twitter_search_queries:
            monitor_names.append("twitter")
        if _settings.reddit_subreddits:
            strategy = "praw" if _settings.reddit_client_id else "rss"
            monitor_names.append(f"reddit ({strategy})")

    return StatusResponse(
        status="running",
        uptime_seconds=round(uptime, 1),
        stats=stats,
        monitors=monitor_names,
        websocket_clients=ws_manager.active_count,
    )


@router.get("/config")
async def get_config():
    """Get current watchlist configuration."""
    if _settings is None:
        raise HTTPException(503, "Settings not initialized")

    return {
        "coins": _settings.watch_coins,
        "keywords": _settings.complaint_words,
        "reddit_subreddits": _settings.reddit_subreddits,
        "discord_token_set": bool(getattr(_settings, "discord_user_token", None)),
        "twitter_queries": _settings.twitter_search_queries,
        "poll_interval": _settings.poll_interval_seconds,
    }
