from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_json


def parse_github_search(payload: dict, fetched_at: str) -> list[SourceItem]:
    items = []
    for repo in payload.get("items", []):
        full_name = str(repo.get("full_name", "")).strip()
        if not full_name:
            continue
        items.append(
            SourceItem(
                source="github",
                external_id=full_name,
                title=full_name,
                url=str(repo.get("html_url", "")),
                summary=str(repo.get("description") or ""),
                published_at=str(repo.get("updated_at") or ""),
                fetched_at=fetched_at,
                raw={
                    "stars": int(repo.get("stargazers_count") or 0),
                    "forks": int(repo.get("forks_count") or 0),
                    "language": repo.get("language"),
                    "topics": repo.get("topics", []),
                },
            )
        )
    return items


def fetch_github_repositories(limit: int, fetched_at: str) -> list[SourceItem]:
    since = (datetime.now(UTC) - timedelta(days=14)).date().isoformat()
    query = quote(f"(ai OR artificial-intelligence OR llm OR agent) pushed:>={since}")
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
    return parse_github_search(fetch_json(url), fetched_at=fetched_at)
