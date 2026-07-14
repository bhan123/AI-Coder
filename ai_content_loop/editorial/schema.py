from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from ai_content_loop.visuals.brief import (
    VisualBriefError,
    coerce_visual_brief,
    normalize_visual_brief,
)
from ai_content_loop.visuals.templates import TEMPLATES


PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")
CORE_FIELDS = {
    "dedupe_key",
    "column",
    "master_title",
    "master_markdown",
    "platform_markdown",
}
FINAL_FIELDS = CORE_FIELDS | {
    "editorial_profile",
    "visual_brief",
    "visual_assets",
    "article_layout",
}
MAX_TEXT_CHARS = 200_000

_EDITORIAL_PROFILE_FIELDS = {
    "version",
    "persona",
    "humor_level",
    "verified_trial",
    "trial_artifact_refs",
    "quality_warnings",
}
_VISUAL_ASSET_FIELDS = {"cover", "body"}
_ARTICLE_LAYOUT_FIELDS = {"theme", "blocks"}
_ARTICLE_LAYOUT_BLOCK_TYPES = {
    "hero",
    "lead",
    "key_judgment",
    "section",
    "workflow_compare",
    "quote",
    "callout",
    "source_note",
}
_ARTICLE_LAYOUT_BLOCK_FIELDS = {
    "hero": {"type", "title", "deck"},
    "lead": {"type", "text"},
    "key_judgment": {"type", "text"},
    "section": {"type", "heading", "paragraphs"},
    "workflow_compare": {
        "type",
        "before",
        "after",
        "remaining_friction",
    },
    "quote": {"type", "text", "attribution"},
    "callout": {"type", "text"},
    "source_note": {"type", "url", "attribution"},
}
_VISUAL_ASSET_REF_FIELDS = {
    "asset_id",
    "revision",
    "path",
    "template",
    "copy_index",
    "ai_generated",
}
_REVISION_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class FinalSchemaError(ValueError):
    """The final article does not match the supported schema."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: str | None = None,
    ) -> None:
        self.failure_code = failure_code
        super().__init__(message)


def article_id_for(dedupe_key: str) -> str:
    """Return the stable opaque identifier shared by review and assets."""

    if not isinstance(dedupe_key, str) or not dedupe_key.strip():
        raise ValueError("dedupe_key must be a non-empty string")
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]


def canonical_payload_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_version(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def legacy_editorial_profile() -> dict[str, object]:
    return {
        "version": "legacy",
        "persona": "unassigned",
        "humor_level": "unassigned",
        "verified_trial": False,
        "trial_artifact_refs": [],
        "quality_warnings": ["legacy_editorial_profile"],
    }


def empty_visual_assets() -> dict[str, object]:
    return {"cover": None, "body": []}


def empty_article_layout() -> dict[str, object]:
    return {"theme": "press", "blocks": []}


def _validate_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalSchemaError(f"{field} must be a non-empty string")
    if len(value) > MAX_TEXT_CHARS:
        raise FinalSchemaError(
            f"{field} exceeds {MAX_TEXT_CHARS} characters"
        )
    return value


def _validate_text_list(value: object, field: str) -> None:
    if not isinstance(value, list):
        raise FinalSchemaError(f"{field} must be a list")
    for item in value:
        _validate_text(item, field)


def _validate_core(value: dict[str, Any]) -> None:
    for field in (
        "dedupe_key",
        "column",
        "master_title",
        "master_markdown",
    ):
        _validate_text(value.get(field), field)

    platform_markdown = value.get("platform_markdown")
    if (
        not isinstance(platform_markdown, dict)
        or set(platform_markdown) != set(PLATFORMS)
    ):
        raise FinalSchemaError(
            "platform_markdown must contain exactly four platforms"
        )
    for platform in PLATFORMS:
        _validate_text(
            platform_markdown.get(platform),
            f"platform_markdown.{platform}",
        )


def _validate_editorial_profile(value: object) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _EDITORIAL_PROFILE_FIELDS
    ):
        raise FinalSchemaError(
            "editorial_profile fields do not match the supported schema"
        )
    for field in ("version", "persona", "humor_level"):
        _validate_text(value.get(field), f"editorial_profile.{field}")
    if value.get("version") == "legacy" and value != legacy_editorial_profile():
        raise FinalSchemaError(
            "editorial_profile cannot forge legacy compatibility"
        )
    if not isinstance(value.get("verified_trial"), bool):
        raise FinalSchemaError(
            "editorial_profile.verified_trial must be a boolean"
        )
    for field in ("trial_artifact_refs", "quality_warnings"):
        _validate_text_list(
            value.get(field),
            f"editorial_profile.{field}",
        )


def _normalize_visual_brief(
    value: object,
    *,
    allow_none: bool,
) -> dict[str, object] | None:
    if value is None and allow_none:
        return None
    try:
        return normalize_visual_brief(value)
    except VisualBriefError as exc:
        raise FinalSchemaError(
            f"visual_brief.{exc.path}: {exc.code}",
            failure_code=f"visual_brief:{exc.path}",
        ) from exc


def _validate_asset_reference(
    value: object,
    *,
    asset_id: str,
    filename: str,
    article_id: str,
) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != _VISUAL_ASSET_REF_FIELDS
    ):
        raise FinalSchemaError(
            "visual_assets reference fields do not match the supported schema"
        )
    revision = value.get("revision")
    if (
        value.get("asset_id") != asset_id
        or not isinstance(revision, str)
        or _REVISION_PATTERN.fullmatch(revision) is None
        or value.get("path")
        != f"assets/{article_id}/{revision}/{filename}"
        or value.get("template") not in TEMPLATES
        or type(value.get("copy_index")) is not int
        or not 0 <= value["copy_index"] <= 2
        or value.get("ai_generated") is not False
    ):
        raise FinalSchemaError(
            "visual_assets reference does not match the supported schema"
        )
    return value


def _validate_visual_assets(value: object, *, dedupe_key: str) -> None:
    if not isinstance(value, dict) or set(value) != _VISUAL_ASSET_FIELDS:
        raise FinalSchemaError(
            "visual_assets fields do not match the supported schema"
        )
    cover = value.get("cover")
    body = value.get("body")
    if cover is None and body == []:
        return
    if cover is None or not isinstance(body, list) or len(body) != 1:
        raise FinalSchemaError(
            "visual_assets must be empty or contain cover and one body asset"
        )
    article_id = article_id_for(dedupe_key)
    cover_ref = _validate_asset_reference(
        cover,
        asset_id="cover",
        filename="cover.jpg",
        article_id=article_id,
    )
    body_ref = _validate_asset_reference(
        body[0],
        asset_id="body-01",
        filename="body.png",
        article_id=article_id,
    )
    for field in (
        "revision",
        "template",
        "copy_index",
        "ai_generated",
    ):
        if cover_ref[field] != body_ref[field]:
            raise FinalSchemaError(
                "visual_assets references must describe one revision"
            )


def _validate_article_layout_block(value: object, index: int) -> None:
    if not isinstance(value, dict):
        raise FinalSchemaError(
            f"article_layout.blocks[{index}] must be an object"
        )
    block_type = value.get("type")
    if block_type not in _ARTICLE_LAYOUT_BLOCK_TYPES:
        raise FinalSchemaError(
            f"article_layout.blocks[{index}].type is not supported"
        )
    if set(value) != _ARTICLE_LAYOUT_BLOCK_FIELDS[block_type]:
        raise FinalSchemaError(
            f"article_layout.blocks[{index}] fields do not match "
            "the supported schema"
        )

    prefix = f"article_layout.blocks[{index}]"
    if block_type == "hero":
        for field in ("title", "deck"):
            _validate_text(value.get(field), f"{prefix}.{field}")
    elif block_type in {"lead", "key_judgment", "callout"}:
        _validate_text(value.get("text"), f"{prefix}.text")
    elif block_type == "section":
        _validate_text(value.get("heading"), f"{prefix}.heading")
        paragraphs = value.get("paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            raise FinalSchemaError(
                f"{prefix}.paragraphs must be a non-empty list"
            )
        _validate_text_list(paragraphs, f"{prefix}.paragraphs")
    elif block_type == "workflow_compare":
        for field in ("before", "after", "remaining_friction"):
            _validate_text(value.get(field), f"{prefix}.{field}")
    elif block_type == "quote":
        for field in ("text", "attribution"):
            _validate_text(value.get(field), f"{prefix}.{field}")
    elif block_type == "source_note":
        url = _validate_text(value.get("url"), f"{prefix}.url")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise FinalSchemaError(
                f"{prefix}.url must be an absolute HTTPS URL"
            )
        _validate_text(value.get("attribution"), f"{prefix}.attribution")


def _validate_article_layout(value: object) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _ARTICLE_LAYOUT_FIELDS
        or value.get("theme") != "press"
        or not isinstance(value.get("blocks"), list)
    ):
        raise FinalSchemaError(
            "article_layout does not match the supported schema"
        )
    for index, block in enumerate(value["blocks"]):
        _validate_article_layout_block(block, index)


def _is_trusted_legacy_expanded(value: dict[str, Any]) -> bool:
    return (
        value.get("editorial_profile") == legacy_editorial_profile()
        and value.get("visual_brief") is None
        and value.get("visual_assets") == empty_visual_assets()
        and value.get("article_layout") == empty_article_layout()
    )


def normalize_final_payload(
    value: object,
    *,
    allow_legacy_expanded: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalSchemaError("final payload must be an object")

    fields = set(value)
    if fields == CORE_FIELDS:
        is_legacy = True
        normalized = deepcopy(value)
        normalized["editorial_profile"] = legacy_editorial_profile()
        normalized["visual_brief"] = None
        normalized["visual_assets"] = empty_visual_assets()
        normalized["article_layout"] = empty_article_layout()
    elif fields == FINAL_FIELDS - {"article_layout"}:
        normalized = deepcopy(value)
        normalized["article_layout"] = empty_article_layout()
        is_legacy = (
            allow_legacy_expanded
            and _is_trusted_legacy_expanded(normalized)
        )
    elif fields == FINAL_FIELDS:
        is_legacy = (
            allow_legacy_expanded
            and _is_trusted_legacy_expanded(value)
        )
        normalized = deepcopy(value)
    else:
        raise FinalSchemaError(
            "final fields do not match the supported schema"
        )

    _validate_core(normalized)
    _validate_editorial_profile(normalized["editorial_profile"])
    allow_visual_brief_none = (
        is_legacy
        or (
            normalized.get("visual_brief") is None
            and normalized.get("visual_assets") == empty_visual_assets()
            and not _is_trusted_legacy_expanded(normalized)
        )
    )
    normalized["visual_brief"] = _normalize_visual_brief(
        normalized["visual_brief"],
        allow_none=allow_visual_brief_none,
    )
    _validate_visual_assets(
        normalized["visual_assets"],
        dedupe_key=normalized["dedupe_key"],
    )
    _validate_article_layout(normalized["article_layout"])
    return normalized


def coerce_reviewable_final_payload(
    value: object,
    *,
    allow_legacy_expanded: bool = False,
) -> dict[str, Any]:
    """Normalize a final payload, repairing visual-only model mistakes.

    Content quality issues should reach the review desk.  Visual brief shape
    errors should not hide the article either: if a brief can be made renderable
    by trimming extra panels, do that; otherwise keep the article with no visual
    brief and empty assets.
    """

    try:
        return normalize_final_payload(
            value,
            allow_legacy_expanded=allow_legacy_expanded,
        )
    except FinalSchemaError as error:
        if (
            not isinstance(value, dict)
            or set(value) != FINAL_FIELDS
            or value.get("visual_assets") != empty_visual_assets()
            or not (
                error.failure_code
                and error.failure_code.startswith("visual_brief:")
            )
        ):
            raise

    repaired = deepcopy(value)
    repaired["visual_brief"] = coerce_visual_brief(
        repaired.get("visual_brief")
    )
    repaired["visual_assets"] = empty_visual_assets()
    return normalize_final_payload(
        repaired,
        allow_legacy_expanded=allow_legacy_expanded,
    )
