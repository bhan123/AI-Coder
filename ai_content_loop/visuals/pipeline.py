from __future__ import annotations

from copy import deepcopy
import hmac
import json
from pathlib import Path
from typing import Any

from ai_content_loop.article_lock import ArticleLockError, article_lock
from ai_content_loop.editorial.schema import (
    FINAL_FIELDS,
    FinalSchemaError,
    article_id_for,
    normalize_final_payload,
    payload_version,
)
from ai_content_loop.visuals.assets import (
    AssetPublicationError,
    asset_relative_path,
    atomic_json_write,
    current_render_contract,
    font_sha256,
    fsync_file,
    inspect_rendered_assets,
    manifest_for,
    publish_revision,
    revision_for,
    revision_directory,
    temporary_revision_directory,
    validate_output_descendant,
    validate_output_root,
    validate_revision,
    validate_revision_directory,
)
from ai_content_loop.visuals.renderer import (
    VisualRenderError,
    render_visuals,
)
from ai_content_loop.visuals.templates import TEMPLATES, select_template


BODY_ASSET_MARKER = "{{asset:body-01}}"
SOURCE_MARKER = "来源："


def _without_body_markers(markdown: str) -> list[str]:
    lines: list[str] = []
    for line in markdown.splitlines():
        if BODY_ASSET_MARKER not in line:
            lines.append(line)
            continue
        cleaned = line.replace(BODY_ASSET_MARKER, "")
        if cleaned.strip():
            lines.append(cleaned)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def insert_body_asset_marker(payload: object) -> dict[str, Any]:
    """Return an unaliased payload with one WeChat body marker.

    The deterministic fallback, used when no source line exists, appends the
    marker after the article copy with one blank line separating it.
    """

    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    result = deepcopy(payload)
    platforms = result.get("platform_markdown")
    if not isinstance(platforms, dict):
        raise ValueError("platform_markdown must be an object")
    wechat = platforms.get("wechat")
    if not isinstance(wechat, str) or not wechat.strip():
        raise ValueError("wechat markdown must be a non-empty string")

    lines = _without_body_markers(wechat)
    source_index = next(
        (
            index
            for index, line in enumerate(lines)
            if SOURCE_MARKER in line
        ),
        None,
    )
    if source_index is None:
        body = "\n".join(lines).rstrip()
        platforms["wechat"] = f"{body}\n\n{BODY_ASSET_MARKER}"
    else:
        lines.insert(source_index, BODY_ASSET_MARKER)
        platforms["wechat"] = "\n".join(lines)
    return result


def has_canonical_body_asset_marker(payload: object) -> bool:
    """Return whether WeChat has exactly the canonical body marker layout."""

    if not isinstance(payload, dict):
        return False
    platforms = payload.get("platform_markdown")
    if not isinstance(platforms, dict):
        return False
    wechat = platforms.get("wechat")
    if not isinstance(wechat, str):
        return False
    try:
        canonical = insert_body_asset_marker(payload)
    except ValueError:
        return False
    return (
        wechat.count(BODY_ASSET_MARKER) == 1
        and canonical["platform_markdown"]["wechat"] == wechat
    )


def _selected_copy(
    visual_brief: dict[str, object],
    copy_index: int,
) -> dict[str, object]:
    if type(copy_index) is not int or not 0 <= copy_index <= 2:
        raise ValueError("copy_index must be an integer from 0 to 2")
    if copy_index == 0:
        return {
            "cover_line": deepcopy(visual_brief["cover_line"]),
            "cover_subline": deepcopy(visual_brief["cover_subline"]),
            "body_panels": deepcopy(visual_brief["body_panels"]),
        }
    return deepcopy(visual_brief["alternatives"][copy_index - 1])


def _template_for(
    *,
    dedupe_key: str,
    hint: str,
    template_name: object,
):
    if template_name is None:
        return select_template(dedupe_key, hint)
    if (
        not isinstance(template_name, str)
        or template_name not in TEMPLATES
    ):
        raise ValueError("template must be a canonical template name")
    return TEMPLATES[template_name]


