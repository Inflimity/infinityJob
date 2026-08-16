"""
GitHub Bounties & Paid Issues Monitor.

Searches GitHub Issues labeled 'bounty', 'paid', or 'hiring' across open source ecosystems
(AI/agents, web frameworks, tooling) for paid bounties and contract work.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

import httpx

from core.engine import RawAlert
from monitors.base import BaseMonitor

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/issues"

SEARCH_QUERIES = [
    'is:issue is:open label:bounty state:open',
    'is:issue is:open label:"help wanted" label:paid state:open',
    'is:issue is:open "paid bounty" state:open',
    'is:issue is:open "we are hiring" state:open',
]


class GitHubBountiesMonitor(BaseMonitor):
    """Monitors GitHub for paid bounties and developer hiring issues."""

    PLATFORM = "github"

    def __init__(self, settings: "Settings") -> None:
        super().__init__(name="GitHubBountiesMonitor")
        self._settings = settings
        self._github_token = settings.github_token
        self._poll_interval = 600  # 10 minutes
        self._seen_ids: set[str] = set()

    async def _run(self) -> None:
        """Poll GitHub Search API for new bounty issues."""
        logger.info("GitHubBountiesMonitor started")

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "JobSearchBot-GitHub-Monitor",
        }
        if self._github_token:
            headers["Authorization"] = f"token {self._github_token}"

        while self._running:
            for query in SEARCH_QUERIES:
                if not self._running:
                    break
                try:
                    await self._search_issues(query, headers)
                except Exception:
                    logger.debug("Error searching GitHub for query: %s", query)

                await asyncio.sleep(10)

            await asyncio.sleep(self._poll_interval)

    async def _search_issues(self, query: str, headers: dict[str, str]) -> None:
        """Search issues matching query created/updated recently."""
        # Query issues updated in the last 24 hours
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        full_query = f"{query} updated:>={yesterday}"

        params = {
            "q": full_query,
            "sort": "updated",
            "order": "desc",
            "per_page": 15,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(GITHUB_SEARCH_URL, headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                return
            data = resp.json()

        now_utc = datetime.now(timezone.utc)
        items = data.get("items", [])
        for item in items:
            issue_id = f"gh:{item.get('id')}"
            if issue_id in self._seen_ids:
                continue
            self._seen_ids.add(issue_id)

            created_ts = now_utc
            date_str = item.get("created_at") or item.get("updated_at")
            if date_str:
                try:
                    created_ts = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if (now_utc - created_ts).total_seconds() > 3600:  # 60 mins
                        continue
                except Exception:
                    pass

            title = item.get("title", "")
            body = item.get("body", "") or ""
            html_url = item.get("html_url", "")
            user = item.get("user", {}).get("login", "github_user")
            repo_url = item.get("repository_url", "")
            repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else "GitHub Repo"

            full_text = f"Repo: {repo_name}\nTitle: {title}\n\n{body}"

            alert = RawAlert(
                platform=self.PLATFORM,
                source_name=f"GitHub ({repo_name})",
                author=f"@{user}",
                text=full_text,
                link=html_url,
                timestamp=created_ts,
            )

            await self._emit(alert)

        if len(self._seen_ids) > 10_000:
            self._seen_ids = set(list(self._seen_ids)[-5_000:])
