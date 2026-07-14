from __future__ import annotations

import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ai_content_loop.visuals.brief import normalize_visual_brief
from ai_content_loop.visuals.templates import TEMPLATES, TemplateSpec


COVER_SIZE = (900, 383)
BODY_SIZE = (1080, 608)

_SPLIT_PANEL_BOXES = (
    (50, 70, 520, 538),
    (560, 70, 1030, 538),
)
_UNASSIGNED_GLYPH_PROBES = ("\u0378", "\u0380", "\u0381")
_ZWJ = "\u200d"


class VisualRenderError(RuntimeError):
    """A stable renderer failure that does not expose local resource details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(font_path), size=size)
    except (OSError, TypeError, ValueError):
        raise VisualRenderError("font_unavailable") from None


def _spacing_for(size: int) -> int:
    return max(4, size // 5)


def _is_variation_selector(character: str) -> bool:
    codepoint = ord(character)
    return (
        0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
    )


def _is_emoji_modifier(character: str) -> bool:
    return 0x1F3FB <= ord(character) <= 0x1F3FF


def _is_regional_indicator(character: str) -> bool:
    return 0x1F1E6 <= ord(character) <= 0x1F1FF


def _is_grapheme_extend(character: str) -> bool:
    return (
        unicodedata.category(character) in {"Mn", "Mc", "Me"}
        or _is_variation_selector(character)
        or _is_emoji_modifier(character)
    )


def _grapheme_clusters(text: str) -> list[str]:
    """Group CJK/Latin and common emoji sequences for bounded wrapping.

    Unsupported scripts or glyphs fail coverage rather than being silently
    split or rendered as tofu.
    """

    clusters: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            clusters.append(character)
            index += 1
            continue

        cluster = character
        index += 1
        if character == _ZWJ and index < len(text) and text[index] != "\n":
            cluster += text[index]
            index += 1
        elif (
            _is_regional_indicator(character)
            and index < len(text)
            and _is_regional_indicator(text[index])
        ):
            cluster += text[index]
            index += 1

        while index < len(text) and _is_grapheme_extend(text[index]):
            cluster += text[index]
            index += 1

        while index < len(text) and text[index] == _ZWJ:
            cluster += text[index]
            index += 1
            if index >= len(text) or text[index] == "\n":
                break
            cluster += text[index]
            index += 1
            while index < len(text) and _is_grapheme_extend(text[index]):
                cluster += text[index]
                index += 1

        clusters.append(cluster)
    return clusters


def _glyph_signature(
    font: ImageFont.FreeTypeFont,
    text: str,
) -> tuple[tuple[int, int], bytes]:
    try:
        mask = font.getmask(text, mode="L")
        return mask.size, bytes(mask)
    except (OSError, TypeError, ValueError):
        raise VisualRenderError("unsupported_glyph") from None


def _is_coverage_ignored(character: str) -> bool:
    return (
        character.isspace()
        or character == _ZWJ
        or _is_variation_selector(character)
    )


def _ensure_supported_text(
    font: ImageFont.FreeTypeFont,
    text: str,
) -> None:
    """Reject tofu-prone base glyphs without exposing copy or font details."""

    missing_signatures = {
        _glyph_signature(font, probe)
        for probe in _UNASSIGNED_GLYPH_PROBES
    }
    base_characters = dict.fromkeys(
        character
        for character in text
        if not _is_coverage_ignored(character)
    )
    for character in base_characters:
        if _glyph_signature(font, character) in missing_signatures:
            raise VisualRenderError("unsupported_glyph")


def _valid_fit_bounds(
    *,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> bool:
    return (
        type(max_width) is int
        and type(max_height) is int
        and type(start_size) is int
        and type(min_size) is int
        and max_width > 0
        and max_height > 0
        and start_size >= min_size > 0
    )


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    *,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> ImageFont.FreeTypeFont:
    """Return the largest declared font whose measured multiline box fits."""

    if not isinstance(text, str) or not _valid_fit_bounds(
        max_width=max_width,
        max_height=max_height,
        start_size=start_size,
        min_size=min_size,
    ):
        raise VisualRenderError("text_overflow")

    font = _load_font(font_path, start_size)
    _ensure_supported_text(font, text)
    for size in range(start_size, min_size - 1, -1):
        if size != start_size:
            font = _load_font(font_path, size)
        box = draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            spacing=_spacing_for(size),
        )
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width <= max_width and height <= max_height:
            return font
    raise VisualRenderError("text_overflow")


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: int,
) -> str:
    """Wrap measured glyphs while preserving every explicit newline."""

    if not isinstance(text, str) or type(max_width) is not int or max_width <= 0:
        raise VisualRenderError("text_overflow")

    lines: list[str] = []
    current = ""
    for cluster in _grapheme_clusters(text):
        if cluster == "\n":
            lines.append(current)
            current = ""
            continue

        candidate = current + cluster
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue

        if not current or _text_width(draw, cluster, font) > max_width:
            raise VisualRenderError("text_overflow")
        lines.append(current)
        current = cluster

    lines.append(current)
    return "\n".join(lines)


def _fit_wrapped_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    *,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> tuple[ImageFont.FreeTypeFont, str, int]:
    if not isinstance(text, str) or not _valid_fit_bounds(
        max_width=max_width,
        max_height=max_height,
        start_size=start_size,
        min_size=min_size,
    ):
        raise VisualRenderError("text_overflow")

    font = _load_font(font_path, start_size)
    _ensure_supported_text(font, text)
    for size in range(start_size, min_size - 1, -1):
        if size != start_size:
            font = _load_font(font_path, size)
        try:
            wrapped = _wrap_text(
                draw,
                text,
                font,
                max_width=max_width,
            )
        except VisualRenderError as exc:
            if exc.code != "text_overflow":
                raise
            continue

        spacing = _spacing_for(size)
        box = draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            spacing=spacing,
            align="center",
        )
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width <= max_width and height <= max_height:
            return font, wrapped, spacing
    raise VisualRenderError("text_overflow")


def _draw_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    box: tuple[int, int, int, int],
    *,
    fill: str,
    start_size: int,
    min_size: int,
) -> None:
    left, top, right, bottom = box
    max_width = right - left
    max_height = bottom - top
    font, wrapped, spacing = _fit_wrapped_font(
        draw,
        text,
        font_path,
        max_width=max_width,
        max_height=max_height,
        start_size=start_size,
        min_size=min_size,
    )
    measured = draw.multiline_textbbox(
        (0, 0),
        wrapped,
        font=font,
        spacing=spacing,
        align="center",
    )
    width = measured[2] - measured[0]
    height = measured[3] - measured[1]
    position = (
        left + (max_width - width) // 2 - measured[0],
        top + (max_height - height) // 2 - measured[1],
    )
    placed = draw.multiline_textbbox(
        position,
        wrapped,
        font=font,
        spacing=spacing,
        align="center",
    )
    if (
        placed[0] < left
        or placed[1] < top
        or placed[2] > right
        or placed[3] > bottom
    ):
        raise VisualRenderError("text_overflow")
    draw.multiline_text(
        position,
        wrapped,
        font=font,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def _render_cover(
    draw: ImageDraw.ImageDraw,
    value: dict[str, object],
    template: TemplateSpec,
    font_path: Path,
) -> None:
    draw.rounded_rectangle(
        (710, 55, 845, 328),
        radius=30,
        fill=template.accent,
    )
    draw.ellipse(
        (742, 105, 813, 176),
        outline=template.background,
        width=7,
    )
    draw.ellipse((761, 128, 770, 137), fill=template.background)
    draw.ellipse((786, 128, 795, 137), fill=template.background)
    draw.line(
        (759, 153, 777, 160, 797, 151),
        fill=template.background,
        width=6,
        joint="curve",
    )
    draw.line(
        (778, 190, 778, 272),
        fill=template.background,
        width=10,
    )
    draw.line(
        (742, 218, 814, 218),
        fill=template.background,
        width=10,
    )

    _draw_text_in_box(
        draw,
        str(value["cover_line"]),
        font_path,
        (60, 42, 670, 242),
        fill=template.foreground,
        start_size=62,
        min_size=36,
    )
    _draw_text_in_box(
        draw,
        str(value["cover_subline"]),
        font_path,
        (70, 255, 660, 342),
        fill=template.foreground,
        start_size=32,
        min_size=22,
    )


def _draw_reaction_face(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    center_y: int,
    variant: int,
    template: TemplateSpec,
) -> None:
    radius = 64
    draw.ellipse(
        (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ),
        outline=template.accent,
        width=8,
    )
    for eye_x in (center_x - 22, center_x + 22):
        draw.ellipse(
            (eye_x - 6, center_y - 25, eye_x + 6, center_y - 13),
            fill=template.foreground,
        )
    if variant == 0:
        mouth = (
            center_x - 31,
            center_y + 20,
            center_x,
            center_y + 34,
            center_x + 31,
            center_y + 18,
        )
    else:
        mouth = (
            center_x - 31,
            center_y + 32,
            center_x,
            center_y + 18,
            center_x + 31,
            center_y + 32,
        )
        draw.line(
            (center_x - 34, center_y - 38, center_x - 12, center_y - 30),
            fill=template.foreground,
            width=6,
        )
        draw.line(
            (center_x + 12, center_y - 30, center_x + 34, center_y - 38),
            fill=template.foreground,
            width=6,
        )
    draw.line(
        mouth,
        fill=template.foreground,
        width=7,
        joint="curve",
    )


def _render_split_body(
    draw: ImageDraw.ImageDraw,
    value: dict[str, object],
    template: TemplateSpec,
    font_path: Path,
) -> None:
    panels = value["body_panels"]
    if not isinstance(panels, list):
        raise VisualRenderError("invalid_template")

    draw.line((540, 108, 540, 500), fill=template.accent, width=6)
    for index, (panel_box, panel) in enumerate(
        zip(_SPLIT_PANEL_BOXES, panels, strict=True)
    ):
        if not isinstance(panel, dict):
            raise VisualRenderError("invalid_template")
        left, top, right, bottom = panel_box
        draw.rounded_rectangle(
            panel_box,
            radius=34,
            outline=template.accent,
            width=8,
        )
        _draw_text_in_box(
            draw,
            str(panel["label"]),
            font_path,
            (left + 30, top + 20, right - 30, top + 140),
            fill=template.foreground,
            start_size=46,
            min_size=28,
        )
        _draw_reaction_face(
            draw,
            center_x=(left + right) // 2,
            center_y=295,
            variant=index,
            template=template,
        )
        _draw_text_in_box(
            draw,
            str(panel["reaction"]),
            font_path,
            (left + 30, 410, right - 30, 515),
            fill=template.foreground,
            start_size=38,
            min_size=24,
        )


def _render_verdict_body(
    draw: ImageDraw.ImageDraw,
    value: dict[str, object],
    template: TemplateSpec,
    font_path: Path,
) -> None:
    draw.rounded_rectangle(
        (110, 50, 970, 558),
        radius=48,
        outline=template.accent,
        width=8,
    )
    draw.rounded_rectangle(
        (400, 72, 680, 148),
        radius=24,
        fill=template.accent,
    )
    _draw_text_in_box(
        draw,
        "VERDICT",
        font_path,
        (420, 82, 660, 138),
        fill=template.background,
        start_size=34,
        min_size=24,
    )
    _draw_text_in_box(
        draw,
        str(value["cover_line"]),
        font_path,
        (150, 165, 930, 350),
        fill=template.foreground,
        start_size=58,
        min_size=34,
    )
    draw.line((240, 375, 840, 375), fill=template.accent, width=10)
    draw.ellipse((218, 365, 238, 385), fill=template.accent)
    draw.ellipse((842, 365, 862, 385), fill=template.accent)
    _draw_text_in_box(
        draw,
        str(value["cover_subline"]),
        font_path,
        (160, 395, 920, 505),
        fill=template.accent,
        start_size=38,
        min_size=24,
    )


def _canonical_template(template: TemplateSpec) -> TemplateSpec:
    if type(template) is not TemplateSpec:
        raise VisualRenderError("invalid_template")
    for approved in TEMPLATES.values():
        if template is approved or template == approved:
            return approved
    raise VisualRenderError("invalid_template")


def _output_paths(
    cover_path: Path,
    body_path: Path,
) -> tuple[Path, Path]:
    try:
        cover = Path(cover_path)
        body = Path(body_path)
        if (
            not cover.name
            or not body.name
            or cover.resolve(strict=False) == body.resolve(strict=False)
        ):
            raise ValueError
    except (OSError, TypeError, ValueError):
        raise VisualRenderError("invalid_output") from None
    return cover, body


def render_visuals(
    *,
    brief: dict[str, object],
    template: TemplateSpec,
    font_path: Path,
    cover_path: Path,
    body_path: Path,
) -> None:
    """Render registered local geometry or fail before publishing tofu glyphs.

    The two file writes are intentionally not a pair-atomic transaction.
    Task 8's atomic revision publication prevents a partial pair from becoming
    visible to readers.
    """

    value = normalize_visual_brief(brief)
    approved_template = _canonical_template(template)
    cover_output, body_output = _output_paths(cover_path, body_path)

    cover: Image.Image | None = None
    body: Image.Image | None = None
    try:
        cover = Image.new("RGB", COVER_SIZE, approved_template.background)
        body = Image.new("RGB", BODY_SIZE, approved_template.background)
        _render_cover(
            ImageDraw.Draw(cover),
            value,
            approved_template,
            font_path,
        )
        body_draw = ImageDraw.Draw(body)
        if approved_template.layout == "split":
            _render_split_body(
                body_draw,
                value,
                approved_template,
                font_path,
            )
        elif approved_template.layout == "verdict":
            _render_verdict_body(
                body_draw,
                value,
                approved_template,
                font_path,
            )
        else:
            raise VisualRenderError("invalid_template")

        # Both images are complete in memory before any filesystem mutation.
        cover_output.parent.mkdir(parents=True, exist_ok=True)
        body_output.parent.mkdir(parents=True, exist_ok=True)
        cover.save(
            cover_output,
            format="JPEG",
            quality=88,
            optimize=True,
        )
        body.save(body_output, format="PNG", optimize=True)
    except VisualRenderError:
        raise
    except (OSError, TypeError, ValueError):
        raise VisualRenderError("invalid_output") from None
    finally:
        if cover is not None:
            cover.close()
        if body is not None:
            body.close()
