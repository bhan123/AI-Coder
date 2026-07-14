from __future__ import annotations

from html import escape
from urllib.parse import urlparse

from ai_content_loop.review.rendering import render_markdown


_BLOCK_FIELDS = {
    "hero": {"type", "title", "deck"},
    "lead": {"type", "text"},
    "key_judgment": {"type", "text"},
    "section": {"type", "heading", "paragraphs"},
    "workflow_compare": {"type", "before", "after", "remaining_friction"},
    "quote": {"type", "text", "attribution"},
    "callout": {"type", "text"},
    "source_note": {"type", "url", "attribution"},
}


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _trusted_press_layout(value: object) -> bool:
    """Defensively re-check the persisted schema before rendering it."""

    if (
        not isinstance(value, dict)
        or set(value) != {"theme", "blocks"}
        or value.get("theme") != "press"
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
        elif block_type == "section":
            paragraphs = block.get("paragraphs")
            if (
                not _nonempty_text(block.get("heading"))
                or not isinstance(paragraphs, list)
                or not paragraphs
                or not all(_nonempty_text(paragraph) for paragraph in paragraphs)
            ):
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
        url = escape(str(block["url"]), quote=True)
        return (
            '<p class="rich-article__source">来源：'
            f'<a href="{url}" rel="noreferrer noopener" target="_blank">'
            f"{escape(str(block['attribution']))}</a></p>"
        )
    raise ValueError("unsupported rich article block")


def render_rich_article(
    article_layout: object,
    *,
    fallback_title: object = "",
    fallback_markdown: object = "",
) -> str:
    """Render trusted semantic blocks, never model-owned markup or styles."""

    if not _trusted_press_layout(article_layout) or not article_layout["blocks"]:
        return _fallback_html(title=fallback_title, markdown=fallback_markdown)

    sections = [
        str(block["heading"])
        for block in article_layout["blocks"]
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

    section_index = 0
    rendered: list[str] = []
    for block in article_layout["blocks"]:
        if block["type"] == "section":
            section_index += 1
        rendered.append(_render_block(block, section_index))
    return (
        '<article class="rich-article">'
        f"{toc_html}{''.join(rendered)}"
        "</article>"
    )
