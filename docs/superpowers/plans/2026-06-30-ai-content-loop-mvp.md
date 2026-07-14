# AI Content Loop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working vertical slice of the Hermes AI content loop: collect AI source items, score candidates, build evidence packs, generate draft bundles, place them into a human-reviewed publish queue, import metrics, and produce weekly recap input.

**Architecture:** Create an isolated Python package under `ai_content_loop/` so this new AI-content system does not couple to the existing robot data pipeline domain. Deterministic Python code handles storage, source normalization, scoring, quality gates, and queue files; Hermes consumes the generated briefs/prompts and writes back draft JSON/Markdown through the same filesystem boundary. The first MVP uses SQLite and local files, with platform auto-publishing intentionally excluded from this implementation plan.

**Tech Stack:** Python 3.11+ standard library, SQLite, pytest, TOML config, JSON/Markdown artifacts, cron/systemd/Hermes cron handoff docs.

---

## Scope

This plan implements the MVP vertical slice from the approved design:

```text
source collection -> SQLite candidate store -> deterministic scoring
-> evidence pack -> Hermes-ready writing brief -> draft bundle
-> quality gates -> human publish queue -> metrics import -> weekly recap
```

This plan does not implement browser-based auto-posting, account login automation, video generation, paid conversion flows, or local LLM hosting. The publish boundary is a queue file that a human can review and copy into WeChat, Xiaohongshu, Toutiao, or Zhihu.

## File Structure

Create these files:

```text
ai_content_loop/
  __init__.py
  cli.py
  config.py
  db.py
  evidence.py
  metrics.py
  models.py
  quality.py
  scoring.py
  templates.py
  sources/
    __init__.py
    arxiv.py
    base.py
    github.py
    hackernews.py
    huggingface.py
    producthunt.py
    rss.py
  prompts/
    scoring.md
    drafting.md
    weekly_recap.md
  config.example.toml
tests/
  ai_content_loop/
    test_config.py
    test_db.py
    test_scoring.py
    test_sources.py
    test_evidence.py
    test_quality_templates.py
    test_metrics.py
docs/
  ai-content-loop/
    lighthouse-deployment.md
    operator-runbook.md
```

Responsibilities:

- `models.py`: small dataclasses shared across the package.
- `config.py`: load TOML config and provide safe defaults.
- `db.py`: own SQLite schema, migrations, upserts, and query methods.
- `sources/*`: normalize external source payloads into `SourceItem`.
- `scoring.py`: deterministic first-pass score before Hermes judgment.
- `evidence.py`: build a compact, source-linked evidence pack.
- `templates.py`: build Hermes writing briefs and platform draft skeletons.
- `quality.py`: enforce safety, fact, and title/body gates.
- `metrics.py`: import manually collected platform metrics and aggregate weekly recap data.
- `cli.py`: expose the daily and weekly commands.
- `prompts/*.md`: stable Hermes instructions for scoring, drafting, and recap.
- `docs/ai-content-loop/*.md`: deployment and operating instructions for Tencent Cloud Lighthouse.

## Task 1: Package scaffold, config, and shared models

**Files:**
- Create: `ai_content_loop/__init__.py`
- Create: `ai_content_loop/models.py`
- Create: `ai_content_loop/config.py`
- Create: `ai_content_loop/config.example.toml`
- Test: `tests/ai_content_loop/test_config.py`

- [ ] **Step 1: Write the failing config/model tests**

Create `tests/ai_content_loop/test_config.py`:

```python
from pathlib import Path

from ai_content_loop.config import load_config
from ai_content_loop.models import SourceItem


def test_load_config_uses_defaults_when_file_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.database_path == tmp_path / "ai_content_loop.sqlite3"
    assert cfg.output_dir == tmp_path / "out"
    assert cfg.daily_raw_limit == 200
    assert cfg.daily_deep_limit == 10
    assert cfg.publish_limit == 2


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_config.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai_content_loop'`.

- [ ] **Step 3: Create the package marker**

Create `ai_content_loop/__init__.py`:

```python
"""AI content loop MVP package."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

- [ ] **Step 4: Create shared dataclasses**

Create `ai_content_loop/models.py`:

```python
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
```

- [ ] **Step 5: Create config loader**

Create `ai_content_loop/config.py`:

```python
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
    source_limits: dict[str, int] = field(default_factory=dict)
    official_rss_feeds: list[str] = field(default_factory=list)
    producthunt_token: str = ""


def _resolve_path(root_dir: Path, value: str | None, default_name: str) -> Path:
    if value:
        raw = Path(value)
        return raw if raw.is_absolute() else root_dir / raw
    return root_dir / default_name


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
    return AppConfig(
        root_dir=root_dir,
        database_path=_resolve_path(root_dir, data.get("database_path"), "ai_content_loop.sqlite3"),
        output_dir=_resolve_path(root_dir, data.get("output_dir"), "out"),
        daily_raw_limit=int(data.get("daily_raw_limit", 200)),
        daily_deep_limit=int(data.get("daily_deep_limit", 10)),
        publish_limit=int(data.get("publish_limit", 2)),
        source_limits={str(k): int(v) for k, v in data.get("source_limits", {}).items()},
        official_rss_feeds=[str(x) for x in data.get("official_rss_feeds", [])],
        producthunt_token=str(data.get("producthunt_token", "")),
    )
```

- [ ] **Step 6: Create example config**

Create `ai_content_loop/config.example.toml`:

```toml
database_path = "data/ai_content_loop.sqlite3"
output_dir = "out"
daily_raw_limit = 200
daily_deep_limit = 10
publish_limit = 2
producthunt_token = ""
official_rss_feeds = [
  "https://openai.com/news/rss.xml",
  "https://blog.google/technology/ai/rss/",
  "https://www.anthropic.com/news/rss.xml"
]

[source_limits]
github = 30
hackernews = 30
arxiv = 30
huggingface = 30
producthunt = 20
official_rss = 30
```

- [ ] **Step 7: Run the tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_config.py -q
```

Expected: PASS, `3 passed`.

- [ ] **Step 8: Commit**

```bash
git add ai_content_loop/__init__.py ai_content_loop/models.py ai_content_loop/config.py ai_content_loop/config.example.toml tests/ai_content_loop/test_config.py
git commit -m "feat: scaffold AI content loop config"
```

## Task 2: SQLite schema and repository

**Files:**
- Create: `ai_content_loop/db.py`
- Test: `tests/ai_content_loop/test_db.py`

- [ ] **Step 1: Write the failing database tests**

Create `tests/ai_content_loop/test_db.py`:

