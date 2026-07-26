"""
Reddit Monitor — Dual-strategy with AsyncPRAW streaming + RSS feed fallback.

Strategy A (preferred): Uses asyncpraw to open real-time submission/comment
streams on configured subreddits. Requires Reddit API credentials.

Strategy B (fallback): Polls subreddit RSS feeds (no credentials needed).
Automatically selected when REDDIT_CLIENT_ID is not set.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)


class RedditMonitor(BaseMonitor):
    """Monitors Reddit subreddits via AsyncPRAW or RSS feeds."""

    PLATFORM = "reddit"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="RedditMonitor")
        self._settings = settings
        self._subreddits = settings.reddit_subreddits
        self._monitor_comments = settings.reddit_monitor_comments
        self._poll_interval = settings.poll_interval_seconds
        self._seen_ids: set[str] = set()

    async def _run(self) -> None:
        """Select and run the appropriate monitoring strategy."""
        if not self._subreddits:
            logger.warning("RedditMonitor: No subreddits configured, skipping")
            while self._running:
                await asyncio.sleep(60)
            return

        if self._settings.reddit_client_id:
            logger.info("RedditMonitor: Using AsyncPRAW real-time stream")
            await self._stream_via_praw()
        else:
            logger.info("RedditMonitor: Using RSS feed fallback (no API credentials)")
            await self._poll_via_rss()

    # ── Strategy A: AsyncPRAW Streaming ──────────────────────────────

    async def _stream_via_praw(self) -> None:
        """Monitor subreddits via asyncpraw's real-time submission stream."""
        import asyncpraw

        reddit = asyncpraw.Reddit(
            client_id=self._settings.reddit_client_id,
            client_secret=self._settings.reddit_client_secret,
            user_agent=self._settings.reddit_user_agent,
        )

        try:
            # Join all configured subreddits into a multi-subreddit string
            multi = "+".join(self._subreddits)
            subreddit = await reddit.subreddit(multi)

            tasks = [
                asyncio.create_task(
                    self._stream_submissions(subreddit), name="reddit-submissions"
                )
            ]

            if self._monitor_comments:
                tasks.append(
                    asyncio.create_task(
                        self._stream_comments(subreddit), name="reddit-comments"
                    )
                )

            # Run until cancelled
            await asyncio.gather(*tasks)
        finally:
            await reddit.close()

    async def _stream_submissions(self, subreddit) -> None:
        """Stream new submissions (posts) from a subreddit."""
        async for submission in subreddit.stream.submissions(skip_existing=True):
            if not self._running:
                break

            post_id = f"post:{submission.id}"
            if post_id in self._seen_ids:
                continue
            self._seen_ids.add(post_id)

            # Combine title and selftext for keyword matching
            text = f"{submission.title}\n{submission.selftext or ''}"

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{submission.subreddit.display_name}",
                author=f"u/{submission.author.name}" if submission.author else "u/[deleted]",
                text=text.strip(),
                link=f"https://reddit.com{submission.permalink}",
            )

            await self._emit(alert)

    async def _stream_comments(self, subreddit) -> None:
        """Stream new comments from a subreddit."""
        async for comment in subreddit.stream.comments(skip_existing=True):
            if not self._running:
                break

            comment_id = f"comment:{comment.id}"
            if comment_id in self._seen_ids:
                continue
            self._seen_ids.add(comment_id)

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{comment.subreddit.display_name}",
                author=f"u/{comment.author.name}" if comment.author else "u/[deleted]",
                text=comment.body,
                link=f"https://reddit.com{comment.permalink}",
            )

            await self._emit(alert)

    # ── Strategy B: RSS Feed Polling ─────────────────────────────────

    async def _poll_via_rss(self) -> None:
        """Poll subreddit RSS feeds at the configured interval."""
        import feedparser

        while self._running:
            for sub_name in self._subreddits:
                try:
                    await self._fetch_rss_feed(sub_name, feedparser)
                except Exception:
                    logger.exception(
                        "Error polling RSS for r/%s", sub_name
                    )

            await asyncio.sleep(self._poll_interval)

    async def _fetch_rss_feed(self, sub_name: str, feedparser) -> None:
        """Fetch and parse a single subreddit's RSS feed."""
        import urllib.request

        url = f"https://www.reddit.com/r/{sub_name}/new/.rss"

        # Fetch RSS feed (blocking I/O — run in executor)
        loop = asyncio.get_running_loop()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self._settings.reddit_user_agent,
                },
            )
            response_text = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8"),
            )
        except Exception:
            logger.warning("Failed to fetch RSS for r/%s", sub_name)
            return

        feed = feedparser.parse(response_text)

        for entry in feed.entries:
            entry_id = f"rss:{entry.get('id', '')}"
            if not entry_id or entry_id in self._seen_ids:
                continue
            self._seen_ids.add(entry_id)

            title = entry.get("title", "")
            # RSS entries have HTML content; extract a plain text summary
            summary = entry.get("summary", "")
            text = f"{title}\n{summary}" if summary else title

            author = entry.get("author", "u/unknown")
            link = entry.get("link", "")

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{sub_name}",
                author=author,
                text=text.strip(),
                link=link,
            )

            await self._emit(alert)

        # Cap seen set
        if len(self._seen_ids) > 10_000:
            keep = set(list(self._seen_ids)[-5_000:])
            self._seen_ids = keep
