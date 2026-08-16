"""
JobSearchBot — Multi-Platform Job Intelligence & Notification Engine.

Wires together monitors (X, Reddit, Hacker News, Remote Boards, GitHub, Telegram, Discord),
orchestration engine, scoring taxonomy, Telegram notifier, and SQLite persistence.
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
from monitors.github_bounties_monitor import GitHubBountiesMonitor
from monitors.hn_monitor import HNMonitor
from monitors.reddit_monitor import RedditMonitor
from monitors.remote_boards_monitor import RemoteBoardsMonitor
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
logger = logging.getLogger("InfinityJobSearch")


async def main() -> None:
    """Bootstrap and run the Infinity Job Search system."""
    print(r"""
========================================================================
 ___ _  _ ___ ___ _  _ ___ _____   __     _  ___  ___   ___ ___   _   ___  ___ _  _ 
|_ _| \| | __|_ _| \| |_ _|_   _\ \ / / _ | |/ _ \| _ ) / __| __| /_\ | _ \/ __| || |
 | || .` | _| | || .` || |  | |  \ V / | || | (_) | _ \ \__ \ _| / _ \|   / (__| __ |
|___|_|\_|_| |___|_|\_|___| |_|   |_|   \__/ \___/|___/ |___/___/_/ \_\_|_\\___|_||_|
========================================================================
""")
    logger.info("Infinity Job Search — Autonomous Job Intelligence & Alert Relay")

    # ── 1. Load configuration ────────────────────────────────────────
    settings = get_settings()
    logger.info("Configuration loaded (Min Score Threshold: %d%%)", settings.min_alert_score)

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
        db=db,
    )
    # Start Telegram callback listener for inline buttons
    await notifier.start_polling_callbacks()

    # ── 5. Create the shared alert queue ─────────────────────────────
    queue: asyncio.Queue[RawAlert] = asyncio.Queue()

    async def enqueue_alert(alert: RawAlert) -> None:
        await queue.put(alert)

    # ── 6. Initialise the engine ─────────────────────────────────────
    engine = AlertEngine(
        queue=queue,
        dedup=dedup,
        notifier=notifier,
        db=db,
        min_alert_score=settings.min_alert_score,
        digest_min_score=settings.digest_min_score,
        max_post_age_minutes=settings.max_post_age_minutes,
        ws_broadcast=ws_manager.broadcast_alert,
    )

    # ── 7. Initialise monitors ───────────────────────────────────────
    monitors = []

    # Hacker News monitor (public Algolia API + Who is hiring?)
    if settings.hn_search_enabled:
        hn_monitor = HNMonitor(settings)
        hn_monitor.on_message(enqueue_alert)
        monitors.append(hn_monitor)
        logger.info("Hacker News monitor registered")

    # Remote Boards monitor (Himalayas, WeWorkRemotely, Jobicy, Arbeitnow)
    if settings.remote_boards_enabled:
        remote_monitor = RemoteBoardsMonitor(settings)
        remote_monitor.on_message(enqueue_alert)
        monitors.append(remote_monitor)
        logger.info("Remote Boards monitor registered (Himalayas, WWR, Jobicy, Arbeitnow)")

    # GitHub Bounties & Paid Issues monitor
    if settings.github_bounties_enabled:
        gh_monitor = GitHubBountiesMonitor(settings)
        gh_monitor.on_message(enqueue_alert)
        monitors.append(gh_monitor)
        logger.info("GitHub Bounties monitor registered")

    # Reddit monitor (AsyncPRAW / RSS fallback)
    if settings.reddit_subreddits:
        rd_monitor = RedditMonitor(settings)
        rd_monitor.on_message(enqueue_alert)
        monitors.append(rd_monitor)
        strategy = "AsyncPRAW" if settings.reddit_client_id else "RSS fallback"
        logger.info("Reddit monitor registered (%d subreddits, %s)", len(settings.reddit_subreddits), strategy)

    # X / Twitter monitor (Playwright DOM scraper)
    tw_monitor = TwitterMonitor(settings)
    tw_monitor.on_message(enqueue_alert)
    monitors.append(tw_monitor)
    logger.info("X / Twitter monitor registered")

    # Telegram userbot monitor (optional, for developer job groups)
    if settings.telegram_api_id and settings.telegram_api_hash:
        tg_monitor = TelegramMonitor(settings)
        tg_monitor.on_message(enqueue_alert)
        monitors.append(tg_monitor)
        logger.info("Telegram Userbot monitor registered")

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
            pass

    # ── 9. Initialise dashboard API ──────────────────────────────────
    app = create_app()
    init_routes(db, engine, settings)
    logger.info("Dashboard API ready at http://localhost:8000")

    # ── 10. Launch everything concurrently ───────────────────────────
    async def run_with_shutdown() -> None:
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

        await shutdown_event.wait()

        logger.info("Initiating graceful shutdown...")
        await engine.stop()

        for monitor in monitors:
            await monitor.stop()

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        await run_with_shutdown()
    finally:
        logger.info("Cleaning up resources...")
        await notifier.close()
        await dedup.close()
        await db.close()
        logger.info("JobSearchBot shut down cleanly ✓")


def cli_entry() -> None:
    """CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_entry()
