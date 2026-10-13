from __future__ import annotations

import pytest

from ai_content_loop.visuals.prompting import (
    build_body_image_prompt,
    build_image_prompt,
    plan_illustration,
)


def visual_brief() -> dict[str, object]:
    return {
        "template_hint": "ai_done_vs_tests",
        "cover_line": "AI 写完了，测试才刚开始",
        "cover_subline": "速度不能替代证据",
        "body_panels": [
            {"label": "生成代码", "reaction": "很快"},
            {"label": "运行测试", "reaction": "见真章"},
        ],
        "alternatives": [
            {
                "cover_line": "先跑再说",
                "cover_subline": "测试不会陪你演戏",
                "body_panels": [
                    {"label": "生成代码", "reaction": "很快"},
                    {"label": "运行测试", "reaction": "见真章"},
                ],
            },
            {
                "cover_line": "代码只是开始",
                "cover_subline": "结果需要验证",
                "body_panels": [
                    {"label": "生成代码", "reaction": "很快"},
                    {"label": "运行测试", "reaction": "见真章"},
                ],
            },
        ],
    }


def article_layout(
    *, theme: str = "press", structure: str = "briefing", compare: bool = False
) -> dict[str, object]:
    blocks: list[dict[str, object]] = [
        {"type": "hero", "title": "标题", "deck": "读者收益"},
        {"type": "lead", "text": "先给结论"},
    ]
    if compare:
        blocks.append(
            {
                "type": "workflow_compare",
                "before": "旧流程",
                "after": "新流程",
                "remaining_friction": "仍需人工复核",
            }
        )
    blocks.append(
        {
            "type": "source_note",
            "url": "https://example.com/private-source",
            "attribution": "来源",
        }
    )
    return {"theme": theme, "structure": structure, "blocks": blocks}


def test_workflow_comparison_is_the_strongest_visual_route():
    plan = plan_illustration(
        visual_brief(),
        article_layout=article_layout(structure="essay", compare=True),
    )

    assert plan.structure == "comparison"
    assert plan.profile == "material_explainer"


@pytest.mark.parametrize(
    ("structure", "expected"),
    [
        ("briefing", "hub"),
        ("explainer", "pipeline"),
        ("essay", "editorial_metaphor"),
    ],
)
def test_article_structure_routes_to_one_clear_visual_grammar(
    structure, expected
):
    plan = plan_illustration(
        visual_brief(),
        article_layout=article_layout(structure=structure),
    )

    assert plan.structure == expected


def test_five_article_themes_map_to_distinct_restrained_accents():
    accents = {
        plan_illustration(
            visual_brief(),
            article_layout=article_layout(theme=theme),
        ).accent_hex
        for theme in ("press", "tufte", "magazine", "vignelli", "kama")
    }

    assert accents == {
        "#002FA7",
        "#FFD500",
        "#FF6B35",
        "#E60012",
        "#0E88EB",
    }


def test_prompt_is_reproducible_bounded_and_keeps_text_outside_image():
    layout = article_layout(theme="vignelli", structure="explainer")

    first = build_image_prompt(visual_brief(), article_layout=layout)
    second = build_image_prompt(visual_brief(), article_layout=layout)

    assert first == second
    assert "AI 写完了，测试才刚开始" in first
    assert "Swiss editorial" in first
    assert "negative space on the left" in first
    assert "No text" in first
    assert "#E60012" in first
    assert "https://example.com/private-source" not in first
    assert len(first) <= 1500


def test_body_prompts_are_distinct_content_specific_full_frame_illustrations():
    layout = article_layout(theme="magazine", structure="explainer")

    first = build_body_image_prompt(
        visual_brief(), panel_index=0, article_layout=layout
    )
    second = build_body_image_prompt(
        visual_brief(), panel_index=1, article_layout=layout
    )

    assert first != second
    assert "information-rich" in first
    assert "generic AI brain" in first
    assert "question or claim" in first
    assert "full frame" in first
    assert "No text" in first
    assert len(first) <= 1500
    assert len(second) <= 1500
