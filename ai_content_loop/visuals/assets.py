from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterator

from PIL import Image, UnidentifiedImageError, __version__ as PILLOW_VERSION
from PIL import features as pillow_features

from ai_content_loop.durability import fsync_directory
from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    article_id_for,
    normalize_final_payload,
)
from ai_content_loop.visuals.renderer import BODY_SIZE, COVER_SIZE
from ai_content_loop.visuals.minimax_image import (
    MiniMaxImageError,
    validate_image_source,
)
from ai_content_loop.visuals.templates import TEMPLATES


MANIFEST_VERSION = 2
AI_MANIFEST_VERSION = 4
RENDER_CONTRACT_VERSION = "content-aware-image-set-v4"
SOURCE_KIND = "original_template"
AI_SOURCE_KIND = "minimax_image_set"
ASSET_FILENAMES = {
    "cover": "cover.jpg",
    "body-01": "body.png",
    "body-02": "body-02.png",
    "body-03": "body-03.png",
}
_ARTICLE_ID_PATTERN = re.compile(r"[0-9a-f]{24}\Z")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = {
    "version",
    "revision",
    "article_id",
    "template",
    "font_sha256",
    "render_contract",
    "source_kind",
    "ai_generated",
    "assets",
}
_AI_MANIFEST_FIELDS = _MANIFEST_FIELDS | {"image_source"}
_FILE_FIELDS = {
    "filename",
    "sha256",
    "size",
    "content_type",
    "format",
    "dimensions",
}
_RENDER_CONTRACT_FIELDS = {
    "renderer_contract_version",
    "pillow_version",
    "jpeg_version",
    "zlib_version",
}
_FILE_EXPECTATIONS = {
    "cover": ("cover.jpg", "JPEG", "image/jpeg", list(COVER_SIZE)),
    "body-01": ("body.png", "PNG", "image/png", list(BODY_SIZE)),
    "body-02": ("body-02.png", "PNG", "image/png", list(BODY_SIZE)),
}


