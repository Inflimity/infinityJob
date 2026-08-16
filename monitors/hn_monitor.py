"""
Hacker News Job Monitor — Algolia Search API + "Ask HN: Who is hiring?" thread watcher.

Polls Hacker News via public Algolia search API for real-time hiring posts, startup roles,
and monthly "Who is hiring?" comments without requiring authentication.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


def clean_hn_html(raw_html: str) -> str:
    """Unescapes HTML entities and strips paragraph tags from HN comment text."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<p>", "\n\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<a\s+href=[\"'](.*?)[\"'].*?>.*?</a>", r" \1 ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


class HNMonitor(BaseMonitor):
    """Monitors Hacker News for startup jobs and Who is hiring comments."""

    PLATFORM = "hacker_news"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="HNMonitor")
        self._settings = settings
        self._poll_interval = 300  # 5 minutes
        self._seen_ids: set[str] = set()

    async def _run(self) -> None:
        """Poll Algolia HN Search API for new hiring comments & job stories."""
        logger.info("HNMonitor started — watching Hacker News hiring feeds")

        while self._running:
            try:
                await self._poll_hn_jobs()
                await self._poll_who_is_hiring_comments()
            except Exception:
                logger.exception("Error during HN polling cycle")

            await asyncio.sleep(self._poll_interval)

    async def _poll_hn_jobs(self) -> None:
        """Poll recent stories tagged with 'job'."""
        params = {
            "tags": "job",
            "hitsPerPage": 20,
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(ALGOLIA_SEARCH_URL, params=params, timeout=15)
                if resp.status_code != 200:
                    return
                data = resp.json()
            except Exception:
                logger.debug("Failed to query HN job stories")
                return

        now_utc = datetime.now(timezone.utc)
        for hit in data.get("hits", []):
            object_id = hit.get("objectID")
            if not object_id or object_id in self._seen_ids:
                continue
            self._seen_ids.add(object_id)

            created_ts = now_utc
            if hit.get("created_at_i"):
                created_ts = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
                if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                    continue

            title = hit.get("title", "")
            story_text = clean_hn_html(hit.get("story_text", ""))
            full_text = f"{title}\n{story_text}" if story_text else title
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            author = hit.get("author", "hn_user")

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name="Hacker News (Jobs)",
                author=author,
                text=full_text,
                link=url,
                is_dedicated_job_board=True,
                timestamp=created_ts,
            )

            await self._emit(alert)

    async def _poll_who_is_hiring_comments(self) -> None:
        """Poll comments within recent 'Ask HN: Who is hiring?' threads."""
        queries = ["Ask HN: Who is hiring", "Who is hiring"]
        now_utc = datetime.now(timezone.utc)
        for query in queries:
            params = {
                "query": query,
                "tags": "comment",
                "hitsPerPage": 25,
            }
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.get(ALGOLIA_SEARCH_URL, params=params, timeout=15)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except Exception:
                    continue

            for hit in data.get("hits", []):
                object_id = hit.get("objectID")
                if not object_id or object_id in self._seen_ids:
                    continue
                self._seen_ids.add(object_id)

                created_ts = now_utc
                if hit.get("created_at_i"):
                    created_ts = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
                    if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                        continue

                comment_text = clean_hn_html(hit.get("comment_text", ""))
                if len(comment_text) < 40:
                    continue

                story_id = hit.get("story_id")
                link = f"https://news.ycombinator.com/item?id={object_id}"
                author = hit.get("author", "hn_founder")

                alert = RawAlert(
                    platform=self.PLATFORM,
                    source_name="HN (Who is Hiring?)",
                    author=author,
                    text=comment_text,
                    link=link,
                    timestamp=created_ts,
                )

                await self._emit(alert)

        if len(self._seen_ids) > 10_000:
            self._seen_ids = set(list(self._seen_ids)[-5_000:])
