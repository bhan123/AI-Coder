"""Validate bounded model-authored copy before text-only image rendering.

The token checks below are a conservative content policy for reducing obvious
resource and execution strings. They are not an exhaustive sanitizer or an
execution boundary. Safety comes from the exact schema and from rendering the
accepted values only as plain text in the later Pillow stage.
"""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from typing import Any


LIMITS = {
    "template_hint": 40,
    "cover_line": 32,
    "cover_subline": 24,
    "label": 16,
    "reaction": 10,
}

_BRIEF_FIELDS = {
    "template_hint",
    "cover_line",
    "cover_subline",
    "body_panels",
    "alternatives",
}
_ALTERNATIVE_FIELDS = {"cover_line", "cover_subline", "body_panels"}
_PANEL_FIELDS = {"label", "reaction"}

_BLOCKED_URI_SCHEMES = (
    "http",
    "https",
    "ftp",
    "file",
    "mailto",
    "javascript",
    "data",
    "vbscript",
    "tel",
    "about",
    "ws",
    "wss",
    "ssh",
    "git",
    "magnet",
    "blob",
)
# Curated common TLDs for visual-copy policy, not a Public Suffix List.
_COMMON_TLDS = (
    "com",
    "org",
    "net",
    "cn",
    "io",
    "ai",
    "co",
    "dev",
    "app",
    "tech",
    "cloud",
    "site",
    "online",
    "xyz",
    "me",
    "info",
    "biz",
    "edu",
    "gov",
    "cc",
    "tv",
    "top",
    "de",
    "uk",
    "jp",
    "fr",
    "au",
    "ca",
    "ch",
    "nl",
    "se",
    "no",
    "es",
    "it",
    "in",
    "br",
    "kr",
    "sg",
    "hk",
    "tw",
    "中国",
    "公司",
    "网络",
)
_HTML_TAG_NAMES = (
    "a",
    "abbr",
    "article",
    "aside",
    "audio",
    "b",
    "body",
    "br",
    "button",
    "canvas",
    "code",
    "div",
    "details",
    "dialog",
    "em",
    "embed",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "html",
    "iframe",
    "img",
    "input",
    "label",
    "li",
    "link",
    "main",
    "marquee",
    "meta",
    "nav",
    "object",
    "ol",
    "p",
    "pre",
    "script",
    "section",
    "select",
    "small",
    "span",
    "strong",
    "style",
    "svg",
    "table",
    "tbody",
    "td",
    "textarea",
    "th",
    "thead",
    "title",
    "tr",
    "ul",
    "video",
)
_PATH_ROOT_NAMES = (
    "assets",
    "bin",
    "build",
    "config",
    "dist",
    "docs",
    "etc",
    "files",
    "folder",
    "home",
    "images",
    "lib",
    "opt",
    "out",
    "path",
    "src",
    "static",
    "temp",
    "tmp",
    "users",
    "usr",
    "var",
)
_PATH_FILE_EXTENSIONS = (
    "bat",
    "cmd",
    "css",
    "csv",
    "dll",
    "exe",
    "gif",
    "gz",
    "html",
    "jpeg",
    "jpg",
    "js",
    "json",
    "jsx",
    "log",
    "md",
    "png",
    "ps1",
    "py",
    "sh",
    "tar",
    "toml",
    "ts",
    "tsx",
    "txt",
    "webp",
    "xml",
    "yaml",
    "yml",
    "zip",
)

_URI_SCHEME_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{'|'.join(_BLOCKED_URI_SCHEMES)}):",
    re.IGNORECASE,
)
_WWW_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])www\.",
    re.IGNORECASE,
)
_LOCALHOST_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])localhost(?::\d{1,5})?"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IPV4_PATTERN = re.compile(
    rf"(?<![\d.])(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}"
    r"(?::\d{1,5})?(?![\d.])"
)
_PUNYCODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:xn--[a-z0-9-]+\.)+"
    r"(?:xn--[a-z0-9-]+|[a-z]{2,63})"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_DOMAIN_LABEL = (
    r"(?:xn--[a-z0-9-]+|"
    r"[a-z0-9\u4e00-\u9fff]"
    r"(?:[a-z0-9\u4e00-\u9fff-]{0,61}"
    r"[a-z0-9\u4e00-\u9fff])?)"
)
_BARE_DOMAIN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_@])"
    rf"(?:{_DOMAIN_LABEL}\.)+"
    rf"(?:{'|'.join(_COMMON_TLDS)})"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_HTML_TAG_NAME_SET = frozenset(_HTML_TAG_NAMES)
