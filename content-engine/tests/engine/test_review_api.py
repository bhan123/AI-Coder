import json
from pathlib import Path
import re
import subprocess

import pytest
from werkzeug.security import generate_password_hash

PACK_ROOT = Path(__file__).resolve().parents[2] / "packs" / "ai-news"

from engine.db import ContentStore
from engine.editorial.schema import ARTICLE_THEMES, article_id_for
from engine.generation import validate_generation_payload
from engine.gpt_polish import AUDITS, DIMENSIONS
from engine.models import SourceItem
from engine.review.app import create_app
from engine.visuals.pipeline import insert_body_asset_marker

PACK_ROOT = Path(__file__).resolve().parents[2] / "packs" / "ai-news"


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"


def _workspace_css_rules(css: str) -> list[dict[str, str]]:
    rules = []
    for match in re.finditer(
        r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", css, re.DOTALL
    ):
        selectors = match.group("selectors").split(",")
        if not any(
            re.search(r"(?<![\w-])\.workspace(?![\w-])", selector)
            for selector in selectors
        ):
            continue
        declarations = {}
        for declaration in match.group("body").split(";"):
            if ":" not in declaration:
                continue
            property_name, value = declaration.split(":", 1)
            declarations[property_name.strip().lower()] = value.strip().lower()
        rules.append(declarations)
    return rules


def _assert_workspace_scrollability(css: str) -> None:
    workspace_rules = _workspace_css_rules(css)
    assert workspace_rules, "expected a .workspace CSS rule"

    base_rule = workspace_rules[0]
    assert base_rule.get("min-height") == "0"
    assert base_rule.get("overflow-x") == "hidden"
    assert base_rule.get("overflow-y") == "auto"

    for rule in workspace_rules[1:]:
        assert (
            "overflow" not in rule
        ), "subsequent .workspace rules must not set overflow"
        overflow_y = rule.get("overflow-y", "").removesuffix(" !important")
        assert overflow_y not in {"hidden", "clip"}, (
            "subsequent .workspace rules must not set overflow-y " f"to {overflow_y}"
        )


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
    body = f"{'正文内容足够长。' * 90}\n\n来源：{SOURCE_URL}"
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
            "REVIEW_PASSWORD_HASH": generate_password_hash("correct horse"),
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
    assert response.get_json()["payload"]["master_title"] == "浏览器里修改的标题"


def test_article_api_exposes_advisory_reader_feedback(review_app):
    client = review_app.test_client()
    login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

    loaded = client.get(f"/api/articles/{article_id}").get_json()

    feedback = loaded["reader_feedback"]
    assert feedback["version"] == "reader-feedback-v1"
    assert len(feedback["dimensions"]) == 5
    assert feedback["priority"]["key"] in {
        item["key"] for item in feedback["dimensions"]
    }


