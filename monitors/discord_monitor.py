"""
Discord Monitor — Playwright persistent context DOM scraper.

Monitors specific Discord web channels by navigating to their URLs
using a persistent browser profile (stays logged in after first manual login).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

# Discord DOM selectors (may need updating if Discord changes their frontend)
MSG_LIST_SELECTOR = 'ol[data-list-id="chat-messages"]'
MSG_ITEM_SELECTOR = 'li[id^="chat-messages-"]'
MSG_CONTENT_SELECTOR = 'div[class*="messageContent"]'
MSG_AUTHOR_SELECTOR = 'span[class*="username"]'
MSG_TIMESTAMP_SELECTOR = "time"


class DiscordMonitor(BaseMonitor):
    """Monitors Discord channels via Playwright browser automation."""

    PLATFORM = "discord"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="DiscordMonitor")
        self._settings = settings
        self._channel_urls = settings.discord_channel_urls
        self._poll_interval = settings.poll_interval_seconds
        self._user_data_dir = os.path.abspath("./browser_profiles/discord")
        self._seen_ids: set[str] = set()

    async def _run(self) -> None:
        """Launch persistent browser and begin polling Discord channels."""
        if not self._channel_urls:
            logger.warning("DiscordMonitor: No channel URLs configured, skipping")
            # Sleep indefinitely so the monitor doesn't restart in a loop
            while self._running:
                await asyncio.sleep(60)
            return

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            # Launch with persistent context so login session is preserved
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=False,  # Set to True once you've logged in manually
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )

            try:
                page = await context.new_page()

                while self._running:
                    for url in self._channel_urls:
                        try:
                            await self._scrape_channel(page, url)
                        except Exception:
                            logger.exception(
                                "Error scraping Discord channel: %s", url
                            )

                    await asyncio.sleep(self._poll_interval)
            finally:
                await context.close()

    async def _scrape_channel(self, page, url: str) -> None:
        """Navigate to a Discord channel and extract new messages."""
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # Wait for the message list to appear
        try:
            await page.wait_for_selector(MSG_LIST_SELECTOR, timeout=15000)
        except Exception:
            logger.debug("Discord message list not found at %s", url)
            return

        # Extract all message items
        items = await page.query_selector_all(MSG_ITEM_SELECTOR)

        for item in items:
            try:
                msg_id = await item.get_attribute("id")
                if not msg_id or msg_id in self._seen_ids:
                    continue

                # Extract message content
                content_el = await item.query_selector(MSG_CONTENT_SELECTOR)
                content = await content_el.inner_text() if content_el else ""
                if not content.strip():
                    continue

                # Extract author
                author_el = await item.query_selector(MSG_AUTHOR_SELECTOR)
                author = await author_el.inner_text() if author_el else "Unknown"

                # Extract channel name from URL
                channel_name = self._extract_channel_name(url)

                self._seen_ids.add(msg_id)

                alert = RawAlert(
                    platform=self.PLATFORM,
                    source_name=f"Discord: {channel_name}",
                    author=author,
                    text=content,
                    link=url,
                )

                await self._emit(alert)

            except Exception:
                logger.debug("Error parsing Discord message item", exc_info=True)

    @staticmethod
    def _extract_channel_name(url: str) -> str:
        """Extract a readable channel identifier from a Discord URL."""
        # URL format: https://discord.com/channels/{server_id}/{channel_id}
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return "unknown-channel"
