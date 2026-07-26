import asyncio
import logging
from typing import TYPE_CHECKING
import discord

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)


class DiscordMonitor(BaseMonitor):
    """Monitors Discord messages using a Userbot (discord.py-self)."""

    PLATFORM = "discord"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="DiscordMonitor")
        self._settings = settings
        self._token = getattr(self._settings, "discord_user_token", "")
        self._client = None
        self._client_task = None

    async def _run(self) -> None:
        """Launch discord.py-self client and listen to events."""
        if not self._token:
            logger.warning("DiscordMonitor: No DISCORD_USER_TOKEN configured, skipping")
            while self._running:
                await asyncio.sleep(60)
            return

        # Initialize the discord.py-self client
        self._client = discord.Client()
        
        @self._client.event
        async def on_ready():
            logger.info("DiscordMonitor: Connected as %s", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message):
            # We only care if we are running
            if not self._running:
                return
                
            # Ignore our own messages to avoid looping
            if message.author == self._client.user:
                return

            if not message.content:
                return

            # Format the source nicely
            source = "DM"
            if message.guild:
                source = f"{message.guild.name} / #{message.channel.name}"
            elif hasattr(message.channel, "name") and message.channel.name:
                source = message.channel.name

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=source,
                author=message.author.display_name or message.author.name,
                text=message.content.strip(),
                link=message.jump_url,
            )

            await self._emit(alert)

        try:
            logger.info("DiscordMonitor: Starting userbot client...")
            # We must run the client using start() inside the asyncio loop
            self._client_task = asyncio.create_task(self._client.start(self._token))
            
            while self._running:
                await asyncio.sleep(1)
                
        except Exception:
            logger.exception("DiscordMonitor error")
        finally:
            if self._client and not self._client.is_closed():
                await self._client.close()
            if self._client_task:
                self._client_task.cancel()
