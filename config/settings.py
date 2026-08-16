"""
Job Search Bot Settings — Central configuration loaded from environment variables.

Uses pydantic-settings for type-safe validation with .env file support.
All credentials, search thresholds, and polling frequencies are defined here.
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

    # ── Telegram (Telethon Userbot for Telegram Job Channels) ────────────
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None

    # ── Telegram Bot (Alert Notifier to your DM) ─────────────────────────
    telegram_bot_token: str
    admin_chat_id: int

    # ── Job Match & Scoring Thresholds ──────────────────────────────────
    min_alert_score: int = 70  # Alerts scoring >= this threshold trigger instant Telegram alerts
    digest_min_score: int = 50  # Alerts scoring between digest_min_score and min_alert_score get saved to DB
    max_post_age_minutes: int = 60  # Only process and alert jobs posted within the last 60 minutes

    # ── X / Twitter (Playwright CDP) ─────────────────────────────────────
    twitter_search_queries: str | list[str] = []

    # ── Reddit (AsyncPRAW + RSS Fallback) ────────────────────────────────
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_user_agent: str = "InfinityJobSearch/1.0"
    reddit_subreddits: str | list[str] = [
        "forhire",
        "jobbit",
        "remotejs",
        "pythonjobs",
        "reactjs",
        "nextjs",
        "Automate",
        "businessanalysis",
        "dataanalysis",
        "analytics",
    ]
    reddit_monitor_comments: bool = False

    # ── Hacker News & Remote Boards ──────────────────────────────────────
    hn_search_enabled: bool = True
    remote_boards_enabled: bool = True
    himalayas_categories: list[str] = [
        "software-development",
        "data-analytics",
        "operations-management",
    ]

    # ── GitHub Bounties & Jobs ───────────────────────────────────────────
    github_bounties_enabled: bool = True
    github_token: Optional[str] = None  # Optional personal access token for higher rate limits

    # ── Deduplication ───────────────────────────────────────────────────
    redis_url: Optional[str] = None
    dedup_ttl_seconds: int = 86400  # 24h deduplication window

    # ── Polling & Batching ──────────────────────────────────────────────
    poll_interval_seconds: int = 30
    alert_batch_window_seconds: int = 60
    alert_batch_threshold: int = 10

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./ginNews.sqlite"

    # ── Validators ──────────────────────────────────────────────────────

    @field_validator(
        "twitter_search_queries",
        "reddit_subreddits",
        "himalayas_categories",
        mode="before",
    )
    @classmethod
    def split_comma_separated(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated strings from .env and split into lists."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return [item.strip() for item in v if item.strip()]


def get_settings() -> Settings:
    """Factory function — creates and caches a Settings instance."""
    return Settings()  # type: ignore[call-arg]
