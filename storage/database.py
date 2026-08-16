"""
Async database manager for JobSearchBot.

Handles SQLite connection pool, table creation, and CRUD operations
for job alerts and muted sources/companies.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from storage.models import Alert, Base, MutedSource

if TYPE_CHECKING:
    from core.engine import ProcessedAlert

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async database manager backed by SQLAlchemy + aiosqlite."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Create all tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialised")

    async def save_alert(self, processed: ProcessedAlert) -> int:
        """Persist a ProcessedAlert and return its database ID."""
        raw = processed.raw
        job = processed.job

        alert = Alert(
            platform=raw.platform,
            source_name=raw.source_name,
            author=raw.author,
            text=raw.text,
            language=getattr(job, "language", "en"),
            track_id=getattr(job, "track_id", "GENERAL"),
            track_badge=getattr(job, "track_badge", "💼 Job"),
            role=getattr(job, "role", "Software Role"),
            company=getattr(job, "company", raw.author),
            salary=getattr(job, "salary", ""),
            location=getattr(job, "location", "Remote"),
            remote_type=getattr(job, "remote_type", "worldwide"),
            score=getattr(job, "score", 0),
            matched_skills=json.dumps(getattr(job, "matched_skills", [])),
            summary=getattr(job, "summary", raw.text[:300]),
            pitch=getattr(job, "pitch", ""),
            link=raw.link or getattr(job, "link", ""),
            created_at=raw.timestamp,
        )

        async with self._session_factory() as session:
            session.add(alert)
            await session.commit()
            await session.refresh(alert)
            logger.debug("Job Alert saved with id=%d", alert.id)
            return alert.id

    async def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark an alert as acknowledged. Returns True if found."""
        async with self._session_factory() as session:
            alert = await session.get(Alert, alert_id)
            if alert is None:
                return False
            alert.acknowledged = True
            await session.commit()
            return True

    async def save_alert_bookmark(self, alert_id: int) -> bool:
        """Mark an alert as saved/bookmarked. Returns True if found."""
        async with self._session_factory() as session:
            alert = await session.get(Alert, alert_id)
            if alert is None:
                return False
            alert.saved = True
            await session.commit()
            return True

    async def get_alert(self, alert_id: int) -> Optional[Alert]:
        """Fetch a single alert by ID."""
        async with self._session_factory() as session:
            return await session.get(Alert, alert_id)

    async def is_source_muted(self, platform: str, source_id: str) -> bool:
        """Check if a source or company is currently muted."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(
                select(MutedSource).where(
                    MutedSource.platform == platform,
                    MutedSource.source_identifier == source_id,
                    MutedSource.muted_until > now,
                )
            )
            return result.scalars().first() is not None

    async def mute_source(
        self, platform: str, source_id: str, until: datetime
    ) -> None:
        """Mute a source until the specified datetime."""
        async with self._session_factory() as session:
            muted = MutedSource(
                platform=platform,
                source_identifier=source_id,
                muted_until=until,
            )
            session.add(muted)
            await session.commit()
            logger.info(
                "Muted %s source '%s' until %s", platform, source_id, until
            )

    async def get_recent_alerts(
        self, limit: int = 50, track_id: Optional[str] = None
    ) -> list[Alert]:
        """Fetch the most recent job alerts, newest first."""
        async with self._session_factory() as session:
            stmt = select(Alert).order_by(Alert.created_at.desc())
            if track_id:
                stmt = stmt.where(Alert.track_id == track_id)
            result = await session.execute(stmt.limit(limit))
            return list(result.scalars().all())

    async def close(self) -> None:
        """Dispose of the database engine."""
        await self._engine.dispose()
        logger.info("Database connection closed")
