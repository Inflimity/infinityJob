"""
Async database manager for ginNews.

Handles SQLite connection pool, table creation, and CRUD operations
for alerts, watch configs, and muted sources.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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
            # SQLite-specific: enable WAL mode for better concurrent read perf
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
        intent = processed.intent

        alert = Alert(
            platform=raw.platform,
            source_name=raw.source_name,
            author=raw.author,
            text=raw.text,
            language=intent.language,
            category=intent.category,
            matched_keywords=json.dumps(intent.matched_keywords),
            summary=intent.summary_sentence,
            link=raw.link,
            created_at=raw.timestamp,
        )

        async with self._session_factory() as session:
            session.add(alert)
            await session.commit()
            await session.refresh(alert)
            logger.debug("Alert saved with id=%d", alert.id)
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

    async def is_source_muted(self, platform: str, source_id: str) -> bool:
        """Check if a source is currently muted."""
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

    async def get_recent_alerts(self, limit: int = 50) -> list[Alert]:
        """Fetch the most recent alerts, newest first."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Alert).order_by(Alert.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def close(self) -> None:
        """Dispose of the database engine."""
        await self._engine.dispose()
        logger.info("Database connection closed")
