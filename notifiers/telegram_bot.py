"""
Telegram Bot Notifier — sends formatted alerts to your personal DMs.

Uses python-telegram-bot v20+ (async) with inline keyboard buttons
for Dismiss / Mute / Save actions, plus batch digest support.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from core.engine import ProcessedAlert

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends alert notifications to a personal Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: str,
        admin_chat_id: int,
        batch_window_seconds: int = 60,
        batch_threshold: int = 10,
    ) -> None:
        self._bot = Bot(token=bot_token)
        self._admin_chat_id = admin_chat_id
        self._batch_window = batch_window_seconds
        self._batch_threshold = batch_threshold

        # Batch accumulator
        self._batch_buffer: list[ProcessedAlert] = []
        self._batch_timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def send_alert(self, alert: ProcessedAlert) -> None:
        """
        Send or batch an alert.

        If too many alerts arrive within the batch window, they are
        bundled into a single digest message instead of individual pings.
        """
        async with self._lock:
            self._batch_buffer.append(alert)

            if len(self._batch_buffer) >= self._batch_threshold:
                # Threshold hit — flush as digest immediately
                await self._flush_digest()
            elif self._batch_timer is None:
                # Start a timer; if it expires without hitting threshold,
                # send alerts individually
                self._batch_timer = asyncio.create_task(
                    self._batch_timeout()
                )

    async def _batch_timeout(self) -> None:
        """Wait for the batch window, then flush individually."""
        await asyncio.sleep(self._batch_window)
        async with self._lock:
            await self._flush_individual()

    async def _flush_individual(self) -> None:
        """Send each buffered alert as its own message."""
        alerts = self._batch_buffer[:]
        self._batch_buffer.clear()
        self._batch_timer = None

        for alert in alerts:
            try:
                text = self._format_alert(alert)
                keyboard = self._build_keyboard(alert)
                await self._bot.send_message(
                    chat_id=self._admin_chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Failed to send individual alert")

            # Small delay between messages to respect rate limits
            await asyncio.sleep(0.3)

    async def _flush_digest(self) -> None:
        """Bundle all buffered alerts into a single digest message."""
        alerts = self._batch_buffer[:]
        self._batch_buffer.clear()
        if self._batch_timer is not None:
            self._batch_timer.cancel()
            self._batch_timer = None

        if not alerts:
            return

        text = self._format_digest(alerts)
        try:
            await self._bot.send_message(
                chat_id=self._admin_chat_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to send digest message")

    @staticmethod
    def _format_alert(alert: ProcessedAlert) -> str:
        """Format a single alert into a rich Markdown message."""
        raw = alert.raw
        match = alert.match

        platform_emoji = {
            "telegram": "📱",
            "discord": "🎮",
            "twitter": "🐦",
            "reddit": "🔴",
        }.get(raw.platform, "📡")

        coins_str = ", ".join(f"`{c.upper()}`" for c in match.matched_coins)
        keywords_str = ", ".join(f"`{k}`" for k in match.matched_keywords)

        # Truncate message text to avoid Telegram's 4096 char limit
        msg_text = raw.text[:500] + ("..." if len(raw.text) > 500 else "")

        lines = [
            f"🚨 *Alert from {raw.platform.title()}* {platform_emoji}",
            "",
            f"💬 *Source:* {raw.source_name}",
            f"👤 *User:* {raw.author}",
            f"🪙 *Coins:* {coins_str}",
            f"🔑 *Keywords:* {keywords_str}",
            f"⚡ *Severity:* {match.severity_score}",
            "",
            f"📝 *Message:*\n{msg_text}",
        ]

        if raw.link:
            lines.append(f"\n🔗 [Jump to Message]({raw.link})")

        return "\n".join(lines)

    @staticmethod
    def _build_keyboard(alert: ProcessedAlert) -> InlineKeyboardMarkup:
        """Build inline action buttons for an alert."""
        alert_id = id(alert)  # Simple identifier; replaced by DB id in production
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Dismiss", callback_data=f"dismiss:{alert_id}"),
                    InlineKeyboardButton("🔇 Mute Source (1h)", callback_data=f"mute:{alert_id}"),
                    InlineKeyboardButton("📌 Save", callback_data=f"save:{alert_id}"),
                ]
            ]
        )

    @staticmethod
    def _format_digest(alerts: list[ProcessedAlert]) -> str:
        """Format multiple alerts into a single digest summary."""
        header = f"📋 *Alert Digest* — {len(alerts)} alerts\n{'─' * 30}\n"

        entries = []
        for i, alert in enumerate(alerts, 1):
            raw = alert.raw
            coins = ", ".join(c.upper() for c in alert.match.matched_coins)
            snippet = raw.text[:80] + ("..." if len(raw.text) > 80 else "")
            link_part = f" [↗]({raw.link})" if raw.link else ""
            entries.append(
                f"*{i}.* [{raw.platform.title()}] {raw.source_name}\n"
                f"   🪙 {coins} — {snippet}{link_part}"
            )

        return header + "\n\n".join(entries)

    async def close(self) -> None:
        """Flush pending alerts and clean up."""
        async with self._lock:
            if self._batch_buffer:
                await self._flush_individual()
        await self._bot.shutdown()
