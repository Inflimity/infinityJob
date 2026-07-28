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
import html as html_lib

if TYPE_CHECKING:
    from core.engine import ProcessedAlert

logger = logging.getLogger(__name__)


def _escape(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html_lib.escape(text) if text else ""


from telegram.request import HTTPXRequest

class TelegramNotifier:
    """Sends alert notifications to a personal Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: str,
        admin_chat_id: int,
        batch_window_seconds: int = 60,
        batch_threshold: int = 10,
    ) -> None:
        # Increased timeouts to help with slow or restricted RDP connections
        request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
        self._bot = Bot(token=bot_token, request=request)
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
                    parse_mode="HTML",
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
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to send digest message")

    @staticmethod
    def _format_alert(alert: ProcessedAlert) -> str:
        """Format a single alert into a rich HTML message."""
        raw = alert.raw
        intent = alert.intent

        platform_emoji = {
            "telegram": "📱",
            "discord": "🎮",
            "twitter": "🐦",
            "reddit": "🔴",
        }.get(raw.platform, "📡")

        keywords_str = ", ".join(f"<code>{_escape(k)}</code>" for k in intent.matched_keywords)
        time_str = raw.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        summary_text = _escape(intent.summary_sentence[:500])

        if getattr(raw, "is_system_event", False):
            lines = [
                f"🎉 <b>New User Alert — {_escape(raw.platform.title())}</b> {platform_emoji}",
                "",
                f"👤 <b>User:</b> {_escape(raw.author)}",
                f"⏰ <b>Timestamp:</b> {time_str}",
                "",
                f"📝 <b>Details:</b>\n{summary_text}",
            ]
        else:
            lines = [
                f"🚨 <b>Real User Complaint — {_escape(raw.platform.title())}</b> {platform_emoji}",
                "",
                f"👤 <b>Author:</b> {_escape(raw.author)}",
                f"🌐 <b>Language:</b> {_escape(intent.language)}",
                f"⏰ <b>Timestamp:</b> {time_str}",
                f"🏷️ <b>Category:</b> {_escape(intent.category.title())}",
                f"🔑 <b>Keywords:</b> {keywords_str}",
                "",
                f"📝 <b>Summary of Issue:</b>\n{summary_text}",
            ]

        if raw.link:
            lines.append(f'\n🔗 <a href="{raw.link}">Jump to Post / Server</a>')

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
        header = f"📋 <b>Alert Digest</b> — {len(alerts)} alerts\n{'─' * 30}\n"

        entries = []
        for i, alert in enumerate(alerts, 1):
            raw = alert.raw
            cat = _escape(alert.intent.category.title())
            snippet = _escape(alert.intent.summary_sentence[:80]) + ("..." if len(alert.intent.summary_sentence) > 80 else "")
            link_part = f' <a href="{raw.link}">↗</a>' if raw.link else ""
            entries.append(
                f"<b>{i}.</b> [{_escape(raw.platform.title())}] {_escape(raw.author)}\n"
                f"   🏷️ {cat} — {snippet}{link_part}"
            )

        return header + "\n\n".join(entries)

    async def close(self) -> None:
        """Flush pending alerts and clean up."""
        async with self._lock:
            if self._batch_buffer:
                await self._flush_individual()
        await self._bot.shutdown()
