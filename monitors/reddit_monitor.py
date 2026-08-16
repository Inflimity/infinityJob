"""
Reddit Job Monitor — Dual-strategy with AsyncPRAW streaming + RSS feed fallback.

Strategy A (preferred): Uses asyncpraw to stream real-time posts from targeted job/tech subreddits.
Strategy B (fallback): Polls subreddit RSS feeds (no credentials needed).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
import time
from typing import TYPE_CHECKING

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)


def clean_html(raw_html: str) -> str:
    """Removes HTML tags and entities from RSS summaries."""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    clean = re.sub(r"&[a-z]+;", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


class RedditMonitor(BaseMonitor):
    """Monitors Reddit subreddits for hiring posts via AsyncPRAW or RSS feeds."""

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
            logger.info("RedditMonitor: Using AsyncPRAW real-time stream across %d subreddits", len(self._subreddits))
            await self._stream_via_praw()
        else:
            logger.info("RedditMonitor: Using RSS feed fallback across %d subreddits", len(self._subreddits))
            await self._poll_via_rss()

    async def _stream_via_praw(self) -> None:
        """Monitor subreddits via asyncpraw's real-time submission stream."""
        import asyncpraw

        reddit = asyncpraw.Reddit(
            client_id=self._settings.reddit_client_id,
            client_secret=self._settings.reddit_client_secret,
            user_agent=self._settings.reddit_user_agent,
        )

        try:
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

            await asyncio.gather(*tasks)
        finally:
            await reddit.close()

    async def _stream_submissions(self, subreddit) -> None:
        """Stream new submissions from configured subreddits."""
        async for submission in subreddit.stream.submissions(skip_existing=True):
            if not self._running:
                break

            post_id = f"post:{submission.id}"
            if post_id in self._seen_ids:
                continue
            self._seen_ids.add(post_id)

            text = f"{submission.title}\n{submission.selftext or ''}"
            flair = f" [{submission.link_flair_text}]" if submission.link_flair_text else ""
            created_ts = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{submission.subreddit.display_name}{flair}",
                author=f"u/{submission.author.name}" if submission.author else "u/[deleted]",
                text=text.strip(),
                link=f"https://reddit.com{submission.permalink}",
                timestamp=created_ts,
            )

            await self._emit(alert)

    async def _stream_comments(self, subreddit) -> None:
        """Stream new comments from configured subreddits."""
        async for comment in subreddit.stream.comments(skip_existing=True):
            if not self._running:
                break

            comment_id = f"comment:{comment.id}"
            if comment_id in self._seen_ids:
                continue
            self._seen_ids.add(comment_id)
            created_ts = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{comment.subreddit.display_name}",
                author=f"u/{comment.author.name}" if comment.author else "u/[deleted]",
                text=comment.body,
                link=f"https://reddit.com{comment.permalink}",
                timestamp=created_ts,
            )

            await self._emit(alert)

    async def _poll_via_rss(self) -> None:
        """Poll subreddit RSS feeds using multi-subreddit feed for 0 rate limits."""
        import feedparser

        while self._running:
            try:
                # Query all configured subreddits in a single combined RSS feed
                multi_sub = "+".join(self._subreddits)
                await self._fetch_rss_feed(multi_sub, feedparser)
            except Exception:
                logger.exception("Error polling Reddit RSS")

            # Wait 90 seconds between cycles
            await asyncio.sleep(90)

    async def _fetch_rss_feed(self, sub_name: str, feedparser) -> None:
        """Fetch and parse a subreddit RSS feed."""
        import httpx

        url = f"https://www.reddit.com/r/{sub_name}/new/.rss"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    },
                    timeout=15,
                    follow_redirects=True,
                )
                if response.status_code != 200:
                    logger.warning("Reddit RSS returned status %d", response.status_code)
                    return
                response_text = response.text
        except Exception:
            logger.warning("Failed to fetch Reddit RSS")
            return

        feed = feedparser.parse(response_text)
        now_utc = datetime.now(timezone.utc)

        for entry in feed.entries:
            # 60-minute age filter
            pub_time = now_utc
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                if (now_utc - pub_time).total_seconds() > 3600:  # 60 minutes
                    continue

            entry_id = f"rss:{entry.get('id', '')}"
            if not entry_id or entry_id in self._seen_ids:
                continue
            self._seen_ids.add(entry_id)

            title = entry.get("title", "")
            raw_summary = entry.get("summary", "")
            clean_summary = clean_html(raw_summary)

            text = f"{title}\n{clean_summary}" if clean_summary else title
            author = entry.get("author", "u/unknown")
            link = entry.get("link", "")

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"r/{sub_name}",
                author=author,
                text=text.strip(),
                link=link,
                timestamp=pub_time,
            )

            await self._emit(alert)

        if len(self._seen_ids) > 10_000:
            self._seen_ids = set(list(self._seen_ids)[-5_000:])
