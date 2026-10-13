"""Baseline quality gates: source link, length, banned phrasing, title shape.

Every threshold and word list comes from the content pack. The engine decides
*what kinds of things* to check; the pack decides the specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from engine.pack import ContentPack


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    failures: list[str]


def has_synthetic_title(title: str, pack: ContentPack) -> bool:
    """True when the title matches a press-release shell the pack rejects."""
    normalized = re.sub(r"\s+", " ", title).strip()
    return any(pattern.search(normalized) for pattern in pack.synthetic_title_patterns)


def evaluate_draft(
    title: str, markdown: str, source_url: str, pack: ContentPack
) -> QualityResult:
    """Collect every gate failure for one draft.

    Callers split the result into hard blockers and advisories; this function
    reports all of them without ranking.
    """
    failures: list[str] = []
    combined = f"{title}\n{markdown}"
    stripped_title = title.strip()

    if source_url not in markdown:
        failures.append("missing_source_link")

    if len(stripped_title) < pack.title_min_chars:
        failures.append("title_too_short")
    if len(stripped_title) > pack.title_max_chars:
        failures.append("title_too_long")
    if len(markdown.strip()) < pack.body_min_chars:
        failures.append("body_too_short")

    if any(phrase in combined for phrase in pack.banned_promises):
        failures.append("overpromise")

    if any(topic in combined for topic in pack.risky_topics):
        failures.append("high_risk_advice")

    if any(word in title for word in pack.clickbait_patterns):
        failures.append("clickbait_title")

    if has_synthetic_title(title, pack):
        failures.append("synthetic_title")

    # Count both full-width and ASCII exclamation marks.
    if combined.count("！") + combined.count("!") > pack.max_exclamations:
        failures.append("too_many_exclamations")

    if title.count("？") > pack.max_title_question_marks:
        failures.append("too_many_question_marks")

    return QualityResult(passed=not failures, failures=failures)
