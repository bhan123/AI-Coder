from __future__ import annotations

from copy import deepcopy

import pytest

from engine.gpt_polish import (
    AUDITS,
    DIMENSIONS,
    GptPolishProposalError,
    candidate_payload,
    validate_gpt_polish_proposal,
)


SOURCE_URL = "https://example.com/original"


def valid_proposal() -> dict[str, object]:
    def score_items(items):
        return [
            {
                "key": key,
                "label": label,
                "score": 4.2,
                "evidence": f"{label}有具体证据。",
                "suggestion": f"继续增强{label}。",
            }
            for key, label in items
        ]

    master = (
        "# 新标题\n\n开头先给出一个反直觉判断。\n\n"
        + "正文提供清楚的例子和可执行步骤。" * 55
        + f"\n\n来源：{SOURCE_URL}"
    )
    return {
        "version": "gpt-polish-v1",
        "master_title": "新的、有吸引力且不夸张的标题",
        "master_markdown": master,
        "platform_markdown": {
            platform: master for platform in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
        "assessment": {
            "overall": 4.2,
            "verdict": "值得发布",
            "summary": "更易读，也有明确启发。",
            "dimensions": score_items(DIMENSIONS),
            "audits": score_items(AUDITS),
        },
        "change_summary": ["重写开头", "压缩重复内容", "加强结尾"],
    }


def test_proposal_contract_requires_all_platforms_and_audits():
    proposal = valid_proposal()
    proposal["platform_markdown"].pop("zhihu")
    with pytest.raises(GptPolishProposalError):
        validate_gpt_polish_proposal(proposal)


def test_proposal_contract_rejects_synthetic_title_template():
    proposal = valid_proposal()
    proposal["master_title"] = "ChatGPT Sites 上线：一句话生成小网站"

    with pytest.raises(GptPolishProposalError, match="master_title.*synthetic"):
        validate_gpt_polish_proposal(proposal)

    proposal = valid_proposal()
    proposal["assessment"]["audits"] = []
    with pytest.raises(GptPolishProposalError):
        validate_gpt_polish_proposal(proposal)


def test_candidate_preserves_non_editorial_state_layout_choice_and_images():
    current = {
        "dedupe_key": "github:owner/repo",
        "column": "AI 工具",
        "master_title": "旧标题",
        "master_markdown": f"旧正文\n\n来源：{SOURCE_URL}",
        "platform_markdown": {
            platform: f"旧正文\n\n来源：{SOURCE_URL}"
            for platform in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
        "editorial_profile": {"version": "tech_friend_v1"},
        "visual_brief": {"cover_line": "保持不变"},
        "visual_assets": {
            "cover": {"asset_id": "cover"},
            "body": [{"asset_id": "body-01", "revision": "r1"}],
        },
        "article_layout": {
            "theme": "vignelli",
            "structure": "essay",
            "blocks": [
                {
                    "type": "source_note",
                    "url": SOURCE_URL,
                    "attribution": "论文原文",
                }
            ],
        },
    }
    before_assets = deepcopy(current["visual_assets"])

    candidate, normalized = candidate_payload(
        current, valid_proposal(), source_url=SOURCE_URL
    )

    assert candidate["dedupe_key"] == current["dedupe_key"]
    assert candidate["column"] == current["column"]
    assert candidate["visual_brief"] == current["visual_brief"]
    assert candidate["visual_assets"] == before_assets
    assert candidate["article_layout"]["theme"] == "vignelli"
    assert candidate["article_layout"]["structure"] == "essay"
    assert "{{asset:body-01}}" in candidate["platform_markdown"]["wechat"]
    assert normalized["master_title"] == candidate["master_title"]
    source_blocks = [
        block
        for block in candidate["article_layout"]["blocks"]
        if block["type"] == "source_note"
    ]
    assert source_blocks == [
        {"type": "source_note", "url": SOURCE_URL, "attribution": "论文原文"}
    ]
