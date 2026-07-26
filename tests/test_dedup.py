"""
Unit tests for core.dedup — deduplication backends.
"""

import pytest

from core.dedup import MemoryDedupBackend, _fingerprint


class TestFingerprint:
    """Tests for the text fingerprinting function."""

    def test_identical_text_produces_same_hash(self):
        assert _fingerprint("hello world") == _fingerprint("hello world")

    def test_case_insensitive(self):
        assert _fingerprint("HELLO WORLD") == _fingerprint("hello world")

    def test_whitespace_normalised(self):
        assert _fingerprint("hello   world") == _fingerprint("hello world")

    def test_leading_trailing_stripped(self):
        assert _fingerprint("  hello world  ") == _fingerprint("hello world")

    def test_different_text_produces_different_hash(self):
        assert _fingerprint("hello world") != _fingerprint("goodbye world")

    def test_emoji_stripped(self):
        assert _fingerprint("hello 🚀 world") == _fingerprint("hello world")


class TestMemoryDedupBackend:
    """Tests for the in-memory deduplication backend."""

    @pytest.fixture
    def backend(self):
        return MemoryDedupBackend(ttl_seconds=3600, max_entries=100)

    @pytest.mark.asyncio
    async def test_first_message_is_not_duplicate(self, backend):
        assert await backend.is_duplicate("new message") is False

    @pytest.mark.asyncio
    async def test_same_message_is_duplicate(self, backend):
        await backend.is_duplicate("hello world")
        assert await backend.is_duplicate("hello world") is True

    @pytest.mark.asyncio
    async def test_different_messages_are_not_duplicates(self, backend):
        await backend.is_duplicate("message one")
        assert await backend.is_duplicate("message two") is False

    @pytest.mark.asyncio
    async def test_case_insensitive_dedup(self, backend):
        await backend.is_duplicate("HELLO WORLD")
        assert await backend.is_duplicate("hello world") is True

    @pytest.mark.asyncio
    async def test_whitespace_normalised_dedup(self, backend):
        await backend.is_duplicate("hello   world")
        assert await backend.is_duplicate("hello world") is True


    @pytest.mark.asyncio
    async def test_max_entries_eviction(self):
        """Oldest entries should be evicted when max_entries is exceeded."""
        backend = MemoryDedupBackend(ttl_seconds=3600, max_entries=5)

        await backend.is_duplicate("msg1")
        await backend.is_duplicate("msg2")
        await backend.is_duplicate("msg3")
        await backend.is_duplicate("msg4")
        await backend.is_duplicate("msg5")

        # This should evict "msg1" (oldest)
        await backend.is_duplicate("msg6")

        # "msg1" should no longer be tracked
        assert await backend.is_duplicate("msg1") is False
        # "msg3" should still be tracked
        assert await backend.is_duplicate("msg3") is True

    @pytest.mark.asyncio
    async def test_close_clears_state(self, backend):
        await backend.is_duplicate("hello")
        await backend.close()
        # After close, the backend should be empty
        assert await backend.is_duplicate("hello") is False
