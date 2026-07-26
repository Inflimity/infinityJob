"""
SQLAlchemy ORM models for ginNews data persistence.

Defines the schema for alerts, watch configuration, and muted sources.
Uses SQLAlchemy 2.0 declarative style with async compatibility.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ginNews models."""

    pass


class Alert(Base):
    """Persisted alert that passed filtering and deduplication."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    matched_keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert id={self.id} platform={self.platform!r} "
            f"category={self.category!r} author={self.author!r}>"
        )


class WatchConfig(Base):
    """User-configurable watchlist (coins and keywords)."""

    __tablename__ = "watch_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coins: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<WatchConfig id={self.id} updated_at={self.updated_at}>"


class MutedSource(Base):
    """Temporarily muted alert source (via inline button action)."""

    __tablename__ = "muted_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    muted_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MutedSource platform={self.platform!r} "
            f"source={self.source_identifier!r} until={self.muted_until}>"
        )
