from __future__ import annotations

import xml.etree.ElementTree as ET

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_text


def parse_rss(xml_text: str, source_name: str, fetched_at: str) -> list[SourceItem]:
    root = ET.fromstring(xml_text)
    channel_items = root.findall("./channel/item")
    items = []
    for index, node in enumerate(channel_items):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        description = (node.findtext("description") or "").strip()
        published_at = (node.findtext("pubDate") or "").strip()
        external_id = link or f"{source_name}:{index}:{title}"
        if not title:
            continue
        items.append(
            SourceItem(
                source=source_name,
                external_id=external_id,
                title=title,
                url=link,
                summary=description,
                published_at=published_at,
                fetched_at=fetched_at,
                raw={},
            )
        )
    return items


def fetch_rss_feed(url: str, source_name: str, fetched_at: str) -> list[SourceItem]:
    return parse_rss(fetch_text(url), source_name=source_name, fetched_at=fetched_at)
