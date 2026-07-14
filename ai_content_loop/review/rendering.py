from __future__ import annotations

import re

from markdown_it import MarkdownIt


_MARKDOWN = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "linkify": False,
        "typographer": False,
    },
)

_ASSET_MARKER = re.compile(r"\{\{asset:([^{}\r\n]{1,200})\}\}")
_SAFE_ASSET_ID = re.compile(r"[a-z0-9-]{1,32}\Z")


def render_markdown(
    markdown: str,
    *,
    asset_urls: dict[str, str] | None = None,
) -> str:
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    urls = asset_urls or {}

    def replace_marker(match: re.Match[str]) -> str:
        asset_id = match.group(1)
        url = urls.get(asset_id) if _SAFE_ASSET_ID.fullmatch(asset_id) else None
        if url is None:
            return "[图片尚未生成]"
        return f"![]({url})"

    return _MARKDOWN.render(_ASSET_MARKER.sub(replace_marker, markdown))
