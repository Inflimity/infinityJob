"""
ginNews Settings — Central configuration loaded from environment variables.

Uses pydantic-settings for type-safe validation with .env file support.
All secrets and tuning knobs are defined here as a single source of truth.
"""

from __future__ import annotations

from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram (Telethon Userbot) ──────────────────────────────────────
    telegram_api_id: int
    telegram_api_hash: str

    # ── Telegram Bot (Alert Notifier) ────────────────────────────────────
    telegram_bot_token: str
    admin_chat_id: int

    # ── Watchlist ────────────────────────────────────────────────────────
    watch_coins: str | list[str] = ["btc", "eth", "sol"]
    complaint_words: str | list[str] = [
        "scam", "bug", "stuck", "failed", "help", "drain",
        "lost", "error", "worst", "hack", "exploit", "rug", "rugpull",
    ]

    # ── Discord (Playwright) ────────────────────────────────────────────
    discord_channel_urls: str | list[str] = []

    # ── X / Twitter (Playwright) ────────────────────────────────────────
    twitter_search_queries: str | list[str] = []

    # ── Reddit (AsyncPRAW + RSS) ────────────────────────────────────────
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_user_agent: str = "ginNews/1.0"
    reddit_subreddits: str | list[str] = []
    reddit_monitor_comments: bool = False

    # ── Deduplication ───────────────────────────────────────────────────
    redis_url: Optional[str] = None
    dedup_ttl_seconds: int = 3600

    # ── Polling & Batching ──────────────────────────────────────────────
    poll_interval_seconds: int = 15
    alert_batch_window_seconds: int = 60
    alert_batch_threshold: int = 10

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./ginNews.sqlite"

    # ── Validators ──────────────────────────────────────────────────────

    @field_validator(
        "watch_coins",
        "complaint_words",
        "discord_channel_urls",
        "twitter_search_queries",
        "reddit_subreddits",
        mode="before",
    )
    @classmethod
    def split_comma_separated(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated strings from .env and split into lists."""
        if isinstance(v, str):
            return [item.strip().lower() for item in v.split(",") if item.strip()]
        return [item.strip().lower() for item in v if item.strip()]


def get_settings() -> Settings:
    """Factory function — creates and caches a Settings instance."""
    return Settings()  # type: ignore[call-arg]
