"""
Core Orchestration Engine for JobSearchBot.

Consumes RawAlert objects from an asyncio.Queue, evaluates them against the
3-track job taxonomy and scoring model, deduplicates, persists to SQLite,
and dispatches high-relevance matches (score >= threshold) to Telegram.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from core.job_filters import JobMatch, evaluate_job

if TYPE_CHECKING:
    from core.dedup import DedupBackend
    from notifiers.telegram_bot import TelegramNotifier
    from storage.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RawAlert:
    """Platform-agnostic alert object produced by job monitors."""

    platform: str  # "twitter", "reddit", "hacker_news", "himalayas", "remote_boards", "github", "telegram", "discord"
    source_name: str  # Channel, Subreddit, Board Name, etc.
    author: str  # Poster username, company, or handle
    text: str  # Full job description / post content
    link: str = ""  # Direct apply link or post link
    is_system_event: bool = False  # True for admin test alerts
    is_dedicated_job_board: bool = False  # True for Himalayas, WeWorkRemotely, etc.
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class ProcessedAlert:
    """Job offer that has passed classification, scoring, and deduplication."""

    raw: RawAlert
    job: JobMatch
    db_id: Optional[int] = None
    processed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AlertEngine:
    """
    Central job processing and dispatch engine.
    """

    def __init__(
        self,
        queue: asyncio.Queue[RawAlert],
        dedup: DedupBackend,
        notifier: TelegramNotifier,
        db: DatabaseManager,
        min_alert_score: int = 70,
        digest_min_score: int = 50,
        max_post_age_minutes: int = 60,
        ws_broadcast=None,
    ) -> None:
        self._queue = queue
        self._dedup = dedup
        self._notifier = notifier
        self._db = db
        self._min_alert_score = min_alert_score
        self._digest_min_score = digest_min_score
        self._max_post_age_minutes = max_post_age_minutes
        self._ws_broadcast = ws_broadcast
        self._running = False
        self._stats = {"received": 0, "matched": 0, "deduplicated": 0, "dispatched": 0, "too_old": 0}

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    async def start(self) -> None:
        """Start the consumer loop. Runs until stop() is called."""
        self._running = True
        logger.info(
            "Job AlertEngine started — monitoring job streams (Min Score: %d%%, Max Age: %dm)",
            self._min_alert_score,
            self._max_post_age_minutes,
        )
        while self._running:
            try:
                try:
                    raw_alert = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._stats["received"] += 1
                await self._process(raw_alert)
                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("AlertEngine cancelled")
                break
            except Exception:
                logger.exception("Error processing job alert")

        logger.info("AlertEngine stopped — stats: %s", self._stats)

    async def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False
        logger.info("AlertEngine stop requested")

    async def _process(self, raw: RawAlert) -> None:
        """Evaluate a single raw post through age filter → heuristic filter → dedup → persist → notify."""
        # Step 0: Check post age (Across board <= 60 minutes)
        if not raw.is_system_event and raw.timestamp:
            now_utc = datetime.now(timezone.utc)
            # Ensure raw.timestamp has timezone info
            ts = raw.timestamp if raw.timestamp.tzinfo else raw.timestamp.replace(tzinfo=timezone.utc)
            age_minutes = (now_utc - ts).total_seconds() / 60.0

            if age_minutes > self._max_post_age_minutes:
                self._stats["too_old"] += 1
                logger.debug(
                    "Skipping post older than %dm (Age: %.1fm): %s",
                    self._max_post_age_minutes,
                    age_minutes,
                    raw.text[:60].replace("\n", " "),
                )
                return

        if raw.is_system_event:
            job = JobMatch(
                track_id="SYSTEM",
                track_badge="⚙️ System",
                role="System Notification",
                company=raw.author,
                salary="",
                location="Local",
                remote_type="worldwide",
                matched_skills=["system"],
                score=100,
                summary=raw.text,
                original_text=raw.text,
                link=raw.link,
            )
        else:
            # Check if source or author is muted
            if await self._db.is_source_muted(raw.platform, raw.author):
                logger.debug("Skipping muted source: %s/%s", raw.platform, raw.author)
                return

            from_search = raw.platform in ("twitter", "github")
            job = evaluate_job(
                text=raw.text,
                author=raw.author,
                link=raw.link,
                from_search=from_search,
                is_dedicated_job_board=raw.is_dedicated_job_board,
            )

            if job is None or job.score < self._digest_min_score:
                logger.debug("Rejected/Low Score (%s): %s", job.score if job else 0, raw.text[:60].replace("\n", " "))
                return

        self._stats["matched"] += 1
        logger.info(
            "🎯 JOB MATCH: Track=%s | Score=%d%% | Role=%s | Comp=%s | Platform=%s",
            job.track_badge,
            job.score,
            job.role,
            job.salary,
            raw.platform,
        )

        # Step 2: Deduplication by URL or Text Hash
        dedup_key = raw.link if raw.link else raw.text
        if await self._dedup.is_duplicate(dedup_key):
            self._stats["deduplicated"] += 1
            logger.debug("Duplicate job posting suppressed: %s", raw.text[:60])
            return

        processed = ProcessedAlert(raw=raw, job=job)

        # Step 3: Persist to database
        try:
            db_id = await self._db.save_alert(processed)
            processed.db_id = db_id
        except Exception:
            logger.exception("Failed to persist job alert to database")

        # Step 4: Dispatch instant notification if score meets threshold
        if job.score >= self._min_alert_score or raw.is_system_event:
            try:
                await self._notifier.send_alert(processed)
                self._stats["dispatched"] += 1
            except Exception:
                logger.exception("Failed to dispatch Telegram job alert")
        else:
            logger.info("Saved to database (Score %d < %d threshold for instant ping)", job.score, self._min_alert_score)

        # Step 5: Broadcast to WebSocket clients
        if self._ws_broadcast is not None:
            try:
                await self._ws_broadcast(processed)
            except Exception:
                logger.debug("WebSocket broadcast failed", exc_info=True)
