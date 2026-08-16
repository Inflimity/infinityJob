"""
Unit tests for core.engine — AlertEngine job processing pipeline.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.engine import AlertEngine, ProcessedAlert, RawAlert


def _make_raw_alert(text: str = "[HIRING] Senior Full Stack Engineer (Next.js, Python, Remote)", **kwargs) -> RawAlert:
    """Helper to create a RawAlert with sensible defaults."""
    defaults = {
        "platform": "telegram",
        "source_name": "Tech Jobs",
        "author": "@techfounder",
        "text": text,
        "link": "https://t.me/techjobs/123",
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return RawAlert(**defaults)


@pytest.fixture
def mock_dedup():
    dedup = AsyncMock()
    dedup.is_duplicate = AsyncMock(return_value=False)
    return dedup


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.send_alert = AsyncMock()
    return notifier


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.save_alert = AsyncMock(return_value=1)
    db.is_source_muted = AsyncMock(return_value=False)
    return db


@pytest.fixture
def engine(mock_dedup, mock_notifier, mock_db):
    queue = asyncio.Queue()
    return AlertEngine(
        queue=queue,
        dedup=mock_dedup,
        notifier=mock_notifier,
        db=mock_db,
        min_alert_score=70,
        digest_min_score=50,
    )


class TestAlertEngine:
    """Tests for the AlertEngine processing pipeline."""

    @pytest.mark.asyncio
    async def test_matching_job_alert_is_dispatched(self, engine, mock_notifier, mock_db):
        """A high-scoring job alert (score >= 70) should be saved and dispatched."""
        alert = _make_raw_alert(
            "[HIRING] Senior Full Stack Engineer. Stack: Next.js, TypeScript, PostgreSQL. "
            "Salary: $120k-$150k. Remote worldwide."
        )
        await engine._process(alert)

        mock_db.save_alert.assert_called_once()
        mock_notifier.send_alert.assert_called_once()
        assert engine.stats["matched"] == 1
        assert engine.stats["dispatched"] == 1

    @pytest.mark.asyncio
    async def test_non_matching_job_is_dropped(self, engine, mock_notifier, mock_db):
        """A random non-job post should be dropped."""
        alert = _make_raw_alert("Just had lunch, pizza was amazing today!")
        await engine._process(alert)

        mock_db.save_alert.assert_not_called()
        mock_notifier.send_alert.assert_not_called()
        assert engine.stats["matched"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_job_is_suppressed(
        self, engine, mock_dedup, mock_notifier, mock_db
    ):
        """A duplicate job posting should be matched but not dispatched."""
        mock_dedup.is_duplicate.return_value = True

        alert = _make_raw_alert(
            "[HIRING] AI Engineer (Python, FastAPI, LangChain, RAG). Remote anywhere."
        )
        await engine._process(alert)

        assert engine.stats["matched"] == 1
        assert engine.stats["deduplicated"] == 1
        mock_notifier.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_prevent_notification(
        self, engine, mock_db, mock_notifier
    ):
        """If the DB fails, the notification should still attempt to send."""
        mock_db.save_alert.side_effect = Exception("DB connection lost")

        alert = _make_raw_alert(
            "We are hiring a Full Stack Developer (React, Next.js, Node.js). Remote worldwide. $100k."
        )
        await engine._process(alert)

        mock_notifier.send_alert.assert_called_once()
        assert engine.stats["dispatched"] == 1

    @pytest.mark.asyncio
    async def test_notifier_failure_does_not_crash(
        self, engine, mock_notifier
    ):
        """If the notifier fails, the engine should log but not crash."""
        mock_notifier.send_alert.side_effect = Exception("Telegram API down")

        alert = _make_raw_alert(
            "[HIRING] AI Developer (Python, LLMs, Agents). Remote worldwide. $120k."
        )
        await engine._process(alert)
        assert engine.stats["dispatched"] == 0

    @pytest.mark.asyncio
    async def test_posts_older_than_60_minutes_are_dropped(
        self, engine, mock_notifier, mock_db
    ):
        """Job postings older than 60 minutes must be dropped across all monitors."""
        from datetime import timedelta
        old_time = datetime.now(timezone.utc) - timedelta(minutes=65)
        old_alert = _make_raw_alert(
            "[HIRING] Senior Full Stack Engineer. Stack: Next.js, Python. $130k. Remote.",
            timestamp=old_time,
        )
        await engine._process(old_alert)

        mock_db.save_alert.assert_not_called()
        mock_notifier.send_alert.assert_not_called()
        assert engine.stats["too_old"] == 1
        assert engine.stats["dispatched"] == 0

    @pytest.mark.asyncio
    async def test_raw_alert_dataclass_defaults(self):
        """RawAlert should have sensible defaults."""
        alert = RawAlert(
            platform="test",
            source_name="Test",
            author="user",
            text="hello",
        )
        assert alert.link == ""
        assert isinstance(alert.timestamp, datetime)
