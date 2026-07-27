"""
Core Orchestration Engine.

Consumes RawAlert objects from an asyncio.Queue, runs them through
the keyword filter and dedup layer, then dispatches matched alerts
to the Telegram notifier and persists them to the database.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.heuristic_filters import IntentMatch, analyze_intent

if TYPE_CHECKING:
    from core.dedup import DedupBackend
    from notifiers.telegram_bot import TelegramNotifier
    from storage.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RawAlert:
    """Platform-agnostic alert object produced by monitors."""

    platform: str  # "telegram", "discord", "twitter", "reddit"
    source_name: str  # Group name, channel, subreddit, etc.
    author: str  # Username or display name
    text: str  # Full message / post text
    link: str = ""  # Direct link to the message / post
    is_system_event: bool = False  # Set to True to bypass keyword filters
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class ProcessedAlert:
    """Alert that has passed filtering and deduplication."""

    raw: RawAlert
    intent: IntentMatch
    processed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AlertEngine:
    """
    Central processing engine.

    Monitors push RawAlert objects into the queue. The engine's consumer
    loop pulls from the queue, applies filters + dedup, and dispatches
    alerts that pass both checks.
    """

    def __init__(
        self,
        queue: asyncio.Queue[RawAlert],
        dedup: DedupBackend,
        notifier: TelegramNotifier,
        db: DatabaseManager,
        coins: list[str],
        keywords: list[str],
        ws_broadcast=None,
    ) -> None:
        self._queue = queue
        self._dedup = dedup
        self._notifier = notifier
        self._db = db
        self._coins = coins
        self._keywords = keywords
        self._ws_broadcast = ws_broadcast
        self._running = False
        self._stats = {"received": 0, "matched": 0, "deduplicated": 0, "dispatched": 0}

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    async def start(self) -> None:
        """Start the consumer loop. Runs until stop() is called."""
        self._running = True
        logger.info("AlertEngine started — waiting for alerts")
        while self._running:
            try:
                # Wait for an alert with a timeout so we can check _running
                try:
                    raw_alert = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._stats["received"] += 1
                logger.info("📥 Received alert from %s by %s: %s", raw_alert.platform, raw_alert.author, raw_alert.text[:100].replace('\n', ' '))
                await self._process(raw_alert)
                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("AlertEngine cancelled")
                break
            except Exception:
                logger.exception("Error processing alert")

        logger.info("AlertEngine stopped — stats: %s", self._stats)

    async def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False
        logger.info("AlertEngine stop requested")

    async def _process(self, raw: RawAlert) -> None:
        """Run a single alert through the filter → dedup → dispatch pipeline."""
        # Step 1: Heuristic intent filter
        if raw.is_system_event:
            intent = IntentMatch(
                category="system", 
                matched_keywords=["system_event"],
                original_text=raw.text,
                translated_text=raw.text,
                language="en",
                summary_sentence="System event"
            )
        else:
            # Twitter alerts come from our deep search queries (already pre-filtered), so use relaxed mode
            from_search = raw.platform == "twitter"
            intent = analyze_intent(raw.text, watch_coins=self._coins, complaint_words=self._keywords, from_search=from_search)
            if intent is None:
                logger.info("❌ Rejected by filter: %s", raw.text[:80].replace('\n', ' '))
                return

        self._stats["matched"] += 1
        logger.info(
            "✅ MATCH FOUND: category=%s keywords=%s author=%s",
            intent.category,
            intent.matched_keywords,
            raw.author,
        )

        # Step 2: Deduplication
        if await self._dedup.is_duplicate(raw.text):
            self._stats["deduplicated"] += 1
            logger.debug("Duplicate alert suppressed: %s", raw.text[:80])
            return

        processed = ProcessedAlert(raw=raw, intent=intent)

        # Step 3: Persist to database
        try:
            await self._db.save_alert(processed)
        except Exception:
            logger.exception("Failed to persist alert to database")

        # Step 4: Dispatch notification (Telegram DM)
        try:
            await self._notifier.send_alert(processed)
            self._stats["dispatched"] += 1
        except Exception:
            logger.exception("Failed to dispatch alert notification")

        # Step 5: Broadcast to WebSocket dashboard clients
        if self._ws_broadcast is not None:
            try:
                await self._ws_broadcast(processed)
            except Exception:
                logger.debug("WebSocket broadcast failed", exc_info=True)
