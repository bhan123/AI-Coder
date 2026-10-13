from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any

from engine.article_lock import ArticleLockError, article_lock
from engine.editorial.schema import (
    FINAL_FIELDS,
    FinalSchemaError,
    article_id_for,
    normalize_final_payload,
    payload_version,
)
from engine.visuals.assets import (
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
from engine.visuals.renderer import (
    VisualRenderError,
    render_visuals,
)
from engine.visuals.minimax_image import (
    MiniMaxImageClient,
    MiniMaxImageError,
    build_body_prompt,
    build_cover_prompt,
    prepare_body_image,
    prepare_cover_background,
)
from engine.visuals.prompting import plan_illustration
from engine.pack import active_pack
from engine.visuals.templates import select_template


BODY_ASSET_IDS = ("body-01", "body-02")
BODY_ASSET_MARKER = "{{asset:body-01}}"
_BODY_MARKER_PATTERN = re.compile(r"\{\{asset:(body-\d{2})\}\}")


def _image_aspect_ratio(asset_id: str) -> str:
    return "21:9" if asset_id == "cover" else "16:9"


def _close_prepared_images(images: dict[str, Any]) -> None:
    for image in images.values():
        if image is not None:
            image.close()
SOURCE_MARKER = "来源："


def _without_body_markers(markdown: str) -> list[str]:
    lines: list[str] = []
    for line in markdown.splitlines():
        if _BODY_MARKER_PATTERN.search(line) is None:
            lines.append(line)
            continue
        cleaned = _BODY_MARKER_PATTERN.sub("", line)
        if cleaned.strip():
            lines.append(cleaned)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _expected_body_asset_ids(payload: object) -> tuple[str, ...]:
    if isinstance(payload, dict):
        assets = payload.get("visual_assets")
        body = assets.get("body") if isinstance(assets, dict) else None
        if isinstance(body, list) and body:
            ids = tuple(
                str(item.get("asset_id"))
                for item in body
                if isinstance(item, dict)
                and _BODY_MARKER_PATTERN.fullmatch(
                    f"{{{{asset:{item.get('asset_id')}}}}}"
                )
            )
            if len(ids) == len(body):
                return ids
    return BODY_ASSET_IDS


def insert_body_asset_marker(payload: object) -> dict[str, Any]:
    """Return an unaliased payload with distributed WeChat body markers.

    Existing one-image articles remain canonical. New empty payloads receive
    the current two-image contract, with one image around the middle and the
    other before the source note/end.
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
    asset_ids = _expected_body_asset_ids(result)
    source_index = next(
        (
            index
            for index, line in enumerate(lines)
            if SOURCE_MARKER in line
        ),
        None,
    )
    content_end = source_index if source_index is not None else len(lines)
    if len(asset_ids) == 1:
        positions = (content_end,)
    else:
        positions = tuple(
            max(
                1,
                (
                    content_end * (index + 1)
                    + len(asset_ids)
                    - 1
                )
                // len(asset_ids),
            )
            for index in range(len(asset_ids))
        )
    for position, asset_id in reversed(tuple(zip(positions, asset_ids))):
        lines.insert(position, f"{{{{asset:{asset_id}}}}}")
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
    expected = _expected_body_asset_ids(payload)
    present = tuple(_BODY_MARKER_PATTERN.findall(wechat))
    return present == expected and canonical["platform_markdown"]["wechat"] == wechat


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
    pack = active_pack()
    if template_name is None:
        return select_template(dedupe_key, hint, pack)
    if not isinstance(template_name, str) or template_name not in pack.visual_templates:
        raise ValueError("template must be a canonical template name")
    return pack.visual_templates[template_name]


def _revision_for(
    *,
    template_name: str,
    selected_copy: dict[str, object],
    font_digest: str,
    render_contract: dict[str, str],
    image_source: dict[str, object] | None = None,
) -> str:
    return revision_for(
        template_name=template_name,
        selected_copy=selected_copy,
        font_sha256=font_digest,
        render_contract=render_contract,
        image_source=image_source,
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
    ai_generated: bool,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "revision": revision,
        "path": asset_relative_path(article_id, revision, asset_id),
        "template": template_name,
        "copy_index": copy_index,
        "ai_generated": ai_generated,
    }


def _result_payload(
    normalized: dict[str, Any],
    *,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
    ai_generated_assets: set[str],
) -> dict[str, Any]:
    result = deepcopy(normalized)
    result["visual_assets"] = {
        "cover": _asset_reference(
            asset_id="cover",
            article_id=article_id,
            revision=revision,
            template_name=template_name,
            copy_index=copy_index,
            ai_generated="cover" in ai_generated_assets,
        ),
        "body": [
            _asset_reference(
                asset_id=asset_id,
                article_id=article_id,
                revision=revision,
                template_name=template_name,
                copy_index=copy_index,
                ai_generated=asset_id in ai_generated_assets,
            )
            for asset_id in BODY_ASSET_IDS
        ],
    }
    result = insert_body_asset_marker(result)
    return normalize_final_payload(result)


def _image_prompts(
    brief: dict[str, object],
    article_layout: object,
) -> dict[str, str]:
    return {
        "cover": build_cover_prompt(
            brief,
            article_layout=article_layout,
        ),
        **{
            asset_id: build_body_prompt(
                brief,
                panel_index=index,
                article_layout=article_layout,
            )
            for index, asset_id in enumerate(BODY_ASSET_IDS)
        },
    }


def _image_set_identity(
    image_client: MiniMaxImageClient,
    prompts: dict[str, str],
    asset_ids: set[str],
) -> dict[str, object] | None:
    if not asset_ids:
        return None
    identities = {
        asset_id: image_client.identity_for_prompt(
            prompts[asset_id],
            aspect_ratio=_image_aspect_ratio(asset_id),
        )
        for asset_id in sorted(asset_ids)
    }
    encoded = json.dumps(
        identities,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "provider": "minimax",
        "model": "image-01",
        "prompt_sha256": digest,
        "seed": int(digest[:16], 16) & ((1 << 63) - 1),
    }


def expected_image_source(
    *,
    payload: object,
    image_client: MiniMaxImageClient | None,
    copy_index: int,
) -> dict[str, object] | None:
    if image_client is None:
        return None
    normalized = _strict_current_payload(payload)
    selected_copy = _selected_copy(normalized["visual_brief"], copy_index)
    prompts = _image_prompts(
        _renderer_brief(normalized["visual_brief"], selected_copy),
        normalized["article_layout"],
    )
    assets = normalized["visual_assets"]
    if assets["cover"] is None:
        generated_assets = set(prompts)
    else:
        references = [assets["cover"], *assets["body"]]
        generated_assets = {
            reference["asset_id"]
            for reference in references
            if reference["ai_generated"]
        }
    return _image_set_identity(image_client, prompts, generated_assets)


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
    image_client: MiniMaxImageClient | None = None,
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
    renderer_brief = _renderer_brief(
        normalized["visual_brief"], selected_copy
    )
    illustration_plan = plan_illustration(
        renderer_brief,
        article_layout=normalized["article_layout"],
    )
    prompts: dict[str, str] = {}
    desired_generated_assets: set[str] = set()
    desired_image_source = None
    if image_client is not None:
        prompts = _image_prompts(
            renderer_brief,
            normalized["article_layout"],
        )
        desired_generated_assets = set(prompts)
        desired_image_source = _image_set_identity(
            image_client,
            prompts,
            desired_generated_assets,
        )
    revision = _revision_for(
        template_name=template.name,
        selected_copy=selected_copy,
        font_digest=font_digest,
        render_contract=render_contract,
        image_source=desired_image_source,
    )
    result = _result_payload(
        normalized,
        article_id=article_id,
        revision=revision,
        template_name=template.name,
        copy_index=copy_index,
        ai_generated_assets=desired_generated_assets,
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
            image_source=desired_image_source,
        )
        return result

    prepared_images: dict[str, Any] = {
        "cover": None,
        "body-01": None,
        "body-02": None,
    }
    generated_assets: set[str] = set()
    if image_client is not None:
        for asset_id, prompt in prompts.items():
            try:
                raw = image_client.generate(
                    prompt,
                    aspect_ratio=_image_aspect_ratio(asset_id),
                )
                prepared_images[asset_id] = (
                    prepare_cover_background(raw)
                    if asset_id == "cover"
                    else prepare_body_image(raw)
                )
                generated_assets.add(asset_id)
            except MiniMaxImageError:
                continue

    image_source = (
        _image_set_identity(image_client, prompts, generated_assets)
        if image_client is not None
        else None
    )
    if generated_assets != desired_generated_assets:
        revision = _revision_for(
            template_name=template.name,
            selected_copy=selected_copy,
            font_digest=font_digest,
            render_contract=render_contract,
            image_source=image_source,
        )
        result = _result_payload(
            normalized,
            article_id=article_id,
            revision=revision,
            template_name=template.name,
            copy_index=copy_index,
            ai_generated_assets=generated_assets,
        )
        final_dir = validate_output_descendant(
            trusted_output_dir,
            revision_directory(trusted_output_dir, article_id, revision),
        )
        if final_dir.exists() or final_dir.is_symlink():
            try:
                validate_revision(
                    output_dir=trusted_output_dir,
                    article_id=article_id,
                    revision=revision,
                    template_name=template.name,
                    copy_index=copy_index,
                    font_digest=font_digest,
                    render_contract=render_contract,
                    image_source=image_source,
                )
                return result
            finally:
                _close_prepared_images(prepared_images)

    try:
        with temporary_revision_directory(
            trusted_output_dir,
            article_id,
            revision,
        ) as temporary:
            cover_path = temporary / "cover.jpg"
            body_path = temporary / "body.png"
            secondary_body_path = temporary / "body-02.png"
            render_visuals(
                brief=renderer_brief,
                template=template,
                font_path=Path(font_path),
                cover_path=cover_path,
                body_path=body_path,
                secondary_body_path=secondary_body_path,
                cover_background=prepared_images["cover"],
                body_backgrounds=(
                    prepared_images["body-01"],
                    prepared_images["body-02"],
                ),
                illustration_structure=illustration_plan.structure,
            )
            for rendered_path in (
                cover_path,
                body_path,
                secondary_body_path,
            ):
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
                image_source=image_source,
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
                image_source=image_source,
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
                        image_source=image_source,
                    )
                    return result
                raise AssetPublicationError(
                    "revision_publication_failed"
                ) from None
        return result
    finally:
        _close_prepared_images(prepared_images)


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
    image_client: MiniMaxImageClient | None = None,
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
        image_client=image_client,
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
