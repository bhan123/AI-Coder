from pathlib import Path

import pytest

from engine.config import load_config
from engine.models import SourceItem


def test_load_config_rejects_missing_file(tmp_path: Path):
    """A missing config is an error, not a silent set of defaults.

    Silently defaulting used to send runs at the wrong database and output
    directory, which is much harder to notice than a startup failure.
    """
    with pytest.raises(ValueError, match="config file not found"):
        load_config(tmp_path / "missing.toml")


def test_load_config_uses_defaults_for_omitted_keys(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")

    cfg = load_config(path)

    assert cfg.database_path == tmp_path / "content_engine.sqlite3"
    assert cfg.output_dir == tmp_path / "out"
    assert cfg.pack_dir == tmp_path / "packs/default"
    assert cfg.daily_raw_limit == 200
    assert cfg.daily_deep_limit == 10
    assert cfg.publish_limit == 2
    assert cfg.scoring_llm_batch_size == 10
    assert cfg.scoring_llm_timeout_seconds == 180


def test_load_config_reads_toml_values(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
database_path = "data/content.sqlite3"
output_dir = "var/out"
daily_raw_limit = 120
daily_deep_limit = 8
publish_limit = 1

[source_limits]
github = 20
hackernews = 15
arxiv = 10
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.database_path == tmp_path / "data/content.sqlite3"
    assert cfg.output_dir == tmp_path / "var/out"
    assert cfg.source_limits["github"] == 20
    assert cfg.source_limits["hackernews"] == 15
    assert cfg.source_limits["arxiv"] == 10


def test_load_config_reads_named_rss_feeds(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[[rss_feeds]]
name = "rss_sspai_ai"
url = "https://sspai.com/feed"
include_keywords = ["AI", "人工智能"]
limit = 12
category = "practical"
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert len(cfg.rss_feeds) == 1
    assert cfg.rss_feeds[0].name == "rss_sspai_ai"
    assert cfg.rss_feeds[0].include_keywords == ("AI", "人工智能")
    assert cfg.rss_feeds[0].limit == 12
    assert cfg.rss_feeds[0].category == "practical"


def test_load_config_uses_generation_defaults_when_keys_omitted(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")

    cfg = load_config(path)
    assert cfg.hermes_command == "hermes"
    assert cfg.generation_timeout_seconds == 600
    assert cfg.generation_retries == 1


def test_load_config_reads_generation_values(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
hermes_command = "/home/agentuser/.local/bin/hermes"
generation_timeout_seconds = 420
generation_retries = 3
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.hermes_command == "/home/agentuser/.local/bin/hermes"
    assert cfg.generation_timeout_seconds == 420
    assert cfg.generation_retries == 3


def test_load_config_reads_llm_scoring_batch_settings(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
scoring_llm_limit = 24
scoring_llm_batch_size = 8
scoring_llm_timeout_seconds = 150
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.scoring_llm_limit == 24
    assert cfg.scoring_llm_batch_size == 8
    assert cfg.scoring_llm_timeout_seconds == 150


def test_load_config_uses_generation_defaults_when_keys_missing(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("publish_limit = 1\n", encoding="utf-8")

    cfg = load_config(path)

    assert cfg.hermes_command == "hermes"
    assert cfg.generation_timeout_seconds == 600
    assert cfg.generation_retries == 1


def test_load_config_uses_visual_defaults_when_keys_omitted(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")

    cfg = load_config(path)

    assert cfg.visual_font_path is None
    assert cfg.visual_render_concurrency == 1


def test_load_config_reads_visual_settings(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        'visual_font_path = "/fonts/NotoSansCJK-Regular.ttc"\n'
        "visual_render_concurrency = 1\n",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.visual_font_path == Path("/fonts/NotoSansCJK-Regular.ttc")
    assert cfg.visual_render_concurrency == 1


def test_load_config_resolves_relative_visual_font_path_from_config(
    tmp_path: Path,
):
    path = tmp_path / "config.toml"
    path.write_text(
        'visual_font_path = "fonts/NotoSansCJK-Regular.ttc"\n',
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.visual_font_path == (
        tmp_path / "fonts" / "NotoSansCJK-Regular.ttc"
    )


def test_load_config_uses_visual_defaults_when_keys_missing(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("publish_limit = 1\n", encoding="utf-8")

    cfg = load_config(path)

    assert cfg.visual_font_path is None
    assert cfg.visual_render_concurrency == 1


@pytest.mark.parametrize(
    "toml_value",
    [
        "true",
        "42",
        "1.5",
        '["fonts/NotoSansCJK-Regular.ttc"]',
        '{ path = "fonts/NotoSansCJK-Regular.ttc" }',
        '""',
        '"   "',
    ],
)
def test_visual_font_path_requires_nonempty_string(
    tmp_path: Path, toml_value: str
):
    path = tmp_path / "config.toml"
    path.write_text(
        f"visual_font_path = {toml_value}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="visual_font_path"):
        load_config(path)


@pytest.mark.parametrize(
    "toml_value",
    ["0", "-1", "2", "true", "false", '"1"', "1.0"],
)
def test_visual_render_concurrency_is_exactly_integer_one(
    tmp_path: Path, toml_value: str
):
    path = tmp_path / "config.toml"
    path.write_text(
        f"visual_render_concurrency = {toml_value}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"^visual_render_concurrency must be the integer 1$",
    ):
        load_config(path)


def test_load_config_rejects_empty_hermes_command(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('hermes_command = "   "\n', encoding="utf-8")

    with pytest.raises(ValueError, match="hermes_command"):
        load_config(path)


@pytest.mark.parametrize("timeout", [0, -1])
def test_load_config_rejects_nonpositive_generation_timeout(
    tmp_path: Path, timeout: int
):
    path = tmp_path / "config.toml"
    path.write_text(
        f"generation_timeout_seconds = {timeout}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="generation_timeout_seconds"):
        load_config(path)


def test_load_config_rejects_negative_generation_retries(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("generation_retries = -1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="generation_retries"):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "toml_value"),
    [
        ("hermes_command", "123"),
        ("generation_timeout_seconds", '"420"'),
        ("generation_retries", "1.0"),
    ],
)
def test_load_config_rejects_invalid_generation_types(
    tmp_path: Path, field: str, toml_value: str
):
    path = tmp_path / "config.toml"
    path.write_text(f"{field} = {toml_value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        load_config(path)


def test_source_item_stable_dedupe_key():
    item = SourceItem(
        source="github",
        external_id="owner/repo",
        title="A Repo",
        url="https://github.com/owner/repo",
        summary="demo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": 42},
    )

    assert item.dedupe_key == "github:owner/repo"


def test_load_config_resolves_pack_dir(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('pack_dir = "packs/my-topic"\n', encoding="utf-8")

    cfg = load_config(path)

    assert cfg.pack_dir == tmp_path / "packs" / "my-topic"
