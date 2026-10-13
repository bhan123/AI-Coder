from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class RssFeedConfig:
    name: str
    url: str
    include_keywords: tuple[str, ...] = ()
    limit: int = 20
    category: str = "news"


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    database_path: Path
    output_dir: Path
    pack_dir: Path
    daily_raw_limit: int = 200
    daily_deep_limit: int = 10
    publish_limit: int = 2
    scoring_llm_limit: int = 50
    scoring_llm_batch_size: int = 10
    scoring_llm_timeout_seconds: int = 180
    deep_research_enabled: bool = False
    hermes_command: str = "hermes"
    generation_timeout_seconds: int = 600
    generation_retries: int = 1
    visual_font_path: Path | None = None
    visual_render_concurrency: int = 1
    source_limits: dict[str, int] = field(default_factory=dict)
    official_rss_feeds: list[str] = field(default_factory=list)
    rss_feeds: list[RssFeedConfig] = field(default_factory=list)
    producthunt_token: str = ""


def _resolve_path(root_dir: Path, value: str | None, default_name: str) -> Path:
    if value:
        raw = Path(value)
        return raw if raw.is_absolute() else root_dir / raw
    return root_dir / default_name


def _read_generation_values(data: dict[str, object]) -> tuple[str, int, int]:
    hermes_command = data.get("hermes_command", "hermes")
    if not isinstance(hermes_command, str) or not hermes_command.strip():
        raise ValueError("hermes_command must be a non-empty string")

    generation_timeout_seconds = data.get("generation_timeout_seconds", 600)
    if (
        type(generation_timeout_seconds) is not int
        or generation_timeout_seconds <= 0
    ):
        raise ValueError("generation_timeout_seconds must be an integer greater than 0")

    generation_retries = data.get("generation_retries", 1)
    if type(generation_retries) is not int or generation_retries < 0:
        raise ValueError("generation_retries must be a non-negative integer")

    return (
        hermes_command.strip(),
        generation_timeout_seconds,
        generation_retries,
    )


def _read_scoring_values(data: dict[str, object]) -> tuple[int, int, int]:
    scoring_llm_limit = data.get("scoring_llm_limit", 50)
    if type(scoring_llm_limit) is not int or scoring_llm_limit < 0:
        raise ValueError("scoring_llm_limit must be a non-negative integer")

    scoring_llm_batch_size = data.get("scoring_llm_batch_size", 10)
    if type(scoring_llm_batch_size) is not int or scoring_llm_batch_size <= 0:
        raise ValueError("scoring_llm_batch_size must be a positive integer")

    scoring_llm_timeout_seconds = data.get("scoring_llm_timeout_seconds", 180)
    if (
        type(scoring_llm_timeout_seconds) is not int
        or scoring_llm_timeout_seconds <= 0
    ):
        raise ValueError(
            "scoring_llm_timeout_seconds must be a positive integer"
        )

    return scoring_llm_limit, scoring_llm_batch_size, scoring_llm_timeout_seconds


def _read_visual_values(
    data: dict[str, object], root_dir: Path
) -> tuple[Path | None, int]:
    raw_font_path = data.get("visual_font_path")
    if raw_font_path is None:
        visual_font_path = None
    else:
        if not isinstance(raw_font_path, str) or not raw_font_path.strip():
            raise ValueError("visual_font_path must be a non-empty string")
        visual_font_path = Path(raw_font_path)
        if not visual_font_path.anchor:
            visual_font_path = root_dir / visual_font_path

    visual_render_concurrency = data.get("visual_render_concurrency", 1)
    if (
        type(visual_render_concurrency) is not int
        or visual_render_concurrency != 1
    ):
        raise ValueError("visual_render_concurrency must be the integer 1")

    return visual_font_path, visual_render_concurrency


def _read_rss_feeds(data: dict[str, object]) -> list[RssFeedConfig]:
    raw_feeds = data.get("rss_feeds", [])
    if not isinstance(raw_feeds, list):
        raise ValueError("rss_feeds must be an array of tables")

    feeds: list[RssFeedConfig] = []
    for index, raw in enumerate(raw_feeds):
        if not isinstance(raw, dict):
            raise ValueError(f"rss_feeds[{index}] must be a table")
        name = raw.get("name")
        url = raw.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"rss_feeds[{index}].name must be a non-empty string")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"rss_feeds[{index}].url must be a non-empty string")
        raw_keywords = raw.get("include_keywords", [])
        if not isinstance(raw_keywords, list) or not all(
            isinstance(keyword, str) and keyword.strip()
            for keyword in raw_keywords
        ):
            raise ValueError(
                f"rss_feeds[{index}].include_keywords must be an array of strings"
            )
        limit = raw.get("limit", 20)
        if type(limit) is not int or limit <= 0:
            raise ValueError(f"rss_feeds[{index}].limit must be a positive integer")
        category = raw.get("category", "news")
        if category not in {"practical", "news"}:
            raise ValueError(
                f"rss_feeds[{index}].category must be practical or news"
            )
        feeds.append(
            RssFeedConfig(
                name=name.strip(),
                url=url.strip(),
                include_keywords=tuple(
                    keyword.strip() for keyword in raw_keywords
                ),
                limit=limit,
                category=str(category),
            )
        )
    return feeds


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    root_dir = config_path.parent
    if not config_path.exists():
        raise ValueError(f"config file not found: {config_path}")

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    hermes_command, generation_timeout_seconds, generation_retries = (
        _read_generation_values(data)
    )
    scoring_llm_limit, scoring_llm_batch_size, scoring_llm_timeout_seconds = (
        _read_scoring_values(data)
    )
    visual_font_path, visual_render_concurrency = _read_visual_values(
        data, root_dir
    )
    return AppConfig(
        root_dir=root_dir,
        database_path=_resolve_path(root_dir, data.get("database_path"), "content_engine.sqlite3"),
        output_dir=_resolve_path(root_dir, data.get("output_dir"), "out"),
        pack_dir=_resolve_path(root_dir, data.get("pack_dir"), "packs/default"),
        daily_raw_limit=int(data.get("daily_raw_limit", 200)),
        daily_deep_limit=int(data.get("daily_deep_limit", 10)),
        publish_limit=int(data.get("publish_limit", 2)),
        scoring_llm_limit=scoring_llm_limit,
        scoring_llm_batch_size=scoring_llm_batch_size,
        scoring_llm_timeout_seconds=scoring_llm_timeout_seconds,
        deep_research_enabled=bool(data.get("deep_research_enabled", False)),
        hermes_command=hermes_command,
        generation_timeout_seconds=generation_timeout_seconds,
        generation_retries=generation_retries,
        visual_font_path=visual_font_path,
        visual_render_concurrency=visual_render_concurrency,
        source_limits={str(k): int(v) for k, v in data.get("source_limits", {}).items()},
        official_rss_feeds=[str(x) for x in data.get("official_rss_feeds", [])],
        rss_feeds=_read_rss_feeds(data),
        producthunt_token=str(data.get("producthunt_token", "")),
    )
