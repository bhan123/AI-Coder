from __future__ import annotations

from copy import deepcopy
from typing import Any

from engine.editorial.layout_completion import complete_layout_for_rendering
from engine.generation import PLATFORMS
from engine.pack import active_pack
from engine.quality import has_synthetic_title
from engine.visuals.pipeline import insert_body_asset_marker


PROPOSAL_VERSION = "gpt-polish-v1"
DIMENSIONS = (
    ("hook", "虎头吸引力"),
    ("comprehension", "轻松理解"),
    ("emotion", "乐趣/情绪价值"),
    ("value", "提效/商业启发"),
    ("ending", "豹尾回味"),
)
AUDITS = (
    ("credibility", "来源支撑度"),
    ("repetition", "内容重复度"),
)
_PROPOSAL_FIELDS = {
    "version",
    "master_title",
    "master_markdown",
    "platform_markdown",
    "assessment",
    "change_summary",
}


class GptPolishProposalError(ValueError):
    """The local editor returned a proposal outside the trusted contract."""


def _text(value: object, path: str, *, maximum: int = 200_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise GptPolishProposalError(f"{path} must be non-empty text")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise GptPolishProposalError(f"{path} contains unsupported characters")
    return value.strip()


def _score(value: object, path: str) -> float:
    if type(value) not in {int, float} or not 0 <= float(value) <= 5:
        raise GptPolishProposalError(f"{path} must be between 0 and 5")
    return round(float(value), 1)


def _assessment_item(
    value: object,
    *,
    key: str,
    label: str,
    path: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "key",
        "label",
        "score",
        "evidence",
        "suggestion",
    }:
        raise GptPolishProposalError(f"{path} does not match the score schema")
    if value.get("key") != key or value.get("label") != label:
        raise GptPolishProposalError(f"{path} identity is invalid")
    return {
        "key": key,
        "label": label,
        "score": _score(value.get("score"), f"{path}.score"),
        "evidence": _text(value.get("evidence"), f"{path}.evidence", maximum=600),
        "suggestion": _text(
            value.get("suggestion"), f"{path}.suggestion", maximum=600
        ),
    }


def validate_gpt_polish_proposal(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROPOSAL_FIELDS:
        raise GptPolishProposalError("proposal fields do not match the contract")
    if value.get("version") != PROPOSAL_VERSION:
        raise GptPolishProposalError("proposal version is unsupported")

    platforms = value.get("platform_markdown")
    if not isinstance(platforms, dict) or set(platforms) != set(PLATFORMS):
        raise GptPolishProposalError("platform_markdown must contain four platforms")

    assessment = value.get("assessment")
    if not isinstance(assessment, dict) or set(assessment) != {
        "overall",
        "verdict",
        "summary",
        "dimensions",
        "audits",
    }:
        raise GptPolishProposalError("assessment does not match the contract")
    dimensions = assessment.get("dimensions")
    audits = assessment.get("audits")
    if not isinstance(dimensions, list) or len(dimensions) != len(DIMENSIONS):
        raise GptPolishProposalError("assessment dimensions are incomplete")
    if not isinstance(audits, list) or len(audits) != len(AUDITS):
        raise GptPolishProposalError("assessment audits are incomplete")

    summaries = value.get("change_summary")
    if (
        not isinstance(summaries, list)
        or not 1 <= len(summaries) <= 8
        or not all(isinstance(item, str) for item in summaries)
    ):
        raise GptPolishProposalError("change_summary must contain 1 to 8 items")

    master_title = _text(value.get("master_title"), "master_title", maximum=160)
    if has_synthetic_title(master_title, active_pack()):
        raise GptPolishProposalError("master_title uses a synthetic title template")

    return {
        "version": PROPOSAL_VERSION,
        "master_title": master_title,
        "master_markdown": _text(value.get("master_markdown"), "master_markdown"),
        "platform_markdown": {
            platform: _text(platforms.get(platform), f"platform_markdown.{platform}")
            for platform in PLATFORMS
        },
        "assessment": {
            "overall": _score(assessment.get("overall"), "assessment.overall"),
            "verdict": _text(
                assessment.get("verdict"), "assessment.verdict", maximum=80
            ),
            "summary": _text(
                assessment.get("summary"), "assessment.summary", maximum=600
            ),
            "dimensions": [
                _assessment_item(
                    item,
                    key=key,
                    label=label,
                    path=f"assessment.dimensions[{index}]",
                )
                for index, (item, (key, label)) in enumerate(
                    zip(dimensions, DIMENSIONS, strict=True)
                )
            ],
            "audits": [
                _assessment_item(
                    item,
                    key=key,
                    label=label,
                    path=f"assessment.audits[{index}]",
                )
                for index, (item, (key, label)) in enumerate(
                    zip(audits, AUDITS, strict=True)
                )
            ],
        },
        "change_summary": [
            _text(item, f"change_summary[{index}]", maximum=300)
            for index, item in enumerate(summaries)
        ],
    }


def _source_attribution(layout: object) -> str:
    if isinstance(layout, dict):
        blocks = layout.get("blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "source_note":
                    attribution = block.get("attribution")
                    if isinstance(attribution, str) and attribution.strip():
                        return attribution.strip()
    return "Original source"


def _rebuilt_layout(
    current_layout: object,
    *,
    title: str,
    markdown: str,
    source_url: str,
) -> dict[str, object]:
    theme = "press"
    structure = "briefing"
    if isinstance(current_layout, dict):
        if isinstance(current_layout.get("theme"), str):
            theme = str(current_layout["theme"])
        if isinstance(current_layout.get("structure"), str):
            structure = str(current_layout["structure"])
    base = {
        "theme": theme,
        "structure": structure,
        "blocks": [
            {
                "type": "source_note",
                "url": source_url,
                "attribution": _source_attribution(current_layout),
            }
        ],
    }
    return complete_layout_for_rendering(base, title=title, markdown=markdown)


def candidate_payload(
    current: dict[str, Any],
    proposal: object,
    *,
    source_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an article candidate while preserving non-editorial state."""

    normalized = validate_gpt_polish_proposal(proposal)
    result = deepcopy(current)
    result["master_title"] = normalized["master_title"]
    result["master_markdown"] = normalized["master_markdown"]
    result["platform_markdown"] = deepcopy(normalized["platform_markdown"])
    result["article_layout"] = _rebuilt_layout(
        current.get("article_layout"),
        title=normalized["master_title"],
        markdown=normalized["master_markdown"],
        source_url=source_url,
    )
    assets = result.get("visual_assets")
    if isinstance(assets, dict) and isinstance(assets.get("body"), list) and assets["body"]:
        result = insert_body_asset_marker(result)
    return result, normalized
