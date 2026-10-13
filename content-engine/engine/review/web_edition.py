from __future__ import annotations

from html import escape
import os
from pathlib import Path
import re
import tempfile

from engine.durability import fsync_directory
from engine.editorial.schema import ARTICLE_THEMES
from engine.review.rich_article import (
    article_theme_for_layout,
    render_rich_article,
)


_BASE_CSS = """
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
.rich-article__prose { margin: 1.5rem 0; }
.rich-article__prose p { line-height: 1.85; margin: 0 0 1.15rem; }
.rich-article__prose p:last-child { margin-bottom: 0; }
.rich-article > section[id^="section-"] { margin: 2.4rem 0; scroll-margin-top: 1rem; }
.rich-article > section[id^="section-"] h2 { font-size: 1.55rem; line-height: 1.35; margin: 0 0 1rem; }
.rich-article > section[id^="section-"] p { line-height: 1.85; margin: 0 0 1.15rem; }
.rich-article > section[id^="section-"] p:last-child { margin-bottom: 0; }
.rich-article__judgment, .rich-article__callout { background: #f0f4f8; border-radius: 0.35rem; margin: 1.25rem 0; padding: 1rem 1.15rem; }
.rich-article__comparison { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 1.25rem 0; }
.rich-article__comparison div { border-top: 2px solid #829ab1; padding-top: 0.45rem; }
.rich-article__quote { border-left: 4px solid #334e68; margin: 1.5rem 0; padding-left: 1rem; }
.rich-article__quote p { font-size: 1.1rem; margin-bottom: 0.35rem; }
.rich-article__source { color: #52606d; font-family: system-ui, sans-serif; font-size: 0.9rem; }
.rich-article__source a { color: #186faf; overflow-wrap: anywhere; }
.rich-article__image { margin: 1.6rem 0 1.9rem; }
.rich-article__image img, .web-edition__cover img { display: block; height: auto; max-width: 100%; width: 100%; }
.rich-article__image figcaption { color: #7a828c; font-family: system-ui, sans-serif; font-size: 0.75rem; margin-top: 0.45rem; text-align: center; }
.web-edition__cover { margin: 0 0 2rem; }
@media (max-width: 680px) { .web-edition { margin: 0; padding: 1.25rem; } .rich-article__hero h1 { font-size: 1.8rem; } }
""".strip()
_THEME_CSS = {
    "press": """
.rich-article--press { --rich-theme: press; color: #1f2933; font-family: Georgia, "Times New Roman", serif; }
.rich-article--press .rich-article__hero { border-color: #1f2933; }
.rich-article--press .rich-article__judgment, .rich-article--press .rich-article__callout { background: #f0f4f8; }
""".strip(),
    "tufte": """
.rich-article--tufte { --rich-theme: tufte; color: #25211c; font-family: Georgia, "Times New Roman", serif; line-height: 1.85; }
.rich-article--tufte .rich-article__hero { border-bottom: 1px solid #9a8565; }
.rich-article--tufte .rich-article__judgment, .rich-article--tufte .rich-article__callout { background: #f8f3ea; border-radius: 0; }
.rich-article--tufte .rich-article__quote { border-color: #8d5c35; }
""".strip(),
    "magazine": """
.rich-article--magazine { --rich-theme: magazine; color: #1a2238; font-family: "Trebuchet MS", Arial, sans-serif; line-height: 1.7; }
.rich-article--magazine .rich-article__hero { border-bottom: 5px solid #e24a3b; }
.rich-article--magazine .rich-article__judgment, .rich-article--magazine .rich-article__callout { background: #edf3fb; border-radius: 0.7rem; }
.rich-article--magazine .rich-article__quote { border-color: #e24a3b; }
""".strip(),
    "vignelli": """
.rich-article--vignelli { --rich-theme: vignelli; color: #111; font-family: Arial, Helvetica, sans-serif; line-height: 1.6; }
.rich-article--vignelli .rich-article__hero { border-bottom: 6px solid #d91e18; }
.rich-article--vignelli .rich-article__judgment, .rich-article--vignelli .rich-article__callout { background: #f5f5f2; border-radius: 0; }
.rich-article--vignelli .rich-article__quote { border-color: #111; }
""".strip(),
    "kama": """
.rich-article--kama { --rich-theme: kama; color: #242424; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 15px; line-height: 1.8; max-width: 680px; }
.rich-article--kama .rich-article__hero { border-bottom: 0; margin-bottom: 1.4rem; padding-bottom: 0; }
.rich-article--kama .rich-article__hero h1 { color: #171717; font-size: 2rem; line-height: 1.35; }
.rich-article--kama .rich-article__deck { color: #666; font-size: 1rem; line-height: 1.8; }
.rich-article--kama .rich-article__toc { border-left-color: #dcecf8; }
.rich-article--kama .rich-article__toc a, .rich-article--kama .rich-article__lead, .rich-article--kama .rich-article__judgment, .rich-article--kama .rich-article__callout { color: #0e88eb; }
.rich-article--kama .rich-article__lead { font-size: 1rem; line-height: 1.8; }
.rich-article--kama .rich-article__judgment, .rich-article--kama .rich-article__callout { background: transparent; border-radius: 0; font-weight: 600; margin: 1.35rem 0; padding: 0; }
.rich-article--kama .rich-article__judgment strong { display: none; }
.rich-article--kama .rich-article__judgment p { margin: 0; }
.rich-article--kama > section[id^="section-"] { margin: 2rem 0; }
.rich-article--kama > section[id^="section-"] h2 { border-left: 5px solid #0e88eb; color: #0e88eb; font-size: 18px; line-height: 1.8; margin: 0 0 1rem; padding-left: 10px; }
.rich-article--kama .rich-article__prose p, .rich-article--kama > section[id^="section-"] p { line-height: 1.8; margin: 0 0 0.9rem; }
.rich-article--kama .rich-article__comparison div, .rich-article--kama .rich-article__quote { border-color: #0e88eb; }
""".strip(),
}

if set(_THEME_CSS) != set(ARTICLE_THEMES):
    raise RuntimeError("web edition CSS must cover every supported article theme")
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
    theme = article_theme_for_layout(article_layout) or "press"
    trusted_images = [
        (source, alt)
        for source, alt in (embedded_images or [])
        if _DATA_IMAGE_URL.fullmatch(source)
    ]
    cover_images = [item for item in trusted_images if item[1] == "文章封面"]
    body_images = [item for item in trusted_images if item[1] != "文章封面"]
    article_html = render_rich_article(
        article_layout,
        fallback_title=safe_title,
        fallback_markdown=fallback_markdown,
        body_images=body_images,
    )
    # The rich renderer strips model/Markdown images before reinserting only
    # the repository-owned data images supplied above.
    image_html = "".join(
        '<figure class="web-edition__cover">'
        f'<img src="{escape(src, quote=True)}" alt="{escape(alt, quote=True)}">'
        "</figure>"
        for src, alt in cover_images[:1]
    )
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:\">\n"
        f"<title>{escape(safe_title)}</title>\n"
        f"<style>{_BASE_CSS}\n{_THEME_CSS[theme]}</style>\n"
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
