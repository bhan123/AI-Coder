"""Candidate scoring: keyword pre-filter plus an LLM selection pass.

The *mechanism* lives here; the *taste* lives in the content pack. Which words
signal a useful item, how much a GitHub star is worth, and how the scoring
dimensions are weighted are all pack-supplied.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.models import CandidateScore, SourceItem
from engine.pack import ContentPack


def _bounded(value: int, low: int = 1, high: int = 10) -> int:
    return max(low, min(high, value))


def _recency_multiplier(pack: ContentPack, published_at: str) -> float:
    """Decay novelty by age using the pack's tier table."""
    if not published_at:
        return 1.0
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_days = (datetime.now(UTC) - published).days
    except (ValueError, TypeError):
        return 1.0
    for max_age_days, multiplier in pack.recency_tiers:
        if age_days <= max_age_days:
            return multiplier
    return pack.recency_tiers[-1][1] if pack.recency_tiers else 1.0


def _clickbait_penalty(pack: ContentPack, title: str) -> int:
    hits = sum(1 for word in pack.clickbait_words if word in title)
    return min(pack.clickbait_penalty_max, hits * pack.clickbait_penalty_per_hit)


def score_item(item: SourceItem, pack: ContentPack) -> CandidateScore:
    """Deterministic keyword pre-filter score for one item."""
    text = f"{item.title} {item.summary}"
    published_at = item.published_at or ""

    base_novelty = (
        pack.novelty_base_dated if published_at else pack.novelty_base_undated
    )
    novelty = _bounded(round(base_novelty * _recency_multiplier(pack, published_at)))

    dimensions = {key: group.score(text) for key, group in pack.keyword_groups.items()}
    heat = pack.heat_for(item.source, item.raw if isinstance(item.raw, dict) else {})
    credibility = pack.credibility_for(item.source)
    penalty = _clickbait_penalty(pack, item.title)

    scored = {
        **dimensions,
        "novelty": novelty,
        "heat": heat,
        "credibility": credibility,
    }
    total = (
        sum(scored.get(key, 0) * weight for key, weight in pack.score_weights.items())
        * 10
        - penalty
    )
    total = max(1.0, round(total, 2))

    reason = ", ".join(f"{key}={value}" for key, value in sorted(scored.items()))
    reason = f"{reason}, penalty={penalty}"

    # CandidateScore keeps fixed columns for storage compatibility; pack
    # dimensions map onto them by name and default to a neutral 5.
    return CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=novelty,
        clarity=dimensions.get("clarity", 5),
        fun=dimensions.get("fun", 5),
        usefulness=dimensions.get("usefulness", 5),
        demo=dimensions.get("demo", 5),
        heat=heat,
        credibility=credibility,
        total=total,
        reason=reason,
    )


def score_items(items: list[SourceItem], pack: ContentPack) -> list[CandidateScore]:
    """Pre-filter: score every item, best first."""
    return sorted(
        (score_item(item, pack) for item in items),
        key=lambda score: score.total,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# LLM selection pass
# ---------------------------------------------------------------------------


def _parse_llm_scores(raw_output: str) -> list[dict[str, Any]]:
    """Pull the first JSON array (or array-bearing object) out of model output."""
    decoder = json.JSONDecoder()
    for idx, start_char in enumerate(raw_output):
        if start_char not in "[{":
            continue
        try:
            result, _ = decoder.raw_decode(raw_output, idx)
        except json.JSONDecodeError:
            continue
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("results", "candidates", "scores"):
                nested = result.get(key)
                if isinstance(nested, list):
                    return nested
            return [result]
    raise ValueError("no JSON scoring result found in model output")


def llm_score_items(
    candidates: list[dict[str, Any]],
    *,
    hermes_command: str,
    prompt_path: str | Path,
    timeout_seconds: int = 300,
) -> list[dict[str, Any]] | None:
    """Ask the model to pick winners from the pre-filtered candidates.

    Returns recommended candidates sorted by score, or ``None`` when the call
    fails. ``None`` is deliberately distinct from ``[]``: callers preserve
    prior recommendations on failure but accept an empty list as a real
    verdict of "nothing here is worth writing".
    """
    scoring_prompt = Path(prompt_path).read_text(encoding="utf-8")

    slim_candidates = []
    for candidate in candidates:
        raw_slim = {}
        if isinstance(candidate.get("raw"), dict):
            for key in ("stars", "likes", "downloads", "votes", "score", "comments"):
                if key in candidate["raw"]:
                    raw_slim[key] = candidate["raw"][key]
        slim_candidates.append(
            {
                "dedupe_key": candidate.get("dedupe_key", ""),
                "source": candidate.get("source", ""),
                "title": candidate.get("title", ""),
                "summary": candidate.get("summary", ""),
                "url": candidate.get("url", ""),
                "keyword_score": candidate.get("total", 0),
                "keyword_reason": candidate.get("reason", ""),
                "raw_metrics": raw_slim,
            }
        )

    prompt = "\n".join(
        [
            scoring_prompt.rstrip(),
            "",
            "以下是预筛后的候选列表（已按关键词初筛排序，分数仅供参考）：",
            json.dumps(slim_candidates, ensure_ascii=False, indent=2),
            "",
            "请对每个候选按评分维度打分，返回 JSON 数组，按 total_score 降序。",
            "只输出 JSON 数组，不要有任何解释。",
        ]
    )

    argv = [hermes_command, "chat", "-Q", "-t", "none", "-q", prompt]

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[scoring] LLM scoring: model timed out after {timeout_seconds}s",
            file=sys.stderr,
        )
        return None
    except (OSError, UnicodeError) as error:
        print(
            f"[scoring] LLM scoring: launch failed ({type(error).__name__})",
            file=sys.stderr,
        )
        return None

    if completed.returncode != 0:
        print(
            f"[scoring] LLM scoring: exited with code {completed.returncode}",
            file=sys.stderr,
        )
        return None

    try:
        scores = _parse_llm_scores(completed.stdout)
    except ValueError:
        print(
            "[scoring] LLM scoring: output could not be parsed as JSON",
            file=sys.stderr,
        )
        return None

    valid_scores = [
        score
        for score in scores
        if isinstance(score, dict)
        and score.get("dedupe_key")
        and score.get("recommended") is True
    ]
    valid_scores.sort(key=lambda score: score.get("total_score", 0), reverse=True)
    if valid_scores:
        print(
            f"[scoring] LLM scoring: {len(valid_scores)} candidates recommended",
            file=sys.stderr,
        )
    else:
        print(
            "[scoring] LLM scoring: no recommended candidates returned",
            file=sys.stderr,
        )
    return valid_scores
