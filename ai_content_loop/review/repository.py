from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from ai_content_loop.article_lock import article_lock
from ai_content_loop.db import ContentStore
from ai_content_loop.durability import fsync_directory
from ai_content_loop.editorial.quality import evaluate_editorial_voice
from ai_content_loop.editorial.schema import (
    CORE_FIELDS,
    FinalSchemaError,
    article_id_for,
    coerce_reviewable_final_payload,
    empty_visual_assets,
    legacy_editorial_profile,
    normalize_final_payload,
    payload_version,
)
from ai_content_loop.generation import validate_generation_payload
from ai_content_loop.gpt_polish import (
    GptPolishProposalError,
    candidate_payload,
)
from ai_content_loop.editorial.reader_feedback import evaluate_reader_feedback
from ai_content_loop.visuals.pipeline import (
    has_canonical_body_asset_marker,
)
from ai_content_loop.review.web_edition import (
    atomic_write_web_edition,
    render_web_edition,
)
from ai_content_loop.wechat.client import WechatApiError, WechatClient
from ai_content_loop.wechat.rendering import render_wechat_article


class ArticleNotFound(KeyError):
    """The requested opaque article or history identifier does not exist."""


class ArticleConflict(RuntimeError):
    """The article changed after the browser loaded its version."""


class InvalidArticle(ValueError):
    """The submitted article does not match the final article schema."""


class WechatDraftResultUnknown(RuntimeError):
    """WeChat may have accepted the draft, so an automatic retry is unsafe."""


_APPROVAL_FAILURE_LABELS = {
    "missing_cover_asset": "缺少封面图",
    "missing_body_asset": "缺少正文配图",
    "missing_body_asset_marker": "正文未插入配图标记",
    "missing_cover_file": "找不到封面图片文件",
    "missing_body_file": "找不到正文图片文件",
    "missing_source_metadata": "缺少来源信息",
    "article_layout:unsafe_plain_text": "富阅读布局包含不支持的文本字符",
}
_VISUAL_APPROVAL_FAILURES = {
    "missing_cover_asset",
    "missing_body_asset",
    "missing_body_asset_marker",
    "missing_cover_file",
    "missing_body_file",
}


def _version(payload: dict[str, object]) -> str:
    return payload_version(payload)


