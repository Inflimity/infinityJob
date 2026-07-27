"""
X (Twitter) Deep Monitor — Playwright persistent context DOM scraper.

Executes massive consolidated OR queries to capture 100% of user intent,
scrolling deep into the "Latest" tab for up to 60 minutes of history.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from core.engine import RawAlert
from core.heuristic_filters import CRYPTO_ENTITIES, CRYPTO_ACTIONS, PROBLEM_WORDS
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

# X/Twitter DOM selectors
TWEET_SELECTOR = 'article[data-testid="tweet"]'
TWEET_TEXT_SELECTOR = 'div[data-testid="tweetText"]'
TWEET_USER_SELECTOR = 'div[data-testid="User-Name"]'
TWEET_LINK_SELECTOR = 'a[href*="/status/"]'
TWEET_TIME_SELECTOR = 'time'


def build_twitter_queries() -> list[str]:
    """Generates just 4 mega-queries to minimize searches and protect the account.
    
    Each query packs maximum keywords into Twitter's ~500 char query limit.
    This covers all 52 keywords in only 4 searches instead of 16.
    """
    return [
        # Query 1: Wallet/token problems
        '(wallet OR token OR coin OR balance OR "smart contract") (error OR failed OR stuck OR missing OR lost OR scam OR bug) -filter:links -giveaway -"dm me" -presale',
        # Query 2: Transaction/transfer issues  
        '(withdraw OR swap OR transfer OR deposit OR bridge OR staking) (error OR failed OR stuck OR pending OR "not working" OR "unable to") -filter:links -giveaway -"dm me" -presale',
        # Query 3: Recovery and help requests
        '(wallet OR token OR crypto OR blockchain) (help OR support OR recover OR restore OR fix OR "how do I" OR "anyone help") -filter:links -giveaway -"dm me" -presale',
        # Query 4: Specific complaint patterns
        '(airdrop OR claim OR reward OR unstake) (scam OR failed OR stuck OR missing OR "not received" OR "can\'t" OR problem) -filter:links -giveaway -"dm me" -presale',
    ]


class TwitterMonitor(BaseMonitor):
    """Monitors X (Twitter) via deep scrolling of the Latest search feed."""

    PLATFORM = "twitter"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="TwitterMonitor")
        self._settings = settings
        # Combine our deep heuristic queries with any custom queries the user put in .env
        self._search_queries = build_twitter_queries() + (settings.twitter_search_queries or [])
        self._poll_interval = settings.poll_interval_seconds
        self._user_data_dir = os.path.abspath("./browser_profiles/twitter")
        self._seen_hashes: set[str] = set()
        logger.info("TwitterMonitor initialized with %d deep queries", len(self._search_queries))

    async def _run(self) -> None:
        """Launch persistent browser and begin deep polling X search feeds."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=True,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            
            # Anti-bot stealth script to bypass "verifying username"
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                page = await context.new_page()
                
                # Navigate to X so the user can actually log in if they need to
                await page.goto("https://x.com", wait_until="domcontentloaded")
                
                # Give X a few seconds to load or redirect
                await page.wait_for_timeout(3000)
                
                # Loop until we detect a logged-in element (like the Tweet button or Home link) or /home URL
                is_logged_in = False
                while not is_logged_in and self._running:
                    if "home" in page.url or await page.query_selector('[data-testid="SideNav_NewTweet_Button"]') or await page.query_selector('[data-testid="AppTabBar_Home_Link"]'):
                        is_logged_in = True
                        break
                    
                    logger.info("Waiting for manual X login. Please log in using the opened browser window...")
                    await asyncio.sleep(5)
                    
                logger.info("Successfully detected login! Proceeding with deep scan.")

                while self._running:
                    # We run a full deep scan cycle
                    logger.info("Starting new deep scan cycle on X across %d queries", len(self._search_queries))
                    
                    for query in self._search_queries:
                        if not self._running:
                            break
                        try:
                            await self._scrape_search(page, query)
                        except Exception:
                            logger.exception("Error during deep scrape for query: %s", query)
                        
                        # 10-minute pause between queries to look exactly like a normal human
                        await asyncio.sleep(600)

                    logger.info("Deep scan cycle complete. Sleeping 30 minutes before next cycle.")
                    await asyncio.sleep(1800)  # 30 minutes between full cycles
            finally:
                await context.close()

    async def _scrape_search(self, page, query: str) -> None:
        """Deep scroll an X live search until we hit posts older than 60 minutes."""
        search_url = f"https://x.com/search?q={quote(query)}&f=live"
        logger.info("Scraping X search: %s", query[:80])
        
        # Use domcontentloaded — X never reaches "networkidle" due to constant background requests
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for tweet articles to actually render on the page
        try:
            await page.wait_for_selector(TWEET_SELECTOR, timeout=20000)
        except Exception:
            logger.info("No tweets loaded for query: %s", query[:60])
            return

        now = datetime.now(timezone.utc)
        scroll_attempts = 0
        max_scrolls = 20  # Hard cap to prevent infinite scroll bugs

        while scroll_attempts < max_scrolls and self._running:
            tweets = await page.query_selector_all(TWEET_SELECTOR)
            oldest_age_minutes = 0

            for tweet in tweets:
                try:
                    # Parse timestamp to enforce 60-minute depth
                    time_el = await tweet.query_selector(TWEET_TIME_SELECTOR)
                    if time_el:
                        dt_str = await time_el.get_attribute("datetime")
                        if dt_str:
                            tweet_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            age_mins = (now - tweet_dt).total_seconds() / 60
                            oldest_age_minutes = max(oldest_age_minutes, age_mins)
                            
                            # If this specific tweet is older than 60 mins, we can skip processing it
                            if age_mins > 60:
                                continue

                    # Extract tweet text
                    text_el = await tweet.query_selector(TWEET_TEXT_SELECTOR)
                    text = await text_el.inner_text() if text_el else ""
                    if not text.strip():
                        continue

                    # Deduplicate by content hash
                    content_hash = hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]
                    if content_hash in self._seen_hashes:
                        continue
                    self._seen_hashes.add(content_hash)

                    # Extract username
                    user_el = await tweet.query_selector(TWEET_USER_SELECTOR)
                    author = "Unknown"
                    if user_el:
                        user_text = await user_el.inner_text()
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
                        source_name=f"X Deep Search",
                        author=author,
                        text=text,
                        link=link,
                    )

                    await self._emit(alert)

                except Exception:
                    logger.debug("Error parsing tweet element", exc_info=True)

            # Cap the seen set to prevent unbounded growth
            if len(self._seen_hashes) > 10_000:
                self._seen_hashes = set(list(self._seen_hashes)[-5_000:])

            # Check if we've scrolled past 60 minutes
            if oldest_age_minutes > 60:
                logger.debug("Reached 60-minute depth (oldest post: %d mins ago). Stopping scroll.", oldest_age_minutes)
                break
                
            # Scroll down to load more
            await page.keyboard.press("PageDown")
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(2000)
            scroll_attempts += 1
