"""
SQLAlchemy ORM models for JobSearchBot data persistence.

Defines the schema for job alerts, track configurations, and muted sources/companies.
Uses SQLAlchemy 2.0 declarative style with async compatibility.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""

    pass


class Alert(Base):
    """Persisted job offer that passed classification and filtering."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    
    # ── Job Specific Metadata ────────────────────────────────────────────
    track_id: Mapped[str] = mapped_column(String(50), nullable=False, default="GENERAL", index=True)
    track_badge: Mapped[str] = mapped_column(String(100), nullable=False, default="💼 Job")
    role: Mapped[str] = mapped_column(String(255), nullable=False, default="Software Professional")
    company: Mapped[str] = mapped_column(String(255), nullable=False, default="Unknown")
    salary: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(150), nullable=False, default="Remote")
    remote_type: Mapped[str] = mapped_column(String(50), nullable=False, default="worldwide")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    matched_skills: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pitch: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── User Action Flags ────────────────────────────────────────────────
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert id={self.id} track={self.track_id!r} "
            f"score={self.score} role={self.role!r} platform={self.platform!r}>"
        )


class MutedSource(Base):
    """Temporarily muted poster, company, or alert source."""

    __tablename__ = "muted_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
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
