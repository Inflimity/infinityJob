"""
X (Twitter) Deep Monitor — Playwright DOM scraper.

Uses CDP (Chrome DevTools Protocol) to connect to an already-running Chrome
browser that is logged into X. This completely bypasses X's bot detection
because it IS the real Chrome browser.

Fallback: If no running Chrome is found on CDP port 9222, launches its own
Playwright browser with persistent profile (for local/dev use).
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
    """
    Exhaustive search queries for X surveillance covering 52 specific keywords.
    Grouped into exactly 6 boolean queries to stay within X's character limits
    and ensure the entire 1-hour interval is searched continuously.
    """
    return [
        # Query 1: Assets & General Actions + Errors/Status
        '(token OR wallet OR coin OR balance OR "wallet connect" OR connection OR connect) (error OR failed OR pending OR stuck OR missing OR lost OR display OR "not showing" OR "not received" OR "not working" OR bug OR issue OR problem)',
        
        # Query 2: Assets & General Actions + Support/Help
        '(token OR wallet OR coin OR balance OR "wallet connect" OR connection OR connect) ("can\'t swap" OR "can\'t withdraw" OR "can\'t deposit" OR "how do I" OR "unable to" OR cannot OR "can\'t" OR fix OR recover OR restore OR help OR support OR why)',
        
        # Query 3: Transfers & Swaps + Errors/Status
        '(withdraw OR withdrawal OR swap OR swapping OR transfer OR transaction OR sent OR received OR deposit OR deposited OR bridge OR bridging) (error OR failed OR pending OR stuck OR missing OR lost OR display OR "not showing" OR "not received" OR "not working" OR bug OR issue OR problem)',
        
        # Query 4: Transfers & Swaps + Support/Help
        '(withdraw OR withdrawal OR swap OR swapping OR transfer OR transaction OR sent OR received OR deposit OR deposited OR bridge OR bridging) ("can\'t swap" OR "can\'t withdraw" OR "can\'t deposit" OR "how do I" OR "unable to" OR cannot OR "can\'t" OR fix OR recover OR restore OR help OR support OR why)',
        
        # Query 5: Staking & Airdrops + Errors/Status
        '(staked OR staking OR "my staking" OR "my stake" OR unstake OR unstaking OR claim OR claiming OR airdrop OR reward OR rewards) (error OR failed OR pending OR stuck OR missing OR lost OR display OR "not showing" OR "not received" OR "not working" OR bug OR issue OR problem)',
        
        # Query 6: Staking & Airdrops + Support/Help
        '(staked OR staking OR "my staking" OR "my stake" OR unstake OR unstaking OR claim OR claiming OR airdrop OR reward OR rewards) ("can\'t swap" OR "can\'t withdraw" OR "can\'t deposit" OR "how do I" OR "unable to" OR cannot OR "can\'t" OR fix OR recover OR restore OR help OR support OR why)'
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
        """Launch browser and scrape X search feeds."""
        import platform
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = None
            page = None

            # Launch Playwright with persistent context
            # Setting headless=False so you can log in manually. Once logged in, you can change this back to True if desired.
            logger.info("Launching Playwright browser...")
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
                # Navigate to X with explicit timeout so it never hangs
                logger.info("Navigating to X (https://x.com)...")
                try:
                    await page.goto("https://x.com", wait_until="domcontentloaded", timeout=20000)
                except Exception as goto_err:
                    logger.warning("Initial goto x.com timed out or notice popped up (%s), continuing...", str(goto_err)[:60])
                
                await page.wait_for_timeout(3000)

                # Smart login detection: proceed if on x.com/home/search without login redirect
                is_logged_in = False
                login_attempts = 0
                while not is_logged_in and self._running:
                    url = page.url.lower()
                    login_btn = await page.query_selector('a[href="/login"]') or await page.query_selector('[data-testid="loginButton"]')
                    has_nav = await page.query_selector('[data-testid="SideNav_NewTweet_Button"]') or await page.query_selector('[aria-label="Home"]') or await page.query_selector('[data-testid="primaryColumn"]')
                    
                    if "flow/login" in url or login_btn:
                        logger.info("Waiting for X login... (Current URL: %s)", page.url)
                    elif has_nav or "home" in url:
                        # Proceed directly to deep search!
                        is_logged_in = True
                        break
                    else:
                        logger.info("Waiting for X page render... (Current URL: %s)", page.url)
                        if login_attempts >= 10:
                            logger.warning("Still waiting for X page render or manual login. It might be stuck or loading slowly. (You have 10 minutes to log in)")

                    login_attempts += 1
                    if login_attempts >= 150:
                        logger.warning("Timeout waiting for X to load after 10 minutes. Continuing anyway, but it may fail...")
                        break
                    await asyncio.sleep(4)

                logger.info("✅ X page ready! Proceeding with deep scan.")

                while self._running:
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
                    await asyncio.sleep(1800)
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
            screenshot_path = os.path.abspath(f"twitter_empty_search.png")
            try:
                await page.screenshot(path=screenshot_path)
                logger.info("No tweets loaded for query: %s. Saved debug screenshot to %s", query[:60], screenshot_path)
            except Exception as e:
                logger.info("No tweets loaded for query: %s. Failed to take screenshot: %s", query[:60], e)
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
