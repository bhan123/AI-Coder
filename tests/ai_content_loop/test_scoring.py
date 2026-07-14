from ai_content_loop.models import SourceItem
from ai_content_loop.scoring import score_item, score_items


def make_item(title: str, summary: str, raw: dict) -> SourceItem:
    return SourceItem(
        source="github",
        external_id=title.lower().replace(" ", "-"),
        title=title,
        url="https://example.com",
        summary=summary,
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw=raw,
    )


def test_score_item_rewards_easy_fun_useful_demo_content():
    item = make_item(
        title="AI screenshot tool for content creators",
        summary="Generate images, summarize pages, and automate daily writing with a demo.",
        raw={"stars": 500, "likes": 100, "downloads": 2000},
    )

    score = score_item(item)

    assert score.clarity >= 7
    assert score.fun >= 6
    assert score.usefulness >= 8
    assert score.demo >= 7
    assert score.total > 70


def test_score_items_orders_by_total_desc():
    strong = make_item("AI demo automation tool", "A useful demo for writing and work.", {"stars": 900})
    weak = make_item("Sparse library", "", {})

    scores = score_items([weak, strong])

    assert scores[0].dedupe_key == strong.dedupe_key