def _revision_for(
    *,
    template_name: str,
    selected_copy: dict[str, object],
    font_digest: str,
    render_contract: dict[str, str],
) -> str:
    return revision_for(
        template_name=template_name,
        selected_copy=selected_copy,
        font_sha256=font_digest,
        render_contract=render_contract,
    )


def _renderer_brief(
    visual_brief: dict[str, object],
    selected_copy: dict[str, object],
) -> dict[str, object]:
    brief = deepcopy(visual_brief)
    for field in ("cover_line", "cover_subline", "body_panels"):
        brief[field] = deepcopy(selected_copy[field])
    return brief


def _asset_reference(
    *,
    asset_id: str,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "revision": revision,
        "path": asset_relative_path(article_id, revision, asset_id),
        "template": template_name,
        "copy_index": copy_index,
        "ai_generated": False,
    }


def _result_payload(
    normalized: dict[str, Any],
    *,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
) -> dict[str, Any]:
    result = insert_body_asset_marker(normalized)
    result["visual_assets"] = {
        "cover": _asset_reference(
            asset_id="cover",
            article_id=article_id,
            revision=revision,
            template_name=template_name,
            copy_index=copy_index,
        ),
        "body": [
            _asset_reference(
                asset_id="body-01",
                article_id=article_id,
                revision=revision,
                template_name=template_name,
                copy_index=copy_index,
            )
        ],
    }
    return normalize_final_payload(result)


def _strict_current_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != FINAL_FIELDS:
        raise FinalSchemaError("current final payload is required")
    normalized = normalize_final_payload(payload)
    if normalized["visual_brief"] is None:
        raise FinalSchemaError("current visual_brief is required")
    return normalized


def generate_visual_assets(
    *,
    payload: object,
    output_dir: str | Path,
    font_path: str | Path,
    template_name: str | None = None,
    copy_index: int = 0,
) -> dict[str, Any]:
    """Render and atomically publish one immutable asset revision."""

    normalized = _strict_current_payload(payload)
    selected_copy = _selected_copy(
        normalized["visual_brief"],
        copy_index,
    )
    template = _template_for(
        dedupe_key=normalized["dedupe_key"],
        hint=normalized["visual_brief"]["template_hint"],
        template_name=template_name,
    )
    article_id = article_id_for(normalized["dedupe_key"])
    font_digest = font_sha256(font_path)
    render_contract = current_render_contract()
    revision = _revision_for(
        template_name=template.name,
        selected_copy=selected_copy,
        font_digest=font_digest,
        render_contract=render_contract,
    )
    result = _result_payload(
        normalized,
        article_id=article_id,
        revision=revision,
        template_name=template.name,
        copy_index=copy_index,
    )
    trusted_output_dir = validate_output_root(output_dir)
    final_dir = validate_output_descendant(
        trusted_output_dir,
        revision_directory(trusted_output_dir, article_id, revision),
    )
    if (
        final_dir.exists()
        or final_dir.is_symlink()
        or (
            getattr(final_dir, "is_junction", None) is not None
            and final_dir.is_junction()
        )
    ):
        validate_revision(
            output_dir=trusted_output_dir,
            article_id=article_id,
            revision=revision,
            template_name=template.name,
            copy_index=copy_index,
            font_digest=font_digest,
            render_contract=render_contract,
        )
        return result

    with temporary_revision_directory(
        trusted_output_dir,
        article_id,
        revision,
    ) as temporary:
        cover_path = temporary / "cover.jpg"
        body_path = temporary / "body.png"
        render_visuals(
            brief=_renderer_brief(
                normalized["visual_brief"],
                selected_copy,
            ),
            template=template,
            font_path=Path(font_path),
            cover_path=cover_path,
            body_path=body_path,
        )
        for rendered_path in (cover_path, body_path):
            if rendered_path.is_symlink() or not rendered_path.is_file():
                raise AssetPublicationError("invalid_rendered_asset")
            fsync_file(rendered_path)
        inspected_assets = inspect_rendered_assets(temporary)
        manifest = manifest_for(
            revision_dir=temporary,
            article_id=article_id,
            revision=revision,
            template_name=template.name,
            copy_index=copy_index,
            font_digest=font_digest,
            render_contract=render_contract,
            inspected_assets=inspected_assets,
        )
        atomic_json_write(temporary / "manifest.json", manifest)
        validate_revision_directory(
            revision_dir=temporary,
            article_id=article_id,
            revision=revision,
            template_name=template.name,
            copy_index=copy_index,
            font_digest=font_digest,
            render_contract=render_contract,
        )
        try:
            publish_revision(temporary, final_dir)
        except OSError:
            if final_dir.exists() or final_dir.is_symlink():
                validate_revision(
                    output_dir=output_dir,
                    article_id=article_id,
                    revision=revision,
                    template_name=template.name,
                    copy_index=copy_index,
                    font_digest=font_digest,
                    render_contract=render_contract,
                )
                return result
            raise AssetPublicationError(
                "revision_publication_failed"
            ) from None
    return result


