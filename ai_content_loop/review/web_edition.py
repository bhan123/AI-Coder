from __future__ import annotations

from html import escape
import os
from pathlib import Path
import re
import tempfile

from ai_content_loop.durability import fsync_directory
from ai_content_loop.review.rich_article import render_rich_article


_PRESS_CSS = """
* { box-sizing: border-box; }
body { background: #f7fafc; color: #1f2933; margin: 0; }
.web-edition { background: #fff; margin: 2rem auto; max-width: 820px; padding: 3rem; }
.rich-article { color: #1f2933; font-family: Georgia, \"Times New Roman\", serif; line-height: 1.75; margin: 0 auto; max-width: 760px; }
.rich-article__hero { border-bottom: 3px solid #1f2933; margin-bottom: 1.5rem; padding-bottom: 1.25rem; }
.rich-article__hero h1 { font-size: 2.35rem; letter-spacing: -0.03em; line-height: 1.2; margin: 0; }
.rich-article__deck { color: #52606d; font-size: 1.15rem; margin: 0.8rem 0 0; }
.rich-article__toc { border-left: 3px solid #d9e2ec; font-family: system-ui, sans-serif; margin: 1.5rem 0; padding-left: 1rem; }
.rich-article__toc ol { margin: 0.5rem 0; padding-left: 1.25rem; }
.rich-article__lead { font-size: 1.2rem; font-weight: 600; }
.rich-article__judgment, .rich-article__callout { background: #f0f4f8; border-radius: 0.35rem; margin: 1.25rem 0; padding: 1rem 1.15rem; }
.rich-article__comparison { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 1.25rem 0; }
.rich-article__comparison div { border-top: 2px solid #829ab1; padding-top: 0.45rem; }
.rich-article__quote { border-left: 4px solid #334e68; margin: 1.5rem 0; padding-left: 1rem; }
.rich-article__quote p { font-size: 1.1rem; margin-bottom: 0.35rem; }
.rich-article__source { color: #52606d; font-family: system-ui, sans-serif; font-size: 0.9rem; }
.rich-article__source a { color: #186faf; overflow-wrap: anywhere; }
@media (max-width: 680px) { .web-edition { margin: 0; padding: 1.25rem; } .rich-article__hero h1 { font-size: 1.8rem; } }
""".strip()
_IMAGE_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_DATA_IMAGE_URL = re.compile(
    r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]*={0,2}\Z"
)


def render_web_edition(
    article_layout: object,
    *,
    title: object = "",
    fallback_markdown: object = "",
    embedded_images: list[tuple[str, str]] | None = None,
) -> str:
    """Return a portable document using only renderer-owned presentation."""

    safe_title = title if isinstance(title, str) else ""
    article_html = render_rich_article(
        article_layout,
        fallback_title=safe_title,
        fallback_markdown=fallback_markdown,
    )
    # The rich renderer's markdown fallback can contain Markdown image links.
    # A standalone edition has no trusted mapping for those URLs, so omit them
    # rather than letting a browser fetch an external or unverified resource.
    article_html = _IMAGE_TAG.sub("", article_html)
    image_html = "".join(
        '<figure class="web-edition__image">'
        f'<img src="{escape(src, quote=True)}" alt="{escape(alt, quote=True)}">'
        "</figure>"
        for src, alt in (embedded_images or [])
        if _DATA_IMAGE_URL.fullmatch(src)
    )
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:\">\n"
        f"<title>{escape(safe_title)}</title>\n"
        f"<style>{_PRESS_CSS}</style>\n"
        "</head>\n<body>\n"
        f'<main class="web-edition">{image_html}{article_html}</main>\n'
        "</body>\n</html>\n"
    )


def atomic_write_web_edition(path: Path, html: str) -> None:
    """Durably replace a server-selected static document without partial reads."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)
