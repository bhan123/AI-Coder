from ai_content_loop.sources.arxiv import parse_arxiv_feed
from ai_content_loop.sources.github import parse_github_search
from ai_content_loop.sources.hackernews import parse_hn_items
from ai_content_loop.sources.huggingface import parse_huggingface_models
from ai_content_loop.sources.producthunt import parse_producthunt_posts


def test_parse_github_search_normalizes_items():
    payload = {
        "items": [
            {
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "description": "AI workflow helper",
                "stargazers_count": 100,
                "forks_count": 8,
                "updated_at": "2026-06-30T00:00:00Z",
            }
        ]
    }

    items = parse_github_search(payload, fetched_at="2026-06-30T08:00:00Z")

    assert items[0].dedupe_key == "github:owner/repo"
    assert items[0].title == "owner/repo"
    assert items[0].raw["stars"] == 100


def test_parse_hn_items_uses_show_hn_title():
    payload = [
        {
            "id": 123,
            "title": "Show HN: Tiny AI tool",
            "url": "https://example.com/tool",
            "score": 55,
            "descendants": 12,
            "time": 1780000000,
        }
    ]

    items = parse_hn_items(payload, fetched_at="2026-06-30T08:00:00Z")

    assert items[0].dedupe_key == "hackernews:123"
    assert "Tiny AI tool" in items[0].title
    assert items[0].raw["comments"] == 12


def test_parse_arxiv_feed_reads_entry():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2606.00001v1</id>
        <title>Useful AI Agents</title>
        <summary>Agents that help with daily work.</summary>
        <published>2026-06-30T00:00:00Z</published>
      </entry>
    </feed>
    """

    items = parse_arxiv_feed(xml, fetched_at="2026-06-30T08:00:00Z")

    assert items[0].source == "arxiv"
    assert items[0].external_id == "2606.00001v1"
    assert items[0].title == "Useful AI Agents"


def test_parse_huggingface_models_normalizes_likes_and_downloads():
    payload = [{"modelId": "org/model", "likes": 33, "downloads": 900, "tags": ["text-generation"]}]

    items = parse_huggingface_models(payload, fetched_at="2026-06-30T08:00:00Z")

    assert items[0].dedupe_key == "huggingface:org/model"
    assert items[0].raw["likes"] == 33
    assert items[0].raw["downloads"] == 900


def test_parse_producthunt_posts_normalizes_votes():
    payload = {
        "data": {
            "posts": {
                "edges": [
                    {
                        "node": {
                            "id": "post-1",
                            "name": "AI Customer Bot",
                            "tagline": "Support bot for tiny teams",
                            "url": "https://producthunt.com/posts/ai-customer-bot",
                            "votesCount": 88,
                            "createdAt": "2026-06-30T00:00:00Z",
                        }
                    }
                ]
            }
        }
    }

    items = parse_producthunt_posts(payload, fetched_at="2026-06-30T08:00:00Z")

    assert items[0].dedupe_key == "producthunt:post-1"
    assert items[0].raw["votes"] == 88
