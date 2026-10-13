from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from ai_content_loop.editorial.schema import ARTICLE_STRUCTURES, ARTICLE_THEMES
from ai_content_loop.editorial.layout_completion import (
    complete_layout_for_rendering,
)
from ai_content_loop.review.rendering import render_markdown


_BLOCK_FIELDS = {
    "hero": {"type", "title", "deck"},
    "lead": {"type", "text"},
    "key_judgment": {"type", "text"},
    "prose": {"type", "paragraphs"},
    "section": {"type", "heading", "paragraphs"},
    "workflow_compare": {"type", "before", "after", "remaining_friction"},
    "quote": {"type", "text", "attribution"},
    "callout": {"type", "text"},
    "source_note": {"type", "url", "attribution"},
}
_HREF_ATTRIBUTE = re.compile(
    r"\s+href=(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')",
    re.IGNORECASE,
)
_IMAGE_TAG = re.compile(
    r"<img\b[^>]*>",
    re.IGNORECASE,
)
_TOC_HREF = re.compile(r"#section-[1-9][0-9]*\Z")
_LOCAL_BODY_IMAGE_URL = re.compile(
    r"/api/articles/[0-9a-f]{24}/assets/body-[0-9]{2}/[0-9a-f]{64}\Z"
)
_DATA_BODY_IMAGE_URL = re.compile(
    r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]*={0,2}\Z"
)


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_layout_for_rendering(value: object) -> object:
    """Expand the legacy persisted press layout without mutating it."""

    if (
        isinstance(value, dict)
        and set(value) == {"theme", "blocks"}
        and value.get("theme") == "press"
    ):
        return {**value, "structure": "briefing"}
    return value


def _trusted_article_layout(value: object) -> bool:
    """Defensively re-check the persisted schema before rendering it."""

    if (
        not isinstance(value, dict)
        or set(value) != {"theme", "structure", "blocks"}
        or value.get("theme") not in ARTICLE_THEMES
        or value.get("structure") not in ARTICLE_STRUCTURES
        or not isinstance(value.get("blocks"), list)
    ):
        return False
    for block in value["blocks"]:
        if not isinstance(block, dict):
            return False
        block_type = block.get("type")
        if (
            block_type not in _BLOCK_FIELDS
            or set(block) != _BLOCK_FIELDS[block_type]
        ):
            return False
        if block_type == "hero":
            if not all(_nonempty_text(block.get(name)) for name in ("title", "deck")):
                return False
        elif block_type in {"lead", "key_judgment", "callout"}:
            if not _nonempty_text(block.get("text")):
                return False
        elif block_type in {"prose", "section"}:
            paragraphs = block.get("paragraphs")
            if (
                not isinstance(paragraphs, list)
                or not paragraphs
                or not all(_nonempty_text(paragraph) for paragraph in paragraphs)
            ):
                return False
            if block_type == "section" and not _nonempty_text(block.get("heading")):
                return False
        elif block_type == "workflow_compare":
            if not all(
                _nonempty_text(block.get(name))
                for name in ("before", "after", "remaining_friction")
            ):
                return False
        elif block_type == "quote":
            if not all(
                _nonempty_text(block.get(name))
                for name in ("text", "attribution")
            ):
                return False
        elif block_type == "source_note":
            url = block.get("url")
            parsed = urlparse(url) if isinstance(url, str) else None
            if (
                not _nonempty_text(block.get("attribution"))
                or parsed is None
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
            ):
                return False
    return True


def article_theme_for_layout(article_layout: object) -> str | None:
    """Return a trusted persisted theme for renderer-owned presentation."""

    layout = _normalize_layout_for_rendering(article_layout)
    if not _trusted_article_layout(layout):
        return None
    return str(layout["theme"])


def _fallback_html(*, title: object, markdown: object) -> str:
    safe_title = title if isinstance(title, str) else ""
    safe_markdown = markdown if isinstance(markdown, str) else ""
    title_html = f"<h1>{escape(safe_title)}</h1>" if safe_title else ""
    body_html = render_markdown(safe_markdown) if safe_markdown else ""
    return (
        '<article class="rich-article rich-article--fallback">'
        f'<header class="rich-article__hero">{title_html}</header>'
        f'<div class="rich-article__body">{body_html}</div>'
        "</article>"
    )


def _allow_only_safe_reading_attributes(html: str) -> str:
    """Leave only renderer-owned table-of-contents anchors and no fallback images."""

    def allow_toc_anchor(match: re.Match[str]) -> str:
        href = match.group("double") or match.group("single") or ""
        return f' href="{href}"' if _TOC_HREF.fullmatch(href) else ""

    return _IMAGE_TAG.sub("", _HREF_ATTRIBUTE.sub(allow_toc_anchor, html))


def _trusted_body_images(
    body_images: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None,
) -> list[tuple[str, str]]:
    if body_images is None:
        return []
    if len(body_images) > 3:
        raise ValueError("no more than three trusted local or embedded body images")
    trusted: list[tuple[str, str]] = []
    for item in body_images:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
        ):
            raise ValueError("body image must be a trusted local or embedded pair")
        source, alt = item
        if not (
            _LOCAL_BODY_IMAGE_URL.fullmatch(source)
            or _DATA_BODY_IMAGE_URL.fullmatch(source)
        ):
            raise ValueError("body image must use a trusted local or embedded URL")
        trusted.append((source, alt.strip() or "正文配图"))
    return trusted


