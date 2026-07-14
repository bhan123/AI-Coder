from __future__ import annotations

from urllib.parse import quote
import re
import xml.etree.ElementTree as ET

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_text


ATOM = "{http://www.w3.org/2005/Atom}"


def _text(parent: ET.Element, name: str) -> str:
    child = parent.find(f"{ATOM}{name}")
    return " ".join((child.text or "").split()) if child is not None else ""


def _arxiv_id(url: str) -> str:
    match = re.search(r"/abs/([^/]+)$", url)
    return match.group(1) if match else url


def parse_arxiv_feed(xml_text: str, fetched_at: str) -> list[SourceItem]:
    root = ET.fromstring(xml_text)
    items = []
    for entry in root.findall(f"{ATOM}entry"):
        url = _text(entry, "id")
        title = _text(entry, "title")
        if not url or not title:
            continue
        items.append(
            SourceItem(
                source="arxiv",
                external_id=_arxiv_id(url),
                title=title,
                url=url,
                summary=_text(entry, "summary"),
                published_at=_text(entry, "published"),
                fetched_at=fetched_at,
                raw={},
            )
        )
    return items


def fetch_arxiv_ai(limit: int, fetched_at: str) -> list[SourceItem]:
    query = quote("cat:cs.AI OR cat:cs.CL OR cat:cs.LG")
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    )
    return parse_arxiv_feed(fetch_text(url), fetched_at=fetched_at)
