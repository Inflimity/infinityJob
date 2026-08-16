"""
Remote Job Boards Monitor — Ingests clean structured jobs from public APIs & RSS feeds.

Sources:
1. Himalayas.app API (Machine-readable JSON with exact remote location tags & salaries)
2. We Work Remotely (RSS feeds for Programming & DevOps)
3. Jobicy API (Free public remote jobs API)
4. Arbeitnow API (Remote-friendly engineering & data jobs)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import feedparser
import httpx

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

WWR_FEEDS = [
    ("WeWorkRemotely (Full-Stack)", "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"),
    ("WeWorkRemotely (Back-End)", "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"),
    ("WeWorkRemotely (DevOps)", "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"),
]


def strip_html(raw_html: str) -> str:
    """Strips HTML formatting and normalizes whitespace."""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    clean = re.sub(r"&[a-z0-9]+;", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def parse_datetime(val: str | int | float | None) -> datetime:
    """Parses various date/time formats into UTC datetime, defaulting to now_utc."""
    now_utc = datetime.now(timezone.utc)
    if val is None:
        return now_utc
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(val, str):
            val_clean = val.replace("Z", "+00:00").strip()
            # Try ISO format
            try:
                return datetime.fromisoformat(val_clean)
            except ValueError:
                pass
            # Try common RFC / HTTP date formats
            import email.utils
            parsed_tuple = email.utils.parsedate_to_datetime(val)
            if parsed_tuple:
                return parsed_tuple if parsed_tuple.tzinfo else parsed_tuple.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return now_utc


class RemoteBoardsMonitor(BaseMonitor):
    """Monitors top remote tech job boards via public APIs and RSS."""

    PLATFORM = "remote_boards"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="RemoteBoardsMonitor")
        self._settings = settings
        self._poll_interval = 300  # 5 minutes
        self._seen_ids: set[str] = set()

    async def _run(self) -> None:
        """Periodic polling cycle across remote job APIs."""
        logger.info("RemoteBoardsMonitor started (Himalayas, WWR, Jobicy, Arbeitnow)")

        while self._running:
            try:
                await self._poll_himalayas()
                await self._poll_weworkremotely()
                await self._poll_jobicy()
                await self._poll_arbeitnow()
            except Exception:
                logger.exception("Error during remote boards polling cycle")

            await asyncio.sleep(self._poll_interval)

    async def _poll_himalayas(self) -> None:
        """Poll Himalayas.app public JSON API."""
        url = "https://himalayas.app/jobs/api?limit=50"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "InfinityJobSearch/1.0"},
                    timeout=20,
                )
                if resp.status_code != 200:
                    return
                data = resp.json()
            except Exception:
                logger.debug("Failed to query Himalayas API")
                return

        now_utc = datetime.now(timezone.utc)
        jobs = data.get("jobs", [])
        for job in jobs:
            guid = f"himalayas:{job.get('slug') or job.get('title')}"
            if guid in self._seen_ids:
                continue
            self._seen_ids.add(guid)

            pub_raw = job.get("pubDate") or job.get("createdAt") or job.get("publishedAt")
            created_ts = parse_datetime(pub_raw)
            if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                continue

            title = job.get("title", "")
            company = job.get("companyName", "Company")
            description = strip_html(job.get("description", ""))
            location = job.get("location", "Remote")
            salary_min = job.get("minSalary")
            salary_max = job.get("maxSalary")
            currency = job.get("currency", "USD")

            salary_str = ""
            if salary_min and salary_max:
                salary_str = f"{currency} {salary_min:,} - {salary_max:,}/yr"
            elif salary_min:
                salary_str = f"{currency} {salary_min:,}+/yr"

            skills = ", ".join(job.get("skills", []))
            full_text = f"Title: {title}\nCompany: {company}\nSalary: {salary_str}\nLocation: {location}\nSkills: {skills}\n\n{description}"
            link = job.get("applicationLink") or f"https://himalayas.app/companies/{job.get('companySlug')}/jobs/{job.get('slug')}"

            alert = RawAlert(
                platform="himalayas",
                source_name=f"Himalayas ({company})",
                author=company,
                text=full_text,
                link=link,
                is_dedicated_job_board=True,
                timestamp=created_ts,
            )

            await self._emit(alert)

    async def _poll_weworkremotely(self) -> None:
        """Poll We Work Remotely RSS feeds."""
        now_utc = datetime.now(timezone.utc)
        for board_name, feed_url in WWR_FEEDS:
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.get(feed_url, timeout=15, follow_redirects=True)
                    if resp.status_code != 200:
                        continue
                    feed = feedparser.parse(resp.text)
                except Exception:
                    continue

            for entry in feed.entries:
                guid = f"wwr:{entry.get('id') or entry.get('link')}"
                if guid in self._seen_ids:
                    continue
                self._seen_ids.add(guid)

                created_ts = now_utc
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    created_ts = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                    if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                        continue

                title = entry.get("title", "")
                summary = strip_html(entry.get("summary", ""))
                link = entry.get("link", "")
                author = entry.get("author", "WWR Employer")

                full_text = f"{title}\n{summary}"

                alert = RawAlert(
                    platform=self.PLATFORM,
                    source_name=board_name,
                    author=author,
                    text=full_text,
                    link=link,
                    is_dedicated_job_board=True,
                    timestamp=created_ts,
                )

                await self._emit(alert)

    async def _poll_jobicy(self) -> None:
        """Poll Jobicy public remote API."""
        url = "https://jobicy.com/api/v2/remote-jobs?count=25"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, timeout=20)
                if resp.status_code != 200:
                    return
                data = resp.json()
            except Exception:
                return

        now_utc = datetime.now(timezone.utc)
        jobs = data.get("jobs", [])
        for job in jobs:
            guid = f"jobicy:{job.get('id')}"
            if guid in self._seen_ids:
                continue
            self._seen_ids.add(guid)

            pub_raw = job.get("pubDate")
            created_ts = parse_datetime(pub_raw)
            if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                continue

            title = job.get("jobTitle", "")
            company = job.get("companyName", "Company")
            description = strip_html(job.get("jobDescription", ""))
            salary_min = job.get("annualSalaryMin")
            salary_max = job.get("annualSalaryMax")
            currency = job.get("salaryCurrency", "USD")

            salary_str = ""
            if salary_min and salary_max:
                salary_str = f"{currency} {salary_min} - {salary_max}"

            full_text = f"Title: {title}\nCompany: {company}\nSalary: {salary_str}\n\n{description}"
            link = job.get("url", "")

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"Jobicy ({company})",
                author=company,
                text=full_text,
                link=link,
                is_dedicated_job_board=True,
                timestamp=created_ts,
            )

            await self._emit(alert)

    async def _poll_arbeitnow(self) -> None:
        """Poll Arbeitnow remote tech jobs API."""
        url = "https://www.arbeitnow.com/api/job-board-api"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, timeout=20)
                if resp.status_code != 200:
                    return
                data = resp.json()
            except Exception:
                return

        now_utc = datetime.now(timezone.utc)
        jobs = data.get("data", [])
        for job in jobs:
            slug = job.get("slug", "")
            guid = f"arbeitnow:{slug}"
            if guid in self._seen_ids:
                continue
            self._seen_ids.add(guid)

            if not job.get("remote", False):
                continue

            pub_raw = job.get("created_at")
            created_ts = parse_datetime(pub_raw)
            if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                continue

            title = job.get("title", "")
            company = job.get("company_name", "Company")
            description = strip_html(job.get("description", ""))
            tags = ", ".join(job.get("tags", []))
            link = job.get("url", "")

            full_text = f"Title: {title}\nCompany: {company}\nTags: {tags}\n\n{description}"

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"Arbeitnow ({company})",
                author=company,
                text=full_text,
                link=link,
                is_dedicated_job_board=True,
                timestamp=created_ts,
            )

            await self._emit(alert)

        if len(self._seen_ids) > 10_000:
            self._seen_ids = set(list(self._seen_ids)[-5_000:])
