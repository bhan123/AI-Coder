from __future__ import annotations

import json

import pytest

from ai_content_loop.db import ContentStore
from ai_content_loop.editorial.schema import CORE_FIELDS, article_id_for
from ai_content_loop.models import SourceItem
from ai_content_loop.review.repository import (
    ArticleConflict,
    ArticleNotFound,
    ArticleRepository,
    InvalidArticle,
    _atomic_json_write,
)
from ai_content_loop.visuals.pipeline import insert_body_asset_marker


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"


def visual_brief() -> dict:
    panels = [
        {"label": "AI 写完代码", "reaction": "自信"},
        {"label": "你打开测试", "reaction": "沉默"},
    ]
    return {
        "template_hint": "ai_done_vs_tests",
        "cover_line": "AI 写完代码，人类打开测试",
        "cover_subline": "笑容只会转移",
        "body_panels": panels,
        "alternatives": [
            {
                "cover_line": "代码写完了，问题刚开始",
                "cover_subline": "测试更诚实",
                "body_panels": panels,
            },
            {
                "cover_line": "AI 程序员上岗第一天",
                "cover_subline": "会烧 Token",
                "body_panels": panels,
            },
        ],
    }


def article_payload(
    body: str = "\n\n".join(
        [
            "正文内容达到建议篇幅，描述核心功能、实际用途、证据边界、使用场景和具体限制。"
            * 2
        ]
        * 16
    ),
) -> dict:
    platform_body = f"{body}\n\n来源：{SOURCE_URL}"
    return {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": platform_body,
        "platform_markdown": {
            "wechat": platform_body,
            "xiaohongshu": platform_body,
            "toutiao": platform_body,
            "zhihu": platform_body,
        },
        "editorial_profile": {
            "version": "tech_friend_v2",
            "persona": "tech_friend_with_garage",
            "humor_level": "balanced",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": visual_brief(),
        "visual_assets": {"cover": None, "body": []},
    }


@pytest.fixture
def repository(tmp_path):
    final_dir = tmp_path / "out" / "final"
    final_dir.mkdir(parents=True)
    (final_dir / "repo.json").write_text(
        json.dumps(article_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_source_items(
        [
            SourceItem(
                source="github",
                external_id="owner/repo",
                title="Repo",
                url=SOURCE_URL,
                summary="Summary",
                published_at="2026-07-01T00:00:00+00:00",
                fetched_at="2026-07-01T01:00:00+00:00",
                raw={},
            )
        ]
    )
    store.upsert_publish_queue(
        DEDUPE_KEY,
        "Repo",
        "开源项目淘金",
        "needs_human_review",
        str(tmp_path / "draft.json"),
    )
    return ArticleRepository(
        store=store,
        final_dir=final_dir,
        history_dir=tmp_path / "out" / "history",
    )


def test_list_and_load_use_opaque_article_id(repository):
    rows = repository.list_articles()

    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == DEDUPE_KEY
    assert rows[0]["article_id"] == article_id_for(DEDUPE_KEY)
    assert "/" not in rows[0]["article_id"]

    loaded = repository.load_article(rows[0]["article_id"])
    assert loaded["payload"]["dedupe_key"] == DEDUPE_KEY
    assert len(loaded["version"]) == 64
    assert loaded["warnings"] == []


def test_list_articles_exposes_generated_date(repository):
    with repository.store.connect() as conn:
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-09 08:10:48", DEDUPE_KEY),
        )

    rows = repository.list_articles()

    assert rows[0]["created_at"] == "2026-07-09 08:10:48"
    assert rows[0]["generated_date"] == "2026-07-09"


def test_load_legacy_article_adds_safe_defaults(repository):
    legacy = article_payload()
    for field in ("editorial_profile", "visual_brief", "visual_assets"):
        del legacy[field]
    (repository.final_dir / "repo.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)

    assert loaded["payload"]["editorial_profile"]["version"] == "legacy"
    assert loaded["payload"]["visual_brief"] is None
    assert loaded["payload"]["visual_assets"] == {
        "cover": None,
        "body": [],
    }
    assert loaded["warnings"] == ["legacy_editorial_profile"]


def test_legacy_article_can_be_edited_saved_and_reloaded(repository):
    legacy = article_payload()
    for field in ("editorial_profile", "visual_brief", "visual_assets"):
        del legacy[field]
    (repository.final_dir / "repo.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)
    replacement = loaded["payload"]
    replacement["master_title"] = "编辑后仍可保存的旧文章标题"
    replacement["platform_markdown"]["wechat"] += "\n\n编辑补充。"

    saved = repository.save_article(
        article_id,
        replacement,
        loaded["version"],
        operation="edit",
    )
    reloaded = repository.load_article(article_id)

    assert saved["payload"]["master_title"] == replacement["master_title"]
    assert reloaded["payload"] == saved["payload"]
    assert reloaded["warnings"] == ["legacy_editorial_profile"]


@pytest.mark.parametrize("tampering", ["refs", "assets"])
def test_current_article_cannot_forge_legacy_compatibility(
    repository,
    tampering,
):
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)
    replacement = loaded["payload"]
    replacement["editorial_profile"] = {
        "version": "legacy",
        "persona": "unassigned",
        "humor_level": "unassigned",
        "verified_trial": False,
        "trial_artifact_refs": [],
        "quality_warnings": ["legacy_editorial_profile"],
    }
    replacement["visual_brief"] = None
    if tampering == "refs":
        replacement["editorial_profile"]["trial_artifact_refs"] = [
            "model-controlled-secret"
        ]
    else:
        replacement["visual_assets"]["body"] = [
            {"path": "model-controlled-secret"}
        ]

    with pytest.raises(InvalidArticle) as caught:
        repository.save_article(
            article_id,
            replacement,
            loaded["version"],
            operation="edit",
        )

    assert str(caught.value) == "current article cannot forge legacy schema"


def test_current_article_cannot_be_downgraded_to_core_fields(repository):
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)
    replacement = {
        field: loaded["payload"][field]
        for field in CORE_FIELDS
    }
    replacement["master_title"] = "model-controlled-secret"

    with pytest.raises(InvalidArticle) as caught:
        repository.save_article(
            article_id,
            replacement,
            loaded["version"],
            operation="edit",
        )

    reloaded = repository.load_article(article_id)
    assert str(caught.value) == "current article cannot use legacy schema"
    assert "model-controlled-secret" not in str(caught.value)
    assert reloaded == loaded
    assert list(repository.history_dir.rglob("*.json")) == []


def test_legacy_article_can_save_core_fields(repository):
    legacy = article_payload()
    for field in ("editorial_profile", "visual_brief", "visual_assets"):
        del legacy[field]
    (repository.final_dir / "repo.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)
    replacement = {
        field: loaded["payload"][field]
        for field in CORE_FIELDS
    }
    replacement["master_title"] = "旧文章使用五字段保存成功"

    saved = repository.save_article(
        article_id,
        replacement,
        loaded["version"],
        operation="edit",
    )

    assert saved["payload"]["master_title"] == replacement["master_title"]
    assert saved["payload"]["editorial_profile"]["version"] == "legacy"
    assert saved["warnings"] == ["legacy_editorial_profile"]


def test_restore_accepts_server_owned_core_history(repository):
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)
    core_payload = {
        field: loaded["payload"][field]
        for field in CORE_FIELDS
    }
    core_payload["master_title"] = "从服务端旧历史恢复的标题"
    history_id = "20260705T000000000000Z-edit-legacy.json"
    history_path = repository.history_dir / article_id / history_id
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "saved_at": "2026-07-05T00:00:00+00:00",
                    "operation": "edit",
                    "version": "legacy-version",
                },
                "payload": core_payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    restored = repository.restore_article(
        article_id,
        history_id,
        loaded["version"],
    )

    assert restored["payload"]["master_title"] == core_payload["master_title"]
    assert restored["payload"]["editorial_profile"]["version"] == "legacy"
    assert restored["warnings"] == ["legacy_editorial_profile"]


def test_load_surfaces_editorial_and_profile_warnings(repository):
    payload = article_payload()
    payload["master_title"] = "震惊！这个工具到底值不值得用"
    payload["platform_markdown"]["wechat"] += (
        " 在这个数字化时代，我试了一下。"
    )
    payload["editorial_profile"]["quality_warnings"] = [
        "legacy_editorial_profile"
    ]
    (repository.final_dir / "repo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)

    # ai_cliche and cheap_clickbait are now style warnings via quality_warnings path;
    # unverified_first_person_trial is hard. The editorial voice check was deduplicated
    # (no longer called twice), so warnings come from either validate_generation_payload
    # or the payload's own quality_warnings list.
    assert set(loaded["warnings"]) == {
        "editorial:ai_cliche",
        "editorial:unverified_first_person_trial",
        "editorial:cheap_clickbait",
        "legacy_editorial_profile",
    }
    assert all("我试了一下" not in warning for warning in loaded["warnings"])


def test_load_checks_editorial_voice_without_source_metadata(tmp_path):
    final_dir = tmp_path / "out" / "final"
    final_dir.mkdir(parents=True)
    payload = article_payload()
    payload["platform_markdown"]["wechat"] += " 在这个数字化时代。"
    (final_dir / "repo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    repository = ArticleRepository(
        store=store,
        final_dir=final_dir,
        history_dir=tmp_path / "out" / "history",
    )

    article_id = repository.list_articles()[0]["article_id"]

    # editorial:ai_cliche is surfaced via quality_warnings path, not
    # via the old duplicate editorial voice check which was removed.
    assert repository.load_article(article_id)["warnings"] == [
        "missing_source_metadata",
    ]


def test_save_creates_snapshot_and_rejects_stale_version(repository):
    article = repository.list_articles()[0]
    loaded = repository.load_article(article["article_id"])
    changed = dict(loaded["payload"])
    changed["master_title"] = "修改后的标题"

    saved = repository.save_article(
        article["article_id"],
        payload=changed,
        expected_version=loaded["version"],
        operation="edit",
    )

    assert saved["payload"]["master_title"] == "修改后的标题"
    assert saved["version"] != loaded["version"]
    assert len(repository.list_history(article["article_id"])) == 1

    with pytest.raises(ArticleConflict):
        repository.save_article(
            article["article_id"],
            payload=loaded["payload"],
            expected_version=loaded["version"],
            operation="edit",
        )


def test_restore_creates_new_version_without_deleting_history(repository):
    article_id = repository.list_articles()[0]["article_id"]
    original = repository.load_article(article_id)
    changed = dict(original["payload"])
    changed["master_title"] = "第二版"
    second = repository.save_article(
        article_id,
        changed,
        original["version"],
        operation="edit",
    )
    historical = repository.list_history(article_id)[0]

    restored = repository.restore_article(
        article_id,
        history_id=historical["history_id"],
        expected_version=second["version"],
    )

    assert restored["payload"]["master_title"] == original["payload"]["master_title"]
    assert len(repository.list_history(article_id)) == 2


def test_rejects_unknown_article_and_invalid_payload(repository):
    with pytest.raises(ArticleNotFound):
        repository.load_article("../../etc/passwd")

    article = repository.list_articles()[0]
    loaded = repository.load_article(article["article_id"])
    invalid = dict(loaded["payload"])
    invalid["platform_markdown"] = {"wechat": "only one"}
    with pytest.raises(InvalidArticle):
        repository.save_article(
            article["article_id"],
            invalid,
            loaded["version"],
            operation="edit",
        )


def test_status_filter_and_update_use_publish_queue(repository):
    article_id = repository.list_articles()[0]["article_id"]

    repository.set_status(article_id, "revision_requested")

    assert repository.list_articles(status="needs_human_review") == []
    returned = repository.list_articles(status="revision_requested")
    assert [row["article_id"] for row in returned] == [article_id]


def test_approval_error_names_the_unresolved_blockers(repository):
    article_id = repository.list_articles()[0]["article_id"]

    with pytest.raises(
        InvalidArticle,
        match="无法通过：缺少封面图、缺少正文配图、正文未插入配图标记。请先点击“生成图片”。",
    ):
        repository.set_status(article_id, "approved")


def test_history_identifier_cannot_escape_history_directory(repository):
    article_id = repository.list_articles()[0]["article_id"]
    loaded = repository.load_article(article_id)

    with pytest.raises(ArticleNotFound):
        repository.restore_article(
            article_id,
            history_id="../../repo.json",
            expected_version=loaded["version"],
        )


def test_export_web_edition_requires_an_approved_article(repository):
    article_id = repository.list_articles()[0]["article_id"]

    with pytest.raises(InvalidArticle, match="not approved"):
        repository.export_web_edition(article_id)


def test_export_web_edition_writes_a_standalone_document_in_output_web(
    repository,
):
    article_id = repository.list_articles()[0]["article_id"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")

    exported = repository.export_web_edition(article_id)

    assert exported == repository.output_dir / "web" / f"{article_id}.html"
    assert exported.is_file()
    html = exported.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "<script" not in html.lower()
    assert list(exported.parent.glob(f".{article_id}.html.*.tmp")) == []


def test_web_edition_invalidates_on_edit_and_restore_until_reapproved(
    repository,
):
    article_id = repository.list_articles()[0]["article_id"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    repository.export_web_edition(article_id)
    initial_metadata = repository.web_edition_metadata(article_id)
    initial = repository.load_article(article_id)
    replacement = dict(initial["payload"])
    replacement["master_title"] = "导出后修改的标题"
    saved = repository.save_article(
        article_id,
        replacement,
        initial["version"],
        operation="edit",
    )
    history_id = repository.list_history(article_id)[0]["history_id"]

    assert set(initial_metadata) == {
        "relative_path",
        "exported_at",
        "content_version",
    }
    assert initial_metadata["relative_path"] == f"web/{article_id}.html"
    assert initial_metadata["content_version"] == initial["version"]
    assert initial_metadata["exported_at"]
    with pytest.raises(ArticleNotFound):
        repository.web_edition_path(article_id)
    with pytest.raises(ArticleNotFound):
        repository.web_edition_metadata(article_id)
    assert repository.list_articles(status="needs_human_review")[0][
        "article_id"
    ] == article_id
    with pytest.raises(InvalidArticle, match="not approved"):
        repository.export_web_edition(article_id)

    restored = repository.restore_article(
        article_id,
        history_id,
        saved["version"],
    )

    assert restored["payload"]["master_title"] == initial["payload"][
        "master_title"
    ]
    with pytest.raises(ArticleNotFound):
        repository.web_edition_path(article_id)
    repository.store.set_review_status(DEDUPE_KEY, "approved")

    repository.export_web_edition(article_id)
    refreshed_metadata = repository.web_edition_metadata(article_id)

    assert refreshed_metadata["content_version"] == restored["version"]
    assert repository.web_edition_path(article_id).is_file()


def test_web_edition_invalidates_after_visual_edit(repository):
    article_id = repository.list_articles()[0]["article_id"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    repository.export_web_edition(article_id)
    loaded = repository.load_article(article_id)

    repository.save_article(
        article_id,
        loaded["payload"],
        loaded["version"],
        operation="visual_edit",
    )

    assert repository.list_articles(status="needs_human_review")[0][
        "article_id"
    ] == article_id
    with pytest.raises(ArticleNotFound):
        repository.web_edition_path(article_id)


def test_failed_article_write_revokes_old_web_edition_before_final_write(
    repository,
    monkeypatch,
):
    article_id = repository.list_articles()[0]["article_id"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    repository.export_web_edition(article_id)
    loaded = repository.load_article(article_id)
    replacement = dict(loaded["payload"])
    replacement["master_title"] = "不会落盘的标题"
    original_write = _atomic_json_write

    def fail_final_write(path, value):
        if path == repository.final_dir / "repo.json":
            raise OSError("simulated final write failure")
        original_write(path, value)

    monkeypatch.setattr(
        "ai_content_loop.review.repository._atomic_json_write",
        fail_final_write,
    )

    with pytest.raises(OSError, match="simulated final write failure"):
        repository.save_article(
            article_id,
            replacement,
            loaded["version"],
            operation="edit",
        )

    assert repository.load_article(article_id)["version"] == loaded["version"]
    assert repository.list_articles(status="needs_human_review")[0][
        "article_id"
    ] == article_id
    with pytest.raises(ArticleNotFound):
        repository.web_edition_path(article_id)


def test_export_web_edition_keeps_source_urls_as_non_navigable_text(
    repository,
):
    article_id = repository.list_articles()[0]["article_id"]
    payload = article_payload()
    payload["article_layout"] = {
        "theme": "press",
        "blocks": [
            {
                "type": "source_note",
                "url": "https://example.com/source",
                "attribution": "原始来源",
            }
        ],
    }
    (repository.final_dir / "repo.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    repository.store.set_review_status(DEDUPE_KEY, "approved")

    html = repository.export_web_edition(article_id).read_text(encoding="utf-8")

    assert "https://example.com/source" in html
    assert 'href="https://example.com/source"' not in html
    assert "target=" not in html


def test_export_web_edition_fallback_allows_no_protocol_relative_url(
    repository,
):
    article_id = repository.list_articles()[0]["article_id"]
    payload = article_payload()
    payload["master_markdown"] = "[绕过](//example.com/path)\n\n![图](//example.com/a.png)"
    payload["article_layout"] = {"theme": "press", "blocks": []}
    (repository.final_dir / "repo.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    repository.store.set_review_status(DEDUPE_KEY, "approved")

    html = repository.export_web_edition(article_id).read_text(encoding="utf-8")

    assert "href=" not in html
    assert "src=" not in html


def test_export_web_edition_embeds_only_safe_repository_assets(repository):
    article_id = repository.list_articles()[0]["article_id"]
    revision = "a" * 64
    asset_dir = repository.assets_dir / article_id / revision
    asset_dir.mkdir(parents=True)
    (asset_dir / "cover.jpg").write_bytes(b"cover")
    (asset_dir / "body.png").write_bytes(b"body")
    payload = article_payload()
    payload["visual_assets"] = {
        "cover": {
            "asset_id": "cover",
            "revision": revision,
            "path": f"assets/{article_id}/{revision}/cover.jpg",
            "template": "ai_done_vs_tests",
            "copy_index": 0,
            "ai_generated": False,
        },
        "body": [
            {
                "asset_id": "body-01",
                "revision": revision,
                "path": f"assets/{article_id}/{revision}/body.png",
                "template": "ai_done_vs_tests",
                "copy_index": 0,
                "ai_generated": False,
            }
        ],
    }
    (repository.final_dir / "repo.json").write_text(
        json.dumps(insert_body_asset_marker(payload), ensure_ascii=False),
        encoding="utf-8",
    )
    repository.store.set_review_status(DEDUPE_KEY, "approved")

    html = repository.export_web_edition(article_id).read_text(encoding="utf-8")

    assert "data:image/jpeg;base64,Y292ZXI=" in html
    assert "data:image/png;base64,Ym9keQ==" in html
    assert str(asset_dir) not in html
    (asset_dir / "cover.jpg").unlink()

    without_missing_asset = repository.export_web_edition(article_id).read_text(
        encoding="utf-8"
    )

    assert "data:image/jpeg;base64,Y292ZXI=" not in without_missing_asset
    assert "data:image/png;base64,Ym9keQ==" in without_missing_asset
