from __future__ import annotations

from datetime import UTC, datetime

from engine.models import SourceItem
from engine.sources.base import fetch_json


def parse_hn_items(payload: list[dict], fetched_at: str) -> list[SourceItem]:
    items = []
    for story in payload:
        story_id = str(story.get("id", "")).strip()
        title = str(story.get("title") or "")
        if not story_id or not title:
            continue
        published_at = datetime.fromtimestamp(int(story.get("time") or 0), tz=UTC).isoformat()
        items.append(
            SourceItem(
                source="hackernews",
                external_id=story_id,
                title=title,
                url=str(story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"),
                summary=title,
                published_at=published_at,
                fetched_at=fetched_at,
                raw={
                    "score": int(story.get("score") or 0),
                    "comments": int(story.get("descendants") or 0),
                },
            )
        )
    return items


def fetch_hackernews_show(limit: int, fetched_at: str) -> list[SourceItem]:
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/showstories.json")[:limit]
    stories = [
        fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        for story_id in ids
    ]
    return parse_hn_items(stories, fetched_at=fetched_at)
