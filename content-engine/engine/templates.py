"""Writing briefs and per-platform skeletons.

Column routing, the brief's task statement, the coverage checklist, and every
platform skeleton come from the content pack. This module only assembles them
around a specific evidence pack.
"""

from __future__ import annotations

from engine.models import EvidencePack
from engine.pack import PLATFORMS, ContentPack

__all__ = ["PLATFORMS", "choose_column", "build_master_brief", "build_platform_skeletons"]


def choose_column(
    evidence: EvidencePack, pack: ContentPack, *, llm_column: str = ""
) -> str:
    """Route an item to a column; an LLM-supplied column always wins."""
    return pack.column_for(
        source=evidence.source,
        text=f"{evidence.title} {evidence.summary}",
        override=llm_column,
    )


def build_master_brief(
    evidence: EvidencePack, pack: ContentPack, *, llm_angle: str = ""
) -> str:
    """Assemble the writing brief handed to the drafting model."""
    column = choose_column(evidence, pack)
    facts = "\n".join(f"- {fact}" for fact in evidence.facts)
    risks = "\n".join(f"- {risk}" for risk in evidence.risks)
    angles = "\n".join(f"- {angle}" for angle in evidence.writing_angles)
    checklist = "\n".join(f"- {item}" for item in pack.brief_checklist)

    llm_angle_block = ""
    if llm_angle and llm_angle.strip():
        llm_angle_block = f"## LLM 推荐写作角度\n\n{llm_angle.strip()}\n\n"

    return f"""# 写作简报：{evidence.title}

栏目：{column}
来源：{evidence.source}
链接：{evidence.url}
评分：{evidence.score_total}
评分理由：{evidence.score_reason}

## 一句话任务

{pack.brief_task}

{llm_angle_block}## 栏目写作指南

{pack.column_guide(column)}

## 证据

{facts}

## 可写角度

{angles}

## 风险

{risks}

## 信息覆盖清单，不是固定结构

{checklist}

以上是必须覆盖的信息，不规定出现顺序，也不要使用固定的小标题编号。
"""


def build_platform_skeletons(
    evidence: EvidencePack, pack: ContentPack, *, llm_column: str = ""
) -> dict[str, str]:
    """Render each platform's starting skeleton from the pack templates.

    Skeleton strings may reference ``{title}``, ``{column}``, ``{url}``,
    ``{source}``, and ``{min_chars}``. Unknown placeholders are left intact so
    a typo degrades into visible literal text rather than a crash.
    """
    column = choose_column(evidence, pack, llm_column=llm_column)
    skeletons: dict[str, str] = {}
    for platform in PLATFORMS:
        template = pack.platform_skeletons[platform]
        skeletons[platform] = _safe_format(
            template,
            title=evidence.title,
            column=column,
            url=evidence.url,
            source=evidence.source,
            min_chars=pack.platform_min_chars[platform],
        )
    return skeletons


def _safe_format(template: str, **values: object) -> str:
    """``str.format`` that leaves unknown placeholders untouched."""
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))
    return result