def _date_part(value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    date = value[:10]
    if len(date) == 10 and date[4] == "-" and date[7] == "-":
        return date
    return None


def _atomic_json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_payload(
    value: object,
    *,
    expected_dedupe_key: str | None = None,
    allow_legacy_expanded: bool = False,
) -> dict[str, Any]:
    if (
        not allow_legacy_expanded
        and isinstance(value, dict)
        and isinstance(value.get("editorial_profile"), dict)
        and value["editorial_profile"].get("version") == "legacy"
    ):
        raise InvalidArticle("current article cannot forge legacy schema")
    try:
        payload = coerce_reviewable_final_payload(
            value,
            allow_legacy_expanded=allow_legacy_expanded,
        )
    except FinalSchemaError as error:
        raise InvalidArticle(str(error)) from error

    if expected_dedupe_key is not None and payload["dedupe_key"] != expected_dedupe_key:
        raise InvalidArticle("dedupe_key cannot be changed")
    return payload


def _is_legacy_expanded(payload: dict[str, Any]) -> bool:
    return (
        payload.get("editorial_profile") == legacy_editorial_profile()
        and payload.get("visual_brief") is None
        and payload.get("visual_assets") == empty_visual_assets()
    )


class ArticleRepository:
    def __init__(
        self,
        *,
        store: ContentStore,
        final_dir: Path,
        history_dir: Path,
        assets_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.final_dir = Path(final_dir)
        self.history_dir = Path(history_dir)
        self.output_dir = self.final_dir.parent
        self.assets_dir = (
            Path(assets_dir) if assets_dir is not None else self.output_dir / "assets"
        )
        self._write_lock = threading.RLock()

    def _scan(self) -> dict[str, tuple[Path, dict[str, Any]]]:
        articles: dict[str, tuple[Path, dict[str, Any]]] = {}
        if not self.final_dir.exists():
            return articles
        for path in sorted(self.final_dir.glob("*.json")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                payload = _validate_payload(
                    value,
                    allow_legacy_expanded=True,
                )
            except (OSError, json.JSONDecodeError, InvalidArticle):
                continue
            articles[article_id_for(payload["dedupe_key"])] = (path, payload)
        return articles

    def _find(self, article_id: str) -> tuple[Path, dict[str, Any]]:
        if not isinstance(article_id, str):
            raise ArticleNotFound(article_id)
        found = self._scan().get(article_id)
        if found is None:
            raise ArticleNotFound(article_id)
        return found

    def _warnings(self, payload: dict[str, Any]) -> list[str]:
        warnings: list[str] = []

        def add_warning(warning: str) -> None:
            if warning not in warnings:
                warnings.append(warning)

        source_url = self.store.get_source_url(payload["dedupe_key"])
        if source_url is None:
            add_warning("missing_source_metadata")
        else:
            is_legacy = payload["editorial_profile"] == legacy_editorial_profile()
            hard, style_warnings = validate_generation_payload(
                payload,
                dedupe_key=payload["dedupe_key"],
                source_url=source_url,
            )
            for warning in hard + style_warnings:
                if is_legacy and warning == "visual_brief:root":
                    continue
                if warning == "nonempty_visual_assets":
                    continue
                add_warning(warning)
        # quality_warnings stored inside the payload itself (style warnings
        # from the generation layer and any legacy markers) are surfaced
        # so the review desk can display all of them.
        for warning in payload["editorial_profile"]["quality_warnings"]:
            add_warning(warning)
        return warnings

    def list_articles(
        self,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        queue = {
            row["dedupe_key"]: row
            for row in self.store.list_publish_queue(status=status)
        }
        rows: list[dict[str, object]] = []
        for article_id, (_, payload) in self._scan().items():
            queue_row = queue.get(payload["dedupe_key"])
            if status is not None and queue_row is None:
                continue
            version = _version(payload)
            gpt_polish = self.store.latest_gpt_polish_job(
                payload["dedupe_key"]
            )
            wechat_draft = self.store.get_wechat_draft_sync(
                payload["dedupe_key"], version
            )
            rows.append(
                {
                    "article_id": article_id,
                    "dedupe_key": payload["dedupe_key"],
                    "title": payload["master_title"],
                    "column": payload["column"],
                    "status": (
                        queue_row["status"] if queue_row is not None else "untracked"
                    ),
                    "created_at": (
                        queue_row["created_at"] if queue_row is not None else None
                    ),
                    "generated_date": _date_part(
                        queue_row["created_at"] if queue_row is not None else None
                    ),
                    "gpt_polish_status": (
                        gpt_polish["status"] if gpt_polish is not None else None
                    ),
                    "wechat_draft_status": (
                        wechat_draft["status"]
                        if wechat_draft is not None
                        else "not_synced"
                    ),
                }
            )
        rows.sort(
            key=lambda row: str(row["created_at"] or ""),
            reverse=True,
        )
        return rows

    def load_article(self, article_id: str) -> dict[str, object]:
        _, payload = self._find(article_id)
        return {
            "article_id": article_id,
            "payload": payload,
            "version": _version(payload),
            "warnings": self._warnings(payload),
        }

    def _asset_references(
        self,
        article_id: str,
    ) -> list[dict[str, object]]:
        _, payload = self._find(article_id)
        assets = payload["visual_assets"]
        references: list[dict[str, object]] = []
        cover = assets["cover"]
        if isinstance(cover, dict):
            references.append(cover)
        body = assets["body"]
        if isinstance(body, list):
            references.extend(item for item in body if isinstance(item, dict))
        return references

    def asset_references(
        self,
        article_id: str,
    ) -> dict[str, dict[str, object]]:
        return {
            str(reference["asset_id"]): dict(reference)
            for reference in self._asset_references(article_id)
        }

    def asset_path(
        self,
        article_id: str,
        asset_id: str,
        revision: str,
    ) -> Path:
        match = next(
            (
                reference
                for reference in self._asset_references(article_id)
                if reference["asset_id"] == asset_id
                and reference["revision"] == revision
            ),
            None,
        )
        if match is None:
            raise ArticleNotFound(asset_id)
        try:
            assets_root = self.assets_dir.resolve(strict=True)
            candidate = (self.output_dir / str(match["path"])).resolve(strict=True)
            candidate.relative_to(assets_root)
            relative = candidate.relative_to(assets_root)
            current = assets_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError
            if not candidate.is_file():
                raise ValueError
        except (OSError, RuntimeError, ValueError):
            raise ArticleNotFound(asset_id) from None
        return candidate

    def save_article(
        self,
        article_id: str,
        payload: object,
        expected_version: str,
        *,
        operation: str,
    ) -> dict[str, object]:
        with self._write_lock:
            with article_lock(
                output_dir=self.final_dir.parent,
                article_id=article_id,
            ):
                if operation not in {"edit", "restore", "visual_edit", "gpt_polish"}:
                    raise ValueError(f"unsupported history operation: {operation}")
                path, current = self._find(article_id)
                current_version = _version(current)
                if not isinstance(expected_version, str) or not hmac.compare_digest(
                    current_version,
                    expected_version,
                ):
                    raise ArticleConflict(article_id)

                current_is_legacy = _is_legacy_expanded(current)
                if (
                    operation == "edit"
                    and not current_is_legacy
                    and isinstance(payload, dict)
                    and set(payload) == CORE_FIELDS
                ):
                    raise InvalidArticle("current article cannot use legacy schema")

                replacement = _validate_payload(
                    payload,
                    expected_dedupe_key=current["dedupe_key"],
                    allow_legacy_expanded=(operation == "restore" or current_is_legacy),
                )
                now = datetime.now(UTC)
                history_id = (
                    f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-"
                    f"{operation}-{current_version[:12]}.json"
                )
                envelope = {
                    "metadata": {
                        "saved_at": now.isoformat(),
                        "operation": operation,
                        "version": current_version,
                    },
                    "payload": current,
                }
                _atomic_json_write(
                    self.history_dir / article_id / history_id,
                    envelope,
                )
                # Revoke the export before replacing final JSON.  This closes
                # the restore-to-an-old-hash window: a concurrent GET sees
                # either no export metadata or the unchanged prior article.
                # If the final write fails, failing closed is intentional.
                self.store.invalidate_web_edition_after_article_change(
                    current["dedupe_key"]
                )
                _atomic_json_write(path, replacement)
                return self.load_article(article_id)

    def request_gpt_polish(
        self,
        article_id: str,
        expected_version: str,
    ) -> dict[str, Any]:
        _, payload = self._find(article_id)
        current_version = _version(payload)
        if not isinstance(expected_version, str) or not hmac.compare_digest(
            current_version, expected_version
        ):
            raise ArticleConflict(article_id)
        source_url = self.store.get_source_url(payload["dedupe_key"])
        if source_url is None:
            raise InvalidArticle("missing source metadata")
        request = {
            "article_id": article_id,
            "base_version": current_version,
            "source_url": source_url,
            "master_title": payload["master_title"],
            "master_markdown": payload["master_markdown"],
            "platform_markdown": deepcopy(payload["platform_markdown"]),
            "layout": {
                "theme": payload["article_layout"]["theme"],
                "structure": payload["article_layout"]["structure"],
            },
            "rule_feedback": {
                "master": evaluate_reader_feedback(
                    payload["master_title"], payload["master_markdown"]
                ),
                "platforms": {
                    platform: evaluate_reader_feedback(
                        payload["master_title"], markdown
                    )
                    for platform, markdown in payload["platform_markdown"].items()
                },
            },
        }
        return self.store.create_gpt_polish_job(
            payload["dedupe_key"], current_version, request
        )

    def gpt_polish_status(self, article_id: str) -> dict[str, Any] | None:
        _, payload = self._find(article_id)
        return self.store.latest_gpt_polish_job(payload["dedupe_key"])

    def apply_gpt_polish(
        self,
        article_id: str,
        job_id: str,
        expected_version: str,
    ) -> dict[str, object]:
        _, current = self._find(article_id)
        job = self.store.get_gpt_polish_job(job_id)
        if (
            job is None
            or job["dedupe_key"] != current["dedupe_key"]
            or job["status"] != "ready"
            or job["proposal"] is None
        ):
            raise ArticleNotFound(job_id)
        current_version = _version(current)
        if (
            not isinstance(expected_version, str)
            or not hmac.compare_digest(current_version, expected_version)
            or not hmac.compare_digest(str(job["base_version"]), current_version)
        ):
            raise ArticleConflict(article_id)
        source_url = self.store.get_source_url(current["dedupe_key"])
        if source_url is None:
            raise InvalidArticle("missing source metadata")
        try:
            replacement, _normalized = candidate_payload(
                current,
                job["proposal"],
                source_url=source_url,
            )
        except GptPolishProposalError as error:
            raise InvalidArticle(str(error)) from error
        replacement = _validate_payload(
            replacement,
            expected_dedupe_key=current["dedupe_key"],
        )
        hard, _warnings = validate_generation_payload(
            replacement,
            dedupe_key=current["dedupe_key"],
            source_url=source_url,
        )
        blocked = [
            failure
            for failure in hard
            if failure != "nonempty_visual_assets"
            and not failure.endswith(":below_target_length")
        ]
        if blocked:
            raise InvalidArticle(f"gpt_polish:{blocked[0]}")
        result = self.save_article(
            article_id,
            replacement,
            expected_version,
            operation="gpt_polish",
        )
        self.store.set_review_status(
            current["dedupe_key"], "needs_human_review"
        )
        if not self.store.transition_gpt_polish_job(
            job_id, "ready", "applied"
        ):
            raise ArticleConflict(article_id)
        result["gpt_polish"] = self.gpt_polish_status(article_id)
        return result

    def discard_gpt_polish(self, article_id: str, job_id: str) -> dict[str, Any]:
        _, payload = self._find(article_id)
        job = self.store.get_gpt_polish_job(job_id)
        if (
            job is None
            or job["dedupe_key"] != payload["dedupe_key"]
            or job["status"] != "ready"
            or not self.store.transition_gpt_polish_job(
                job_id, "ready", "discarded"
            )
        ):
            raise ArticleNotFound(job_id)
        return self.store.get_gpt_polish_job(job_id) or {}

    def list_history(self, article_id: str) -> list[dict[str, str]]:
        self._find(article_id)
        directory = self.history_dir / article_id
        rows: list[dict[str, str]] = []
        if not directory.exists():
            return rows
        for path in directory.glob("*.json"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                metadata = value["metadata"]
                rows.append(
                    {
                        "history_id": path.name,
                        "saved_at": str(metadata["saved_at"]),
                        "operation": str(metadata["operation"]),
                        "version": str(metadata["version"]),
                    }
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
            ):
                continue
        rows.sort(key=lambda row: row["saved_at"], reverse=True)
        return rows

    def restore_article(
        self,
        article_id: str,
        history_id: str,
        expected_version: str,
    ) -> dict[str, object]:
        known = {row["history_id"] for row in self.list_history(article_id)}
        if history_id not in known:
            raise ArticleNotFound(history_id)
        value = json.loads(
            (self.history_dir / article_id / history_id).read_text(encoding="utf-8")
        )
        return self.save_article(
            article_id,
            value["payload"],
            expected_version,
            operation="restore",
        )

    def set_status(self, article_id: str, status: str) -> None:
        with self._write_lock:
            with article_lock(
                output_dir=self.output_dir,
                article_id=article_id,
            ):
                _, payload = self._find(article_id)
                if status == "approved":
                    failures = self._approval_failures(article_id, payload)
                    if failures:
                        labels = [
                            _APPROVAL_FAILURE_LABELS.get(failure, failure)
                            for failure in failures
                        ]
                        has_visual_failure = any(
                            failure in _VISUAL_APPROVAL_FAILURES
                            for failure in failures
                        )
                        has_other_failure = any(
                            failure not in _VISUAL_APPROVAL_FAILURES
                            for failure in failures
                        )
                        if has_visual_failure and has_other_failure:
                            guidance = (
                                "请先点击“生成图片”；其余问题请退回并重新生成文章。"
                            )
                        elif has_visual_failure:
                            guidance = "请先点击“生成图片”。"
                        else:
                            guidance = "请退回并重新生成文章。"
                        raise InvalidArticle(
                            "无法通过：" + "、".join(labels) + "。" + guidance
                        )
                self.store.set_review_status(payload["dedupe_key"], status)

    def export_web_edition(self, article_id: str) -> Path:
        """Export only the currently approved, server-owned article."""

        with self._write_lock:
            with article_lock(
                output_dir=self.output_dir,
                article_id=article_id,
            ):
                _, payload = self._find(article_id)
                queue_rows = {
                    str(row["dedupe_key"]): row
                    for row in self.store.list_publish_queue()
                }
                queue_row = queue_rows.get(payload["dedupe_key"])
                if queue_row is None or queue_row["status"] != "approved":
                    raise InvalidArticle("article is not approved for export")
                relative_path = f"web/{article_id}.html"
                destination = self.output_dir / relative_path
                atomic_write_web_edition(
                    destination,
                    render_web_edition(
                        payload.get("article_layout"),
                        title=payload.get("master_title"),
                        fallback_markdown=payload.get("master_markdown"),
                        embedded_images=self._web_edition_images(article_id),
                    ),
                )
                self.store.record_web_edition_export(
                    payload["dedupe_key"],
                    relative_path,
                    datetime.now(UTC).isoformat(),
                    _version(payload),
                )
                return destination

    def wechat_draft_status(self, article_id: str) -> dict[str, object] | None:
        """Return the persisted status for the article's current version."""

        _, payload = self._find(article_id)
        return self.store.get_wechat_draft_sync(
            payload["dedupe_key"], _version(payload)
        )

    def sync_wechat_draft(
        self,
        article_id: str,
        expected_version: str,
        client: WechatClient,
    ) -> dict[str, object]:
        """Create one draft for an approved immutable article version."""

        with self._write_lock:
            with article_lock(output_dir=self.output_dir, article_id=article_id):
                _, payload = self._find(article_id)
                current_version = _version(payload)
                if not isinstance(expected_version, str) or not hmac.compare_digest(
                    current_version, expected_version
                ):
                    raise ArticleConflict(article_id)
                queue_row = next(
                    (
                        row
                        for row in self.store.list_publish_queue()
                        if row["dedupe_key"] == payload["dedupe_key"]
                    ),
                    None,
                )
                if queue_row is None or queue_row["status"] != "approved":
                    raise InvalidArticle(
                        "article is not approved for WeChat draft sync"
                    )
                existing = self.store.get_wechat_draft_sync(
                    payload["dedupe_key"], current_version
                )
                if existing is not None and existing["status"] == "success":
                    return {
                        "status": "success",
                        "media_id": existing["media_id"],
                        "content_version": current_version,
                        "idempotent": True,
                    }
                if existing is not None and existing["status"] == "pending":
                    raise InvalidArticle(
                        "公众号草稿同步结果待确认，请先在公众号后台核对，避免重复创建"
                    )

                references = self.asset_references(article_id)
                cover = references.get("cover")
                bodies = [
                    reference
                    for asset_id, reference in sorted(references.items())
                    if asset_id.startswith("body-")
                ]
                if cover is None or not bodies:
                    raise InvalidArticle(
                        "approved article is missing WeChat visual assets"
                    )
                cover_path = self.asset_path(
                    article_id, "cover", str(cover["revision"])
                )
                body_paths = [
                    self.asset_path(
                        article_id,
                        str(body["asset_id"]),
                        str(body["revision"]),
                    )
                    for body in bodies
                ]
                try:
                    token = client.get_access_token()
                    cover_media_id = client.upload_permanent_image(token, cover_path)
                    body_urls = [
                        client.upload_body_image(token, body_path)
                        for body_path in body_paths
                    ]
                    platform_markdown = payload.get("platform_markdown", {})
                    fallback_markdown = (
                        platform_markdown.get("wechat", "")
                        if isinstance(platform_markdown, dict)
                        else payload.get("master_markdown", "")
                    )
                    html = render_wechat_article(
                        payload.get("article_layout"),
                        fallback_title=payload.get("master_title"),
                        fallback_markdown=fallback_markdown,
                        body_image_urls=body_urls,
                    )
                except WechatApiError as error:
                    self.store.record_wechat_draft_sync(
                        payload["dedupe_key"],
                        current_version,
                        status="error",
                        media_id=None,
                        error=str(error),
                    )
                    raise
                self.store.record_wechat_draft_sync(
                    payload["dedupe_key"],
                    current_version,
                    status="pending",
                    media_id=None,
                    error="WeChat draft result is unknown",
                )
                try:
                    media_id = client.add_draft(
                        token,
                        title=str(payload["master_title"]),
                        content=html,
                        thumb_media_id=cover_media_id,
                    )
                except WechatApiError as error:
                    raise WechatDraftResultUnknown(
                        "公众号可能已接收草稿，请先在后台核对，系统不会自动重试"
                    ) from error
                self.store.record_wechat_draft_sync(
                    payload["dedupe_key"],
                    current_version,
                    status="success",
                    media_id=media_id,
                    error=None,
                )
                return {
                    "status": "success",
                    "media_id": media_id,
                    "content_version": current_version,
                    "idempotent": False,
                }

    def _web_edition_images(
        self,
        article_id: str,
    ) -> list[tuple[str, str]]:
        """Encode only current, repository-confined visual assets."""

        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        images: list[tuple[str, str]] = []
        for reference in self._asset_references(article_id):
            try:
                path = self.asset_path(
                    article_id,
                    str(reference["asset_id"]),
                    str(reference["revision"]),
                )
                media_type = media_types.get(path.suffix.lower())
                if media_type is None or path.stat().st_size > 8_000_000:
                    continue
                content = path.read_bytes()
            except (ArticleNotFound, OSError, KeyError):
                continue
            encoded = base64.b64encode(content).decode("ascii")
            images.append(
                (
                    f"data:{media_type};base64,{encoded}",
                    (
                        "文章封面"
                        if reference["asset_id"] == "cover"
                        else f"正文配图 {str(reference['asset_id']).removeprefix('body-')}"
                    ),
                )
            )
        return images

    def web_edition_path(self, article_id: str) -> Path:
        """Return a previously exported edition only while approval is current."""

        _, payload = self._find(article_id)
        queue_rows = {
            str(row["dedupe_key"]): row for row in self.store.list_publish_queue()
        }
        queue_row = queue_rows.get(payload["dedupe_key"])
        destination = self.output_dir / "web" / f"{article_id}.html"
        metadata = self.store.get_web_edition_export(payload["dedupe_key"])
        if (
            queue_row is None
            or queue_row["status"] != "approved"
            or metadata is None
            or metadata.get("relative_path") != f"web/{article_id}.html"
            or not hmac.compare_digest(
                str(metadata.get("content_version", "")),
                _version(payload),
            )
            or not destination.is_file()
            or destination.is_symlink()
        ):
            raise ArticleNotFound(article_id)
        return destination

    def web_edition_metadata(self, article_id: str) -> dict[str, str]:
        """Return server-owned export metadata for a known article."""

        _, payload = self._find(article_id)
        metadata = self.store.get_web_edition_export(payload["dedupe_key"])
        if metadata is None:
            raise ArticleNotFound(article_id)
        return metadata

    def _approval_failures(
        self,
        article_id: str,
        payload: dict[str, Any],
    ) -> list[str]:
        """Return only hard blockers that prevent approval.

        Style warnings are shown to the reviewer but do not block approval.
        """
        hard: list[str] = []
        source_url = self.store.get_source_url(payload["dedupe_key"])
        if source_url is None:
            hard.append("missing_source_metadata")
        else:
            hard_blockers, _style = validate_generation_payload(
                payload,
                dedupe_key=payload["dedupe_key"],
                source_url=source_url,
            )
            # nonempty_visual_assets is the generation contract: the editorial
            # pass must emit {"cover": null, "body": []}.  Once the rendering
            # stage has published assets the payload IS non-empty, and that is
            # expected — not a failure.
            hard.extend(b for b in hard_blockers if b != "nonempty_visual_assets")
        assets = payload["visual_assets"]
        cover = assets.get("cover")
        body = assets.get("body")
        if not isinstance(cover, dict):
            hard.append("missing_cover_asset")
        if not isinstance(body, list) or not 1 <= len(body) <= 3:
            hard.append("missing_body_asset")
        if not has_canonical_body_asset_marker(payload):
            hard.append("missing_body_asset_marker")
        if isinstance(cover, dict):
            try:
                self.asset_path(
                    article_id,
                    str(cover["asset_id"]),
                    str(cover["revision"]),
                )
            except (ArticleNotFound, KeyError):
                hard.append("missing_cover_file")
        if isinstance(body, list) and 1 <= len(body) <= 3:
            for reference in body:
                if not isinstance(reference, dict):
                    hard.append("missing_body_file")
                    continue
                try:
                    self.asset_path(
                        article_id,
                        str(reference["asset_id"]),
                        str(reference["revision"]),
                    )
                except (ArticleNotFound, KeyError):
                    hard.append("missing_body_file")
        return list(dict.fromkeys(hard))
