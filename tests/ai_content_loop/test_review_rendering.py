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


def test_render_rich_article_renders_whitelisted_press_blocks_as_escaped_html():
    from ai_content_loop.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": "press",
            "blocks": [
                {
                    "type": "hero",
                    "title": "<script>不能执行</script>",
                    "deck": "先看结论",
                },
                {"type": "lead", "text": "这是导读"},
                {"type": "key_judgment", "text": "关键判断"},
                {
                    "type": "section",
                    "heading": "主要发现",
                    "paragraphs": ["第一段", "第二段"],
                },
                {
                    "type": "workflow_compare",
                    "before": "之前的方式",
                    "after": "现在的方式",
                    "remaining_friction": "仍需核验",
                },
                {
                    "type": "quote",
                    "text": "只能把它当候选结论",
                    "attribution": "项目文档",
                },
                {"type": "callout", "text": "人工审核是最后一道门"},
                {
                    "type": "source_note",
                    "url": "https://example.com/source",
                    "attribution": "原始来源",
                },
            ],
        }
    )

    assert "<style>" in html
    assert 'class="rich-article__toc"' in html
    assert "<script>" not in html
    assert "&lt;script&gt;不能执行&lt;/script&gt;" in html
    assert 'href="https://example.com/source"' in html
    assert "主要发现" in html


def test_render_rich_article_falls_back_for_an_empty_or_untrusted_layout():
    from ai_content_loop.review.rich_article import render_rich_article

    html = render_rich_article(
        {"theme": "press", "blocks": []},
        fallback_title="旧文章标题",
        fallback_markdown="# 旧文章标题\n\n正文内容",
    )

    assert "旧文章标题" in html
    assert "正文内容" in html
    assert "<style>" in html