_HTML_TAG_CANDIDATE_PATTERN = re.compile(
    r"<\s*(?P<closing>/?)\s*"
    r"(?P<name>[A-Za-z][A-Za-z0-9]*)\b"
    r"(?P<rest>[^<>]*)>"
)
_HTML_PARTIAL_CANDIDATE_PATTERN = re.compile(
    r"<\s*(?P<closing>/?)\s*"
    r"(?P<name>[A-Za-z][A-Za-z0-9]*)\b"
    r"(?P<rest>[^<>]*)$"
)
_UNIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])/[A-Za-z0-9._~-]+"
    r"(?=$|/|[\s.,;:!?，。！？、)\]])"
)
_WINDOWS_DRIVE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]"
)
_UNC_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\\\\|//)[A-Za-z0-9._-]+[\\/]"
)
_ASCII_PATH_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_ROOTED_RELATIVE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    rf"(?:\./)?(?:{'|'.join(_PATH_ROOT_NAMES)})/"
    rf"(?:{_ASCII_PATH_SEGMENT}/)*{_ASCII_PATH_SEGMENT}"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_EXTENSION_RELATIVE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    rf"(?:{_ASCII_PATH_SEGMENT}/)+"
    rf"{_ASCII_PATH_SEGMENT}\.(?:{'|'.join(_PATH_FILE_EXTENSIONS)})"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


class VisualBriefError(ValueError):
    """A bounded validation failure for model-controlled visual copy."""

    def __init__(self, path: str, code: str, detail: str) -> None:
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}")