```python
from pathlib import Path

from ai_content_loop.db import ContentStore
from ai_content_loop.models import CandidateScore, SourceItem


def make_item(stars: int = 10) -> SourceItem:
    return SourceItem(
        source="github",
        external_id="owner/repo",
        title="Useful AI Repo",
        url="https://github.com/owner/repo",
        summary="A useful AI automation repo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": stars},
    )


def test_store_upserts_source_item(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    store.upsert_source_items([make_item(stars=10)])
    store.upsert_source_items([make_item(stars=20)])

    rows = store.list_source_items(limit=10)
    assert len(rows) == 1
    assert rows[0].raw["stars"] == 20


def test_store_saves_and_lists_scores(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    store.upsert_source_items([item])
    score = CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=8,
        clarity=9,
        fun=7,
        usefulness=9,
        demo=6,
        heat=5,
        credibility=8,
        total=78.0,
        reason="Clear, useful, and credible.",
    )

    store.upsert_scores([score])

    ranked = store.list_ranked_candidates(limit=5)
    assert ranked[0]["dedupe_key"] == "github:owner/repo"
    assert ranked[0]["title"] == "Useful AI Repo"
    assert ranked[0]["total"] == 78.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_db.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai_content_loop.db'`.

- [ ] **Step 3: Create SQLite repository**

Create `ai_content_loop/db.py`:

```python
from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from ai_content_loop.models import CandidateScore, SourceItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS source_items (
    dedupe_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_scores (
    dedupe_key TEXT PRIMARY KEY,
    novelty INTEGER NOT NULL,
    clarity INTEGER NOT NULL,
    fun INTEGER NOT NULL,
    usefulness INTEGER NOT NULL,
    demo INTEGER NOT NULL,
    heat INTEGER NOT NULL,
    credibility INTEGER NOT NULL,
    total REAL NOT NULL,
    reason TEXT NOT NULL,
    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dedupe_key) REFERENCES source_items(dedupe_key)
);

CREATE TABLE IF NOT EXISTS evidence_packs (
    dedupe_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dedupe_key) REFERENCES source_items(dedupe_key)
);

CREATE TABLE IF NOT EXISTS publish_queue (
    dedupe_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    column_name TEXT NOT NULL,
    status TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS platform_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL,
    platform TEXT NOT NULL,
    metric_date TEXT NOT NULL,
    views INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    collects INTEGER NOT NULL,
    comments INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    follows INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
"""


class ContentStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_source_items(self, items: list[SourceItem]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO source_items (
                    dedupe_key, source, external_id, title, url, summary,
                    published_at, fetched_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    summary=excluded.summary,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    raw_json=excluded.raw_json
                """,
                [
                    (
                        item.dedupe_key,
                        item.source,
                        item.external_id,
                        item.title,
                        item.url,
                        item.summary,
                        item.published_at,
                        item.fetched_at,
                        json.dumps(item.raw, ensure_ascii=False, sort_keys=True),
                    )
                    for item in items
                ],
            )

    def list_source_items(self, limit: int) -> list[SourceItem]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source, external_id, title, url, summary, published_at, fetched_at, raw_json
                FROM source_items
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            SourceItem(
                source=row["source"],
                external_id=row["external_id"],
                title=row["title"],
                url=row["url"],
                summary=row["summary"],
                published_at=row["published_at"],
                fetched_at=row["fetched_at"],
                raw=json.loads(row["raw_json"]),
            )
            for row in rows
        ]

    def upsert_scores(self, scores: list[CandidateScore]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO candidate_scores (
                    dedupe_key, novelty, clarity, fun, usefulness, demo,
                    heat, credibility, total, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    novelty=excluded.novelty,
                    clarity=excluded.clarity,
                    fun=excluded.fun,
                    usefulness=excluded.usefulness,
                    demo=excluded.demo,
                    heat=excluded.heat,
                    credibility=excluded.credibility,
                    total=excluded.total,
                    reason=excluded.reason,
                    scored_at=CURRENT_TIMESTAMP
                """,
                [
                    (
                        score.dedupe_key,
                        score.novelty,
                        score.clarity,
                        score.fun,
                        score.usefulness,
                        score.demo,
                        score.heat,
                        score.credibility,
                        score.total,
                        score.reason,
                    )
                    for score in scores
                ],
            )

    def list_ranked_candidates(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.dedupe_key, s.source, s.title, s.url, s.summary, s.raw_json,
                       c.total, c.reason
                FROM source_items s
                JOIN candidate_scores c ON c.dedupe_key = s.dedupe_key
                ORDER BY c.total DESC, s.fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "dedupe_key": row["dedupe_key"],
                "source": row["source"],
                "title": row["title"],
                "url": row["url"],
                "summary": row["summary"],
                "raw": json.loads(row["raw_json"]),
                "total": row["total"],
                "reason": row["reason"],
            }
            for row in rows
        ]
```

- [ ] **Step 4: Run the database tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_db.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add ai_content_loop/db.py tests/ai_content_loop/test_db.py
git commit -m "feat: add AI content SQLite store"
```

## Task 3: Deterministic source adapters

**Files:**
- Create: `ai_content_loop/sources/__init__.py`
- Create: `ai_content_loop/sources/base.py`
- Create: `ai_content_loop/sources/github.py`
- Create: `ai_content_loop/sources/hackernews.py`
- Create: `ai_content_loop/sources/arxiv.py`
- Create: `ai_content_loop/sources/huggingface.py`
- Create: `ai_content_loop/sources/producthunt.py`
- Create: `ai_content_loop/sources/rss.py`
- Test: `tests/ai_content_loop/test_sources.py`

- [ ] **Step 1: Write parser-focused failing tests**

Create `tests/ai_content_loop/test_sources.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_sources.py -q
```

Expected: FAIL with missing `ai_content_loop.sources` modules.

- [ ] **Step 3: Create source package files**

Create `ai_content_loop/sources/__init__.py`:

```python
"""Source adapters for the AI content loop."""
```

Create `ai_content_loop/sources/base.py`:

```python
from __future__ import annotations

