from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ai_content_loop.visuals.brief import normalize_visual_brief


PROMPT_CONTRACT_VERSION = "material-editorial-v2"
MAX_PROMPT_CHARS = 1500

_THEME_ACCENTS = {
    "press": ("IKB blue", "#002FA7"),
    "tufte": ("lemon yellow", "#FFD500"),
    "magazine": ("safety orange", "#FF6B35"),
    "vignelli": ("signal red", "#E60012"),
    "kama": ("clear sky blue", "#0E88EB"),
}
_STRUCTURE_DIRECTIONS = {
    "comparison": (
        "a before-and-after comparison made from two small physical models, "
        "with one clear transformation between them"
    ),
    "pipeline": (
        "a compact left-to-right three-stage pipeline made from physical "
        "blocks and restrained directional arrows"
    ),
    "hub": (
        "one central coordinating object with three short, clearly separated "
        "branches, like a material hub-and-spoke diagram"
    ),
    "editorial_metaphor": (
        "one memorable physical metaphor that expresses the article's core "
        "tension or payoff without becoming a literal dashboard"
    ),
}


@dataclass(frozen=True)
class IllustrationPlan:
    profile: str
    structure: str
    accent_name: str
    accent_hex: str


def _layout_value(
    article_layout: object,
    field: str,
    default: str,
) -> str:
    if not isinstance(article_layout, Mapping):
        return default
    value = article_layout.get(field)
    return value if isinstance(value, str) else default


def _contains_workflow_compare(article_layout: object) -> bool:
    if not isinstance(article_layout, Mapping):
        return False
    blocks = article_layout.get("blocks")
    if not isinstance(blocks, list):
        return False
    return any(
        isinstance(block, Mapping)
        and block.get("type") == "workflow_compare"
        for block in blocks
    )


def plan_illustration(
    brief: object,
    *,
    article_layout: object | None = None,
) -> IllustrationPlan:
    """Choose one stable visual grammar from trusted semantic inputs."""

    normalize_visual_brief(brief)
    theme = _layout_value(article_layout, "theme", "press")
    accent_name, accent_hex = _THEME_ACCENTS.get(
        theme,
        _THEME_ACCENTS["press"],
    )
    article_structure = _layout_value(
        article_layout,
        "structure",
        "briefing",
    )
    if _contains_workflow_compare(article_layout):
        structure = "comparison"
    elif article_structure == "explainer":
        structure = "pipeline"
    elif article_structure == "essay":
        structure = "editorial_metaphor"
    else:
        structure = "hub"
    profile = (
        "editorial_concept"
        if structure == "editorial_metaphor"
        else "material_explainer"
    )
    return IllustrationPlan(
        profile=profile,
        structure=structure,
        accent_name=accent_name,
        accent_hex=accent_hex,
    )


def build_image_prompt(
    brief: object,
    *,
    article_layout: object | None = None,
) -> str:
    """Render a bounded MiniMax Image-01 prompt from a semantic plan.

    Text is deliberately kept out of the generated bitmap. The local renderer
    adds exact Chinese typography after the image API returns.
    """

    value = normalize_visual_brief(brief)
    plan = plan_illustration(value, article_layout=article_layout)
    panels = value["body_panels"]
    cues = "; ".join(str(panel["label"]) for panel in panels)
    prompt = (
        f"Prompt contract: {PROMPT_CONTRACT_VERSION}. "
        "Create one premium supporting illustration for a Chinese technology "
        "article, not a poster, slide, dashboard, screenshot, or full page. "
        f"Content anchor: {value['cover_line']}. {value['cover_subline']}. "
        f"Supporting semantic cues: {cues}. "
        f"Visual structure: {_STRUCTURE_DIRECTIONS[plan.structure]}. "
        "Style: clean Swiss editorial material illustration, off-white and "
        "refined gray physical surfaces, black ink outlines, soft studio light, "
        f"mild contact shadows, and one {plan.accent_name} accent "
        f"({plan.accent_hex}). Use one metaphor only. "
        "Composition: 21:9 landscape; keep the meaningful subject on the right "
        "third, centered vertically, fully visible, with generous safe margins "
        "and calm negative space on the left for deterministic title overlay. "
        "No crop. No text, letters, numbers, captions, labels, legend, logo, "
        "watermark, brand marks, interface chrome, decorative blobs, gradient "
        "orbs, or unrelated English. Do not invent facts, metrics, products, "
        "people, screenshots, or source details."
    )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("image prompt exceeds the supported contract")
    return prompt


def build_body_image_prompt(
    brief: object,
    *,
    panel_index: int,
    article_layout: object | None = None,
) -> str:
    """Build one content-specific full-frame body illustration prompt."""

    value = normalize_visual_brief(brief)
    if type(panel_index) is not int or not 0 <= panel_index < len(
        value["body_panels"]
    ):
        raise ValueError("body panel index is invalid")
    plan = plan_illustration(value, article_layout=article_layout)
    panel = value["body_panels"][panel_index]
    prompt = (
        f"Prompt contract: {PROMPT_CONTRACT_VERSION}. "
        "Create one information-rich editorial explanatory illustration for "
        "the body of a Chinese technology article. It must communicate a "
        "specific idea through concrete objects, spatial relationships, and "
        "a clear cause-and-effect scene, not generic decoration. "
        f"Article anchor: {value['cover_line']}. {value['cover_subline']}. "
        f"This image focuses only on: {panel['label']}; intended reader "
        f"takeaway: {panel['reaction']}. "
        "The image must answer the section's question or claim at a glance. "
        f"Visual grammar: {_STRUCTURE_DIRECTIONS[plan.structure]}. "
        "Show two or three meaningful visual elements whose relationship is "
        "immediately readable. Use a full frame 16:9 composition with the "
        "main subject centered and safe margins on every edge; do not reserve "
        "a blank title panel. "
        "Style: polished contemporary editorial illustration with tactile "
        "materials, realistic depth, soft directional light, precise details, "
        f"and one {plan.accent_name} accent ({plan.accent_hex}). "
        "Avoid a generic AI brain, robot head, floating circuit, or decorative "
        "technology symbol. "
        "No text, letters, numbers, captions, labels, legend, logo, watermark, "
        "interface chrome, poster layout, slide layout, or decorative filler. "
        "Do not invent metrics, brands, people, screenshots, or source details."
    )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("image prompt exceeds the supported contract")
    return prompt
