from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from ai_content_loop.editorial.schema import ARTICLE_STRUCTURES, ARTICLE_THEMES


_FIELDS = {
    "hero": {"type", "title", "deck"},
    "lead": {"type", "text"},
    "key_judgment": {"type", "text"},
    "section": {"type", "heading", "paragraphs"},
    "workflow_compare": {"type", "before", "after", "remaining_friction"},
    "quote": {"type", "text", "attribution"},
    "callout": {"type", "text"},
    "source_note": {"type", "url", "attribution"},
}
_BASE = "box-sizing:border-box;max-width:100%;word-wrap:break-word;"
_SECTION = _BASE + "margin:24px 0;color:#242424;font-size:16px;line-height:1.8;"
_PARAGRAPH = _BASE + "margin:12px 0;color:#242424;font-size:16px;line-height:1.8;"


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _trusted_layout(value: object) -> dict[str, object] | None:
    if (
        isinstance(value, dict)
        and set(value) == {"theme", "blocks"}
        and value.get("theme") == "press"
    ):
        value = {**value, "structure": "briefing"}
    if (
        not isinstance(value, dict)
        or set(value) != {"theme", "structure", "blocks"}
        or value.get("theme") not in ARTICLE_THEMES
        or value.get("structure") not in ARTICLE_STRUCTURES
        or not isinstance(value.get("blocks"), list)
    ):
        return None
    for block in value["blocks"]:
        if not isinstance(block, dict) or block.get("type") not in _FIELDS:
            return None
        kind = str(block["type"])
        if set(block) != _FIELDS[kind]:
            return None
        values = [item for name, item in block.items() if name != "type"]
        for item in values:
            if isinstance(item, list):
                if not item or not all(_text(entry) for entry in item):
                    return None
            elif not _text(item):
                return None
    return value


def _safe_image_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError("body image URL must be an absolute HTTPS URL")
    return value


def _image(url: str) -> str:
    return (
        f'<p style="{_BASE}margin:22px 0;text-align:center;">'
        f'<img src="{escape(_safe_image_url(url), quote=True)}" '
        f'style="{_BASE}display:block;margin:0 auto;height:auto;" alt="正文配图">'
        "</p>"
    )


def _render_block(block: dict[str, object]) -> str:
    kind = block["type"]
    if kind == "hero":
        return (
            f'<section style="{_SECTION}margin-top:0;">'
            f'<h1 style="{_BASE}margin:0 0 12px;font-size:28px;line-height:1.35;">{escape(str(block["title"]))}</h1>'
            f'<p style="{_PARAGRAPH}color:#666;">{escape(str(block["deck"]))}</p></section>'
        )
    if kind == "lead":
        return f'<p style="{_PARAGRAPH}font-size:18px;font-weight:600;">{escape(str(block["text"]))}</p>'
    if kind in {"key_judgment", "callout"}:
        label = "关键判断" if kind == "key_judgment" else "提示"
        return (
            f'<section style="{_SECTION}padding:16px;border-left:4px solid #111;background:#f5f5f5;">'
            f'<strong style="{_BASE}">{label}</strong>'
            f'<p style="{_PARAGRAPH}">{escape(str(block["text"]))}</p></section>'
        )
    if kind == "section":
        paragraphs = "".join(
            f'<p style="{_PARAGRAPH}">{escape(str(value))}</p>'
            for value in block["paragraphs"]
        )
        return (
            f'<section style="{_SECTION}"><h2 style="{_BASE}margin:0 0 12px;font-size:22px;line-height:1.45;">'
            f'{escape(str(block["heading"]))}</h2>{paragraphs}</section>'
        )
    if kind == "workflow_compare":
        rows = (
            ("之前", "before"),
            ("现在", "after"),
            ("仍需克服", "remaining_friction"),
        )
        return (
            '<section style="'
            + _SECTION
            + '">'
            + "".join(
                f'<p style="{_PARAGRAPH}"><strong>{label}：</strong>{escape(str(block[key]))}</p>'
                for label, key in rows
            )
            + "</section>"
        )
    if kind == "quote":
        return (
            f'<blockquote style="{_SECTION}margin-left:0;padding:4px 18px;border-left:3px solid #999;color:#555;">'
            f'<p style="{_PARAGRAPH}">{escape(str(block["text"]))}</p>'
            f'<p style="{_PARAGRAPH}text-align:right;">— {escape(str(block["attribution"]))}</p></blockquote>'
        )
    if kind == "source_note":
        return f'<p style="{_PARAGRAPH}color:#777;font-size:13px;">来源：{escape(str(block["attribution"]))} {escape(str(block["url"]))}</p>'
    raise ValueError("unsupported article block")


def _fallback(title: object, markdown: object) -> str:
    safe_title = escape(title if isinstance(title, str) else "")
    source = markdown if isinstance(markdown, str) else ""
    paragraphs = []
    for chunk in re.split(r"\n\s*\n", source):
        text = re.sub(r"^#{1,6}\s+", "", chunk.strip())
        if text:
            paragraphs.append(f'<p style="{_PARAGRAPH}">{escape(text)}</p>')
    heading = (
        f'<h1 style="{_BASE}font-size:28px;line-height:1.35;">{safe_title}</h1>'
        if safe_title
        else ""
    )
    return heading + "".join(paragraphs)


def render_wechat_article(
    article_layout: object,
    *,
    fallback_title: object,
    fallback_markdown: object,
    body_image_url: str,
) -> str:
    """Render escaped, inline-styled HTML accepted by WeChat drafts."""

    safe_image = _image(body_image_url)
    layout = _trusted_layout(article_layout)
    if layout is None or not layout["blocks"]:
        content = _fallback(fallback_title, fallback_markdown)
        return f'<section style="{_BASE}padding:0 4px;">{content}{safe_image}</section>'
    rendered = [_render_block(block) for block in layout["blocks"]]
    insert_at = min(2, len(rendered))
    rendered.insert(insert_at, safe_image)
    return f'<section style="{_BASE}padding:0 4px;">{"".join(rendered)}</section>'