class AssetPublicationError(RuntimeError):
    """A stable asset error that does not expose content or local paths."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def revision_for(
    *,
    template_name: str,
    selected_copy: dict[str, object],
    font_sha256: str,
    render_contract: dict[str, str],
    image_source: dict[str, object] | None = None,
) -> str:
    """Return the content identity shared by publication and validation."""

    identity = {
        "render_contract": render_contract,
        "font_sha256": font_sha256,
        "template": template_name,
        "copy": selected_copy,
    }
    if image_source is not None:
        try:
            identity["image_source"] = validate_image_source(image_source)
        except MiniMaxImageError:
            raise AssetPublicationError("invalid_asset_component") from None
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def current_render_contract() -> dict[str, str]:
    return {
        "renderer_contract_version": RENDER_CONTRACT_VERSION,
        "pillow_version": PILLOW_VERSION,
        "jpeg_version": pillow_features.version("jpg") or "unavailable",
        "zlib_version": pillow_features.version("zlib") or "unavailable",
    }


def font_sha256(path: str | Path) -> str:
    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            raise AssetPublicationError("font_unavailable")
        return file_sha256_and_size(candidate)[0]
    except OSError:
        raise AssetPublicationError("font_unavailable") from None


def inspect_rendered_assets(
    revision_dir: str | Path,
    *,
    mismatch_code: str = "invalid_rendered_asset",
) -> dict[str, dict[str, object]]:
    inspected: dict[str, dict[str, object]] = {}
    for asset_id, (
        filename,
        expected_format,
        content_type,
        expected_dimensions,
    ) in _FILE_EXPECTATIONS.items():
        path = Path(revision_dir) / filename
        if not _regular_file(path):
            raise AssetPublicationError(mismatch_code)
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                actual_format = image.format
                actual_dimensions = list(image.size)
        except (
            Image.DecompressionBombError,
            OSError,
            UnidentifiedImageError,
            ValueError,
        ):
            raise AssetPublicationError(mismatch_code) from None
        if (
            actual_format != expected_format
            or actual_dimensions != expected_dimensions
        ):
            raise AssetPublicationError(mismatch_code)
        inspected[asset_id] = {
            "filename": filename,
            "format": actual_format,
            "content_type": content_type,
            "dimensions": actual_dimensions,
        }
    return inspected


def _absolute_lexical_path(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if ".." in candidate.parts:
        raise AssetPublicationError("invalid_asset_root")
    return candidate


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())
    except OSError:
        raise AssetPublicationError("invalid_asset_root") from None


def validate_output_root(output_dir: str | Path) -> Path:
    """Return an absolute lexical root after rejecting link-like ancestry."""

    root = _absolute_lexical_path(output_dir)
    for component in (root, *root.parents):
        if _is_link_or_junction(component):
            raise AssetPublicationError("invalid_asset_root")
    try:
        if root.exists() and not root.is_dir():
            raise AssetPublicationError("invalid_asset_root")
        root.resolve(strict=False)
    except OSError:
        raise AssetPublicationError("invalid_asset_root") from None
    return root


def validate_output_descendant(
    output_dir: str | Path,
    candidate: str | Path,
) -> Path:
    """Validate a lexical descendant and its resolved containment."""

    root = validate_output_root(output_dir)
    target = _absolute_lexical_path(candidate)
    try:
        target.relative_to(root)
    except ValueError:
        raise AssetPublicationError("invalid_asset_root") from None

    current = target
    while True:
        if _is_link_or_junction(current):
            raise AssetPublicationError("invalid_asset_root")
        if current == root:
            break
        parent = current.parent
        if parent == current:
            raise AssetPublicationError("invalid_asset_root")
        current = parent

    try:
        resolved_root = root.resolve(strict=False)
        resolved_target = target.resolve(strict=False)
        resolved_target.relative_to(resolved_root)
    except (OSError, ValueError):
        raise AssetPublicationError("invalid_asset_root") from None
    return target


def _trusted_article_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or _ARTICLE_ID_PATTERN.fullmatch(value) is None
    ):
        raise AssetPublicationError("invalid_asset_component")
    return value


def _trusted_revision(value: object) -> str:
    if (
        not isinstance(value, str)
        or _REVISION_PATTERN.fullmatch(value) is None
    ):
        raise AssetPublicationError("invalid_asset_component")
    return value


def asset_relative_path(
    article_id: str,
    revision: str,
    asset_id: str,
) -> str:
    """Build a relative POSIX path from validated internal components."""

    trusted_article_id = _trusted_article_id(article_id)
    trusted_revision = _trusted_revision(revision)
    try:
        filename = ASSET_FILENAMES[asset_id]
    except (KeyError, TypeError):
        raise AssetPublicationError("invalid_asset_component") from None
    return (
        f"assets/{trusted_article_id}/{trusted_revision}/{filename}"
    )


def revision_directory(
    output_dir: str | Path,
    article_id: str,
    revision: str,
) -> Path:
    """Build a filesystem revision path without accepting an asset path."""

    return (
        Path(output_dir)
        / "assets"
        / _trusted_article_id(article_id)
        / _trusted_revision(revision)
    )


def asset_path(
    output_dir: str | Path,
    article_id: str,
    revision: str,
    asset_id: str,
) -> Path:
    try:
        filename = ASSET_FILENAMES[asset_id]
    except (KeyError, TypeError):
        raise AssetPublicationError("invalid_asset_component") from None
    return revision_directory(output_dir, article_id, revision) / filename


def atomic_write_bytes(path: Path, data: bytes) -> None:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json_write(path: Path, value: object) -> None:
    atomic_write_bytes(
        Path(path),
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n",
    )


def file_sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def fsync_file(path: Path) -> None:
    # Windows' ``os.fsync`` delegates to ``_commit``, which rejects a
    # read-only descriptor even though POSIX accepts one.  Open the completed
    # render read/write so both platforms can durably flush it without
    # modifying its bytes.
    with Path(path).open("r+b") as handle:
        os.fsync(handle.fileno())


def publish_revision(temporary: Path, final: Path) -> None:
    Path(temporary).rename(Path(final))
    fsync_directory(Path(final).parent)


def manifest_for(
    *,
    revision_dir: Path,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
    font_digest: str,
    render_contract: dict[str, str],
    inspected_assets: dict[str, dict[str, object]],
    image_source: dict[str, object] | None = None,
) -> dict[str, object]:
    if template_name not in TEMPLATES:
        raise AssetPublicationError("invalid_asset_component")
    if type(copy_index) is not int or not 0 <= copy_index <= 2:
        raise AssetPublicationError("invalid_asset_component")
    files: dict[str, object] = {}
    if (
        _HASH_PATTERN.fullmatch(font_digest) is None
        or set(render_contract) != _RENDER_CONTRACT_FIELDS
        or not all(isinstance(value, str) for value in render_contract.values())
    ):
        raise AssetPublicationError("invalid_asset_component")
    for asset_id, metadata in inspected_assets.items():
        filename = metadata["filename"]
        digest, size = file_sha256_and_size(revision_dir / filename)
        files[asset_id] = {
            **metadata,
            "sha256": digest,
            "size": size,
        }
    trusted_image_source = None
    if image_source is not None:
        try:
            trusted_image_source = validate_image_source(image_source)
        except MiniMaxImageError:
            raise AssetPublicationError("invalid_asset_component") from None
    manifest = {
        "version": (
            AI_MANIFEST_VERSION
            if trusted_image_source is not None
            else MANIFEST_VERSION
        ),
        "revision": _trusted_revision(revision),
        "article_id": _trusted_article_id(article_id),
        "template": template_name,
        "font_sha256": font_digest,
        "render_contract": render_contract,
        "source_kind": (
            AI_SOURCE_KIND
            if trusted_image_source is not None
            else SOURCE_KIND
        ),
        "ai_generated": trusted_image_source is not None,
        "assets": files,
    }
    if trusted_image_source is not None:
        manifest["image_source"] = trusted_image_source
    return manifest


def _regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file()
    except OSError:
        return False


def _load_manifest(path: Path) -> dict[str, object]:
    if not _regular_file(path):
        raise AssetPublicationError("existing_revision_mismatch")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise AssetPublicationError("existing_revision_mismatch") from None
    if not isinstance(value, dict):
        raise AssetPublicationError("existing_revision_mismatch")
    return value


def validate_revision(
    *,
    output_dir: str | Path,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
    font_digest: str,
    render_contract: dict[str, str],
    image_source: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate one immutable revision, including exact hashes and sizes."""

    revision_dir = validate_output_descendant(
        output_dir,
        revision_directory(output_dir, article_id, revision),
    )
    article_dir = revision_dir.parent
    assets_dir = article_dir.parent
    if any(
        path.is_symlink()
        for path in (assets_dir, article_dir, revision_dir)
    ) or not revision_dir.is_dir():
        raise AssetPublicationError("existing_revision_mismatch")
    return validate_revision_directory(
        revision_dir=revision_dir,
        article_id=article_id,
        revision=revision,
        template_name=template_name,
        copy_index=copy_index,
        font_digest=font_digest,
        render_contract=render_contract,
        image_source=image_source,
    )


