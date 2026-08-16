"""
X (Twitter) Job Monitor — Playwright DOM scraper.

Uses persistent Chrome context to scan X live search feeds for real-time hiring tweets,
direct founder posts, and tech job bounties across the 3 career tracks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

from core.engine import RawAlert
from monitors.base import BaseMonitor
from query_builder import build_twitter_job_queries

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

# X/Twitter DOM selectors
TWEET_SELECTOR = 'article[data-testid="tweet"]'
TWEET_TEXT_SELECTOR = 'div[data-testid="tweetText"]'
TWEET_USER_SELECTOR = 'div[data-testid="User-Name"]'
TWEET_LINK_SELECTOR = 'a[href*="/status/"]'
TWEET_TIME_SELECTOR = 'time'


class TwitterMonitor(BaseMonitor):
    """Monitors X (Twitter) via deep scrolling of the Latest search feed."""

    PLATFORM = "twitter"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="TwitterMonitor")
        self._settings = settings
        self._search_queries = build_twitter_job_queries() + (settings.twitter_search_queries or [])
        self._poll_interval = settings.poll_interval_seconds
        self._user_data_dir = os.path.abspath("./browser_profiles/twitter")
        self._seen_hashes: set[str] = set()
        logger.info("TwitterMonitor initialized with %d job search queries", len(self._search_queries))

    async def _run(self) -> None:
        """Launch browser and scrape X search feeds."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            logger.info("Launching Playwright browser for X monitoring...")
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--disable-gpu"],
                ignore_default_args=["--enable-automation"],
            )

            # Anti-bot stealth
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()

            try:
                logger.info("Navigating to X (https://x.com)...")
                try:
                    await page.goto("https://x.com", wait_until="domcontentloaded", timeout=20000)
                except Exception as goto_err:
                    logger.warning("Initial goto x.com notice (%s), continuing...", str(goto_err)[:60])

                await page.wait_for_timeout(3000)

                # Wait for user to be logged in if not already
                is_logged_in = False
                login_attempts = 0
                while not is_logged_in and self._running:
                    url = page.url.lower()
                    login_btn = await page.query_selector('a[href="/login"]') or await page.query_selector('[data-testid="loginButton"]')
                    has_nav = await page.query_selector('[data-testid="SideNav_NewTweet_Button"]') or await page.query_selector('[aria-label="Home"]') or await page.query_selector('[data-testid="primaryColumn"]')

                    if "flow/login" in url or login_btn:
                        logger.info("Waiting for X login... (Current URL: %s)", page.url)
                    elif has_nav or "home" in url:
                        is_logged_in = True
                        break
                    else:
                        if login_attempts >= 10:
                            logger.warning("Still waiting for X login or session render (Session saved in %s)", self._user_data_dir)

                    login_attempts += 1
                    if login_attempts >= 120:
                        logger.warning("Continuing scan after timeout...")
                        break
                    await asyncio.sleep(4)

                logger.info("✅ X page ready! Proceeding with job search cycles.")

                while self._running:
                    for query in self._search_queries:
                        if not self._running:
                            break
                        try:
                            await self._scrape_search(page, query)
                        except Exception:
                            logger.exception("Error during X search scrape for: %s", query)

                        # Respectful pause between queries
                        await asyncio.sleep(180)

                    logger.info("X job search cycle complete. Sleeping 15 minutes.")
                    await asyncio.sleep(900)
            finally:
                await context.close()

    async def _scrape_search(self, page, query: str) -> None:
        """Deep scroll an X live search until we hit older tweets."""
        search_url = f"https://x.com/search?q={quote(query)}&f=live"
        logger.info("Scraping X job search: %s", query[:80])

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        try:
            await page.wait_for_selector(TWEET_SELECTOR, timeout=15000)
        except Exception:
            logger.info("No tweets found for query: %s", query[:60])
            return

        now = datetime.now(timezone.utc)
        scroll_attempts = 0
        max_scrolls = 15

        while scroll_attempts < max_scrolls and self._running:
            tweets = await page.query_selector_all(TWEET_SELECTOR)
            oldest_age_minutes = 0

            for tweet in tweets:
                try:
                    tweet_dt = now
                    time_el = await tweet.query_selector(TWEET_TIME_SELECTOR)
                    if time_el:
                        dt_str = await time_el.get_attribute("datetime")
                        if dt_str:
                            tweet_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            age_mins = (now - tweet_dt).total_seconds() / 60
                            oldest_age_minutes = max(oldest_age_minutes, age_mins)

                            if age_mins > 60:  # Skip tweets older than 60 minutes
                                continue

                    text_el = await tweet.query_selector(TWEET_TEXT_SELECTOR)
                    text = await text_el.inner_text() if text_el else ""
                    if not text.strip():
                        continue

                    content_hash = hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]
                    if content_hash in self._seen_hashes:
                        continue
                    self._seen_hashes.add(content_hash)

                    user_el = await tweet.query_selector(TWEET_USER_SELECTOR)
                    author = "Unknown"
                    if user_el:
                        user_text = await user_el.inner_text()
                        lines = user_text.strip().split("\n")
                        author = lines[-1] if lines else "Unknown"

                    link = ""
                    link_el = await tweet.query_selector(TWEET_LINK_SELECTOR)
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href:
                            link = f"https://x.com{href}" if href.startswith("/") else href

                    alert = RawAlert(
                        platform=self.PLATFORM,
                        source_name="X Live Search",
                        author=author,
                        text=text,
                        link=link,
                        timestamp=tweet_dt,
                    )

                    await self._emit(alert)

                except Exception:
                    logger.debug("Error parsing tweet element", exc_info=True)

            if len(self._seen_hashes) > 10_000:
                self._seen_hashes = set(list(self._seen_hashes)[-5_000:])

            if oldest_age_minutes > 60:
                break

            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(1500)
            scroll_attempts += 1