import json
from urllib.request import Request, urlopen


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20):
    req = Request(url, headers=headers or {"User-Agent": "ai-content-loop/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> str:
    req = Request(url, headers=headers or {"User-Agent": "ai-content-loop/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")
```

- [ ] **Step 4: Create GitHub adapter**

Create `ai_content_loop/sources/github.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_json


def parse_github_search(payload: dict, fetched_at: str) -> list[SourceItem]:
    items = []
    for repo in payload.get("items", []):
        full_name = str(repo.get("full_name", "")).strip()
        if not full_name:
            continue
        items.append(
            SourceItem(
                source="github",
                external_id=full_name,
                title=full_name,
                url=str(repo.get("html_url", "")),
                summary=str(repo.get("description") or ""),
                published_at=str(repo.get("updated_at") or ""),
                fetched_at=fetched_at,
                raw={
                    "stars": int(repo.get("stargazers_count") or 0),
                    "forks": int(repo.get("forks_count") or 0),
                    "language": repo.get("language"),
                    "topics": repo.get("topics", []),
                },
            )
        )
    return items


def fetch_github_repositories(limit: int, fetched_at: str) -> list[SourceItem]:
    since = (datetime.now(UTC) - timedelta(days=14)).date().isoformat()
    query = quote(f"(ai OR artificial-intelligence OR llm OR agent) pushed:>={since}")
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
    return parse_github_search(fetch_json(url), fetched_at=fetched_at)
```

- [ ] **Step 5: Create Hacker News adapter**

Create `ai_content_loop/sources/hackernews.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_json


def parse_hn_items(payload: list[dict], fetched_at: str) -> list[SourceItem]:
    items = []
    for story in payload:
        story_id = str(story.get("id", "")).strip()
        title = str(story.get("title") or "")
        if not story_id or not title:
            continue
        published_at = datetime.fromtimestamp(int(story.get("time") or 0), tz=UTC).isoformat()
        items.append(
            SourceItem(
                source="hackernews",
                external_id=story_id,
                title=title,
                url=str(story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"),
                summary=title,
                published_at=published_at,
                fetched_at=fetched_at,
                raw={
                    "score": int(story.get("score") or 0),
                    "comments": int(story.get("descendants") or 0),
                },
            )
        )
    return items


def fetch_hackernews_show(limit: int, fetched_at: str) -> list[SourceItem]:
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/showstories.json")[:limit]
    stories = [
        fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        for story_id in ids
    ]
    return parse_hn_items(stories, fetched_at=fetched_at)
```

- [ ] **Step 6: Create arXiv adapter**

Create `ai_content_loop/sources/arxiv.py`:

```python
from __future__ import annotations

from urllib.parse import quote
import re
import xml.etree.ElementTree as ET

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_text


ATOM = "{http://www.w3.org/2005/Atom}"


def _text(parent: ET.Element, name: str) -> str:
    child = parent.find(f"{ATOM}{name}")
    return " ".join((child.text or "").split()) if child is not None else ""


def _arxiv_id(url: str) -> str:
    match = re.search(r"/abs/([^/]+)$", url)
    return match.group(1) if match else url


def parse_arxiv_feed(xml_text: str, fetched_at: str) -> list[SourceItem]:
    root = ET.fromstring(xml_text)
    items = []
    for entry in root.findall(f"{ATOM}entry"):
        url = _text(entry, "id")
        title = _text(entry, "title")
        if not url or not title:
            continue
        items.append(
            SourceItem(
                source="arxiv",
                external_id=_arxiv_id(url),
                title=title,
                url=url,
                summary=_text(entry, "summary"),
                published_at=_text(entry, "published"),
                fetched_at=fetched_at,
                raw={},
            )
        )
    return items


def fetch_arxiv_ai(limit: int, fetched_at: str) -> list[SourceItem]:
    query = quote("cat:cs.AI OR cat:cs.CL OR cat:cs.LG")
    url = f"https://export.arxiv.org/api/query?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    return parse_arxiv_feed(fetch_text(url), fetched_at=fetched_at)
```

- [ ] **Step 7: Create Hugging Face adapter**

Create `ai_content_loop/sources/huggingface.py`:

```python
from __future__ import annotations

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_json


def parse_huggingface_models(payload: list[dict], fetched_at: str) -> list[SourceItem]:
    items = []
    for model in payload:
        model_id = str(model.get("modelId", "")).strip()
        if not model_id:
            continue
        tags = model.get("tags") or []
        items.append(
            SourceItem(
                source="huggingface",
                external_id=model_id,
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                summary=", ".join(str(tag) for tag in tags[:8]),
                published_at=str(model.get("lastModified") or ""),
                fetched_at=fetched_at,
                raw={
                    "likes": int(model.get("likes") or 0),
                    "downloads": int(model.get("downloads") or 0),
                    "tags": tags,
                },
            )
        )
    return items


def fetch_huggingface_models(limit: int, fetched_at: str) -> list[SourceItem]:
    url = f"https://huggingface.co/api/models?sort=likes&direction=-1&limit={limit}"
    return parse_huggingface_models(fetch_json(url), fetched_at=fetched_at)
```

- [ ] **Step 8: Create Product Hunt adapter**

Create `ai_content_loop/sources/producthunt.py`:

```python
from __future__ import annotations

from urllib.request import Request, urlopen
import json

from ai_content_loop.models import SourceItem


QUERY = """
query Posts($first: Int!) {
  posts(first: $first, order: VOTES) {
    edges {
      node {
        id
        name
        tagline
        url
        votesCount
        createdAt
      }
    }
  }
}
"""


def parse_producthunt_posts(payload: dict, fetched_at: str) -> list[SourceItem]:
    edges = payload.get("data", {}).get("posts", {}).get("edges", [])
    items = []
    for edge in edges:
        node = edge.get("node", {})
        post_id = str(node.get("id", "")).strip()
        if not post_id:
            continue
        items.append(
            SourceItem(
                source="producthunt",
                external_id=post_id,
                title=str(node.get("name") or ""),
                url=str(node.get("url") or ""),
                summary=str(node.get("tagline") or ""),
                published_at=str(node.get("createdAt") or ""),
                fetched_at=fetched_at,
                raw={"votes": int(node.get("votesCount") or 0)},
            )
        )
    return items


def fetch_producthunt_posts(limit: int, fetched_at: str, token: str) -> list[SourceItem]:
    if not token:
        return []
    body = json.dumps({"query": QUERY, "variables": {"first": limit}}).encode("utf-8")
    req = Request(
        "https://api.producthunt.com/v2/api/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ai-content-loop/0.1",
        },
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_producthunt_posts(payload, fetched_at=fetched_at)
```

- [ ] **Step 9: Create RSS adapter**

Create `ai_content_loop/sources/rss.py`:

```python
from __future__ import annotations

import xml.etree.ElementTree as ET

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_text


def parse_rss(xml_text: str, source_name: str, fetched_at: str) -> list[SourceItem]:
    root = ET.fromstring(xml_text)
    channel_items = root.findall("./channel/item")
    items = []
    for index, node in enumerate(channel_items):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        description = (node.findtext("description") or "").strip()
        published_at = (node.findtext("pubDate") or "").strip()
        external_id = link or f"{source_name}:{index}:{title}"
        if not title:
            continue
        items.append(
            SourceItem(
                source=source_name,
                external_id=external_id,
                title=title,
                url=link,
                summary=description,
                published_at=published_at,
                fetched_at=fetched_at,
                raw={},
            )
        )
    return items


def fetch_rss_feed(url: str, source_name: str, fetched_at: str) -> list[SourceItem]:
    return parse_rss(fetch_text(url), source_name=source_name, fetched_at=fetched_at)
```

- [ ] **Step 10: Run source tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_sources.py -q
```

Expected: PASS, `5 passed`.

- [ ] **Step 11: Commit**

```bash
git add ai_content_loop/sources tests/ai_content_loop/test_sources.py
git commit -m "feat: add AI source adapters"
```

## Task 4: Scoring engine

**Files:**
- Create: `ai_content_loop/scoring.py`
- Create: `ai_content_loop/prompts/scoring.md`
- Test: `tests/ai_content_loop/test_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `tests/ai_content_loop/test_scoring.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_scoring.py -q
```

Expected: FAIL with missing `ai_content_loop.scoring`.

- [ ] **Step 3: Implement deterministic scoring**

Create `ai_content_loop/scoring.py`:

```python
from __future__ import annotations

from ai_content_loop.models import CandidateScore, SourceItem


EASY_WORDS = {"tool", "demo", "app", "workflow", "assistant", "bot", "generator", "automation"}
FUN_WORDS = {"fun", "interesting", "creative", "image", "video", "voice", "agent", "game", "chat"}
USEFUL_WORDS = {"automate", "save", "summarize", "write", "customer", "content", "sales", "work", "productivity"}
DEMO_WORDS = {"demo", "screenshot", "space", "example", "preview", "ui", "app"}


def _bounded(value: int) -> int:
    return max(1, min(10, value))


def _keyword_score(text: str, words: set[str], base: int) -> int:
    lowered = text.lower()
    hits = sum(1 for word in words if word in lowered)
    return _bounded(base + hits)


def _heat(raw: dict) -> int:
    stars = int(raw.get("stars") or 0)
    likes = int(raw.get("likes") or 0)
    downloads = int(raw.get("downloads") or 0)
    votes = int(raw.get("votes") or 0)
    hn_score = int(raw.get("score") or 0)
    value = stars + likes * 3 + downloads // 20 + votes * 4 + hn_score * 3
    if value >= 1000:
        return 10
    if value >= 500:
        return 8
    if value >= 100:
        return 6
    if value >= 20:
        return 4
    return 2


def score_item(item: SourceItem) -> CandidateScore:
    text = f"{item.title} {item.summary}"
    novelty = 7 if item.published_at else 5
    clarity = _keyword_score(text, EASY_WORDS, 5)
    fun = _keyword_score(text, FUN_WORDS, 4)
    usefulness = _keyword_score(text, USEFUL_WORDS, 5)
    demo = _keyword_score(text, DEMO_WORDS, 4)
    heat = _heat(item.raw)
    credibility = 8 if item.url.startswith("https://") else 5
    total = (
        novelty * 0.20
        + clarity * 0.20
        + fun * 0.20
        + usefulness * 0.20
        + demo * 0.10
        + heat * 0.05
        + credibility * 0.05
    ) * 10
    reason = (
        f"novelty={novelty}, clarity={clarity}, fun={fun}, usefulness={usefulness}, "
        f"demo={demo}, heat={heat}, credibility={credibility}"
    )
    return CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=novelty,
        clarity=clarity,
        fun=fun,
        usefulness=usefulness,
        demo=demo,
        heat=heat,
        credibility=credibility,
        total=round(total, 2),
        reason=reason,
    )


def score_items(items: list[SourceItem]) -> list[CandidateScore]:
    return sorted((score_item(item) for item in items), key=lambda score: score.total, reverse=True)
```

- [ ] **Step 4: Create Hermes scoring prompt**

Create `ai_content_loop/prompts/scoring.md`:

````markdown
# Hermes 选题评分提示词

你是 AI 内容传播账号的选题编辑。目标不是写技术论文，而是找到“普通读者看得懂、觉得有趣、愿意收藏/转发”的 AI 工具、项目或趋势。

请基于候选项目的标题、摘要、来源、热度和证据链接，给出 0-10 分评分：

- 新鲜度
- 易懂程度
- 趣味/传播性
- 实用价值
- 演示效果/截图效果
- 讨论热度
- 事实可信度

优先选择：

- 3 秒内能讲清楚价值；
- 有截图、Demo、案例、Repo、产品页；
- 能关联提效、学习、内容生产、生活便利、情绪价值、获客、降本中的至少一种；
- 不是纯程序员自嗨；
- 有可核验的一手来源。

输出 JSON 数组，每个元素包含：

```json
{
  "dedupe_key": "source:id",
  "recommended": true,
  "score": 86,
  "column": "AI 神器发现",
  "angle": "面向泛读者的写作角度",
  "risk": "事实或平台风险"
}
```
````

- [ ] **Step 5: Run scoring tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_scoring.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add ai_content_loop/scoring.py ai_content_loop/prompts/scoring.md tests/ai_content_loop/test_scoring.py
git commit -m "feat: add first-pass topic scoring"
```

## Task 5: Evidence packs and writing briefs

**Files:**
- Create: `ai_content_loop/evidence.py`
- Create: `ai_content_loop/templates.py`
- Create: `ai_content_loop/prompts/drafting.md`
- Test: `tests/ai_content_loop/test_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

Create `tests/ai_content_loop/test_evidence.py`:

```python
from ai_content_loop.evidence import build_evidence_pack


def test_build_evidence_pack_keeps_source_link_and_angles():
    candidate = {
        "dedupe_key": "github:owner/repo",
        "source": "github",
        "title": "AI Screenshot Agent",
        "url": "https://github.com/owner/repo",
        "summary": "An AI agent that takes screenshots and writes content drafts.",
        "raw": {"stars": 300, "forks": 20},
        "total": 82.0,
        "reason": "high clarity and usefulness",
    }

    pack = build_evidence_pack(candidate)

    assert pack.url == "https://github.com/owner/repo"
    assert "一手来源" in pack.facts[0]
    assert any("普通读者" in angle for angle in pack.writing_angles)
    assert pack.risks
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_evidence.py -q
```

Expected: FAIL with missing `ai_content_loop.evidence`.

- [ ] **Step 3: Implement evidence pack builder**

Create `ai_content_loop/evidence.py`:

```python
from __future__ import annotations

from ai_content_loop.models import EvidencePack


def build_evidence_pack(candidate: dict) -> EvidencePack:
    raw = candidate.get("raw", {})
    facts = [
        f"一手来源：{candidate['url']}",
        f"来源平台：{candidate['source']}",
        f"候选摘要：{candidate.get('summary', '')}",
    ]
    if "stars" in raw:
        facts.append(f"GitHub stars：{raw.get('stars', 0)}")
    if "likes" in raw:
        facts.append(f"Hugging Face likes：{raw.get('likes', 0)}")
    if "downloads" in raw:
        facts.append(f"Hugging Face downloads：{raw.get('downloads', 0)}")
    if "votes" in raw:
        facts.append(f"Product Hunt votes：{raw.get('votes', 0)}")

    risks = [
        "不要承诺收益或替代人工结果，只描述可能用途。",
        "标题可以有钩子，但正文必须回到证据。",
    ]
    if not candidate.get("summary"):
        risks.append("摘要为空，发布前需要人工补充项目实际用途。")

    writing_angles = [
        "普通读者：这个东西到底有什么用，为什么值得看一眼。",
        "职场/学生/创作者：它能不能节省时间、提高表达或辅助学习。",
        "小老板/个体户：它是否能辅助获客、客服、内容生产或交付。",
    ]
    return EvidencePack(
        dedupe_key=candidate["dedupe_key"],
        title=candidate["title"],
        url=candidate["url"],
        source=candidate["source"],
        summary=candidate.get("summary", ""),
        score_total=float(candidate["total"]),
        score_reason=candidate["reason"],
        facts=facts,
        risks=risks,
        writing_angles=writing_angles,
    )
```

- [ ] **Step 4: Implement writing templates**

Create `ai_content_loop/templates.py`:

```python
from __future__ import annotations

from ai_content_loop.models import EvidencePack


PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")


def choose_column(pack: EvidencePack) -> str:
    text = f"{pack.title} {pack.summary}".lower()
    if "github" in pack.source or "repo" in text:
        return "开源项目淘金"
    if "paper" in text or "arxiv" in pack.source:
        return "普通人也看得懂的 AI 趋势"
    if "business" in text or "sales" in text or "customer" in text:
        return "AI 副业/生意灵感"
    return "AI 神器发现"


def build_master_brief(pack: EvidencePack) -> str:
    facts = "\n".join(f"- {fact}" for fact in pack.facts)
    risks = "\n".join(f"- {risk}" for risk in pack.risks)
    angles = "\n".join(f"- {angle}" for angle in pack.writing_angles)
    return f"""# 写作简报：{pack.title}

栏目：{choose_column(pack)}
来源：{pack.source}
链接：{pack.url}
评分：{pack.score_total}
评分理由：{pack.score_reason}

## 一句话任务

写一篇好懂、有趣、重点前置的 AI 内容，让泛读者先看懂，再让高频受益人群看到用法。

## 证据

{facts}

## 可写角度

{angles}

## 风险

{risks}

## 文章结构

1. 标题：强钩子，但不虚假。
2. 开头 3 秒：它解决什么痛点。
3. 一句话结论：值不值得关注。
4. 它是什么：用人话解释。
5. 怎么用：给生活/学习/工作 2-3 个场景。
6. 价值点：能省什么、学到什么、好玩在哪、可能赚什么。
7. 限制和坑：部署、价格、门槛、可靠性。
8. 行动建议：今天可以怎么试。
9. 来源链接：保留证据。
"""


def build_platform_skeletons(pack: EvidencePack) -> dict[str, str]:
    column = choose_column(pack)
    return {
        "wechat": f"# {pack.title}\n\n栏目：{column}\n\n适合 900-1500 字，解释完整，保留来源链接：{pack.url}\n",
        "xiaohongshu": f"# {pack.title}\n\n栏目：{column}\n\n适合 300-600 字，拆成 4-6 张卡片，第一屏直接讲用途。\n",
        "toutiao": f"# {pack.title}\n\n栏目：{column}\n\n适合 700-1200 字，标题直接，信息密度高，少玩梗。\n",
        "zhihu": f"# {pack.title}\n\n栏目：{column}\n\n适合 800-1600 字，用问答口吻解释为什么值得关注。\n",
    }
```

- [ ] **Step 5: Create Hermes drafting prompt**

Create `ai_content_loop/prompts/drafting.md`:

````markdown
# Hermes 平台化草稿提示词

你是一个 AI 内容传播博主的写作搭档。根据写作简报生成 1 篇母稿和 4 个平台版本。

硬性要求：

- 先让泛读者看懂，再补充职场人、学生、创作者、小老板、个体户的使用场景。
- 标题可以有钩子，但不得捏造事实。
- 不承诺暴富，不承诺替代人工，不给医疗/法律/金融建议。
- 每篇都保留来源链接。
- 语气专业但不装，诙谐但不油。
- 重点放前面，少讲技术名词，多讲能帮读者做什么、为什么有趣。

输出 JSON：

```json
{
  "dedupe_key": "source:id",
  "column": "AI 神器发现",
  "master_title": "标题",
  "master_markdown": "母稿",
  "platform_markdown": {
    "wechat": "公众号版本",
    "xiaohongshu": "小红书版本",
    "toutiao": "头条版本",
    "zhihu": "知乎版本"
  }
}
```
````

- [ ] **Step 6: Run evidence tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_evidence.py -q
```

Expected: PASS, `1 passed`.

- [ ] **Step 7: Commit**

```bash
git add ai_content_loop/evidence.py ai_content_loop/templates.py ai_content_loop/prompts/drafting.md tests/ai_content_loop/test_evidence.py
git commit -m "feat: build evidence packs and writing briefs"
```

## Task 6: Quality gates and draft bundle generation

**Files:**
- Create: `ai_content_loop/quality.py`
- Test: `tests/ai_content_loop/test_quality_templates.py`

- [ ] **Step 1: Write failing quality tests**

Create `tests/ai_content_loop/test_quality_templates.py`:

```python
from ai_content_loop.evidence import build_evidence_pack
from ai_content_loop.quality import evaluate_draft
from ai_content_loop.templates import build_master_brief, build_platform_skeletons, choose_column


def make_pack():
    return build_evidence_pack(
        {
            "dedupe_key": "github:owner/repo",
            "source": "github",
            "title": "AI Screenshot Agent",
            "url": "https://github.com/owner/repo",
            "summary": "An AI agent that helps generate screenshots and content drafts.",
            "raw": {"stars": 100},
            "total": 80.0,
            "reason": "clear and useful",
        }
    )


def test_templates_create_brief_and_platform_skeletons():
    pack = make_pack()

    assert choose_column(pack) == "开源项目淘金"
    assert "普通读者" in build_master_brief(pack)
    assert set(build_platform_skeletons(pack)) == {"wechat", "xiaohongshu", "toutiao", "zhihu"}


def test_quality_gate_rejects_missing_source_link():
    result = evaluate_draft(
        title="这个 AI 工具有点离谱",
        markdown="它很好用，但是没有链接。",
        source_url="https://github.com/owner/repo",
    )

    assert result.passed is False
    assert "missing_source_link" in result.failures


def test_quality_gate_accepts_grounded_draft():
    result = evaluate_draft(
        title="这个 AI 工具有点离谱，但别先急着吹",
        markdown="它能辅助截图和内容草稿。来源：https://github.com/owner/repo",
        source_url="https://github.com/owner/repo",
    )

    assert result.passed is True
    assert result.failures == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/ai_content_loop/test_quality_templates.py -q
```

Expected: FAIL with missing `ai_content_loop.quality`.

- [ ] **Step 3: Implement quality gate**

Create `ai_content_loop/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


BANNED_PROMISES = ("保证赚钱", "躺赚", "稳赚", "替代所有", "100%")
RISKY_TOPICS = ("诊断疾病", "投资建议", "法律意见")


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    failures: list[str]


def evaluate_draft(title: str, markdown: str, source_url: str) -> QualityResult:
    failures: list[str] = []
    combined = f"{title}\n{markdown}"
    if source_url not in markdown:
        failures.append("missing_source_link")
    if len(title.strip()) < 8:
        failures.append("title_too_short")
    if len(markdown.strip()) < 20:
        failures.append("body_too_short")
    if any(phrase in combined for phrase in BANNED_PROMISES):
        failures.append("overpromise")
    if any(topic in combined for topic in RISKY_TOPICS):
        failures.append("high_risk_advice")
    return QualityResult(passed=not failures, failures=failures)
```

- [ ] **Step 4: Run quality/template tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_quality_templates.py -q
```

Expected: PASS, `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add ai_content_loop/quality.py tests/ai_content_loop/test_quality_templates.py
git commit -m "feat: add draft quality gates"
```

## Task 7: Metrics import and weekly recap prompt

**Files:**
- Create: `ai_content_loop/metrics.py`
- Create: `ai_content_loop/prompts/weekly_recap.md`
- Test: `tests/ai_content_loop/test_metrics.py`

- [ ] **Step 1: Write failing metrics tests**

Create `tests/ai_content_loop/test_metrics.py`:

```python
from pathlib import Path

from ai_content_loop.db import ContentStore
from ai_content_loop.metrics import import_metrics_csv, weekly_summary


def test_import_metrics_csv_and_summarize(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text(
        "dedupe_key,platform,metric_date,views,likes,collects,comments,shares,follows,notes\n"
        "github:owner/repo,wechat,2026-06-30,1000,50,30,10,8,12,good\n"
        "github:owner/repo,zhihu,2026-06-30,500,20,15,6,5,4,ok\n",
        encoding="utf-8",
    )

    imported = import_metrics_csv(store, csv_path)
    summary = weekly_summary(store, since_date="2026-06-24")

    assert imported == 2
    assert summary["total_views"] == 1500
    assert summary["total_follows"] == 16
    assert summary["platforms"]["wechat"]["views"] == 1000
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/ai_content_loop/test_metrics.py -q
```

Expected: FAIL with missing `ai_content_loop.metrics`.

- [ ] **Step 3: Add metrics methods to store**

Modify `ai_content_loop/db.py` by adding these methods inside `ContentStore`:

```python
    def insert_platform_metrics(self, rows: list[dict[str, Any]]) -> int:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO platform_metrics (
                    dedupe_key, platform, metric_date, views, likes, collects,
                    comments, shares, follows, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["dedupe_key"],
                        row["platform"],
                        row["metric_date"],
                        int(row["views"]),
                        int(row["likes"]),
                        int(row["collects"]),
                        int(row["comments"]),
                        int(row["shares"]),
                        int(row["follows"]),
                        row.get("notes", ""),
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def list_metrics_since(self, since_date: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, platform, metric_date, views, likes, collects,
                       comments, shares, follows, notes
                FROM platform_metrics
                WHERE metric_date >= ?
                ORDER BY metric_date, platform
                """,
                (since_date,),
            ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Implement metrics module**

Create `ai_content_loop/metrics.py`:

```python
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
from typing import Any

from ai_content_loop.db import ContentStore


def import_metrics_csv(store: ContentStore, csv_path: str | Path) -> int:
    with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized = []
    for row in rows:
        normalized.append(
            {
                "dedupe_key": row["dedupe_key"],
                "platform": row["platform"],
                "metric_date": row["metric_date"],
                "views": int(row["views"]),
                "likes": int(row["likes"]),
                "collects": int(row["collects"]),
                "comments": int(row["comments"]),
                "shares": int(row["shares"]),
                "follows": int(row["follows"]),
                "notes": row.get("notes", ""),
            }
        )
    return store.insert_platform_metrics(normalized)


def weekly_summary(store: ContentStore, since_date: str) -> dict[str, Any]:
    rows = store.list_metrics_since(since_date)
    platforms: dict[str, dict[str, int]] = defaultdict(
        lambda: {"views": 0, "likes": 0, "collects": 0, "comments": 0, "shares": 0, "follows": 0}
    )
    totals = {"views": 0, "likes": 0, "collects": 0, "comments": 0, "shares": 0, "follows": 0}
    for row in rows:
        platform = platforms[row["platform"]]
        for key in totals:
            value = int(row[key])
            totals[key] += value
            platform[key] += value
    return {
        "since_date": since_date,
        "total_views": totals["views"],
        "total_likes": totals["likes"],
        "total_collects": totals["collects"],
        "total_comments": totals["comments"],
        "total_shares": totals["shares"],
        "total_follows": totals["follows"],
        "platforms": dict(platforms),
    }
```

- [ ] **Step 5: Create weekly recap prompt**

Create `ai_content_loop/prompts/weekly_recap.md`:

```markdown
# Hermes 周复盘提示词

你是 AI 内容传播账号的数据复盘助手。请基于本周选题、发布记录和平台指标，给出下一周内容策略。

重点回答：

1. 哪个信息源更容易出高阅读？
2. 哪个栏目更容易涨粉？
3. 哪些标题模板点击高但互动差？
4. 哪些内容收藏高，说明有长期价值？
5. 哪些内容评论多，说明适合做系列？
6. 哪些题材触发平台风险？
7. 下周信息源权重怎么调？
8. 下周标题模板怎么调？

输出结构：

- 本周一句话结论
- 表现最好的 3 个选题
- 表现最弱的 3 个选题
- 下周加权的信息源
- 下周降权的信息源
- 下周推荐栏目比例
- 需要人工注意的平台风险
```

- [ ] **Step 6: Run metrics tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_metrics.py -q
```

Expected: PASS, `1 passed`.

- [ ] **Step 7: Commit**

```bash
git add ai_content_loop/db.py ai_content_loop/metrics.py ai_content_loop/prompts/weekly_recap.md tests/ai_content_loop/test_metrics.py
git commit -m "feat: add metrics import and recap summary"
```

## Task 8: CLI daily pipeline and publish queue

**Files:**
- Create: `ai_content_loop/cli.py`
- Modify: `ai_content_loop/db.py`
- Test: extend `tests/ai_content_loop/test_db.py`

- [ ] **Step 1: Add publish queue test**

Append to `tests/ai_content_loop/test_db.py`:

```python

def test_store_publish_queue(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="AI Screenshot Agent",
        column_name="AI 神器发现",
        status="needs_human_review",
        bundle_path="out/drafts/github-owner-repo.md",
    )

    rows = store.list_publish_queue()
    assert rows[0]["status"] == "needs_human_review"
    assert rows[0]["bundle_path"] == "out/drafts/github-owner-repo.md"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/ai_content_loop/test_db.py::test_store_publish_queue -q
```

Expected: FAIL with `AttributeError: 'ContentStore' object has no attribute 'upsert_publish_queue'`.

- [ ] **Step 3: Add publish queue store methods**

Modify `ai_content_loop/db.py` by adding these methods inside `ContentStore`:

```python
    def upsert_publish_queue(
        self,
        dedupe_key: str,
        title: str,
        column_name: str,
        status: str,
        bundle_path: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO publish_queue (dedupe_key, title, column_name, status, bundle_path)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    title=excluded.title,
                    column_name=excluded.column_name,
                    status=excluded.status,
                    bundle_path=excluded.bundle_path,
                    created_at=CURRENT_TIMESTAMP
                """,
                (dedupe_key, title, column_name, status, bundle_path),
            )

    def list_publish_queue(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, title, column_name, status, bundle_path, created_at
                FROM publish_queue
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Create CLI**

Create `ai_content_loop/cli.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import argparse
import json

from ai_content_loop.config import load_config
from ai_content_loop.db import ContentStore
from ai_content_loop.evidence import build_evidence_pack
from ai_content_loop.metrics import import_metrics_csv, weekly_summary
from ai_content_loop.scoring import score_items
from ai_content_loop.templates import build_master_brief, build_platform_skeletons, choose_column


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(dedupe_key: str) -> str:
    return dedupe_key.replace(":", "-").replace("/", "-")


def cmd_init(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    ContentStore(cfg.database_path).initialize()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"initialized {cfg.database_path}")


def cmd_score(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    items = store.list_source_items(limit=cfg.daily_raw_limit)
    scores = score_items(items)
    store.upsert_scores(scores)
    print(f"scored {len(scores)} candidates")


def cmd_build_queue(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    drafts_dir = cfg.output_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    candidates = store.list_ranked_candidates(limit=cfg.publish_limit)
    for candidate in candidates:
        pack = build_evidence_pack(candidate)
        brief = build_master_brief(pack)
        skeletons = build_platform_skeletons(pack)
        payload = {
            "dedupe_key": pack.dedupe_key,
            "title": pack.title,
            "column": choose_column(pack),
            "source_url": pack.url,
            "brief": brief,
            "platform_skeletons": skeletons,
        }
        bundle_path = drafts_dir / f"{_safe_name(pack.dedupe_key)}.json"
        bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        store.upsert_publish_queue(
            dedupe_key=pack.dedupe_key,
            title=pack.title,
            column_name=payload["column"],
            status="needs_human_review",
            bundle_path=str(bundle_path),
        )
    print(f"queued {len(candidates)} draft bundles")


def cmd_import_metrics(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    count = import_metrics_csv(store, args.csv)
    print(f"imported {count} metric rows")


def cmd_weekly_summary(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    summary = weekly_summary(store, since_date=args.since)
    output = cfg.output_dir / "weekly-summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI content loop MVP")
    parser.add_argument("--config", default="ai_content_loop/config.example.toml")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init")
    init.set_defaults(func=cmd_init)

    score = sub.add_parser("score")
    score.set_defaults(func=cmd_score)

    queue = sub.add_parser("build-queue")
    queue.set_defaults(func=cmd_build_queue)

    metrics = sub.add_parser("import-metrics")
    metrics.add_argument("csv")
    metrics.set_defaults(func=cmd_import_metrics)

    weekly = sub.add_parser("weekly-summary")
    weekly.add_argument("--since", required=True)
    weekly.set_defaults(func=cmd_weekly_summary)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run database and CLI-adjacent tests**

Run:

```bash
python -m pytest tests/ai_content_loop/test_db.py tests/ai_content_loop/test_evidence.py tests/ai_content_loop/test_quality_templates.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai_content_loop/cli.py ai_content_loop/db.py tests/ai_content_loop/test_db.py
git commit -m "feat: add AI content publish queue CLI"
```

## Task 9: Source ingestion CLI

**Files:**
- Modify: `ai_content_loop/cli.py`
- Test: parser smoke check can stay manual for this task

- [ ] **Step 1: Add ingest command imports**

Modify the import section of `ai_content_loop/cli.py` to include:

```python
from ai_content_loop.sources.arxiv import fetch_arxiv_ai
from ai_content_loop.sources.github import fetch_github_repositories
from ai_content_loop.sources.hackernews import fetch_hackernews_show
from ai_content_loop.sources.huggingface import fetch_huggingface_models
from ai_content_loop.sources.producthunt import fetch_producthunt_posts
from ai_content_loop.sources.rss import fetch_rss_feed
```

- [ ] **Step 2: Add ingest command function**

Add this function to `ai_content_loop/cli.py`:

```python
def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    fetched_at = _now()
    collected = []

    limits = cfg.source_limits
    collected.extend(fetch_github_repositories(limits.get("github", 30), fetched_at=fetched_at))
    collected.extend(fetch_hackernews_show(limits.get("hackernews", 30), fetched_at=fetched_at))
    collected.extend(fetch_arxiv_ai(limits.get("arxiv", 30), fetched_at=fetched_at))
    collected.extend(fetch_huggingface_models(limits.get("huggingface", 30), fetched_at=fetched_at))
    collected.extend(
        fetch_producthunt_posts(
            limits.get("producthunt", 20),
            fetched_at=fetched_at,
            token=cfg.producthunt_token,
        )
    )
    for index, feed_url in enumerate(cfg.official_rss_feeds):
        collected.extend(fetch_rss_feed(feed_url, source_name=f"official_rss_{index}", fetched_at=fetched_at))

    store.upsert_source_items(collected[: cfg.daily_raw_limit])
    print(f"ingested {min(len(collected), cfg.daily_raw_limit)} source items")
```

- [ ] **Step 3: Register ingest command**

Modify `build_parser()` in `ai_content_loop/cli.py` by adding this block before the `score` command:

```python
    ingest = sub.add_parser("ingest")
    ingest.set_defaults(func=cmd_ingest)
```

- [ ] **Step 4: Run full unit tests**

Run:

```bash
python -m pytest tests/ai_content_loop -q
```

Expected: PASS.

- [ ] **Step 5: Run CLI help smoke test**

Run:

```bash
python -m ai_content_loop.cli --help
```

Expected: exit code 0 and output containing `ingest`, `score`, `build-queue`, `import-metrics`, and `weekly-summary`.

- [ ] **Step 6: Commit**

```bash
git add ai_content_loop/cli.py
git commit -m "feat: add source ingestion command"
```

## Task 10: Lighthouse deployment and operator runbook

**Files:**
- Create: `docs/ai-content-loop/lighthouse-deployment.md`
- Create: `docs/ai-content-loop/operator-runbook.md`

- [ ] **Step 1: Create Lighthouse deployment doc**

Create `docs/ai-content-loop/lighthouse-deployment.md`:

````markdown
# AI Content Loop Lighthouse Deployment

Target server:

- Tencent Cloud Lighthouse
- Ubuntu
- 4 cores / 8 GB RAM

## Resource rules

- Do not run local LLMs on this server.
- Prefer API and RSS sources.
- Keep daily raw items at or below 200.
- Keep deep research candidates at or below 10.
- Generate 1-2 publish queue items per day.
- Treat browser automation as out of scope for the first 30 days.

## Suggested layout

```text
/opt/ai-content-loop/
  repo/
  data/
    ai_content_loop.sqlite3
  out/
    drafts/
    weekly-summary.json
  logs/
```

## Daily commands

```bash
cd /opt/ai-content-loop/repo
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml init
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml ingest
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml score
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml build-queue
```

## Weekly command

```bash
cd /opt/ai-content-loop/repo
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml weekly-summary --since 2026-06-24
```

## Human review boundary

The MVP writes draft bundles into `out/drafts/`. A human reviews them before publishing to WeChat, Xiaohongshu, Toutiao, or Zhihu.
````

- [ ] **Step 2: Create operator runbook**

Create `docs/ai-content-loop/operator-runbook.md`:

````markdown
# AI Content Loop Operator Runbook

## Daily review

1. Open the newest JSON files under `out/drafts/`.
2. Check source URL and evidence.
3. Reject drafts with missing source links, exaggerated claims, or risky advice.
4. Copy the platform version into the target platform editor.
5. Record platform metrics manually in a CSV with this header:

```csv
dedupe_key,platform,metric_date,views,likes,collects,comments,shares,follows,notes
```

## Metrics import

```bash
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml import-metrics /opt/ai-content-loop/metrics.csv
```

## Stop conditions

Stop publishing and inspect manually when any of these happen:

- platform login abnormality;
- captcha or account risk prompt;
- source item has no first-party URL;
- title and body do not describe the same thing;
- draft includes medical, legal, or financial advice;
- draft claims guaranteed income.

## Weekly review

Use `out/weekly-summary.json` plus Hermes weekly recap prompt to decide:

- source weights to increase;
- source weights to decrease;
- title patterns to reuse;
- columns to expand;
- topics to avoid.
````

- [ ] **Step 3: Verify docs mention the human review boundary**

Run:

```bash
rg -n "human|人工|Human|review|审核|out/drafts|Stop conditions|Stop" docs/ai-content-loop
```

Expected: output includes both `lighthouse-deployment.md` and `operator-runbook.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/ai-content-loop/lighthouse-deployment.md docs/ai-content-loop/operator-runbook.md
git commit -m "docs: add AI content loop operations guide"
```

## Task 11: End-to-end local dry run

**Files:**
- No new files required unless a failure reveals a missing test.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
python -m pytest tests/ai_content_loop -q
```

Expected: all tests pass.

- [ ] **Step 2: Initialize a temporary config and database**

Run from repo root:

```bash
python -m ai_content_loop.cli --config ai_content_loop/config.example.toml init
```

Expected: output contains `initialized`.

- [ ] **Step 3: Run a deterministic no-network score on an empty DB**

Run:

```bash
python -m ai_content_loop.cli --config ai_content_loop/config.example.toml score
```

Expected: output contains `scored 0 candidates`.

- [ ] **Step 4: Run queue generation on an empty DB**

Run:

```bash
python -m ai_content_loop.cli --config ai_content_loop/config.example.toml build-queue
```

Expected: output contains `queued 0 draft bundles`.

- [ ] **Step 5: Run CLI help**

Run:

```bash
python -m ai_content_loop.cli --help
```

Expected: output includes all command names.

- [ ] **Step 6: Commit any final corrections**

If the dry run required edits, commit only those files:

```bash
git add ai_content_loop tests/ai_content_loop docs/ai-content-loop
git commit -m "fix: stabilize AI content loop dry run"
```

If no edits were needed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage:
  - Information source collection: Tasks 3 and 9.
  - Candidate scoring: Task 4.
  - Evidence pack: Task 5.
  - Platform writing brief: Task 5.
  - Quality gates: Task 6.
  - Human publish queue: Task 8.
  - Metrics import and recap input: Task 7.
  - Lighthouse deployment guidance: Task 10.
  - End-to-end verification: Task 11.
- Safety boundary:
  - Full platform auto-publishing is excluded.
  - Human review is required before publishing.
  - Risky claims and missing source links are blocked by quality gates.
- Isolation:
  - New package lives in `ai_content_loop/`.
  - Existing robot data pipeline files are not modified.
- Test strategy:
  - Parser tests avoid network.
  - Store tests use temporary SQLite files.
  - CLI dry run is safe with an empty DB.
