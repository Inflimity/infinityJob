"""
Cross-platform message deduplication.

Provides two backends:
  1. Redis (preferred) — atomic SET NX EX with configurable TTL
  2. In-memory fallback — bounded OrderedDict with timestamp eviction

The correct backend is chosen automatically based on whether REDIS_URL is set.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from typing import Protocol

logger = logging.getLogger(__name__)

# ── Text normalisation ──────────────────────────────────────────────────

# Strip emojis, extra whitespace, and punctuation for fingerprinting
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002700-\U000027bf"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "]+",
    flags=re.UNICODE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _fingerprint(text: str) -> str:
    """Generate a deterministic SHA-256 hash from normalised text."""
    normalised = text.lower().strip()
    normalised = _EMOJI_RE.sub("", normalised)
    normalised = _WHITESPACE_RE.sub(" ", normalised).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ── Backend Protocol ─────────────────────────────────────────────────────


class DedupBackend(Protocol):
    """Protocol that all dedup backends must satisfy."""

    async def is_duplicate(self, text: str) -> bool: ...

    async def close(self) -> None: ...


# ── Redis Backend ────────────────────────────────────────────────────────


class RedisDedupBackend:
    """Deduplication via Redis atomic SET NX EX."""

    def __init__(self, redis_url: str, ttl_seconds: int = 3600) -> None:
        self._redis_url = redis_url
        self._ttl = ttl_seconds
        self._client = None

    async def _ensure_client(self):
        """Lazy-init the Redis client."""
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )

    async def is_duplicate(self, text: str) -> bool:
        """Return True if text was already seen within the TTL window."""
        await self._ensure_client()
        fp = _fingerprint(text)
        key = f"dedup:{fp}"
        try:
            is_new = await self._client.set(key, "1", nx=True, ex=self._ttl)
            return not bool(is_new)
        except Exception:
            logger.warning("Redis dedup check failed, treating as non-duplicate", exc_info=True)
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── In-Memory Backend ────────────────────────────────────────────────────


class MemoryDedupBackend:
    """In-memory deduplication using a bounded OrderedDict with TTL eviction."""

    def __init__(self, ttl_seconds: int = 3600, max_entries: int = 10_000) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()

    def _evict_expired(self) -> None:
        """Remove entries older than TTL."""
        now = time.monotonic()
        # OrderedDict is ordered by insertion; evict from the front
        while self._seen:
            key, ts = next(iter(self._seen.items()))
            if now - ts > self._ttl:
                self._seen.pop(key)
            else:
                break

    async def is_duplicate(self, text: str) -> bool:
        """Return True if text was already seen within the TTL window."""
        self._evict_expired()

        fp = _fingerprint(text)

        if fp in self._seen:
            # Refresh its position (move to end)
            self._seen.move_to_end(fp)
            return True

        # Enforce max size
        while len(self._seen) >= self._max_entries:
            self._seen.popitem(last=False)

        self._seen[fp] = time.monotonic()
        return False

    async def close(self) -> None:
        self._seen.clear()


# ── Factory ──────────────────────────────────────────────────────────────


def create_dedup_backend(
    redis_url: str | None = None,
    ttl_seconds: int = 3600,
) -> DedupBackend:
    """Create the appropriate dedup backend based on configuration."""
    if redis_url:
        logger.info("Using Redis dedup backend at %s", redis_url)
        return RedisDedupBackend(redis_url=redis_url, ttl_seconds=ttl_seconds)
    else:
        logger.info("No REDIS_URL set — using in-memory dedup backend")
        return MemoryDedupBackend(ttl_seconds=ttl_seconds)
