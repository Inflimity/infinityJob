"""
Telegram Bot Notifier — sends structured Job Alert Cards with interactive buttons.

Features:
- Track Badges (💻 Full-Stack, 🤖 AI/Agentic, 📊 Systems/Workforce)
- Match Score & Pay Transparency
- Interactive Buttons:
  - [⭐ Save Job]
  - [📋 Copy Pitch Snippet] (Replies with a pre-written outreach message tailored to the role)
  - [🚫 Hide Source / Poster]
  - [🌐 Open / Apply]
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.request import HTTPXRequest

if TYPE_CHECKING:
    from core.engine import ProcessedAlert
    from storage.database import DatabaseManager

logger = logging.getLogger(__name__)


def _escape(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html_lib.escape(str(text)) if text else ""


PLATFORM_EMOJIS = {
    "twitter": "🐦",
    "reddit": "🔴",
    "hacker_news": "🟠",
    "himalayas": "🏔️",
    "remote_boards": "🌐",
    "github": "🐙",
    "telegram": "📱",
    "discord": "🎮",
}


class TelegramNotifier:
    """Sends job alert notifications to a personal Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: str,
        admin_chat_id: int,
        batch_window_seconds: int = 60,
        batch_threshold: int = 10,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self._bot_token = bot_token
        self._admin_chat_id = admin_chat_id
        self._batch_window = batch_window_seconds
        self._batch_threshold = batch_threshold
        self._db = db

        request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
        self._bot = Bot(token=bot_token, request=request)

        # Batch accumulator
        self._batch_buffer: list[ProcessedAlert] = []
        self._batch_timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # Alert in-memory store for quick callback lookups (maps alert_id -> ProcessedAlert)
        self._alert_cache: dict[int, ProcessedAlert] = {}
        self._app: Optional[Application] = None

    def set_db(self, db: DatabaseManager) -> None:
        """Inject database manager."""
        self._db = db

    async def start_polling_callbacks(self) -> None:
        """Start listening for inline button callbacks (pitch copy, save, mute)."""
        try:
            self._app = Application.builder().token(self._bot_token).build()
            self._app.add_handler(CallbackQueryHandler(self._handle_callback))
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram callback bot handler started")
        except Exception:
            logger.exception("Failed to start Telegram callback polling")

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button clicks."""
        query = update.callback_query
        if not query or not query.data:
            return

        data = query.data
        action, _, alert_id_str = data.partition(":")

        try:
            alert_id = int(alert_id_str)
        except ValueError:
            await query.answer("Invalid action.")
            return

        cached = self._alert_cache.get(alert_id)

        if action == "pitch":
            if cached and cached.job and cached.job.pitch:
                pitch_msg = (
                    f"📋 <b>Outreach Pitch Snippet:</b>\n\n"
                    f"<code>{_escape(cached.job.pitch)}</code>\n\n"
                    f"<i>(Tap to copy on mobile, or paste directly into your email/DM)</i>"
                )
                await query.message.reply_text(pitch_msg, parse_mode="HTML")
                await query.answer("Pitch snippet sent!")
            else:
                await query.answer("Pitch template unavailable.")

        elif action == "save":
            if self._db and cached and cached.db_id:
                await self._db.save_alert_bookmark(cached.db_id)
            await query.answer("⭐ Job saved to bookmarks!")
            try:
                await query.edit_message_reply_markup(
                    reply_markup=self._build_keyboard(cached, saved=True) if cached else None
                )
            except Exception:
                pass

        elif action == "mute":
            if cached:
                if self._db:
                    until = datetime.now(timezone.utc) + timedelta(days=7)
                    await self._db.mute_source(cached.raw.platform, cached.raw.author, until)
                await query.answer(f"🔇 Muted {cached.raw.author} for 7 days.")
            else:
                await query.answer("Muted.")

        elif action == "dismiss":
            await query.answer("Dismissed.")
            try:
                await query.message.delete()
            except Exception:
                pass

    async def send_alert(self, alert: ProcessedAlert) -> None:
        """Send or batch a high-priority job alert."""
        # Cache for callbacks
        alert_id = alert.db_id or id(alert)
        self._alert_cache[alert_id] = alert
        if len(self._alert_cache) > 2000:
            old_keys = list(self._alert_cache.keys())[:500]
            for k in old_keys:
                del self._alert_cache[k]

        async with self._lock:
            self._batch_buffer.append(alert)

            if len(self._batch_buffer) >= self._batch_threshold:
                await self._flush_digest()
            elif self._batch_timer is None:
                self._batch_timer = asyncio.create_task(self._batch_timeout())

    async def _batch_timeout(self) -> None:
        """Wait for batch window, then send individually."""
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
                text = self._format_job_card(alert)
                keyboard = self._build_keyboard(alert)
                await self._bot.send_message(
                    chat_id=self._admin_chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Failed to send Telegram job alert")

            await asyncio.sleep(0.3)

    async def _flush_digest(self) -> None:
        """Bundle multiple alerts into a digest."""
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
    def _format_job_card(alert: ProcessedAlert) -> str:
        """Format a single JobMatch into a clean, modern HTML Telegram Card."""
        raw = alert.raw
        job = alert.job

        platform_emoji = PLATFORM_EMOJIS.get(raw.platform, "💼")
        skills_str = ", ".join(f"<code>{_escape(s)}</code>" for s in job.matched_skills) or "<i>General Stack</i>"
        time_str = raw.timestamp.strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"💼 <b>NEW JOB MATCH — [{_escape(raw.platform.replace('_', ' ').title())}]</b> {platform_emoji}",
            f"🏷️ <b>Track:</b> {job.track_badge}  |  ⭐ <b>Score:</b> <code>{job.score}%</code>",
            "",
            f"🎯 <b>Role:</b> <b>{_escape(job.role)}</b>",
            f"🏢 <b>Company / Poster:</b> {_escape(job.company)}",
            f"💰 <b>Comp:</b> {_escape(job.salary or 'Competitive / Negotiable')}",
            f"🌍 <b>Location:</b> {_escape(job.location)}",
            f"🛠️ <b>Tech Stack:</b> {skills_str}",
            f"⏰ <b>Posted:</b> {time_str}",
            "",
            f"📝 <b>Overview:</b>\n{_escape(job.summary)}",
        ]

        if raw.link:
            lines.append(f'\n🔗 <a href="{raw.link}">View Original Post & Apply</a>')

        return "\n".join(lines)

    @staticmethod
    def _build_keyboard(alert: ProcessedAlert, saved: bool = False) -> InlineKeyboardMarkup:
        """Build interactive callback and URL action buttons."""
        alert_id = alert.db_id or id(alert)
        save_btn_text = "✅ Saved" if saved else "⭐ Save Job"

        buttons = [
            [
                InlineKeyboardButton(save_btn_text, callback_data=f"save:{alert_id}"),
                InlineKeyboardButton("📋 Pitch Snippet", callback_data=f"pitch:{alert_id}"),
            ],
            [
                InlineKeyboardButton("🔇 Hide Poster (7d)", callback_data=f"mute:{alert_id}"),
                InlineKeyboardButton("🗑️ Dismiss", callback_data=f"dismiss:{alert_id}"),
            ],
        ]

        if alert.raw.link:
            buttons.append([InlineKeyboardButton("🌐 Open & Apply", url=alert.raw.link)])

        return InlineKeyboardMarkup(buttons)

    @staticmethod
    def _format_digest(alerts: list[ProcessedAlert]) -> str:
        """Format multiple alerts into a single digest summary."""
        header = f"📋 <b>Job Digest</b> — {len(alerts)} new matches\n{'─' * 30}\n"

        entries = []
        for i, alert in enumerate(alerts, 1):
            raw = alert.raw
            job = alert.job
            snippet = _escape(job.summary[:90]) + ("..." if len(job.summary) > 90 else "")
            link_part = f' <a href="{raw.link}">↗</a>' if raw.link else ""
            entries.append(
                f"<b>{i}.</b> [{job.track_badge}] <b>{_escape(job.role)}</b> @ {_escape(job.company)}\n"
                f"   ⭐ Score: {job.score}% | 💰 {_escape(job.salary or 'N/A')}\n"
                f"   {snippet}{link_part}"
            )

        return header + "\n\n".join(entries)

    async def close(self) -> None:
        """Flush pending alerts and clean up."""
        async with self._lock:
            if self._batch_buffer:
                await self._flush_individual()
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass
        await self._bot.shutdown()
