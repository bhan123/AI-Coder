from ai_content_loop.review.rendering import render_markdown


def test_render_markdown_supports_article_structure():
    html = render_markdown(
        "# 标题\n\n> 结论\n\n- 第一项\n- 第二项\n\n[来源](https://example.com)"
    )

    assert "<h1>标题</h1>" in html
    assert "<blockquote>" in html
    assert "<li>第一项</li>" in html
    assert 'href="https://example.com"' in html


def test_render_markdown_disables_raw_html():
    html = render_markdown(
        '<script>alert("x")</script>\n\n<img src=x onerror=alert(1)>'
    )

    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_render_markdown_expands_only_server_mapped_asset_markers():
    html = render_markdown(
        "开头\n\n{{asset:body-01}}\n\n结尾",
        asset_urls={
            "body-01": (
                "/api/articles/article/assets/body-01/"
                + "a" * 64
            )
        },
    )

    assert "<img" in html
    assert "/api/articles/article/assets/body-01/" in html
    assert "{{asset:" not in html
    assert 'alt=""' in html
    assert "正文配图" not in html


def test_render_markdown_replaces_unknown_or_malicious_asset_markers():
    html = render_markdown(
        "{{asset:not-current}}\n\n{{asset:../../etc/passwd}}",
        asset_urls={},
    )

    assert "<img" not in html
    assert "/etc/passwd" not in html
    assert html.count("图片尚未生成") == 2
