from __future__ import annotations

from copy import deepcopy
from math import ceil
import re


_ASSET_MARKER_LINE = re.compile(r"^\s*\{\{asset:body-\d{2}\}\}\s*$")
_MARKDOWN_HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_MARKDOWN_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+?)\s*$")
_MARKDOWN_BLOCKQUOTE = re.compile(r"^\s*>\s?(.*?)\s*$")
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKDOWN_REFERENCE_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_MARKDOWN_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MIN_REDUNDANT_PREFIX_LENGTH = 24
_MAX_FALLBACK_SECTIONS = 5
_TARGET_SECTION_CHARS = 420
_LEGACY_GENERIC_HEADINGS = {
    "先看发生了什么",
    "关键事实与细节",
    "这意味着什么",
    "真正值得注意的地方",
    "最后看实际影响",
    "先把问题说清楚",
    "它为什么会发生",
    "可以怎么理解",
    "真正的关键",
    "最后落到实际应用",
    "从一个现象说起",
    "问题是怎么展开的",
    "再往前想一步",
    "换到现实中看",
    "留给我们的启发",
}


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _plain_text(value: str) -> str:
    """Remove Markdown presentation syntax from trusted article prose."""

    text = _MARKDOWN_IMAGE.sub(r"\1", value)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _MARKDOWN_REFERENCE_LINK.sub(r"\1", text)
    text = _MARKDOWN_INLINE_CODE.sub(r"\1", text)
    for marker in ("**", "__", "~~"):
        text = text.replace(marker, "")
    text = re.sub(r"(?<!\w)([*_])([^*_\n]+)\1(?!\w)", r"\2", text)
    return _normalized(text)


def _paragraph_units(lines: list[str]) -> list[str]:
    """Turn a Markdown paragraph or list block into safe semantic paragraphs."""

    units: list[str] = []
    prose: list[str] = []

    def flush_prose() -> None:
        if prose:
            text = _plain_text(" ".join(prose))
            if text:
                units.append(text)
            prose.clear()

    for line in lines:
        list_match = _MARKDOWN_LIST_ITEM.fullmatch(line)
        quote_match = _MARKDOWN_BLOCKQUOTE.fullmatch(line)
        if list_match is not None:
            flush_prose()
            text = _plain_text(list_match.group(1))
            if text:
                units.append(text)
        elif quote_match is not None:
            flush_prose()
            text = _plain_text(quote_match.group(1))
            if text:
                units.append(text)
        else:
            prose.append(line.strip())
    flush_prose()
    return units


def _markdown_body(
    markdown: object,
    *,
    title: object = "",
    source_url: object = "",
) -> tuple[list[str], list[tuple[str, list[str]]]]:
    if not isinstance(markdown, str):
        return [], []
    normalized_title = _normalized(title) if isinstance(title, str) else ""
    trusted_source = source_url if isinstance(source_url, str) else ""
    paragraphs: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_paragraphs: list[str] = []

    def flush_section() -> None:
        nonlocal current_paragraphs
        if current_paragraphs:
            sections.append((current_heading, current_paragraphs))
            current_paragraphs = []

    for chunk in re.split(r"\n\s*\n", markdown):
        lines = [
            line
            for line in chunk.splitlines()
            if _ASSET_MARKER_LINE.fullmatch(line) is None
        ]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue

        heading_match = _MARKDOWN_HEADING.fullmatch(lines[0])
        if heading_match is not None:
            flush_section()
            heading = _plain_text(heading_match.group(2))
            current_heading = (
                ""
                if normalized_title and _normalized(heading) == normalized_title
                else heading
            )
            lines = lines[1:]

        for text in _paragraph_units(lines):
            if normalized_title and _normalized(text) == normalized_title:
                continue
            if trusted_source and trusted_source in text:
                continue
            paragraphs.append(text)
            current_paragraphs.append(text)

    flush_section()
    return paragraphs, sections


def body_paragraphs(
    markdown: object,
    *,
    title: object = "",
    source_url: object = "",
) -> list[str]:
    """Extract ordered reader-visible paragraphs from trusted article Markdown."""

    paragraphs, _sections = _markdown_body(
        markdown,
        title=title,
        source_url=source_url,
    )
    return paragraphs


def _lead_repeats_body(block: object, paragraphs: list[str]) -> bool:
    if not isinstance(block, dict) or block.get("type") != "lead":
        return False
    text = block.get("text")
    if not isinstance(text, str):
        return False
    lead = _normalized(text)
    if not lead:
        return False
    for paragraph in paragraphs:
        body = _normalized(paragraph)
        if lead == body:
            return True
        if len(lead) >= _MIN_REDUNDANT_PREFIX_LENGTH and body.startswith(lead):
            return True
    return False


