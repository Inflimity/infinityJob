"""
X (Twitter) Monitor — Playwright persistent context DOM scraper.

Monitors X search feeds using live search URLs via a persistent
browser profile. Extracts tweets from the DOM and emits alerts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import TYPE_CHECKING
from urllib.parse import quote

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

# X/Twitter DOM selectors
TWEET_SELECTOR = 'article[data-testid="tweet"]'
TWEET_TEXT_SELECTOR = 'div[data-testid="tweetText"]'
TWEET_USER_SELECTOR = 'div[data-testid="User-Name"]'
TWEET_LINK_SELECTOR = 'a[href*="/status/"]'


class TwitterMonitor(BaseMonitor):
    """Monitors X (Twitter) search feeds via Playwright browser automation."""

    PLATFORM = "twitter"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="TwitterMonitor")
        self._settings = settings
        self._search_queries = settings.twitter_search_queries
        self._poll_interval = settings.poll_interval_seconds
        self._user_data_dir = os.path.abspath("./browser_profiles/twitter")
        self._seen_hashes: set[str] = set()

    async def _run(self) -> None:
        """Launch persistent browser and begin polling X search feeds."""
        if not self._search_queries:
            logger.warning("TwitterMonitor: No search queries configured, skipping")
            while self._running:
                await asyncio.sleep(60)
            return

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=False,  # Set to True once you've logged in manually
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )

            try:
                page = await context.new_page()

                while self._running:
                    for query in self._search_queries:
                        try:
                            await self._scrape_search(page, query)
                        except Exception:
                            logger.exception(
                                "Error scraping X search: %s", query
                            )

                    await asyncio.sleep(self._poll_interval)
            finally:
                await context.close()

    async def _scrape_search(self, page, query: str) -> None:
        """Navigate to an X live search and extract new tweets."""
        search_url = f"https://x.com/search?q={quote(query)}&f=live"
        await page.goto(search_url, wait_until="networkidle", timeout=30000)

        # Wait for tweet articles to load
        try:
            await page.wait_for_selector(TWEET_SELECTOR, timeout=15000)
        except Exception:
            logger.debug("No tweets found for query: %s", query)
            return

        # Extract all tweet articles
        tweets = await page.query_selector_all(TWEET_SELECTOR)

        for tweet in tweets:
            try:
                # Extract tweet text
                text_el = await tweet.query_selector(TWEET_TEXT_SELECTOR)
                text = await text_el.inner_text() if text_el else ""
                if not text.strip():
                    continue

                # Deduplicate by content hash
                content_hash = hashlib.sha256(
                    text.strip().lower().encode()
                ).hexdigest()[:16]
                if content_hash in self._seen_hashes:
                    continue
                self._seen_hashes.add(content_hash)

                # Extract username
                user_el = await tweet.query_selector(TWEET_USER_SELECTOR)
                author = "Unknown"
                if user_el:
                    user_text = await user_el.inner_text()
                    # User-Name div typically contains "Display Name\n@username"
                    lines = user_text.strip().split("\n")
                    author = lines[-1] if lines else "Unknown"

                # Extract tweet link
                link = ""
                link_el = await tweet.query_selector(TWEET_LINK_SELECTOR)
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        link = f"https://x.com{href}" if href.startswith("/") else href

                alert = RawAlert(
                    platform=self.PLATFORM,
                    source_name=f"X Search: {query}",
                    author=author,
                    text=text,
                    link=link,
                )

                await self._emit(alert)

            except Exception:
                logger.debug("Error parsing tweet element", exc_info=True)

        # Cap the seen set to prevent unbounded growth
        if len(self._seen_hashes) > 10_000:
            # Keep the most recent half
            keep = set(list(self._seen_hashes)[-5_000:])
            self._seen_hashes = keep
