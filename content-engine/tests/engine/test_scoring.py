from pathlib import Path
import subprocess
from datetime import UTC, datetime

from engine.pack import active_pack
from engine.models import SourceItem
from engine.scoring import (
    _parse_llm_scores,
    llm_score_items,
    score_item,
    score_items,
)


def make_item(title: str, summary: str, raw: dict) -> SourceItem:
    return SourceItem(
        source="github",
        external_id=title.lower().replace(" ", "-"),
        title=title,
        url="https://example.com",
        summary=summary,
        published_at=datetime.now(UTC).isoformat(),
        fetched_at="2026-06-30T08:00:00Z",
        raw=raw,
    )


def test_score_item_rewards_easy_fun_useful_demo_content():
    item = make_item(
        title="AI screenshot tool for content creators",
        summary="Generate images, summarize pages, and automate daily writing with a demo.",
        raw={"stars": 500, "likes": 100, "downloads": 2000},
    )

    score = score_item(item, active_pack())

    assert score.clarity >= 7
    assert score.fun >= 6
    assert score.usefulness >= 8
    assert score.demo >= 7
    assert score.total > 70


def test_score_items_orders_by_total_desc():
    strong = make_item("AI demo automation tool", "A useful demo for writing and work.", {"stars": 900})
    weak = make_item("Sparse library", "", {})

    scores = score_items([weak, strong], active_pack())

    assert scores[0].dedupe_key == strong.dedupe_key


def test_llm_score_items_distinguishes_valid_empty_result_from_failure(
    tmp_path: Path, monkeypatch
):
    prompt_path = tmp_path / "scoring.md"
    prompt_path.write_text("score these", encoding="utf-8")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "[]", ""),
    )
    assert llm_score_items(
        [], hermes_command="hermes", prompt_path=prompt_path
    ) == []

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "boom"),
    )
    assert llm_score_items(
        [], hermes_command="hermes", prompt_path=prompt_path
    ) is None


def test_parse_llm_scores_skips_non_json_brackets_before_result():
    output = (
        "Hermes [scoring] started\n"
        "```json\n"
        '[{"dedupe_key":"rss:1","recommended":true,"total_score":82}]\n'
        "```"
    )

    scores = _parse_llm_scores(output)

    assert scores[0]["dedupe_key"] == "rss:1"


def test_llm_score_items_requires_boolean_true_recommendation(
    tmp_path: Path, monkeypatch
):
    prompt_path = tmp_path / "scoring.md"
    prompt_path.write_text("score these", encoding="utf-8")
    stdout = (
        '[{"dedupe_key":"rss:bad","recommended":"false","total_score":99},'
        '{"dedupe_key":"rss:good","recommended":true,"total_score":80}]'
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout, ""),
    )

    scores = llm_score_items(
        [], hermes_command="hermes", prompt_path=prompt_path
    )

    assert [score["dedupe_key"] for score in scores] == ["rss:good"]
