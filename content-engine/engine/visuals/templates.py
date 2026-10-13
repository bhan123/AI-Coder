"""Cover template selection.

The registry itself lives in the content pack's ``style.toml``. Selection is
deterministic: the same article always gets the same template, so re-running
the visual pipeline is idempotent.
"""

from __future__ import annotations

import hashlib

from engine.pack import ContentPack, VisualTemplate

# Re-exported so callers that only need the shape don't import the pack module.
TemplateSpec = VisualTemplate

__all__ = ["TemplateSpec", "select_template"]


def select_template(dedupe_key: str, hint: str, pack: ContentPack) -> VisualTemplate:
    """Pick a cover template, honouring an explicit hint when it is valid.

    Without a usable hint the choice is derived from a hash of the article
    identity, which keeps it stable across runs while still spreading articles
    across the available templates.
    """
    if not isinstance(dedupe_key, str):
        raise TypeError("dedupe_key must be a string")
    if not isinstance(hint, str):
        raise TypeError("hint must be a string")

    templates = pack.visual_templates
    if hint in templates:
        return templates[hint]

    names = tuple(templates)
    if not names:
        raise ValueError("content pack defines no visual templates")
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:2], "big") % len(names)
    return templates[names[index]]
