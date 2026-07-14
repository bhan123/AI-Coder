from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    database_path: Path
    output_dir: Path
    daily_raw_limit: int = 200
    daily_deep_limit: int = 10
    publish_limit: int = 2
    scoring_llm_limit: int = 50
    deep_research_enabled: bool = False
    hermes_command: str = "hermes"
    generation_timeout_seconds: int = 600
    generation_retries: int = 1
    visual_font_path: Path | None = None
    visual_render_concurrency: int = 1
    source_limits: dict[str, int] = field(default_factory=dict)
    official_rss_feeds: list[str] = field(default_factory=list)
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


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    root_dir = config_path.parent
    if not config_path.exists():
        return AppConfig(
            root_dir=root_dir,
            database_path=root_dir / "ai_content_loop.sqlite3",
            output_dir=root_dir / "out",
        )

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    hermes_command, generation_timeout_seconds, generation_retries = (
        _read_generation_values(data)
    )
    visual_font_path, visual_render_concurrency = _read_visual_values(
        data, root_dir
    )
    return AppConfig(
        root_dir=root_dir,
        database_path=_resolve_path(root_dir, data.get("database_path"), "ai_content_loop.sqlite3"),
        output_dir=_resolve_path(root_dir, data.get("output_dir"), "out"),
        daily_raw_limit=int(data.get("daily_raw_limit", 200)),
        daily_deep_limit=int(data.get("daily_deep_limit", 10)),
        publish_limit=int(data.get("publish_limit", 2)),
        scoring_llm_limit=int(data.get("scoring_llm_limit", 50)),
        deep_research_enabled=bool(data.get("deep_research_enabled", False)),
        hermes_command=hermes_command,
        generation_timeout_seconds=generation_timeout_seconds,
        generation_retries=generation_retries,
        visual_font_path=visual_font_path,
        visual_render_concurrency=visual_render_concurrency,
        source_limits={str(k): int(v) for k, v in data.get("source_limits", {}).items()},
        official_rss_feeds=[str(x) for x in data.get("official_rss_feeds", [])],
        producthunt_token=str(data.get("producthunt_token", "")),
    )
