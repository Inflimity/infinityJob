"""
Telegram Monitor — Telethon userbot with passive event streams.

Hooks into all group/supergroup/channel messages your account receives
via events.NewMessage. No polling, no admin rights needed — just a
regular group member session.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telethon import TelegramClient, events

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)


class TelegramMonitor(BaseMonitor):
    """Monitors Telegram groups via Telethon MTProto event streams."""

    PLATFORM = "telegram"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="TelegramMonitor")
        self._settings = settings
        self._client = TelegramClient(
            "monitor_session",
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    async def _run(self) -> None:
        """Connect the Telethon client and register the event handler."""
        # Register the new-message event handler
        self._client.add_event_handler(
            self._on_new_message,
            events.NewMessage,
        )

        # Start the client (first run will prompt for phone + code interactively)
        await self._client.start()
        me = await self._client.get_me()
        logger.info(
            "TelegramMonitor connected as @%s (ID: %s)",
            me.username or "unknown",
            me.id,
        )

        # Run until disconnected or stopped
        await self._client.run_until_disconnected()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        """Handle each incoming message from groups/channels."""
        # Skip private messages — we only care about group activity
        if event.is_private:
            return

        # Skip messages without text content
        if not event.raw_text:
            return

        try:
            chat = await event.get_chat()
            sender = await event.get_sender()

            chat_title = getattr(chat, "title", "Unknown Group")
            sender_username = getattr(sender, "username", None)
            sender_name = (
                f"@{sender_username}"
                if sender_username
                else getattr(sender, "first_name", "Unknown User")
            )

            # Build message link (works for supergroups/channels)
            link = ""
            if hasattr(event.message, "id") and hasattr(chat, "username"):
                if chat.username:
                    link = f"https://t.me/{chat.username}/{event.message.id}"

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=chat_title,
                author=sender_name,
                text=event.raw_text,
                link=link,
            )

            await self._emit(alert)

        except Exception:
            logger.exception("Error processing Telegram message")

    async def stop(self) -> None:
        """Disconnect the Telethon client and stop the monitor."""
        await super().stop()
        if self._client.is_connected():
            await self._client.disconnect()