def _render_body_image(source: str, alt: str) -> str:
    return (
        '<figure class="rich-article__image">'
        f'<img src="{escape(source, quote=True)}" '
        f'alt="{escape(alt, quote=True)}" loading="lazy">'
        f"<figcaption>{escape(alt)}</figcaption></figure>"
    )


def _render_block(block: dict[str, object], section_index: int) -> str:
    block_type = block["type"]
    if block_type == "hero":
        return (
            '<header class="rich-article__hero">'
            f"<h1>{escape(str(block['title']))}</h1>"
            f'<p class="rich-article__deck">{escape(str(block["deck"]))}</p>'
            "</header>"
        )
    if block_type == "lead":
        return f'<p class="rich-article__lead">{escape(str(block["text"]))}</p>'
    if block_type == "key_judgment":
        return (
            '<aside class="rich-article__judgment"><strong>关键判断</strong>'
            f"<p>{escape(str(block['text']))}</p></aside>"
        )
    if block_type == "prose":
        paragraphs = "".join(
            f"<p>{escape(str(paragraph))}</p>"
            for paragraph in block["paragraphs"]
        )
        return f'<div class="rich-article__prose">{paragraphs}</div>'
    if block_type == "section":
        paragraphs = "".join(
            f"<p>{escape(str(paragraph))}</p>"
            for paragraph in block["paragraphs"]
        )
        return (
            f'<section id="section-{section_index}">'
            f"<h2>{escape(str(block['heading']))}</h2>{paragraphs}</section>"
        )
    if block_type == "workflow_compare":
        return (
            '<section class="rich-article__comparison" aria-label="流程对比">'
            f"<div><strong>之前</strong><p>{escape(str(block['before']))}</p></div>"
            f"<div><strong>现在</strong><p>{escape(str(block['after']))}</p></div>"
            "<div><strong>仍需克服</strong>"
            f"<p>{escape(str(block['remaining_friction']))}</p></div></section>"
        )
    if block_type == "quote":
        return (
            '<blockquote class="rich-article__quote">'
            f"<p>{escape(str(block['text']))}</p>"
            f"<footer>— {escape(str(block['attribution']))}</footer></blockquote>"
        )
    if block_type == "callout":
        return (
            '<aside class="rich-article__callout">'
            f"{escape(str(block['text']))}</aside>"
        )
    if block_type == "source_note":
        return (
            '<p class="rich-article__source">来源：'
            f'<span>{escape(str(block["attribution"]))}</span> '
            f"<code>{escape(str(block['url']))}</code></p>"
        )
    raise ValueError("unsupported rich article block")


def render_rich_article(
    article_layout: object,
    *,
    fallback_title: object = "",
    fallback_markdown: object = "",
    body_images: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None = None,
) -> str:
    """Render trusted semantic blocks, never model-owned markup or styles."""

    safe_images = _trusted_body_images(body_images)
    layout = _normalize_layout_for_rendering(article_layout)
    if not _trusted_article_layout(layout) or not layout["blocks"]:
        fallback = _allow_only_safe_reading_attributes(
            _fallback_html(title=fallback_title, markdown=fallback_markdown)
        )
        if safe_images:
            image_html = "".join(
                _render_body_image(source, alt) for source, alt in safe_images
            )
            fallback = fallback.replace("</article>", f"{image_html}</article>")
        return fallback
    layout = complete_layout_for_rendering(
        layout,
        title=fallback_title,
        markdown=fallback_markdown,
    )

    sections = [
        str(block["heading"])
        for block in layout["blocks"]
        if block["type"] == "section"
    ]
    toc_html = ""
    if sections:
        toc_html = (
            '<nav class="rich-article__toc" aria-label="文章目录">'
            "<strong>目录</strong><ol>"
            + "".join(
                f'<li><a href="#section-{index}">{escape(heading)}</a></li>'
                for index, heading in enumerate(sections, start=1)
            )
            + "</ol></nav>"
        )

    has_hero = any(block["type"] == "hero" for block in layout["blocks"])
    title_html = ""
    if not has_hero and isinstance(fallback_title, str) and fallback_title:
        title_html = (
            '<header class="rich-article__hero">'
            f"<h1>{escape(fallback_title)}</h1></header>"
        )

    section_index = 0
    rendered: list[str] = []
    for block in layout["blocks"]:
        if block["type"] == "section":
            section_index += 1
        rendered.append(_render_block(block, section_index))
    content_length = len(rendered)
    if rendered and layout["blocks"][-1]["type"] == "source_note":
        content_length -= 1
    image_tokens: dict[str, str] = {}
    positions = [
        round(content_length * (index + 1) / (len(safe_images) + 1))
        for index in range(len(safe_images))
    ]
    for index, ((source, alt), position) in reversed(
        tuple(enumerate(zip(safe_images, positions)))
    ):
        token = f"RICHARTICLEBODYIMAGE{index}"
        image_tokens[token] = _render_body_image(source, alt)
        rendered.insert(position, token)
    sanitized = _allow_only_safe_reading_attributes(
        '<article class="rich-article '
        f'rich-article--{layout["theme"]} '
        f'rich-article--{layout["structure"]}">'
        f"{toc_html}{title_html}{''.join(rendered)}"
        "</article>"
    )
    for token, image_html in image_tokens.items():
        sanitized = sanitized.replace(token, image_html)
    return sanitized
