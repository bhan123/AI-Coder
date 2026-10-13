from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceItem:
    source: str
    external_id: str
    title: str
    url: str
    summary: str
    published_at: str
    fetched_at: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source}:{self.external_id}"


@dataclass(frozen=True)
class CandidateScore:
    dedupe_key: str
    novelty: int
    clarity: int
    fun: int
    usefulness: int
    demo: int
    heat: int
    credibility: int
    total: float
    reason: str
    llm_column: str = ""
    llm_angle: str = ""


@dataclass(frozen=True)
class EvidencePack:
    dedupe_key: str
    title: str
    url: str
    source: str
    summary: str
    score_total: float
    score_reason: str
    facts: list[str]
    risks: list[str]
    writing_angles: list[str]


@dataclass(frozen=True)
class DraftBundle:
    dedupe_key: str
    title: str
    column: str
    master_markdown: str
    platform_markdown: dict[str, str]
    output_path: Path