def _safe_final_path(
    final_path: str | Path,
    output_dir: str | Path,
) -> Path:
    candidate = Path(final_path)
    trusted_output_dir = validate_output_root(output_dir)
    try:
        final_directory = validate_output_descendant(
            trusted_output_dir,
            trusted_output_dir / "final",
        )
        if (
            final_directory.is_symlink()
            or (
                getattr(final_directory, "is_junction", None) is not None
                and final_directory.is_junction()
            )
            or not final_directory.is_dir()
            or candidate.suffix.lower() != ".json"
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            raise ValueError
        expected_parent = final_directory.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        if resolved.parent != expected_parent:
            raise ValueError
    except (
        AssetPublicationError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        raise ValueError("final_path must be a safe final JSON file") from None
    return resolved


def generate_visual_assets_for_file(
    *,
    final_path: str | Path,
    output_dir: str | Path,
    font_path: str | Path,
    template_name: str | None = None,
    copy_index: int = 0,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Publish assets, then atomically replace a validated final JSON file."""

    safe_path = _safe_final_path(final_path, output_dir)
    preliminary = safe_path.read_bytes()
    try:
        preliminary_payload = _strict_current_payload(
            json.loads(preliminary.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("final_path must contain valid JSON") from None
    article_id = article_id_for(preliminary_payload["dedupe_key"])
    try:
        with article_lock(output_dir=output_dir, article_id=article_id):
            original = safe_path.read_bytes()
            payload = _strict_current_payload(
                json.loads(original.decode("utf-8"))
            )
            if article_id_for(payload["dedupe_key"]) != article_id:
                raise AssetPublicationError("article_conflict")
            captured_version = payload_version(payload)
            if (
                expected_version is not None
                and (
                    not isinstance(expected_version, str)
                    or not hmac.compare_digest(
                        captured_version,
                        expected_version,
                    )
                )
            ):
                raise AssetPublicationError("article_conflict")
    except ArticleLockError as error:
        raise AssetPublicationError(error.code) from None
    result = generate_visual_assets(
        payload=payload,
        output_dir=output_dir,
        font_path=font_path,
        template_name=template_name,
        copy_index=copy_index,
    )
    try:
        with article_lock(output_dir=output_dir, article_id=article_id):
            current_bytes = safe_path.read_bytes()
            try:
                current = _strict_current_payload(
                    json.loads(current_bytes.decode("utf-8"))
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise AssetPublicationError("article_conflict") from None
            if (
                current_bytes != original
                or not hmac.compare_digest(
                    payload_version(current),
                    captured_version,
                )
            ):
                raise AssetPublicationError("article_conflict")
            atomic_json_write(safe_path, result)
    except ArticleLockError as error:
        raise AssetPublicationError(error.code) from None
    return result
