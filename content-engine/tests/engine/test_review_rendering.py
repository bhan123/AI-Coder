import pytest

from engine.editorial.schema import ARTICLE_STRUCTURES, ARTICLE_THEMES
from engine.review.rendering import render_markdown


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
    from engine.review.rich_article import render_rich_article

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

    assert "<style>" not in html
    assert 'class="rich-article__toc"' in html
    assert "<script>" not in html
    assert "&lt;script&gt;不能执行&lt;/script&gt;" in html
    assert "https://example.com/source" in html
    assert 'href="https://example.com/source"' not in html
    assert "target=" not in html
    assert "主要发现" in html


def test_rich_article_layout_never_drops_full_fallback_body_paragraphs():
    from engine.review.rich_article import render_rich_article

    source_url = "https://example.com/source"
    html = render_rich_article(
        {
            "theme": "vignelli",
            "structure": "essay",
            "blocks": [
                {"type": "hero", "title": "完整文章", "deck": "摘要"},
                {"type": "lead", "text": "摘要"},
                {
                    "type": "section",
                    "heading": "原布局只放了摘要",
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
            "# 完整文章\n\n第一段必须完整出现。\n\n"
            "{{asset:body-01}}\n\n第二段也不能被布局摘要丢掉。\n\n"
            f"来源：{source_url}"
        ),
    )

    assert "第一段必须完整出现。" in html
    assert "第二段也不能被布局摘要丢掉。" in html
    assert "{{asset:" not in html
    assert html.count(source_url) == 1


def test_rich_article_drops_a_lead_that_repeats_the_start_of_full_body():
    from engine.review.rich_article import render_rich_article

    repeated = "一份 GitHub 仓库，把 100 多个能直接跑的 AI 应用摆在你面前。"
    html = render_rich_article(
        {
            "theme": "press",
            "structure": "explainer",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "副标题"},
                {"type": "lead", "text": repeated},
                {
                    "type": "section",
                    "heading": "它到底是什么？",
                    "paragraphs": [repeated],
                },
            ],
        },
        fallback_title="标题",
        fallback_markdown=(
            f"{repeated} 下面用具体场景说明它能帮你做什么。\n\n"
            "第二段仍然必须完整保留。"
        ),
    )

    assert html.count(repeated) == 1
    assert "下面用具体场景说明它能帮你做什么。" in html
    assert "第二段仍然必须完整保留。" in html


def test_rich_article_drops_a_lead_that_duplicates_the_hero_deck():
    from engine.review.rich_article import render_rich_article

    repeated = "同一段摘要不应该换一种粗体格式再出现一次。"
    html = render_rich_article(
        {
            "theme": "vignelli",
            "structure": "essay",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": repeated},
                {"type": "lead", "text": repeated},
                {
                    "type": "section",
                    "heading": "正文",
                    "paragraphs": ["正文段落。"],
                },
            ],
        },
        fallback_title="标题",
        fallback_markdown="正文段落。",
    )

    assert html.count(repeated) == 1
    assert 'class="rich-article__lead"' not in html


def test_rich_article_preserves_complete_authored_sections_instead_of_flattening():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": "press",
            "structure": "explainer",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "摘要"},
                {"type": "section", "heading": "发生了什么", "paragraphs": ["第一段。"]},
                {"type": "section", "heading": "为什么重要", "paragraphs": ["第二段。"]},
            ],
        },
        fallback_title="标题",
        fallback_markdown="第一段。\n\n第二段。",
    )

    assert "发生了什么" in html
    assert "为什么重要" in html
    assert "完整正文" not in html
    assert html.count('<section id="section-') == 2


def test_rich_article_reflows_a_complete_headingless_essay_wall():
    from engine.review.rich_article import render_rich_article

    paragraphs = [f"第{index}段正文，必须完整保留。" for index in range(1, 7)]
    html = render_rich_article(
        {
            "theme": "magazine",
            "structure": "essay",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "摘要"},
                {"type": "section", "heading": "标题", "paragraphs": paragraphs},
            ],
        },
        fallback_title="标题",
        fallback_markdown="\n\n".join(paragraphs),
    )

    assert "从一个现象说起" not in html
    assert "问题是怎么展开的" not in html
    assert "再往前想一步" not in html
    assert "完整正文" not in html
    assert 'class="rich-article__toc"' not in html
    assert html.count('class="rich-article__prose"') == 3
    assert all(html.count(paragraph) == 1 for paragraph in paragraphs)


def test_rich_article_keeps_unheaded_intro_as_prose_before_authored_sections():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
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
    )

    assert "先看发生了什么" not in html
    assert "关键事实与细节" not in html
    assert html.count('class="rich-article__prose"') == 1
    assert html.count("作者写的具体问题") == 2
    assert html.index("引言第二段。") < html.index("<h2>作者写的具体问题</h2>")


@pytest.mark.parametrize("theme", ARTICLE_THEMES)
@pytest.mark.parametrize("structure", ARTICLE_STRUCTURES)
def test_render_rich_article_preserves_semantic_blocks_for_every_theme_and_structure(
    theme,
    structure,
):
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": theme,
            "structure": structure,
            "blocks": [
                {"type": "hero", "title": "Title", "deck": "Deck"},
                {"type": "lead", "text": "Lead"},
                {
                    "type": "section",
                    "heading": "Finding",
                    "paragraphs": ["Evidence"],
                },
            ],
        }
    )

    assert (
        f'<article class="rich-article rich-article--{theme} '
        f'rich-article--{structure}">' in html
    )
    assert 'class="rich-article__hero"' in html
    assert 'class="rich-article__lead"' in html
    assert 'class="rich-article__toc"' in html
    assert '<section id="section-1">' in html