def _require_mapping(
    value: object,
    *,
    path: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VisualBriefError(path, "invalid_type", "must be an object")
    if set(value) != fields:
        raise VisualBriefError(
            path,
            "invalid_fields",
            "fields do not match the supported schema",
        )
    return value


def _require_list(value: object, *, path: str) -> list[object]:
    if not isinstance(value, list):
        raise VisualBriefError(path, "invalid_type", "must be a list")
    return value


def _contains_url(value: str) -> bool:
    return any(
        pattern.search(value)
        for pattern in (
            _URI_SCHEME_PATTERN,
            _WWW_PATTERN,
            _LOCALHOST_PATTERN,
            _IPV4_PATTERN,
            _PUNYCODE_PATTERN,
            _BARE_DOMAIN_PATTERN,
        )
    )


def _is_blocked_html_candidate(
    candidate: re.Match[str],
    *,
    complete: bool,
) -> bool:
    name = candidate.group("name")
    if name.lower() not in _HTML_TAG_NAME_SET:
        return False
    is_plain_uppercase_generic = (
        complete
        and not candidate.group("closing")
        and len(name) == 1
        and name.isupper()
        and not candidate.group("rest").strip()
    )
    return not is_plain_uppercase_generic


def _contains_html(value: str) -> bool:
    if any(
        _is_blocked_html_candidate(candidate, complete=True)
        for candidate in _HTML_TAG_CANDIDATE_PATTERN.finditer(value)
    ):
        return True
    candidate = _HTML_PARTIAL_CANDIDATE_PATTERN.search(value)
    return bool(
        candidate
        and _is_blocked_html_candidate(candidate, complete=False)
    )


def _is_emoji(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x2300 <= codepoint <= 0x23FF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x1F000 <= codepoint <= 0x1FAFF
    )


def _is_emoji_modifier(character: str) -> bool:
    return 0x1F3FB <= ord(character) <= 0x1F3FF


def _nearest_emoji_neighbor(
    value: str,
    index: int,
    step: int,
) -> str | None:
    cursor = index + step
    while 0 <= cursor < len(value):
        character = value[cursor]
        if character not in {"\ufe0e", "\ufe0f"} and not (
            _is_emoji_modifier(character)
        ):
            return character
        cursor += step
    return None


def _is_emoji_joiner(value: str, index: int) -> bool:
    before = _nearest_emoji_neighbor(value, index, -1)
    after = _nearest_emoji_neighbor(value, index, 1)
    return (
        value[index] == "\u200d"
        and before is not None
        and after is not None
        and _is_emoji(before)
        and _is_emoji(after)
    )


def _contains_control(value: str) -> bool:
    for index, character in enumerate(value):
        category = unicodedata.category(character)
        if category == "Cc":
            return True
        if category == "Cf" and not _is_emoji_joiner(value, index):
            return True
    return False


def _contains_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if any(segment == ".." for segment in normalized.split("/")):
        return True
    if "\\" in value:
        return True
    return any(
        pattern.search(value)
        for pattern in (
            _UNIX_ABSOLUTE_PATH_PATTERN,
            _WINDOWS_DRIVE_PATH_PATTERN,
            _UNC_PATH_PATTERN,
            _ROOTED_RELATIVE_PATH_PATTERN,
            _EXTENSION_RELATIVE_PATH_PATTERN,
        )
    )


def _normalize_string(value: object, *, path: str, field: str) -> str:
    """Apply bounded copy policy; this is not executable-content sanitizing."""

    if not isinstance(value, str):
        raise VisualBriefError(path, "invalid_type", "must be a string")
    if not value.strip():
        raise VisualBriefError(path, "empty", "must be a non-empty string")
    if _contains_control(value):
        raise VisualBriefError(
            path,
            "unsafe_control",
            "must not contain control or format characters",
        )
    if _contains_url(value):
        raise VisualBriefError(path, "unsafe_url", "must not contain a URL")
    if _contains_html(value):
        raise VisualBriefError(
            path,
            "unsafe_html",
            "must not contain HTML-like tags",
        )
    if _contains_path(value):
        raise VisualBriefError(
            path,
            "unsafe_path",
            "must not contain path-like content",
        )
    if len(value) > LIMITS[field]:
        raise VisualBriefError(
            path,
            "too_long",
            f"must not exceed {LIMITS[field]} characters",
        )
    return value


def _normalize_panel(value: object, *, path: str) -> dict[str, str]:
    panel = _require_mapping(value, path=path, fields=_PANEL_FIELDS)
    return {
        "label": _normalize_string(
            panel["label"],
            path=f"{path}.label",
            field="label",
        ),
        "reaction": _normalize_string(
            panel["reaction"],
            path=f"{path}.reaction",
            field="reaction",
        ),
    }


def _normalize_panels(value: object, *, path: str) -> list[dict[str, str]]:
    panels = _require_list(value, path=path)
    if len(panels) != 2:
        raise VisualBriefError(
            path,
            "invalid_count",
            "must contain exactly two panels",
        )
    return [
        _normalize_panel(panel, path=f"{path}[{index}]")
        for index, panel in enumerate(panels)
    ]


def _normalize_alternative(
    value: object,
    *,
    path: str,
) -> dict[str, object]:
    alternative = _require_mapping(
        value,
        path=path,
        fields=_ALTERNATIVE_FIELDS,
    )
    return {
        "cover_line": _normalize_string(
            alternative["cover_line"],
            path=f"{path}.cover_line",
            field="cover_line",
        ),
        "cover_subline": _normalize_string(
            alternative["cover_subline"],
            path=f"{path}.cover_subline",
            field="cover_subline",
        ),
        "body_panels": _normalize_panels(
            alternative["body_panels"],
            path=f"{path}.body_panels",
        ),
    }


def normalize_visual_brief(value: object) -> dict[str, object]:
    """Validate a model-authored visual brief and return an unaliased copy."""

    brief = _require_mapping(value, path="root", fields=_BRIEF_FIELDS)
    alternatives = _require_list(
        brief["alternatives"],
        path="alternatives",
    )
    if len(alternatives) != 2:
        raise VisualBriefError(
            "alternatives",
            "invalid_count",
            "must contain exactly two alternatives",
        )

    return {
        "template_hint": _normalize_string(
            brief["template_hint"],
            path="template_hint",
            field="template_hint",
        ),
        "cover_line": _normalize_string(
            brief["cover_line"],
            path="cover_line",
            field="cover_line",
        ),
        "cover_subline": _normalize_string(
            brief["cover_subline"],
            path="cover_subline",
            field="cover_subline",
        ),
        "body_panels": _normalize_panels(
            brief["body_panels"],
            path="body_panels",
        ),
        "alternatives": [
            _normalize_alternative(
                alternative,
                path=f"alternatives[{index}]",
            )
            for index, alternative in enumerate(alternatives)
        ],
    }


def coerce_visual_brief(value: object) -> dict[str, object] | None:
    """Return a reviewable visual brief, repairing common model over-output.

    The renderer contract needs exactly two body panels and exactly two
    alternatives.  Models often produce a useful brief with three or four
    panels; keep the first two rather than blocking the article from review.
    If the brief is structurally unsafe or too incomplete, drop visuals by
    returning None.
    """

    try:
        return normalize_visual_brief(value)
    except VisualBriefError:
        pass
    if not isinstance(value, dict):
        return None

    candidate = deepcopy(value)

    def trim_two_panels(container: object) -> bool:
        if not isinstance(container, dict):
            return False
        panels = container.get("body_panels")
        if not isinstance(panels, list) or len(panels) < 2:
            return False
        container["body_panels"] = panels[:2]
        return True

    alternatives = candidate.get("alternatives")
    if not isinstance(alternatives, list) or len(alternatives) < 2:
        return None
    candidate["alternatives"] = alternatives[:2]
    if not trim_two_panels(candidate):
        return None
    for alternative in candidate["alternatives"]:
        if not trim_two_panels(alternative):
            return None

    try:
        return normalize_visual_brief(candidate)
    except VisualBriefError:
        return None