def _deduplicate_decorative_blocks(
    blocks: list[object],
    paragraphs: list[str],
) -> list[object]:
    seen: set[str] = set()
    deduplicated: list[object] = []
    for block in blocks:
        if not isinstance(block, dict):
            deduplicated.append(block)
            continue
        kind = block.get("type")
        if kind == "hero":
            for field in ("title", "deck"):
                value = block.get(field)
                if isinstance(value, str) and _normalized(value):
                    seen.add(_normalized(value))
        elif kind in {"lead", "key_judgment", "callout"}:
            value = block.get("text")
            normalized = _normalized(value) if isinstance(value, str) else ""
            if normalized and (
                normalized in seen
                or (kind == "lead" and _lead_repeats_body(block, paragraphs))
            ):
                continue
            if normalized:
                seen.add(normalized)
        deduplicated.append(block)
    return deduplicated


def _sections_cover_body(blocks: list[object], paragraphs: list[str]) -> bool:
    rendered_paragraphs: list[str] = []
    for block in blocks:
        if (
            not isinstance(block, dict)
            or block.get("type") not in {"prose", "section"}
        ):
            continue
        values = block.get("paragraphs")
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            return False
        rendered_paragraphs.extend(values)
    return [_normalized(value) for value in rendered_paragraphs] == [
        _normalized(value) for value in paragraphs
    ]


def _sections_have_readable_rhythm(
    blocks: list[object],
    title: object,
) -> bool:
    normalized_title = _normalized(title) if isinstance(title, str) else ""
    content_blocks = [
        block
        for block in blocks
        if isinstance(block, dict) and block.get("type") in {"prose", "section"}
    ]
    if not content_blocks:
        return False
    for block in content_blocks:
        kind = block.get("type")
        heading = block.get("heading")
        values = block.get("paragraphs")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value.strip() for value in values)
            or len(values) > 3
            or sum(len(_normalized(value)) for value in values) > 600
        ):
            return False
        if kind == "section" and (
            not isinstance(heading, str)
            or not heading.strip()
            or heading in _LEGACY_GENERIC_HEADINGS
            or (normalized_title and _normalized(heading) == normalized_title)
        ):
            return False
    return True


def _balanced_groups(paragraphs: list[str], count: int) -> list[list[str]]:
    base, extra = divmod(len(paragraphs), count)
    groups: list[list[str]] = []
    start = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append(paragraphs[start : start + size])
        start += size
    return groups


def _paragraph_groups(paragraphs: list[str]) -> list[list[str]]:
    total_chars = sum(len(_normalized(value)) for value in paragraphs)
    group_count = min(
        len(paragraphs),
        _MAX_FALLBACK_SECTIONS,
        max(
            1,
            ceil(len(paragraphs) / 2),
            ceil(total_chars / _TARGET_SECTION_CHARS),
        ),
    )
    return _balanced_groups(paragraphs, group_count)


def _prose_blocks(paragraphs: list[str]) -> list[dict[str, object]]:
    return [
        {"type": "prose", "paragraphs": group}
        for group in _paragraph_groups(paragraphs)
    ]


def _replacement_sections(
    paragraphs: list[str],
    markdown_sections: list[tuple[str, list[str]]],
) -> list[dict[str, object]]:
    if any(heading for heading, _values in markdown_sections):
        replacements: list[dict[str, object]] = []
        for heading, values in markdown_sections:
            if heading:
                groups = _paragraph_groups(values)
                replacements.append(
                    {"type": "section", "heading": heading, "paragraphs": groups[0]}
                )
                replacements.extend(
                    {"type": "prose", "paragraphs": group}
                    for group in groups[1:]
                )
            else:
                replacements.extend(_prose_blocks(values))
        return replacements
    return _prose_blocks(paragraphs)


def _replace_sections(
    blocks: list[object],
    replacements: list[dict[str, object]],
) -> list[object]:
    result: list[object] = []
    inserted = False
    had_section = any(
        isinstance(block, dict) and block.get("type") in {"prose", "section"}
        for block in blocks
    )
    for block in blocks:
        is_section = (
            isinstance(block, dict)
            and block.get("type") in {"prose", "section"}
        )
        is_source = isinstance(block, dict) and block.get("type") == "source_note"
        if is_section:
            if not inserted:
                result.extend(replacements)
                inserted = True
            continue
        if is_source and not had_section and not inserted:
            result.extend(replacements)
            inserted = True
        result.append(block)
    if not inserted:
        result.extend(replacements)
    return result


def complete_layout_for_rendering(
    layout: dict[str, object],
    *,
    title: object,
    markdown: object,
) -> dict[str, object]:
    """Return a complete, non-repetitive layout with a readable section rhythm."""

    result = deepcopy(layout)
    blocks = result.get("blocks")
    if not isinstance(blocks, list):
        return result
    source_url = next(
        (
            block.get("url")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "source_note"
        ),
        "",
    )
    paragraphs, markdown_sections = _markdown_body(
        markdown,
        title=title,
        source_url=source_url,
    )
    if not paragraphs:
        return result

    if not _sections_cover_body(blocks, paragraphs) or not _sections_have_readable_rhythm(
        blocks,
        title,
    ):
        blocks = _replace_sections(
            blocks,
            _replacement_sections(
                paragraphs,
                markdown_sections,
            ),
        )
    result["blocks"] = _deduplicate_decorative_blocks(blocks, paragraphs)
    return result
