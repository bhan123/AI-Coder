import json
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from ai_content_loop.db import ContentStore
from ai_content_loop.models import SourceItem
from ai_content_loop.review.app import create_app


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"


def visual_brief():
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


def make_payload():
    body = f"{'正文内容足够长。' * 8}\n\n来源：{SOURCE_URL}"
    return {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": body,
        "platform_markdown": {
            "wechat": body,
            "xiaohongshu": body,
            "toutiao": body,
            "zhihu": body,
        },
        "editorial_profile": {
            "version": "tech_friend_v1",
            "persona": "tech_friend",
            "humor_level": "light",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": visual_brief(),
        "visual_assets": {"cover": None, "body": []},
    }


@pytest.fixture
def review_app(tmp_path):
    database_path = tmp_path / "content.sqlite3"
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "repo.json").write_text(
        json.dumps(make_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
        str(tmp_path / "draft.json"),
    )
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "REVIEW_USERNAME": "owner",
            "REVIEW_PASSWORD_HASH": generate_password_hash(
                "correct horse"
            ),
            "DATABASE_PATH": database_path,
            "FINAL_DIR": final_dir,
            "HISTORY_DIR": tmp_path / "history",
        }
    )


def login(client):
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


def test_article_api_round_trip(review_app):
    client = review_app.test_client()
    csrf = login(client)

    listed = client.get("/api/articles").get_json()
    article_id = listed["articles"][0]["article_id"]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    loaded["payload"]["master_title"] = "浏览器里修改的标题"

    response = client.put(
        f"/api/articles/{article_id}",
        json={
            "payload": loaded["payload"],
            "version": loaded["version"],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert (
        response.get_json()["payload"]["master_title"]
        == "浏览器里修改的标题"
    )


def test_stale_save_returns_conflict(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    changed = dict(loaded["payload"])
    changed["master_title"] = "第一次保存"

    first = client.put(
        f"/api/articles/{article_id}",
        json={"payload": changed, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 200

    stale = client.put(
        f"/api/articles/{article_id}",
        json={
            "payload": loaded["payload"],
            "version": loaded["version"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"] == "version_conflict"


def test_history_restore_and_status(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    changed = dict(loaded["payload"])
    changed["master_title"] = "新标题"
    saved = client.put(
        f"/api/articles/{article_id}",
        json={"payload": changed, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).get_json()

    history = client.get(
        f"/api/articles/{article_id}/history"
    ).get_json()["history"]
    restored = client.post(
        f"/api/articles/{article_id}/restore/{history[0]['history_id']}",
        json={"version": saved["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert restored.status_code == 200
    assert (
        restored.get_json()["payload"]["master_title"]
        == "一个值得关注的开源项目"
    )

    status_response = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "revision_requested"},
        headers={"X-CSRF-Token": csrf},
    )
    assert status_response.status_code == 200
    returned = client.get(
        "/api/articles?status=revision_requested"
    ).get_json()
    assert [row["article_id"] for row in returned["articles"]] == [
        article_id
    ]


def test_api_rejects_invalid_filter_and_save_version(review_app):
    client = review_app.test_client()
    csrf = login(client)

    assert client.get("/api/articles?status=generating").status_code == 400
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]
    response = client.put(
        f"/api/articles/{article_id}",
        json={"payload": make_payload(), "version": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 400


def test_api_does_not_treat_article_id_as_a_path(review_app):
    client = review_app.test_client()
    login(client)

    response = client.get("/api/articles/..%2F..%2Fetc%2Fpasswd")

    assert response.status_code in {404, 405}


def test_rich_preview_requires_authenticated_csrf_protected_article_lookup(
    review_app,
):
    client = review_app.test_client()

    assert client.post("/api/rich-preview", json={}).status_code == 401
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]

    rejected = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
    )
    assert rejected.status_code == 403

    response = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    html = response.get_json()["html"]
    assert "一个值得关注的开源项目" in html
    assert "正文内容足够长。" in html
    assert "<style>" not in html


def test_rich_preview_keeps_source_urls_as_non_navigable_text(review_app):
    article_path = Path(review_app.config["FINAL_DIR"]) / "repo.json"
    payload = json.loads(article_path.read_text(encoding="utf-8"))
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
    article_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]

    html = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["html"]

    assert "https://example.com/source" in html
    assert 'href="https://example.com/source"' not in html
    assert "target=" not in html


def test_rich_preview_fallback_allows_no_protocol_relative_url(review_app):
    article_path = Path(review_app.config["FINAL_DIR"]) / "repo.json"
    payload = json.loads(article_path.read_text(encoding="utf-8"))
    payload["master_markdown"] = "[绕过](//example.com/path)\n\n![图](//example.com/a.png)"
    payload["article_layout"] = {"theme": "press", "blocks": []}
    article_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]

    html = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["html"]

    assert "href=" not in html
    assert "src=" not in html


def test_review_page_contains_editor_shell(review_app):
    client = review_app.test_client()
    login(client)

    html = client.get("/").get_data(as_text=True)

    assert 'id="article-list"' in html
    assert 'id="markdown-editor"' in html
    assert 'id="article-preview"' in html
    assert 'id="save-button"' in html
    assert 'id="history-dialog"' in html
    assert 'data-platform="wechat"' in html
    assert 'data-platform="xiaohongshu"' in html
    assert 'data-platform="toutiao"' in html
    assert 'data-platform="zhihu"' in html
    assert 'href="/static/rich_article.css"' in html


def test_review_page_serves_rich_article_styles_from_own_static_origin(
    review_app,
):
    css = review_app.test_client().get(
        "/static/rich_article.css"
    ).get_data(as_text=True)

    assert ".rich-article__toc" in css
    assert ".rich-article__hero" in css


def test_create_app_loads_production_environment(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'database_path = "data/content.sqlite3"\noutput_dir = "out"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_CONTENT_CONFIG", str(config_path))
    monkeypatch.setenv("AI_CONTENT_REVIEW_USERNAME", "owner")
    monkeypatch.setenv(
        "AI_CONTENT_REVIEW_PASSWORD_HASH",
        generate_password_hash("secret"),
    )
    monkeypatch.setenv(
        "AI_CONTENT_REVIEW_SECRET_KEY",
        "production-secret",
    )

    app = create_app()

    assert (
        app.config["DATABASE_PATH"]
        == tmp_path / "data" / "content.sqlite3"
    )
    assert app.config["FINAL_DIR"] == tmp_path / "out" / "final"
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_responses_include_security_headers(review_app):
    response = review_app.test_client().get("/login")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers[
        "Content-Security-Policy"
    ]


def test_review_styles_preserve_hidden_state(review_app):
    css = review_app.test_client().get(
        "/static/review.css"
    ).get_data(as_text=True)

    assert "[hidden]" in css
    assert "display: none !important" in css


def test_review_sidebar_renders_generated_date():
    script = (
        Path(__file__).parents[2]
        / "ai_content_loop"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert "formatArticleDate" in script
    assert "article.generated_date" in script
    assert "article-date" in script


def test_web_edition_api_exports_only_approved_server_owned_article(
    review_app,
):
    client = review_app.test_client()
    assert client.post("/api/articles/nope/web-edition").status_code == 401
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]

    rejected = client.post(
        f"/api/articles/{article_id}/web-edition",
        json={},
        headers={"X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 400

    repository = review_app.extensions["article_repository"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    response = client.post(
        f"/api/articles/{article_id}/web-edition",
        json={},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    value = response.get_json()
    assert value["view_url"] == f"/api/articles/{article_id}/web-edition"
    assert value["download_url"] == (
        f"/api/articles/{article_id}/web-edition?download=1"
    )
    view = client.get(value["view_url"])
    html = view.get_data(as_text=True)

    assert html.startswith("<!doctype html>")
    assert "<script" not in html.lower()
    assert 'href="http' not in html
    assert 'src="http' not in html
    assert view.headers["Content-Security-Policy"] == (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        "script-src 'none'; connect-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'none'"
    )
    assert "style-src 'self'" in client.get("/login").headers[
        "Content-Security-Policy"
    ]
    assert client.get(value["download_url"]).headers[
        "Content-Security-Policy"
    ] == view.headers["Content-Security-Policy"]


def test_web_edition_api_rejects_request_body_injection(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0][
        "article_id"
    ]

    response = client.post(
        f"/api/articles/{article_id}/web-edition",
        json={"html": "<script>alert(1)</script>", "path": "../../x"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 400


def test_review_ui_labels_non_blocking_editorial_warnings():
    script = (
        Path(__file__).parents[2]
        / "ai_content_loop"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert 'below_target_length: "未达到平台建议篇幅"' in script
    assert 'editorial_placeholder: "正文包含编辑占位文字"' in script
