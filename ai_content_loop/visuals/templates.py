from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    layout: str
    background: str
    accent: str
    foreground: str


_TEMPLATE_REGISTRY = {
    "boss_vs_worker": TemplateSpec(
        "boss_vs_worker",
        "split",
        "#FFF7E8",
        "#E54B4B",
        "#172033",
    ),
    "expectation_vs_reality": TemplateSpec(
        "expectation_vs_reality",
        "split",
        "#F4F1FF",
        "#6D5EF7",
        "#172033",
    ),
    "ai_done_vs_tests": TemplateSpec(
        "ai_done_vs_tests",
        "split",
        "#07111F",
        "#43F0B6",
        "#FFFFFF",
    ),
    "before_vs_after": TemplateSpec(
        "before_vs_after",
        "split",
        "#EDF7FF",
        "#1473E6",
        "#172033",
    ),
    "do_vs_dont": TemplateSpec(
        "do_vs_dont",
        "split",
        "#F8FAFC",
        "#F59E0B",
        "#172033",
    ),
    "one_line_verdict": TemplateSpec(
        "one_line_verdict",
        "verdict",
        "#111827",
        "#FDE047",
        "#FFFFFF",
    ),
}
TEMPLATES = MappingProxyType(_TEMPLATE_REGISTRY)


def select_template(dedupe_key: str, hint: str) -> TemplateSpec:
    if not isinstance(dedupe_key, str):
        raise TypeError("dedupe_key must be a string")
    if not isinstance(hint, str):
        raise TypeError("hint must be a string")
    if hint in TEMPLATES:
        return TEMPLATES[hint]

    names = tuple(TEMPLATES)
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:2], "big") % len(names)
    return TEMPLATES[names[index]]
