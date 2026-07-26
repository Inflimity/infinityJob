"""
Unit tests for core.engine — AlertEngine processing pipeline.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.engine import AlertEngine, ProcessedAlert, RawAlert
from core.filters import MatchResult


def _make_raw_alert(text: str = "BTC is a scam", **kwargs) -> RawAlert:
    """Helper to create a RawAlert with sensible defaults."""
    defaults = {
        "platform": "telegram",
        "source_name": "Test Group",
        "author": "@testuser",
        "text": text,
        "link": "https://t.me/test/123",
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
    return db


@pytest.fixture
def engine(mock_dedup, mock_notifier, mock_db):
    queue = asyncio.Queue()
    return AlertEngine(
        queue=queue,
        dedup=mock_dedup,
        notifier=mock_notifier,
        db=mock_db,
        coins=["btc", "eth", "sol"],
        keywords=["scam", "bug", "exploit"],
    )


class TestAlertEngine:
    """Tests for the AlertEngine processing pipeline."""

    @pytest.mark.asyncio
    async def test_matching_alert_is_dispatched(self, engine, mock_notifier, mock_db):
        """An alert with both coin + keyword should be saved and sent."""
        alert = _make_raw_alert("BTC is a scam!")
        await engine._process(alert)

        mock_db.save_alert.assert_called_once()
        mock_notifier.send_alert.assert_called_once()
        assert engine.stats["matched"] == 1
        assert engine.stats["dispatched"] == 1

    @pytest.mark.asyncio
    async def test_non_matching_alert_is_dropped(self, engine, mock_notifier, mock_db):
        """An alert without matching coins/keywords should be silently dropped."""
        alert = _make_raw_alert("I love pizza")
        await engine._process(alert)

        mock_db.save_alert.assert_not_called()
        mock_notifier.send_alert.assert_not_called()
        assert engine.stats["matched"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_alert_is_suppressed(
        self, engine, mock_dedup, mock_notifier, mock_db
    ):
        """A duplicate alert should be matched but not dispatched."""
        mock_dedup.is_duplicate.return_value = True

        alert = _make_raw_alert("ETH has a critical bug")
        await engine._process(alert)

        assert engine.stats["matched"] == 1
        assert engine.stats["deduplicated"] == 1
        mock_notifier.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_prevent_notification(
        self, engine, mock_db, mock_notifier
    ):
        """If the DB fails, the notification should still be sent."""
        mock_db.save_alert.side_effect = Exception("DB connection lost")

        alert = _make_raw_alert("SOL exploit detected!")
        await engine._process(alert)

        # Notification should still go through
        mock_notifier.send_alert.assert_called_once()
        assert engine.stats["dispatched"] == 1

    @pytest.mark.asyncio
    async def test_notifier_failure_does_not_crash(
        self, engine, mock_notifier
    ):
        """If the notifier fails, the engine should log but not crash."""
        mock_notifier.send_alert.side_effect = Exception("Telegram API down")

        alert = _make_raw_alert("BTC scam alert!")
        # Should not raise
        await engine._process(alert)
        assert engine.stats["dispatched"] == 0

    @pytest.mark.asyncio
    async def test_stats_accumulate(self, engine):
        """Stats should accumulate across multiple process calls."""
        await engine._process(_make_raw_alert("BTC scam"))
        await engine._process(_make_raw_alert("ETH bug"))
        await engine._process(_make_raw_alert("I love crypto"))

        assert engine.stats["matched"] == 2
        assert engine.stats["dispatched"] == 2

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
