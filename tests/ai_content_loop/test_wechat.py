import json
from urllib.request import Request
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


def test_wechat_renderer_distributes_multiple_body_images():
    from ai_content_loop.wechat.rendering import render_wechat_article

    layout = {
        "theme": "press",
        "structure": "explainer",
        "blocks": [
            {"type": "hero", "title": "标题", "deck": "收益"},
            {"type": "lead", "text": "结论"},
            {"type": "section", "heading": "第一步", "paragraphs": ["正文一"]},
            {"type": "section", "heading": "第二步", "paragraphs": ["正文二"]},
        ],
    }
    urls = [
        "https://mmbiz.qpic.cn/body-01.png",
        "https://mmbiz.qpic.cn/body-02.png",
    ]

    html = render_wechat_article(
        layout,
        fallback_title="unused",
        fallback_markdown="unused",
        body_image_urls=urls,
    )

    assert all(f'src="{url}"' in html for url in urls)
    assert html.index(urls[0]) < html.index("第一步")
    assert html.index(urls[1]) > html.index("第一步")


def test_wechat_kama_theme_uses_sample_derived_inline_reading_styles():
    from ai_content_loop.wechat.rendering import render_wechat_article

    html = render_wechat_article(
        {
            "theme": "kama",
            "structure": "explainer",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "先把收益说清楚"},
                {"type": "key_judgment", "text": "这句值得读者记住。"},
                {
                    "type": "section",
                    "heading": "它到底解决了什么？",
                    "paragraphs": ["一段只说一件事。", "下一段继续推进。"],
                },
            ],
        },
        fallback_title="unused",
        fallback_markdown="unused",
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert "#0e88eb" in html.lower()
    assert "border-left:5px solid #0e88eb" in html.lower()
    assert "font-size:15px" in html
    assert "line-height:1.8" in html
    assert "关键判断" not in html


def test_wechat_layout_never_drops_full_platform_markdown_paragraphs():
    from ai_content_loop.wechat.rendering import render_wechat_article

    source_url = "https://example.com/source"
    html = render_wechat_article(
        {
            "theme": "press",
            "structure": "briefing",
            "blocks": [
                {"type": "hero", "title": "完整文章", "deck": "摘要"},
                {
                    "type": "section",
                    "heading": "摘要",
                    "paragraphs": ["摘要"],
                },
                {
                    "type": "source_note",
                    "url": source_url,
                    "attribution": "原始来源",
                },
            ],
        },
        fallback_title="完整文章",
        fallback_markdown=(
            "第一段必须进入公众号。\n\n{{asset:body-01}}\n\n"
            "第二段也必须进入公众号。\n\n"
            f"来源：{source_url}"
        ),
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert "第一段必须进入公众号。" in html
    assert "第二段也必须进入公众号。" in html
    assert "{{asset:" not in html
    assert html.count(source_url) == 1


def test_wechat_layout_deduplicates_the_hero_deck_and_lead():
    from ai_content_loop.wechat.rendering import render_wechat_article

    repeated = "同一段摘要在公众号里也只应该出现一次。"
    html = render_wechat_article(
        {
            "theme": "vignelli",
            "structure": "essay",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": repeated},
                {"type": "lead", "text": repeated},
                {"type": "section", "heading": "正文", "paragraphs": ["正文段落。"]},
            ],
        },
        fallback_title="标题",
        fallback_markdown="正文段落。",
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert html.count(repeated) == 1


def test_wechat_renderer_removes_legacy_generic_headings_from_authored_intro():
    from ai_content_loop.wechat.rendering import render_wechat_article

    html = render_wechat_article(
        {
            "theme": "press",
            "structure": "briefing",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "摘要"},
                {
                    "type": "section",
                    "heading": "先看发生了什么",
                    "paragraphs": ["引言第一段。", "引言第二段。"],
                },
                {
                    "type": "section",
                    "heading": "关键事实与细节",
                    "paragraphs": ["作者正文。"],
                },
            ],
        },
        fallback_title="标题",
        fallback_markdown=(
            "引言第一段。\n\n引言第二段。\n\n"
            "## 作者写的具体问题\n\n作者正文。"
        ),
        body_image_url="https://mmbiz.qpic.cn/body.png",
    )

    assert "先看发生了什么" not in html
    assert "关键事实与细节" not in html
    assert "作者写的具体问题" in html
    assert html.index("引言第二段。") < html.index("作者写的具体问题")


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return json.dumps(self.responses.pop(0)).encode("utf-8")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.weixin.qq.com",
        "https://user:pass@api.weixin.qq.com",
        "https://api.weixin.qq.com?token=unsafe",
        "https://api.weixin.qq.com/#fragment",
    ],
)
def test_wechat_client_rejects_unsafe_api_base_urls(base_url):
    from ai_content_loop.wechat.client import WechatClient

    with pytest.raises(ValueError, match="safe HTTPS URL"):
        WechatClient("app-id", "super-secret", api_base_url=base_url)


def test_default_wechat_transport_disables_redirects(monkeypatch):
    import ai_content_loop.wechat.client as client_module

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    class Opener:
        def open(self, request, timeout):
            assert timeout == 30
            return Response()

    handlers = []

    def fake_build_opener(*values):
        handlers.extend(values)
        return Opener()

    monkeypatch.setattr(client_module, "build_opener", fake_build_opener, raising=False)
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("redirect-following urlopen was used"),
        raising=False,
    )

    assert client_module._default_transport(Request("https://api.weixin.qq.com")) == b"{}"
    assert handlers
    assert handlers[0].redirect_request(None, None, None, None, {}, None) is None


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


def test_wechat_client_upgrades_official_http_body_image_url_to_https(tmp_path):
    from ai_content_loop.wechat.client import WechatApiError, WechatClient

    image = tmp_path / "body.png"
    image.write_bytes(b"png")
    official = WechatClient(
        "app-id",
        "super-secret",
        transport=FakeTransport(
            [{"url": "http://mmbiz.qpic.cn/body.png?wx_fmt=png"}]
        ),
    )

    assert official.upload_body_image("token-value", image) == (
        "https://mmbiz.qpic.cn/body.png?wx_fmt=png"
    )

    untrusted = WechatClient(
        "app-id",
        "super-secret",
        transport=FakeTransport([{"url": "http://example.com/body.png"}]),
    )
    with pytest.raises(WechatApiError, match="safe image URL"):
        untrusted.upload_body_image("token-value", image)


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


def test_wechat_draft_sync_store_supports_pending_result(tmp_path):
    from ai_content_loop.db import ContentStore

    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.record_wechat_draft_sync(
        "github:owner/repo",
        "v1",
        status="pending",
        media_id=None,
        error="WeChat draft result is unknown",
    )

    row = store.get_wechat_draft_sync("github:owner/repo", "v1")
    assert row["status"] == "pending"