def validate_revision_directory(
    *,
    revision_dir: Path,
    article_id: str,
    revision: str,
    template_name: str,
    copy_index: int,
    font_digest: str,
    render_contract: dict[str, str],
    image_source: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate a final revision or an unpublished sibling directory."""

    _trusted_article_id(article_id)
    _trusted_revision(revision)
    if template_name not in TEMPLATES:
        raise AssetPublicationError("existing_revision_mismatch")
    if type(copy_index) is not int or not 0 <= copy_index <= 2:
        raise AssetPublicationError("existing_revision_mismatch")
    revision_dir = Path(revision_dir)
    if revision_dir.is_symlink() or not revision_dir.is_dir():
        raise AssetPublicationError("existing_revision_mismatch")

    trusted_image_source = None
    if image_source is not None:
        try:
            trusted_image_source = validate_image_source(image_source)
        except MiniMaxImageError:
            raise AssetPublicationError("existing_revision_mismatch") from None
    manifest = _load_manifest(revision_dir / "manifest.json")
    expected_fields = (
        _AI_MANIFEST_FIELDS
        if trusted_image_source is not None
        else _MANIFEST_FIELDS
    )
    expected_version = (
        AI_MANIFEST_VERSION
        if trusted_image_source is not None
        else MANIFEST_VERSION
    )
    expected_source_kind = (
        AI_SOURCE_KIND
        if trusted_image_source is not None
        else SOURCE_KIND
    )
    if (
        set(manifest) != expected_fields
        or manifest.get("version") != expected_version
        or manifest.get("revision") != revision
        or manifest.get("article_id") != article_id
        or manifest.get("template") != template_name
        or manifest.get("font_sha256") != font_digest
        or manifest.get("render_contract") != render_contract
        or manifest.get("source_kind") != expected_source_kind
        or manifest.get("ai_generated")
        is not (trusted_image_source is not None)
        or (
            trusted_image_source is not None
            and manifest.get("image_source") != trusted_image_source
        )
    ):
        raise AssetPublicationError("existing_revision_mismatch")
    files = manifest.get("assets")
    if not isinstance(files, dict) or set(files) != set(_FILE_EXPECTATIONS):
        raise AssetPublicationError("existing_revision_mismatch")
    expected_names = {"manifest.json"}
    inspected = inspect_rendered_assets(
        revision_dir,
        mismatch_code="existing_revision_mismatch",
    )
    for asset_id, (
        filename,
        expected_format,
        content_type,
        dimensions,
    ) in _FILE_EXPECTATIONS.items():
        expected_names.add(filename)
        metadata = files.get(asset_id)
        if (
            not isinstance(metadata, dict)
            or set(metadata) != _FILE_FIELDS
            or metadata.get("filename") != filename
            or metadata.get("format") != expected_format
            or metadata.get("content_type") != content_type
            or metadata.get("dimensions") != dimensions
            or metadata.get("format") != inspected[asset_id]["format"]
            or metadata.get("dimensions")
            != inspected[asset_id]["dimensions"]
            or type(metadata.get("size")) is not int
            or metadata["size"] <= 0
            or not isinstance(metadata.get("sha256"), str)
            or _HASH_PATTERN.fullmatch(metadata["sha256"]) is None
        ):
            raise AssetPublicationError("existing_revision_mismatch")
        file_path = revision_dir / filename
        if not _regular_file(file_path):
            raise AssetPublicationError("existing_revision_mismatch")
        try:
            actual_hash, actual_size = file_sha256_and_size(file_path)
        except OSError:
            raise AssetPublicationError(
                "existing_revision_mismatch"
            ) from None
        if (
            actual_size != metadata["size"]
            or not hmac.compare_digest(actual_hash, metadata["sha256"])
        ):
            raise AssetPublicationError("existing_revision_mismatch")
    try:
        actual_names = {path.name for path in revision_dir.iterdir()}
    except OSError:
        raise AssetPublicationError("existing_revision_mismatch") from None
    if actual_names != expected_names:
        raise AssetPublicationError("existing_revision_mismatch")
    return manifest


def validate_payload_revision(
    payload: object,
    output_dir: str | Path,
    font_path: str | Path,
    image_source: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        normalized = normalize_final_payload(payload)
    except FinalSchemaError:
        raise AssetPublicationError("invalid_asset_references") from None
    assets = normalized["visual_assets"]
    cover = assets["cover"]
    if cover is None:
        raise AssetPublicationError("invalid_asset_references")
    visual_brief = normalized["visual_brief"]
    references = [cover, *assets["body"]]
    if any(reference["ai_generated"] for reference in references) is not (
        image_source is not None
    ):
        raise AssetPublicationError("asset_source_mismatch")
    copy_index = cover["copy_index"]
    if copy_index == 0:
        selected_copy = {
            field: visual_brief[field]
            for field in ("cover_line", "cover_subline", "body_panels")
        }
    else:
        selected_copy = visual_brief["alternatives"][copy_index - 1]
    font_digest = font_sha256(font_path)
    render_contract = current_render_contract()
    expected_revision = revision_for(
        template_name=cover["template"],
        selected_copy=selected_copy,
        font_sha256=font_digest,
        render_contract=render_contract,
        image_source=image_source,
    )
    if not hmac.compare_digest(expected_revision, cover["revision"]):
        raise AssetPublicationError("asset_identity_mismatch")
    article_id = article_id_for(normalized["dedupe_key"])
    return validate_revision(
        output_dir=output_dir,
        article_id=article_id,
        revision=cover["revision"],
        template_name=cover["template"],
        copy_index=copy_index,
        font_digest=font_digest,
        render_contract=render_contract,
        image_source=image_source,
    )


@contextmanager
def temporary_revision_directory(
    output_dir: str | Path,
    article_id: str,
    revision: str,
) -> Iterator[Path]:
    final_dir = validate_output_descendant(
        output_dir,
        revision_directory(output_dir, article_id, revision),
    )
    article_dir = final_dir.parent
    article_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{revision}.",
            suffix=".tmp",
            dir=article_dir,
        )
    )
    try:
        yield temporary
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