def valid_gpt_polish_proposal():
    def scores(items):
        return [
            {
                "key": key,
                "label": label,
                "score": 4.3,
                "evidence": f"{label}有具体证据。",
                "suggestion": f"继续增强{label}。",
            }
            for key, label in items
        ]

    body = (
        "# 先别急着追最强模型\n\n"
        + "一个反直觉的事实是：先把低风险流程跑通，往往比追逐参数更能提效。\n\n"
        + "这里用普通人能理解的例子拆开说明，并给出今天就能执行的小步骤。" * 50
        + f"\n\n来源：{SOURCE_URL}"
    )
    return {
        "version": "gpt-polish-v1",
        "master_title": "先别追最强模型：真正省时间的是这一步",
        "master_markdown": body,
        "platform_markdown": {
            platform: body
            for platform in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
        "assessment": {
            "overall": 4.3,
            "verdict": "更值得读",
            "summary": "开头有钩子，中段更易懂，结尾能落到行动。",
            "dimensions": scores(DIMENSIONS),
            "audits": scores(AUDITS),
        },
        "change_summary": ["重写标题和开头", "增加具体行动", "收紧结尾"],
    }


def test_live_reader_feedback_requires_login_csrf_and_bounded_text(review_app):
    client = review_app.test_client()
    path = "/api/editorial-feedback"
    payload = {
        "title": "短视频流水线把成本挪到了哪里",
        "markdown": "晚上还在找素材。\n\n先用低风险任务测试，失败就不要迁移正式流程。",
    }

    assert client.post(path, json=payload).status_code == 401
    csrf = login(client)
    assert client.post(path, json=payload).status_code == 403
    assert (
        client.post(
            path,
            json={"title": "标题", "markdown": None},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 400
    )

    response = client.post(
        path,
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.get_json()["reader_feedback"]["version"] == "reader-feedback-v1"


def test_gpt_polish_api_queues_candidate_and_applies_only_after_confirmation(
    review_app,
):
    client = review_app.test_client()
    article_id = article_id_for(DEDUPE_KEY)

    assert client.post(f"/api/articles/{article_id}/gpt-polish").status_code == 401
    csrf = login(client)
    assert client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "revision_requested"},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    assert loaded["gpt_polish"] is None
    assert client.post(
        f"/api/articles/{article_id}/gpt-polish",
        json={"version": loaded["version"]},
    ).status_code == 403

    queued_response = client.post(
        f"/api/articles/{article_id}/gpt-polish",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert queued_response.status_code == 200
    queued = queued_response.get_json()["gpt_polish"]
    assert queued["status"] == "queued"
    assert queued["request"]["source_url"] == SOURCE_URL
    assert queued["request"]["rule_feedback"]["master"]["version"] == (
        "reader-feedback-v1"
    )

    store = ContentStore(review_app.config["DATABASE_PATH"])
    claimed = store.claim_next_gpt_polish_job("windows-codex")
    assert claimed["job_id"] == queued["job_id"]
    assert store.submit_gpt_polish_proposal(
        queued["job_id"], "windows-codex", valid_gpt_polish_proposal()
    )

    ready = client.get(
        f"/api/articles/{article_id}/gpt-polish"
    ).get_json()["gpt_polish"]
    assert ready["status"] == "ready"
    assert ready["proposal"]["assessment"]["overall"] == 4.3
    unchanged = client.get(f"/api/articles/{article_id}").get_json()
    assert unchanged["payload"]["master_title"] == loaded["payload"]["master_title"]

    applied_response = client.post(
        f"/api/articles/{article_id}/gpt-polish/{queued['job_id']}/apply",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert applied_response.status_code == 200
    applied = applied_response.get_json()
    assert applied["payload"]["master_title"] == (
        "先别追最强模型：真正省时间的是这一步"
    )
    assert applied["gpt_polish"]["status"] == "applied"
    queue = {row["dedupe_key"]: row for row in store.list_publish_queue()}
    assert queue[DEDUPE_KEY]["status"] == "needs_human_review"
    assert client.post(
        f"/api/articles/{article_id}/gpt-polish/{queued['job_id']}/apply",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).status_code in {404, 409}


def test_gpt_polish_apply_accepts_markdown_lists_and_inline_emphasis(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = article_id_for(DEDUPE_KEY)
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    queued = client.post(
        f"/api/articles/{article_id}/gpt-polish",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["gpt_polish"]

    proposal = valid_gpt_polish_proposal()
    body = (
        "# 先别急着做一个大网站\n\n"
        "真正省时间的办法，是先从**低风险场景**验证价值。\n\n"
        "## 一个今天就能试的判断法\n\n"
        "- 大家是否在反复回答同一个问题？\n"
        "- 每次比较方案都要重新翻资料？\n"
        "- 新人总在寻找同一批链接？\n\n"
        + "如果答案是肯定的，就先做一个内部页面，把信息收拢并交给真实同事试用。"
        * 35
        + f"\n\n来源：{SOURCE_URL}"
    )
    proposal["master_markdown"] = body
    proposal["platform_markdown"] = {
        platform: body
        for platform in ("wechat", "xiaohongshu", "toutiao", "zhihu")
    }
    store = ContentStore(review_app.config["DATABASE_PATH"])
    claimed = store.claim_next_gpt_polish_job("windows-codex")
    assert claimed["job_id"] == queued["job_id"]
    assert store.submit_gpt_polish_proposal(
        queued["job_id"], "windows-codex", proposal
    )

    response = client.post(
        f"/api/articles/{article_id}/gpt-polish/{queued['job_id']}/apply",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    layout = response.get_json()["payload"]["article_layout"]
    assert all(
        "**" not in value and not value.lstrip().startswith(("- ", "* ", "+ "))
        for block in layout["blocks"]
        for value in (
            [block.get("title", ""), block.get("deck", ""), block.get("text", "")]
            + block.get("paragraphs", [])
        )
        if isinstance(value, str)
    )


def test_gpt_polish_apply_treats_platform_target_length_as_advisory(review_app):
    article_id = article_id_for(DEDUPE_KEY)
    revision = "e" * 64
    asset_dir = Path(review_app.config["ASSET_DIR"]) / article_id / revision
    asset_dir.mkdir(parents=True)
    (asset_dir / "cover.jpg").write_bytes(b"cover")
    (asset_dir / "body.png").write_bytes(b"body")
    payload = make_payload()
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
    (Path(review_app.config["FINAL_DIR"]) / "repo.json").write_text(
        json.dumps(insert_body_asset_marker(payload), ensure_ascii=False),
        encoding="utf-8",
    )

    client = review_app.test_client()
    csrf = login(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    queued = client.post(
        f"/api/articles/{article_id}/gpt-polish",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["gpt_polish"]

    proposal = valid_gpt_polish_proposal()
    short_xiaohongshu = (
        "# 三步判断 AI 值不值得买\n\n"
        + "先找重复劳动，再用低风险任务试跑，最后只看真实节省的时间。"
        * 18
        + f"\n\n来源：{SOURCE_URL}"
    )
    proposal["platform_markdown"]["xiaohongshu"] = short_xiaohongshu
    store = ContentStore(review_app.config["DATABASE_PATH"])
    claimed = store.claim_next_gpt_polish_job("windows-codex")
    assert claimed["job_id"] == queued["job_id"]
    assert store.submit_gpt_polish_proposal(
        queued["job_id"], "windows-codex", proposal
    )

    response = client.post(
        f"/api/articles/{article_id}/gpt-polish/{queued['job_id']}/apply",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    applied = response.get_json()
    assert applied["version"] != loaded["version"]
    assert (
        applied["payload"]["platform_markdown"]["xiaohongshu"]
        == short_xiaohongshu
    )
    assert applied["gpt_polish"]["status"] == "applied"

    approved = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert approved.status_code == 200


def test_stale_save_returns_conflict(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]
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
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    changed = dict(loaded["payload"])
    changed["master_title"] = "新标题"
    saved = client.put(
        f"/api/articles/{article_id}",
        json={"payload": changed, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).get_json()

    history = client.get(f"/api/articles/{article_id}/history").get_json()["history"]
    restored = client.post(
        f"/api/articles/{article_id}/restore/{history[0]['history_id']}",
        json={"version": saved["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert restored.status_code == 200
    assert restored.get_json()["payload"]["master_title"] == "一个值得关注的开源项目"

    status_response = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "revision_requested"},
        headers={"X-CSRF-Token": csrf},
    )
    assert status_response.status_code == 200
    returned = client.get("/api/articles?status=revision_requested").get_json()
    assert [row["article_id"] for row in returned["articles"]] == [article_id]


def test_api_rejects_invalid_filter_and_save_version(review_app):
    client = review_app.test_client()
    csrf = login(client)

    assert client.get("/api/articles?status=generating").status_code == 400
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]
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
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

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
        "structure": "briefing",
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
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

    html = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["html"]

    assert "https://example.com/source" in html
    assert 'href="https://example.com/source"' not in html
    assert "target=" not in html


def generated_press_payload():
    """Return the model-stage payload before server-side visual rendering."""

    payload = make_payload()
    title = payload["master_title"]
    lead = payload["master_markdown"].split("\n\n", 1)[0]
    payload["article_layout"] = {
        "theme": "press",
        "structure": "briefing",
        "blocks": [
            {"type": "hero", "title": title, "deck": lead},
            {"type": "lead", "text": lead},
            {"type": "key_judgment", "text": lead},
            {
                "type": "section",
                "heading": title,
                "paragraphs": [lead],
            },
            {"type": "callout", "text": lead},
            {
                "type": "source_note",
                "url": SOURCE_URL,
                "attribution": title,
            },
        ],
    }
    return payload


def test_rich_preview_fallback_allows_no_protocol_relative_url(review_app):
    article_path = Path(review_app.config["FINAL_DIR"]) / "repo.json"
    payload = json.loads(article_path.read_text(encoding="utf-8"))
    payload["master_markdown"] = (
        "[绕过](//example.com/path)\n\n![图](//example.com/a.png)"
    )
    payload["article_layout"] = {
        "theme": "press",
        "structure": "briefing",
        "blocks": [],
    }
    article_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

    html = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["html"]

    assert "href=" not in html
    assert "src=" not in html


def test_generated_press_article_can_be_approved_exported_and_is_revoked_on_edit(
    review_app,
):
    """Exercise the contract across generation, review, export, and editing."""

    article_path = Path(review_app.config["FINAL_DIR"]) / "repo.json"
    generated = generated_press_payload()
    lead = generated["master_markdown"].split("\n\n", 1)[0]
    hard, _warnings = validate_generation_payload(
        generated,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
        require_rich_layout=True,
        layout_fact_evidence={
            "title": generated["master_title"],
            "facts": [lead],
            "source_url": SOURCE_URL,
        },
    )
    assert hard == []

    # Visual rendering is server-owned and happens only after model output has
    # cleared the generation contract.  Supply its canonical persisted result
    # so approval exercises the real asset gate rather than bypassing it.
    article_id = article_id_for(DEDUPE_KEY)
    revision = "c" * 64
    asset_dir = Path(review_app.config["ASSET_DIR"]) / article_id / revision
    asset_dir.mkdir(parents=True)
    (asset_dir / "cover.jpg").write_bytes(b"cover")
    (asset_dir / "body.png").write_bytes(b"body")
    generated["visual_assets"] = {
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
    article_path.write_text(
        json.dumps(insert_body_asset_marker(generated), ensure_ascii=False),
        encoding="utf-8",
    )

    client = review_app.test_client()
    csrf = login(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    preview = client.post(
        "/api/rich-preview",
        json={"article_id": article_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    assert (
        'class="rich-article rich-article--press rich-article--briefing"'
        in preview.get_json()["html"]
    )
    assert (
        f"/api/articles/{article_id}/assets/body-01/{revision}"
        in preview.get_json()["html"]
    )

    approved = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert approved.status_code == 200
    exported = client.post(
        f"/api/articles/{article_id}/web-edition",
        json={},
        headers={"X-CSRF-Token": csrf},
    )
    assert exported.status_code == 200
    assert (
        Path(review_app.config["OUTPUT_DIR"]) / "web" / f"{article_id}.html"
    ).is_file()

    replacement = dict(loaded["payload"])
    replacement["master_title"] = "Edited title revokes the prior export"
    saved = client.put(
        f"/api/articles/{article_id}",
        json={"payload": replacement, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200
    assert client.get(exported.get_json()["view_url"]).status_code == 404
    assert (
        client.get("/api/articles?status=needs_human_review").get_json()["articles"][0][
            "article_id"
        ]
        == article_id
    )


def test_review_page_contains_editor_shell(review_app):
    client = review_app.test_client()
    login(client)

    html = client.get("/").get_data(as_text=True)

    assert 'id="article-list"' in html
    assert 'id="article-search"' in html
    assert 'id="progress-filter"' in html
    assert 'id="markdown-editor"' in html
    assert 'id="article-preview"' in html
    assert 'id="save-button"' in html
    assert 'id="history-dialog"' in html
    assert 'id="reader-feedback-panel"' in html
    assert 'id="reader-feedback-summary"' in html
    assert 'id="reader-feedback-grid"' in html
    assert 'id="gpt-polish-request-button"' in html
    assert 'id="gpt-polish-apply-button"' in html
    assert 'id="gpt-polish-before"' in html
    assert 'id="gpt-polish-after"' in html
    assert 'data-platform="wechat"' in html
    assert 'data-platform="xiaohongshu"' in html
    assert 'data-platform="toutiao"' in html
    assert 'data-platform="zhihu"' in html
    assert 'href="/static/rich_article.css"' in html


def test_review_page_exposes_live_reader_feedback_loop():
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert '"/api/editorial-feedback"' in script
    assert "renderReaderFeedback" in script
    assert "scheduleReaderFeedback" in script
    assert "reader-feedback-v1" in script


def test_review_page_serves_rich_article_styles_from_own_static_origin(
    review_app,
):
    css = (
        review_app.test_client().get("/static/rich_article.css").get_data(as_text=True)
    )

    assert ".rich-article__toc" in css
    assert ".rich-article__hero" in css
    for theme in ARTICLE_THEMES:
        assert f".rich-article--{theme}" in css
        assert f"--rich-theme: {theme};" in css


def test_create_app_loads_production_environment(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'database_path = "data/content.sqlite3"\n'
        'output_dir = "out"\n'
        f'pack_dir = "{PACK_ROOT.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENT_ENGINE_CONFIG", str(config_path))
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

    assert app.config["DATABASE_PATH"] == tmp_path / "data" / "content.sqlite3"
    assert app.config["FINAL_DIR"] == tmp_path / "out" / "final"
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_responses_include_security_headers(review_app):
    response = review_app.test_client().get("/login")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_review_styles_preserve_hidden_state(review_app):
    css = review_app.test_client().get("/static/review.css").get_data(as_text=True)

    assert "[hidden]" in css
    assert "display: none !important" in css


def test_review_sidebar_renders_generated_date():
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert "formatArticleDate" in script
    assert "article.generated_date" in script
    assert "article-date" in script


def test_review_sidebar_exposes_review_gpt_and_wechat_progress(review_app):
    client = review_app.test_client()
    login(client)

    article = client.get("/api/articles").get_json()["articles"][0]
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert article["gpt_polish_status"] is None
    assert article["wechat_draft_status"] == "not_synced"
    assert "filterVisibleArticles" in script
    assert "article.gpt_polish_status" in script
    assert "article.wechat_draft_status" in script


def test_web_edition_api_exports_only_approved_server_owned_article(
    review_app,
):
    client = review_app.test_client()
    assert client.post("/api/articles/nope/web-edition").status_code == 401
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

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
    assert "style-src 'self'" in client.get("/login").headers["Content-Security-Policy"]
    assert (
        client.get(value["download_url"]).headers["Content-Security-Policy"]
        == view.headers["Content-Security-Policy"]
    )
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    updated_payload = dict(loaded["payload"])
    updated_payload["master_title"] = "编辑后需要重新导出的标题"
    saved = client.put(
        f"/api/articles/{article_id}",
        json={"payload": updated_payload, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert saved.status_code == 200
    assert client.get(value["view_url"]).status_code == 404
    assert (
        client.post(
            f"/api/articles/{article_id}/web-edition",
            json={},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 400
    )
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    assert (
        client.post(
            f"/api/articles/{article_id}/web-edition",
            json={},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    assert client.get(value["view_url"]).status_code == 200


def test_web_edition_api_rejects_request_body_injection(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]

    response = client.post(
        f"/api/articles/{article_id}/web-edition",
        json={"html": "<script>alert(1)</script>", "path": "../../x"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 400


def test_review_ui_labels_non_blocking_editorial_warnings():
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert 'below_target_length: "未达到平台建议篇幅"' in script
    assert 'editorial_placeholder: "正文包含编辑占位文字"' in script


def test_review_page_exposes_safe_rich_preview_and_approved_export_controls(
    review_app,
):
    client = review_app.test_client()
    login(client)
    html = client.get("/").get_data(as_text=True)
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    for element_id in (
        "rich-preview-button",
        "rich-preview-pane",
        "rich-article-preview",
        "rich-preview-close-button",
        "export-web-edition-button",
        "web-edition-links",
    ):
        assert f'id="{element_id}"' in html

    assert 'api("/api/rich-preview"' in script
    assert "/web-edition" in script
    assert "updateWebEditionControls" in script
    assert "clearWebEditionLinks" in script
    assert "richArticlePreview.innerHTML = value.html" in script


class _FakeWechatClient:
    def __init__(self, *, fail=False, fail_draft=False):
        self.fail = fail
        self.fail_draft = fail_draft
        self.calls = []

    def get_access_token(self):
        from engine.wechat.client import WechatApiError

        self.calls.append("token")
        if self.fail:
            raise WechatApiError("WeChat API error (errcode=45009)")
        return "token"

    def upload_permanent_image(self, token, path):
        self.calls.append(("cover", Path(path).name))
        return "cover-media"

    def upload_body_image(self, token, path):
        self.calls.append(("body", Path(path).name))
        return "https://mmbiz.qpic.cn/body.png"

    def add_draft(self, token, *, title, content, thumb_media_id):
        from engine.wechat.client import WechatApiError

        self.calls.append(("draft", title, content, thumb_media_id))
        if self.fail_draft:
            raise WechatApiError("WeChat API request failed")
        return "draft-media"


def _prepare_approved_wechat_article(review_app):
    article_id = article_id_for(DEDUPE_KEY)
    article_path = Path(review_app.config["FINAL_DIR"]) / "repo.json"
    payload = generated_press_payload()
    revision = "d" * 64
    asset_dir = Path(review_app.config["ASSET_DIR"]) / article_id / revision
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "cover.jpg").write_bytes(b"cover")
    (asset_dir / "body.png").write_bytes(b"body")
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
    article_path.write_text(
        json.dumps(insert_body_asset_marker(payload), ensure_ascii=False),
        encoding="utf-8",
    )
    repository = review_app.extensions["article_repository"]
    repository.store.set_review_status(DEDUPE_KEY, "approved")
    return article_id


def test_wechat_draft_api_requires_configuration_approval_and_csrf(review_app):
    client = review_app.test_client()
    article_id = article_id_for(DEDUPE_KEY)
    assert client.post(f"/api/articles/{article_id}/wechat/draft").status_code == 401
    csrf = login(client)

    unconfigured = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": "x" * 64},
        headers={"X-CSRF-Token": csrf},
    )
    assert unconfigured.status_code == 503
    assert unconfigured.get_json()["status"] == "not_configured"

    review_app.extensions["wechat_client"] = _FakeWechatClient()
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    unapproved = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert unapproved.status_code == 400
    assert "approved" in unapproved.get_json()["detail"]
    assert (
        client.post(
            f"/api/articles/{article_id}/wechat/draft",
            json={"version": loaded["version"]},
        ).status_code
        == 403
    )


def test_wechat_draft_api_creates_once_and_returns_persisted_success(review_app):
    article_id = _prepare_approved_wechat_article(review_app)
    fake = _FakeWechatClient()
    review_app.extensions["wechat_client"] = fake
    client = review_app.test_client()
    csrf = login(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()

    stale = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": "0" * 64},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409
    assert fake.calls == []

    first = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    second = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == second.status_code == 200
    assert first.get_json()["status"] == "success"
    assert first.get_json()["media_id"] == "draft-media"
    assert second.get_json()["idempotent"] is True
    assert [
        call for call in fake.calls if isinstance(call, tuple) and call[0] == "draft"
    ]
    assert len([call for call in fake.calls if call == "token"]) == 1
    draft_call = next(
        call for call in fake.calls if isinstance(call, tuple) and call[0] == "draft"
    )
    assert "https://mmbiz.qpic.cn/body.png" in draft_call[2]
    assert "<script" not in draft_call[2]

    review_app.extensions["wechat_client"] = None
    persisted = client.get(f"/api/articles/{article_id}").get_json()
    assert persisted["wechat_draft"]["status"] == "success"
    assert persisted["wechat_draft"]["media_id"] == "draft-media"


def test_wechat_draft_api_blocks_retry_when_create_result_is_unknown(review_app):
    article_id = _prepare_approved_wechat_article(review_app)
    fake = _FakeWechatClient(fail_draft=True)
    review_app.extensions["wechat_client"] = fake
    client = review_app.test_client()
    csrf = login(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()

    first = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    second = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == 502
    assert first.get_json()["status"] == "pending"
    assert second.status_code == 400
    assert "核对" in second.get_json()["detail"]
    assert len(
        [call for call in fake.calls if isinstance(call, tuple) and call[0] == "draft"]
    ) == 1
    row = review_app.extensions["article_repository"].store.get_wechat_draft_sync(
        DEDUPE_KEY, loaded["version"]
    )
    assert row["status"] == "pending"


def test_wechat_draft_api_persists_safe_error_without_credentials(review_app):
    article_id = _prepare_approved_wechat_article(review_app)
    review_app.extensions["wechat_client"] = _FakeWechatClient(fail=True)
    client = review_app.test_client()
    csrf = login(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()

    response = client.post(
        f"/api/articles/{article_id}/wechat/draft",
        json={"version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "wechat_api_error",
        "detail": "WeChat API error (errcode=45009)",
        "status": "error",
    }
    row = review_app.extensions["article_repository"].store.get_wechat_draft_sync(
        DEDUPE_KEY, loaded["version"]
    )
    assert row["status"] == "error"
    assert row["media_id"] is None


def test_review_page_exposes_manual_wechat_draft_control(review_app):
    client = review_app.test_client()
    login(client)
    html = client.get("/").get_data(as_text=True)
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert 'id="wechat-draft-button"' in html
    assert 'id="wechat-draft-status"' in html
    assert "/wechat/draft" in script
    assert 'state.articleStatus !== "approved"' in script
    assert "state.dirty" in script


def test_review_page_refreshes_article_list_after_returning_to_the_tab(review_app):
    script = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    ).read_text(encoding="utf-8")

    assert 'window.addEventListener("focus", refreshArticlesOnFocus)' in script
    assert "if (state.dirty) return;" in script
    assert "await loadArticles(statusFilter.value);" in script
    assert "发现新文章，请在左侧打开查看" in script


def test_rich_preview_stays_inside_the_single_scrollable_workspace(
    review_app,
):
    client = review_app.test_client()
    login(client)
    html = client.get("/").get_data(as_text=True)
    css = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.css"
    ).read_text(encoding="utf-8")

    assert 'id="preview-workspace"' in html
    assert html.index('id="preview-workspace"') < html.index('id="rich-preview-pane"')
    assert "height: auto;" in css
    assert "min-height: 100%;" in css
    assert "minmax(520px, 1fr)" in css
    assert ".preview-workspace" in css
    assert "min-height: 520px" in css


def test_review_layout_keeps_rich_preview_in_scrollable_workspace():
    css = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.css"
    ).read_text(encoding="utf-8")

    _assert_workspace_scrollability(css)


def test_workspace_scrollability_rejects_hidden_vertical_override():
    css_with_hidden_override = """
    .workspace {
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }

    @media (max-height: 700px) {
      .workspace {
        overflow-y: hidden;
      }
    }
    """

    with pytest.raises(AssertionError, match="overflow-y.*hidden"):
        _assert_workspace_scrollability(css_with_hidden_override)


@pytest.mark.parametrize(
    "workspace_override",
    [
        ".workspace, .compact-workspace { overflow: hidden !important; }",
        ".workspace.is-compact { overflow-y: clip !important; }",
    ],
)
def test_workspace_scrollability_rejects_compound_workspace_overrides(
    workspace_override,
):
    css = f"""
    .workspace {{
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }}
    {workspace_override}
    """

    with pytest.raises(AssertionError):
        _assert_workspace_scrollability(css)


def test_workspace_scrollability_ignores_non_workspace_rules():
    css = """
    .workspace {
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }
    .compact-workspace { overflow: hidden !important; }
    """

    _assert_workspace_scrollability(css)


def test_rich_preview_runtime_discards_stale_response_and_recovers_button():
    script_path = (
        Path(__file__).parents[2]
        / "engine"
        / "review"
        / "static"
        / "review.js"
    )
    node_script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");

class Element {
  constructor() {
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.content = "csrf";
    this.dataset = {};
    this.className = "";
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  addEventListener() {}
  append() {}
  replaceChildren(...children) { this.children = children; }
}

const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
}
let resolveRichResponse;
const context = {
  URL,
  console,
  document: {
    querySelector: element,
    querySelectorAll: () => [],
    createElement: () => new Element(),
  },
  navigator: {clipboard: {writeText: async () => {}}},
  window: {
    location: {origin: "https://review.example", assign() {}},
    setTimeout(callback) { callback(); return 0; },
    confirm() { return true; },
    addEventListener() {},
  },
  fetch(path) {
    if (path === "/api/rich-preview") {
      return new Promise((resolve) => {
        resolveRichResponse = () => resolve({
          ok: true,
          status: 200,
          json: async () => ({html: "<p>stale rich preview</p>"}),
        });
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({articles: []}),
    });
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  `${source}\nglobalThis.__reviewHooks = {state, showRichPreview, invalidateRichPreview};`,
  context,
);

(async () => {
  const hooks = context.__reviewHooks;
  const button = element("#rich-preview-button");
  const pane = element("#rich-preview-pane");
  const article = element("#rich-article-preview");
  hooks.state.articleId = "old-article";
  const pending = hooks.showRichPreview();
  await Promise.resolve();
  assert.equal(button.disabled, true);

  hooks.invalidateRichPreview();
  assert.equal(button.disabled, false);
  assert.equal(pane.hidden, true);
  resolveRichResponse();
  await pending;
  assert.notEqual(article.innerHTML, "<p>stale rich preview</p>");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        ["node", "-e", node_script, str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
