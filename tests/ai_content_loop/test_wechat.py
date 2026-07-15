import json
from urllib.parse import parse_qs, urlparse

import pytest


def test_wechat_renderer_escapes_layout_text_and_uses_only_https_body_image():
    from ai_content_loop.wechat.rendering import render_wechat_article

    layout = {
        "theme": "vignelli",
        "structure": "essay",
        "blocks": [
            {"type": "hero", "title": "<script>alert(1)</script>", "deck": "副标题"},
            {"type": "section", "heading": "第一节", "paragraphs": ["正文 & 内容"]},
        ],
    }
    html = render_wechat_article(
        layout,
        fallback_title="unused",
        fallback_markdown="unused",
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert "<script" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "正文 &amp; 内容" in html
    assert 'src="https://mmbiz.qpic.cn/body.png"' in html
    assert "class=" not in html
    assert "style=" in html

    with pytest.raises(ValueError, match="body image URL"):
        render_wechat_article(
            layout,
            fallback_title="unused",
            fallback_markdown="unused",
            body_image_url="javascript:alert(1)",
        )


def test_wechat_renderer_safely_falls_back_for_legacy_empty_layout():
    from ai_content_loop.wechat.rendering import render_wechat_article

    html = render_wechat_article(
        {"theme": "press", "blocks": []},
        fallback_title="标题 <img>",
        fallback_markdown="# 小节\n\n正文 <script>alert(1)</script>",
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert "标题 &lt;img&gt;" in html
    assert "正文 &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert 'src="https://mmbiz.qpic.cn/body.png"' in html


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return json.dumps(self.responses.pop(0)).encode("utf-8")


def test_wechat_client_calls_only_token_material_uploadimg_and_draft_endpoints(
    tmp_path,
):
    from ai_content_loop.wechat.client import WechatClient

    image = tmp_path / "cover.jpg"
    image.write_bytes(b"jpeg")
    transport = FakeTransport(
        [
            {"access_token": "token-value", "expires_in": 7200},
            {"media_id": "cover-media"},
            {"url": "https://mmbiz.qpic.cn/body.png"},
            {"media_id": "draft-media"},
        ]
    )
    client = WechatClient("app-id", "super-secret", transport=transport)

    token = client.get_access_token()
    assert token == "token-value"
    assert client.upload_permanent_image(token, image) == "cover-media"
    assert client.upload_body_image(token, image) == "https://mmbiz.qpic.cn/body.png"
    assert (
        client.add_draft(
            token,
            title="标题",
            content="<section>正文</section>",
            thumb_media_id="cover-media",
        )
        == "draft-media"
    )

    paths = [urlparse(item.full_url).path for item in transport.requests]
    assert paths == [
        "/cgi-bin/token",
        "/cgi-bin/material/add_material",
        "/cgi-bin/media/uploadimg",
        "/cgi-bin/draft/add",
    ]
    token_query = parse_qs(urlparse(transport.requests[0].full_url).query)
    assert token_query["appid"] == ["app-id"]
    assert token_query["secret"] == ["super-secret"]
    draft_payload = json.loads(transport.requests[-1].data.decode("utf-8"))
    assert draft_payload["articles"][0]["thumb_media_id"] == "cover-media"
    assert draft_payload["articles"][0]["content"] == "<section>正文</section>"


def test_wechat_client_errors_never_echo_credentials_or_token():
    from ai_content_loop.wechat.client import WechatApiError, WechatClient

    transport = FakeTransport(
        [{"errcode": 40013, "errmsg": "invalid appid super-secret token-value"}]
    )
    client = WechatClient("app-id", "super-secret", transport=transport)

    with pytest.raises(WechatApiError) as caught:
        client.get_access_token()

    message = str(caught.value)
    assert "40013" in message
    assert "super-secret" not in message
    assert "token-value" not in message


def test_wechat_client_rejects_credential_bearing_body_image_url(tmp_path):
    from ai_content_loop.wechat.client import WechatApiError, WechatClient

    image = tmp_path / "body.png"
    image.write_bytes(b"png")
    client = WechatClient(
        "app-id",
        "super-secret",
        transport=FakeTransport([{"url": "https://user:pass@example.com/body.png"}]),
    )

    with pytest.raises(WechatApiError, match="safe image URL"):
        client.upload_body_image("token-value", image)


def test_wechat_draft_sync_store_is_idempotent_and_failure_cannot_overwrite_success(
    tmp_path,
):
    from ai_content_loop.db import ContentStore

    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.record_wechat_draft_sync(
        "github:owner/repo",
        "v1",
        status="success",
        media_id="draft-one",
        error=None,
    )
    store.record_wechat_draft_sync(
        "github:owner/repo",
        "v1",
        status="error",
        media_id=None,
        error="temporary failure",
    )

    row = store.get_wechat_draft_sync("github:owner/repo", "v1")
    assert row["status"] == "success"
    assert row["media_id"] == "draft-one"
    assert row["error"] is None
