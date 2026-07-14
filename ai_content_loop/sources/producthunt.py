from __future__ import annotations

from urllib.request import Request, urlopen
import json

from ai_content_loop.models import SourceItem


QUERY = """
query Posts($first: Int!) {
  posts(first: $first, order: VOTES) {
    edges {
      node {
        id
        name
        tagline
        url
        votesCount
        createdAt
      }
    }
  }
}
"""


def parse_producthunt_posts(payload: dict, fetched_at: str) -> list[SourceItem]:
    edges = payload.get("data", {}).get("posts", {}).get("edges", [])
    items = []
    for edge in edges:
        node = edge.get("node", {})
        post_id = str(node.get("id", "")).strip()
        if not post_id:
            continue
        items.append(
            SourceItem(
                source="producthunt",
                external_id=post_id,
                title=str(node.get("name") or ""),
                url=str(node.get("url") or ""),
                summary=str(node.get("tagline") or ""),
                published_at=str(node.get("createdAt") or ""),
                fetched_at=fetched_at,
                raw={"votes": int(node.get("votesCount") or 0)},
            )
        )
    return items


def fetch_producthunt_posts(limit: int, fetched_at: str, token: str) -> list[SourceItem]:
    if not token:
        return []
    body = json.dumps({"query": QUERY, "variables": {"first": limit}}).encode("utf-8")
    req = Request(
        "https://api.producthunt.com/v2/api/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ai-content-loop/0.1",
        },
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_producthunt_posts(payload, fetched_at=fetched_at)
