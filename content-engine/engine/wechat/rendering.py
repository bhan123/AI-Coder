from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from engine.editorial.schema import ARTICLE_STRUCTURES, ARTICLE_THEMES
from engine.editorial.layout_completion import (
    complete_layout_for_rendering,
)


_FIELDS = {
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
_BASE = "box-sizing:border-box;max-width:100%;word-wrap:break-word;"
_SECTION = _BASE + "margin:32px 0;color:#242424;font-size:16px;line-height:1.8;"
_PARAGRAPH = _BASE + "margin:12px 0;color:#242424;font-size:16px;line-height:1.8;"
_BODY_PARAGRAPH = _BASE + "margin:0 0 18px;color:#242424;font-size:16px;line-height:1.9;"
_KAMA_SECTION = _BASE + "margin:30px 0;color:#242424;font-size:15px;line-height:1.8;"
_KAMA_PARAGRAPH = _BASE + "margin:8px 0;color:#242424;font-size:15px;line-height:1.8;"
_KAMA_BODY_PARAGRAPH = _BASE + "margin:0 0 14px;color:#242424;font-size:15px;line-height:1.8;"


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


def _render_kama_block(block: dict[str, object]) -> str:
    kind = block["type"]
    if kind == "hero":
        return (
            f'<section style="{_KAMA_SECTION}margin-top:0;">'
            f'<h1 style="{_BASE}margin:0 0 12px;color:#171717;font-size:25px;line-height:1.4;">{escape(str(block["title"]))}</h1>'
            f'<p style="{_KAMA_PARAGRAPH}color:#666;">{escape(str(block["deck"]))}</p></section>'
        )
    if kind == "lead":
        return f'<p style="{_KAMA_PARAGRAPH}color:#0e88eb;font-weight:600;">{escape(str(block["text"]))}</p>'
    if kind in {"key_judgment", "callout"}:
        return (
            f'<p style="{_KAMA_PARAGRAPH}margin:18px 0;color:#0e88eb;font-weight:600;">'
            f'{escape(str(block["text"]))}</p>'
        )
    if kind == "prose":
        return "".join(
            f'<p style="{_KAMA_BODY_PARAGRAPH}">{escape(str(value))}</p>'
            for value in block["paragraphs"]
        )
    if kind == "section":
        paragraphs = "".join(
            f'<p style="{_KAMA_BODY_PARAGRAPH}">{escape(str(value))}</p>'
            for value in block["paragraphs"]
        )
        return (
            f'<section style="{_KAMA_SECTION}"><h2 style="{_BASE}margin:0 0 14px;'
            'padding-left:10px;border-left:5px solid #0e88eb;color:#0e88eb;'
            'font-size:18px;line-height:1.8;">'
            f'{escape(str(block["heading"]))}</h2>{paragraphs}</section>'
        )
    if kind == "workflow_compare":
        rows = (("之前", "before"), ("现在", "after"), ("仍需克服", "remaining_friction"))
        return (
            f'<section style="{_KAMA_SECTION}">'
            + "".join(
                f'<p style="{_KAMA_PARAGRAPH}"><strong style="color:#0e88eb;">{label}：</strong>{escape(str(block[key]))}</p>'
                for label, key in rows
            )
            + "</section>"
        )
    if kind == "quote":
        return (
            f'<blockquote style="{_KAMA_SECTION}margin-left:0;padding:4px 18px;border-left:3px solid #0e88eb;color:#555;">'
            f'<p style="{_KAMA_PARAGRAPH}">{escape(str(block["text"]))}</p>'
            f'<p style="{_KAMA_PARAGRAPH}text-align:right;">— {escape(str(block["attribution"]))}</p></blockquote>'
        )
    if kind == "source_note":
        return f'<p style="{_KAMA_PARAGRAPH}color:#777;font-size:13px;">来源：{escape(str(block["attribution"]))} {escape(str(block["url"]))}</p>'
    raise ValueError("unsupported article block")


def _render_block(block: dict[str, object], theme: str) -> str:
    if theme == "kama":
        return _render_kama_block(block)
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
    if kind == "prose":
        paragraphs = "".join(
            f'<p style="{_BODY_PARAGRAPH}">{escape(str(value))}</p>'
            for value in block["paragraphs"]
        )
        return f'<section style="{_SECTION}">{paragraphs}</section>'
    if kind == "section":
        paragraphs = "".join(
            f'<p style="{_BODY_PARAGRAPH}">{escape(str(value))}</p>'
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
    body_image_url: str | None = None,
    body_image_urls: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Render escaped, inline-styled HTML accepted by WeChat drafts."""

    if body_image_urls is None:
        body_image_urls = [body_image_url] if body_image_url is not None else []
    if not body_image_urls or len(body_image_urls) > 3:
        raise ValueError("one to three body image URLs are required")
    safe_images = [_image(url) for url in body_image_urls]
    layout = _trusted_layout(article_layout)
    if layout is None or not layout["blocks"]:
        content = _fallback(fallback_title, fallback_markdown)
        return (
            f'<section style="{_BASE}padding:0 4px;">'
            f'{content}{"".join(safe_images)}</section>'
        )
    layout = complete_layout_for_rendering(
        layout,
        title=fallback_title,
        markdown=fallback_markdown,
    )
    theme = str(layout["theme"])
    rendered = [_render_block(block, theme) for block in layout["blocks"]]
    positions = [
        round(len(rendered) * (index + 1) / (len(safe_images) + 1))
        for index in range(len(safe_images))
    ]
    for position, safe_image in reversed(tuple(zip(positions, safe_images))):
        rendered.insert(position, safe_image)
    return f'<section style="{_BASE}padding:0 4px;">{"".join(rendered)}</section>'