def test_kama_theme_uses_short_form_blue_reading_rhythm():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": "kama",
            "structure": "explainer",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "一句话接住标题"},
                {"type": "key_judgment", "text": "真正重要的是判断，不是参数。"},
                {
                    "type": "section",
                    "heading": "它到底替你省了哪一步？",
                    "paragraphs": ["短段落一。", "短段落二。"],
                },
            ],
        }
    )

    assert "rich-article--kama" in html
    assert 'class="rich-article__judgment"' in html
    assert "它到底替你省了哪一步？" in html


def test_rich_article_distributes_only_renderer_owned_body_images():
    from engine.review.rich_article import render_rich_article

    article_id = "a" * 24
    revision = "b" * 64
    first = f"/api/articles/{article_id}/assets/body-01/{revision}"
    second = f"/api/articles/{article_id}/assets/body-02/{revision}"
    layout = {
        "theme": "kama",
        "structure": "explainer",
        "blocks": [
            {"type": "hero", "title": "标题", "deck": "摘要"},
            {"type": "section", "heading": "第一问", "paragraphs": ["第一段。"]},
            {"type": "section", "heading": "第二问", "paragraphs": ["第二段。"]},
            {"type": "section", "heading": "第三问", "paragraphs": ["第三段。"]},
        ],
    }

    html = render_rich_article(
        layout,
        body_images=[(first, "第一节示意图"), (second, "第二节示意图")],
    )

    assert html.count('class="rich-article__image"') == 2
    assert html.index(first) < html.index("<h2>第二问</h2>")
    assert html.index(second) > html.index("<h2>第二问</h2>")
    with pytest.raises(ValueError, match="trusted local or embedded"):
        render_rich_article(
            layout,
            body_images=[("https://evil.example/image.png", "不可信图片")],
        )


def test_render_rich_article_expands_a_legacy_two_key_layout_in_memory():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": "press",
            "blocks": [{"type": "lead", "text": "Legacy content"}],
        }
    )

    assert (
        '<article class="rich-article rich-article--press '
        'rich-article--briefing">' in html
    )


def test_render_rich_article_falls_back_for_an_unknown_theme_and_escapes_text():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {
            "theme": "neon",
            "structure": "briefing",
            "blocks": [{"type": "lead", "text": "<script>alert(1)</script>"}],
        },
        fallback_title="<script>title()</script>",
        fallback_markdown="<script>alert(2)</script>",
    )

    assert 'class="rich-article rich-article--fallback"' in html
    assert "<script" not in html
    assert "&lt;script&gt;title()&lt;/script&gt;" in html


def test_render_rich_article_escapes_every_textual_block_value():
    from engine.review.rich_article import render_rich_article

    unsafe = "<script>alert(1)</script>"
    html = render_rich_article(
        {
            "theme": "tufte",
            "structure": "essay",
            "blocks": [
                {"type": "hero", "title": unsafe, "deck": unsafe},
                {"type": "lead", "text": unsafe},
                {"type": "key_judgment", "text": unsafe},
                {"type": "section", "heading": unsafe, "paragraphs": [unsafe]},
                {
                    "type": "workflow_compare",
                    "before": unsafe,
                    "after": unsafe,
                    "remaining_friction": unsafe,
                },
                {"type": "quote", "text": unsafe, "attribution": unsafe},
                {"type": "callout", "text": unsafe},
                {
                    "type": "source_note",
                    "url": "https://example.com/source",
                    "attribution": unsafe,
                },
            ],
        }
    )

    assert "<script" not in html
    assert html.count("&lt;script&gt;alert(1)&lt;/script&gt;") == 14


@pytest.mark.parametrize("theme", ARTICLE_THEMES)
def test_web_edition_selects_the_persisted_theme_css(theme):
    from engine.review.web_edition import render_web_edition

    html = render_web_edition(
        {
            "theme": theme,
            "structure": "briefing",
            "blocks": [{"type": "lead", "text": "Theme content"}],
        },
        title="Theme edition",
    )

    assert f"rich-article--{theme}" in html
    assert f"--rich-theme: {theme};" in html


def test_web_edition_places_embedded_body_images_inside_article_flow():
    from engine.review.web_edition import render_web_edition

    image = "data:image/png;base64,aGVsbG8="
    html = render_web_edition(
        {
            "theme": "kama",
            "structure": "explainer",
            "blocks": [
                {"type": "hero", "title": "标题", "deck": "摘要"},
                {"type": "section", "heading": "第一节", "paragraphs": ["正文。"]},
            ],
        },
        title="标题",
        embedded_images=[(image, "正文配图")],
    )

    assert html.index("标题") < html.index(image)
    assert 'class="rich-article__image"' in html


def test_rich_article_fallback_has_no_external_navigation_or_resources():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {"theme": "press", "blocks": []},
        fallback_title="标题",
        fallback_markdown=(
            "[HTTPS](https://example.com/source) [协议相对](//example.com/a) "
            "[相对路径](/outside) [其他协议](mailto:owner@example.com)\n\n"
            "![HTTPS 图](https://example.com/remote.png) "
            "![协议相对图](//example.com/remote.png) "
            "![相对图](/remote.png)"
        ),
    )

    assert "href=" not in html
    assert "src=" not in html


def test_render_rich_article_falls_back_for_an_empty_or_untrusted_layout():
    from engine.review.rich_article import render_rich_article

    html = render_rich_article(
        {"theme": "press", "blocks": []},
        fallback_title="旧文章标题",
        fallback_markdown="# 旧文章标题\n\n正文内容",
    )

    assert "旧文章标题" in html
    assert "正文内容" in html
    assert "<style>" not in html
