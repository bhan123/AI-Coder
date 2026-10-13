from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from engine.db import ContentStore
from engine.editorial.schema import article_id_for
from engine.models import SourceItem
from engine.review.app import _minimal_visual_brief, create_app
from engine.visuals.pipeline import insert_body_asset_marker


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"
REVISION = "a" * 64


def _brief():
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


def test_minimal_visual_brief_makes_null_visuals_renderable():
    fallback = _minimal_visual_brief(
        {"master_title": "一个很长但仍然可以用于封面的文章标题"},
        "boss_vs_worker",
    )

    assert fallback["template_hint"] == "boss_vs_worker"
    assert fallback["cover_line"].startswith("一个很长")
    assert len(fallback["body_panels"]) == 2
    assert len(fallback["alternatives"]) == 2


def _payload(*, rendered: bool) -> dict[str, object]:
    body = f"{'正文内容足够长。' * 90}\n\n来源：{SOURCE_URL}"
    value: dict[str, object] = {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": body,
        "platform_markdown": {
            name: body
            for name in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
        "editorial_profile": {
            "version": "tech_friend_v1",
            "persona": "tech_friend",
            "humor_level": "light",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": _brief(),
        "visual_assets": {"cover": None, "body": []},
    }
    if not rendered:
        return value

    article_id = article_id_for(DEDUPE_KEY)

    def reference(asset_id: str, filename: str):
        return {
            "asset_id": asset_id,
            "revision": REVISION,
            "path": f"assets/{article_id}/{REVISION}/{filename}",
            "template": "ai_done_vs_tests",
            "copy_index": 0,
            "ai_generated": False,
        }

    value["visual_assets"] = {
        "cover": reference("cover", "cover.jpg"),
        "body": [reference("body-01", "body.png")],
    }
    return insert_body_asset_marker(value)


def _make_app(tmp_path: Path, *, rendered: bool = True):
    output_dir = tmp_path / "out"
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True)
    payload = _payload(rendered=rendered)
    (final_dir / "repo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if rendered:
        revision_dir = (
            output_dir
            / "assets"
            / article_id_for(DEDUPE_KEY)
            / REVISION
        )
        revision_dir.mkdir(parents=True)
        (revision_dir / "cover.jpg").write_bytes(b"cover")
        (revision_dir / "body.png").write_bytes(b"body")

    database_path = output_dir / "content.sqlite3"
    store = ContentStore(database_path)
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
        str(output_dir / "draft.json"),
    )
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"test-font")
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "REVIEW_USERNAME": "owner",
            "REVIEW_PASSWORD_HASH": generate_password_hash("correct horse"),
            "DATABASE_PATH": database_path,
            "FINAL_DIR": final_dir,
            "HISTORY_DIR": output_dir / "history",
            "OUTPUT_DIR": output_dir,
            "ASSET_DIR": output_dir / "assets",
            "VISUAL_FONT_PATH": font_path,
        }
    )


def _login(client):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": token,
        },
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        return session["csrf_token"]


def _article_id(client) -> str:
    return client.get("/api/articles").get_json()["articles"][0]["article_id"]


def test_asset_route_requires_login_and_serves_current_reference(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    article_id = article_id_for(DEDUPE_KEY)
    url = f"/api/articles/{article_id}/assets/body-01/{REVISION}"

    assert client.get(url).status_code == 401
    _login(client)
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == b"body"
    assert client.get(
        f"/api/articles/{article_id}/assets/body-01/{'b' * 64}"
    ).status_code == 404


def test_preview_maps_marker_from_current_article_only(tmp_path):
    client = _make_app(tmp_path).test_client()
    csrf = _login(client)
    article_id = _article_id(client)

    response = client.post(
        "/api/preview",
        json={
            "article_id": article_id,
            "markdown": "开头\n\n{{asset:body-01}}\n\n结尾",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    html = response.get_json()["html"]
    assert f"/api/articles/{article_id}/assets/body-01/{REVISION}" in html


def test_visual_render_route_saves_new_version_and_history(
    tmp_path, monkeypatch
):
    app = _make_app(tmp_path)
    client = app.test_client()
    csrf = _login(client)
    article_id = _article_id(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    image_client = object()
    app.extensions["minimax_image_client"] = image_client

    def fake_generate_visual_assets(
        *,
        payload,
        output_dir,
        font_path,
        template_name,
        copy_index,
        image_client: object,
    ):
        assert image_client is app.extensions["minimax_image_client"]
        assert Path(output_dir) == tmp_path / "out"
        assert Path(font_path) == tmp_path / "font.ttf"
        updated = deepcopy(payload)
        new_revision = "b" * 64
        revision_dir = (
            Path(output_dir) / "assets" / article_id / new_revision
        )
        revision_dir.mkdir(parents=True)
        (revision_dir / "cover.jpg").write_bytes(b"new-cover")
        (revision_dir / "body.png").write_bytes(b"new-body")
        for reference in [
            updated["visual_assets"]["cover"],
            *updated["visual_assets"]["body"],
        ]:
            reference["revision"] = new_revision
            reference["template"] = template_name
            reference["copy_index"] = copy_index
            filename = (
                "cover.jpg"
                if reference["asset_id"] == "cover"
                else "body.png"
            )
            reference["path"] = (
                f"assets/{article_id}/{new_revision}/{filename}"
            )
        return updated

    monkeypatch.setattr(
        "engine.review.app.generate_visual_assets",
        fake_generate_visual_assets,
    )
    response = client.post(
        f"/api/articles/{article_id}/visuals/render",
        json={
            "version": loaded["version"],
            "template": "boss_vs_worker",
            "copy_index": 2,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    value = response.get_json()
    assert value["payload"]["visual_assets"]["cover"]["template"] == (
        "boss_vs_worker"
    )
    assert value["payload"]["visual_assets"]["cover"]["copy_index"] == 2
    history = client.get(
        f"/api/articles/{article_id}/history"
    ).get_json()["history"]
    assert history[0]["operation"] == "visual_edit"


def test_approval_requires_complete_visuals(tmp_path):
    client = _make_app(tmp_path, rendered=False).test_client()
    csrf = _login(client)
    article_id = _article_id(client)

    response = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_article"


def test_approval_accepts_complete_visuals(tmp_path):
    client = _make_app(tmp_path).test_client()
    csrf = _login(client)
    article_id = _article_id(client)

    response = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200


def test_review_page_contains_visual_controls(tmp_path):
    client = _make_app(tmp_path).test_client()
    _login(client)

    html = client.get("/").get_data(as_text=True)

    for element_id in (
        "cover-preview",
        "body-image-preview",
        "visual-template",
        "next-copy-button",
        "render-visuals-button",
    ):
        assert f'id="{element_id}"' in html


@pytest.mark.parametrize(
    "path",
    [
        "/api/articles/not-real/assets/body-01/" + "a" * 64,
        "/api/articles/../../etc/assets/body-01/" + "a" * 64,
    ],
)
def test_asset_route_does_not_accept_path_identifiers(tmp_path, path):
    client = _make_app(tmp_path).test_client()
    _login(client)
    assert client.get(path).status_code in {404, 405}
