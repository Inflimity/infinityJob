"""
ginNews — Main entry point.

Wires together all components (config, engine, monitors, notifier, database)
and runs them concurrently via asyncio.gather with graceful shutdown handling.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import uvicorn

from api.routes import init_routes
from api.server import create_app
from api.websocket import ws_manager
from config.settings import get_settings
from core.dedup import create_dedup_backend
from core.engine import AlertEngine, RawAlert
from monitors.discord_monitor import DiscordMonitor
from monitors.reddit_monitor import RedditMonitor
from monitors.telegram_monitor import TelegramMonitor
from monitors.twitter_monitor import TwitterMonitor
from notifiers.telegram_bot import TelegramNotifier
from storage.database import DatabaseManager

# ── Logging setup ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("ginNews")


async def main() -> None:
    """Bootstrap and run the entire ginNews system."""
    logger.info("=" * 60)
    logger.info("  ginNews — Cross-Platform Surveillance Relay")
    logger.info("=" * 60)

    # ── 1. Load configuration ────────────────────────────────────────
    settings = get_settings()
    logger.info("Configuration loaded")

    # ── 2. Initialise database ───────────────────────────────────────
    db = DatabaseManager(settings.database_url)
    await db.init_db()

    # ── 3. Initialise dedup backend ──────────────────────────────────
    dedup = create_dedup_backend(
        redis_url=settings.redis_url,
        ttl_seconds=settings.dedup_ttl_seconds,
    )

    # ── 4. Initialise notifier ───────────────────────────────────────
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        admin_chat_id=settings.admin_chat_id,
        batch_window_seconds=settings.alert_batch_window_seconds,
        batch_threshold=settings.alert_batch_threshold,
    )

    # ── 5. Create the shared alert queue ─────────────────────────────
    queue: asyncio.Queue[RawAlert] = asyncio.Queue()

    # Helper to push alerts into the queue (used by monitors)
    async def enqueue_alert(alert: RawAlert) -> None:
        await queue.put(alert)

    # ── 6. Initialise the engine ─────────────────────────────────────
    engine = AlertEngine(
        queue=queue,
        dedup=dedup,
        notifier=notifier,
        db=db,
        coins=settings.watch_coins,
        keywords=settings.complaint_words,
        ws_broadcast=ws_manager.broadcast_alert,
    )

    # ── 7. Initialise monitors ───────────────────────────────────────
    monitors = []

    # Telegram monitor (always enabled — core platform)
    tg_monitor = TelegramMonitor(settings)
    tg_monitor.on_message(enqueue_alert)
    monitors.append(tg_monitor)
    logger.info("Telegram monitor registered")

    # Discord monitor (enabled when channel URLs are configured)
    if settings.discord_channel_urls:
        dc_monitor = DiscordMonitor(settings)
        dc_monitor.on_message(enqueue_alert)
        monitors.append(dc_monitor)
        logger.info("Discord monitor registered (%d channels)", len(settings.discord_channel_urls))

    # X / Twitter monitor (enabled when search queries are configured)
    if settings.twitter_search_queries:
        tw_monitor = TwitterMonitor(settings)
        tw_monitor.on_message(enqueue_alert)
        monitors.append(tw_monitor)
        logger.info("Twitter monitor registered (%d queries)", len(settings.twitter_search_queries))

    # Reddit monitor (enabled when subreddits are configured)
    if settings.reddit_subreddits:
        rd_monitor = RedditMonitor(settings)
        rd_monitor.on_message(enqueue_alert)
        monitors.append(rd_monitor)
        strategy = "AsyncPRAW" if settings.reddit_client_id else "RSS fallback"
        logger.info("Reddit monitor registered (%d subreddits, %s)", len(settings.reddit_subreddits), strategy)

    # ── 8. Set up graceful shutdown ──────────────────────────────────
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # ── 9. Initialise the web dashboard API ──────────────────────────
    app = create_app()
    init_routes(db, engine, settings)
    logger.info("Dashboard API ready at http://localhost:8000")

    # ── 10. Launch everything concurrently ───────────────────────────
    async def run_with_shutdown() -> None:
        """Run monitors + engine + API server, stop when shutdown_event is set."""
        # Start the API server as a background task
        uvicorn_config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="warning",
            access_log=False,
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)

        tasks = [
            asyncio.create_task(engine.start(), name="engine"),
            asyncio.create_task(uvicorn_server.serve(), name="api-server"),
        ]
        for monitor in monitors:
            tasks.append(
                asyncio.create_task(monitor.start(), name=monitor.name)
            )

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Graceful teardown
        logger.info("Initiating graceful shutdown...")

        # Stop engine first (drains queue)
        await engine.stop()

        # Stop all monitors
        for monitor in monitors:
            await monitor.stop()

        # Cancel remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        await run_with_shutdown()
    finally:
        # ── 10. Cleanup ──────────────────────────────────────────────
        logger.info("Cleaning up resources...")
        await notifier.close()
        await dedup.close()
        await db.close()
        logger.info("ginNews shut down cleanly ✓")


def cli_entry() -> None:
    """CLI entry point for `ginnews` command."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_entry()
