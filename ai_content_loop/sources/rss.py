from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_text


ATOM = "{http://www.w3.org/2005/Atom}"


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _matches_keywords(
    title: str, summary: str, include_keywords: tuple[str, ...]
) -> bool:
    if not include_keywords:
        return True
    haystack = f"{title}\n{summary}"
    for keyword in include_keywords:
        if keyword.isascii() and keyword.isalnum():
            if re.search(
                rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])",
                haystack,
                flags=re.IGNORECASE,
            ):
                return True
        elif keyword.casefold() in haystack.casefold():
            return True
    return False


def _atom_link(node: ET.Element) -> str:
    links = node.findall(f"{ATOM}link")
    for link in links:
        if link.attrib.get("rel", "alternate") == "alternate":
            return str(link.attrib.get("href") or "").strip()
    return str(links[0].attrib.get("href") or "").strip() if links else ""


def parse_rss(
    xml_text: str,
    source_name: str,
    fetched_at: str,
    include_keywords: tuple[str, ...] = (),
) -> list[SourceItem]:
    root = ET.fromstring(xml_text)
    channel_items = root.findall("./channel/item")
    is_atom = not channel_items
    if is_atom:
        channel_items = root.findall(f"./{ATOM}entry")
    items = []
    for index, node in enumerate(channel_items):
        if is_atom:
            title = _plain_text(node.findtext(f"{ATOM}title") or "")
            link = _atom_link(node)
            description = _plain_text(
                node.findtext(f"{ATOM}summary")
                or node.findtext(f"{ATOM}content")
                or ""
            )
            published_at = (
                node.findtext(f"{ATOM}published")
                or node.findtext(f"{ATOM}updated")
                or ""
            ).strip()
            external_id = (node.findtext(f"{ATOM}id") or "").strip()
        else:
            title = _plain_text(node.findtext("title") or "")
            link = (node.findtext("link") or "").strip()
            description = _plain_text(node.findtext("description") or "")
            published_at = (node.findtext("pubDate") or "").strip()
            external_id = (node.findtext("guid") or "").strip()
        external_id = external_id or link or f"{source_name}:{index}:{title}"
        if not title:
            continue
        if not _matches_keywords(title, description, include_keywords):
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


def fetch_rss_feed(
    url: str,
    source_name: str,
    fetched_at: str,
    include_keywords: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[SourceItem]:
    items = parse_rss(
        fetch_text(url),
        source_name=source_name,
        fetched_at=fetched_at,
        include_keywords=include_keywords,
    )
    return items if limit is None else items[:limit]
