from pathlib import Path
import sqlite3

import pytest

from engine.db import ContentStore
from engine.models import CandidateScore, SourceItem


def make_item(
    stars: int = 10,
    external_id: str = "owner/repo",
    title: str = "Useful AI Repo",
) -> SourceItem:
    return SourceItem(
        source="github",
        external_id=external_id,
        title=title,
        url=f"https://github.com/{external_id}",
        summary="A useful AI automation repo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": stars},
    )


def make_score(item: SourceItem, total: float = 78.0) -> CandidateScore:
    return CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=8,
        clarity=9,
        fun=7,
        usefulness=9,
        demo=6,
        heat=5,
        credibility=8,
        total=total,
        reason="Clear, useful, and credible.",
    )


def test_store_upserts_source_item(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    store.upsert_source_items([make_item(stars=10)])
    store.upsert_source_items([make_item(stars=20)])

    rows = store.list_source_items(limit=10)
    assert len(rows) == 1
    assert rows[0].raw["stars"] == 20


def test_store_gpt_polish_job_is_idempotent_claimed_once_and_submitted(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    store.upsert_source_items([item])
    store.upsert_publish_queue(
        item.dedupe_key,
        item.title,
        "AI discoveries",
        "needs_human_review",
        "draft.json",
    )
    request = {"article_id": "article-1", "master_markdown": "original"}

    first = store.create_gpt_polish_job(item.dedupe_key, "version-1", request)
    duplicate = store.create_gpt_polish_job(
        item.dedupe_key, "version-1", {"ignored": True}
    )
    claimed = store.claim_next_gpt_polish_job("windows-codex")

    assert duplicate["job_id"] == first["job_id"]
    assert claimed["job_id"] == first["job_id"]
    assert store.claim_next_gpt_polish_job("second-worker") is None
    assert store.submit_gpt_polish_proposal(
        first["job_id"], "wrong-worker", {"candidate": "bad"}
    ) is False
    assert store.submit_gpt_polish_proposal(
        first["job_id"], "windows-codex", {"candidate": "ready"}
    ) is True
    latest = store.latest_gpt_polish_job(item.dedupe_key)
    assert latest["status"] == "ready"
    assert latest["proposal"] == {"candidate": "ready"}


def test_store_saves_and_lists_scores(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    store.upsert_source_items([item])
    score = make_score(item)

    store.upsert_scores([score])

    ranked = store.list_ranked_candidates(limit=5)
    assert ranked[0]["dedupe_key"] == "github:owner/repo"
    assert ranked[0]["title"] == "Useful AI Repo"
    assert ranked[0]["total"] == 78.0


def test_store_only_lists_candidates_explicitly_recommended_by_llm(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    recommended = make_item(external_id="owner/useful", title="Useful app")
    rejected = make_item(external_id="owner/technical", title="Technical paper")
    store.upsert_source_items([recommended, rejected])
    store.upsert_scores(
        [make_score(recommended, total=80.0), make_score(rejected, total=95.0)]
    )

    store.reset_llm_recommendations(
        [recommended.dedupe_key, rejected.dedupe_key]
    )
    store.record_llm_recommendations(
        reviewed_keys=[recommended.dedupe_key, rejected.dedupe_key],
        recommended_keys=[recommended.dedupe_key],
    )

    ranked = store.list_ranked_candidates(limit=5, recommended_only=True)
    assert [row["dedupe_key"] for row in ranked] == [recommended.dedupe_key]


def test_store_excludes_queued_ranked_candidates(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    queued_item = make_item()
    unqueued_item = make_item(
        external_id="owner/alternative",
        title="Alternative AI Repo",
    )
    store.upsert_source_items([queued_item, unqueued_item])
    store.upsert_scores(
        [
            make_score(queued_item, total=90.0),
            make_score(unqueued_item, total=70.0),
        ]
    )
    store.upsert_publish_queue(
        dedupe_key=queued_item.dedupe_key,
        title=queued_item.title,
        column_name="AI discoveries",
        status="generation_failed",
        bundle_path="out/drafts/github-owner-repo.md",
    )

    ranked = store.list_ranked_candidates(limit=1, exclude_queued=True)

    assert [candidate["dedupe_key"] for candidate in ranked] == [
        unqueued_item.dedupe_key
    ]


@pytest.mark.parametrize("exclude_queued", [None, False])
def test_store_keeps_queued_ranked_candidates_by_default(
    tmp_path: Path, exclude_queued: bool | None
):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    store.upsert_source_items([item])
    store.upsert_scores([make_score(item)])
    store.upsert_publish_queue(
        dedupe_key=item.dedupe_key,
        title=item.title,
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="",
    )

    if exclude_queued is None:
        ranked = store.list_ranked_candidates(limit=5)
    else:
        ranked = store.list_ranked_candidates(
            limit=5, exclude_queued=exclude_queued
        )

    assert [candidate["dedupe_key"] for candidate in ranked] == [item.dedupe_key]


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


def test_store_filters_publish_queue_by_status(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/ready",
        title="Ready draft",
        column_name="AI discoveries",
        status="needs_human_review",
        bundle_path="out/drafts/ready.md",
    )
    store.upsert_publish_queue(
        dedupe_key="github:owner/pending",
        title="Pending draft",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="",
    )

    rows = store.list_publish_queue(status="needs_generation")

    assert [row["dedupe_key"] for row in rows] == ["github:owner/pending"]


def test_store_updates_publish_queue_status(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="AI Screenshot Agent",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="",
    )

    assert store.claim_publish_queue_item("github:owner/repo", "worker-a") is True
    store.update_publish_queue_status(
        dedupe_key="github:owner/repo", status="needs_human_review"
    )

    rows = store.list_publish_queue()
    assert rows[0]["status"] == "needs_human_review"
    assert rows[0]["claimed_at"] is None
    assert rows[0]["claim_token"] is None


def test_store_rejects_publish_queue_status_update_for_unknown_item(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    with pytest.raises(
        KeyError, match="unknown publish queue item: github:owner/missing"
    ):
        store.update_publish_queue_status(
            dedupe_key="github:owner/missing", status="generation_failed"
        )


def test_store_claims_publish_queue_item_only_once(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="AI Screenshot Agent",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="out/drafts/github-owner-repo.json",
    )

    first_claim = store.claim_publish_queue_item(
        "github:owner/repo", "worker-a"
    )
    competing_store = ContentStore(tmp_path / "content.sqlite3")
    second_claim = competing_store.claim_publish_queue_item(
        "github:owner/repo", "worker-b"
    )

    assert first_claim is True
    assert second_claim is False
    row = store.list_publish_queue()[0]
    assert row["status"] == "generating"
    assert row["claimed_at"] is not None
    assert row["claim_token"] == "worker-a"


def test_store_initialize_migrates_legacy_publish_queue(tmp_path: Path):
    database_path = tmp_path / "content.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE publish_queue (
                dedupe_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                column_name TEXT NOT NULL,
                status TEXT NOT NULL,
                bundle_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO publish_queue (
                dedupe_key, title, column_name, status, bundle_path
            ) VALUES (
                'github:owner/legacy', 'Legacy row', 'AI discoveries',
                'needs_generation', 'legacy.json'
            );
            """
        )

    store = ContentStore(database_path)
    store.initialize()
    store.initialize()

    with store.connect() as conn:
        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(publish_queue)")
        ]
    assert columns.count("claimed_at") == 1
    assert columns.count("claim_token") == 1
    row = store.list_publish_queue()[0]
    assert row["dedupe_key"] == "github:owner/legacy"
    assert row["claimed_at"] is None
    assert row["claim_token"] is None


def test_store_initialize_migrates_legacy_candidate_recommendation_columns(
    tmp_path: Path,
):
    database_path = tmp_path / "content.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE candidate_scores (
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
                scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    store = ContentStore(database_path)
    store.initialize()
    store.initialize()

    with store.connect() as conn:
        columns = {
            row["name"]: row
            for row in conn.execute("PRAGMA table_info(candidate_scores)")
        }
    assert columns["llm_reviewed"]["dflt_value"] == "0"
    assert columns["llm_recommended"]["dflt_value"] == "0"


def test_store_does_not_requeue_active_generation_claim(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/active",
        title="Active generation",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="active.json",
    )
    assert store.claim_publish_queue_item(
        "github:owner/active", "worker-a"
    ) is True

    requeued = store.requeue_stale_generation_claims(lease_seconds=3600)

    assert requeued == 0
    row = store.list_publish_queue()[0]
    assert row["status"] == "generating"
    assert row["claimed_at"] is not None
    assert row["claim_token"] == "worker-a"


def test_store_requeues_old_and_null_generation_claims(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    for suffix in ("old", "null"):
        store.upsert_publish_queue(
            dedupe_key=f"github:owner/{suffix}",
            title=f"{suffix} generation",
            column_name="AI discoveries",
            status="needs_generation",
            bundle_path=f"{suffix}.json",
        )
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE publish_queue
            SET status = 'generating',
                claimed_at = '2000-01-01 00:00:00',
                claim_token = 'worker-old'
            WHERE dedupe_key = 'github:owner/old'
            """
        )
        conn.execute(
            """
            UPDATE publish_queue
            SET status = 'generating',
                claimed_at = NULL,
                claim_token = 'worker-null'
            WHERE dedupe_key = 'github:owner/null'
            """
        )

    requeued = store.requeue_stale_generation_claims(lease_seconds=3600)

    assert requeued == 2
    rows = store.list_publish_queue(status="needs_generation")
    assert {row["dedupe_key"] for row in rows} == {
        "github:owner/old",
        "github:owner/null",
    }
    assert all(row["claimed_at"] is None for row in rows)
    assert all(row["claim_token"] is None for row in rows)


@pytest.mark.parametrize("claim_token", ["", "   ", None, 17])
def test_store_rejects_empty_generation_claim_token(
    tmp_path: Path, claim_token
):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    with pytest.raises(ValueError, match="claim_token"):
        store.claim_publish_queue_item("github:owner/repo", claim_token)


def test_store_only_claim_owner_can_finalize_or_requeue(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="AI Screenshot Agent",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="out/drafts/github-owner-repo.json",
    )
    assert store.claim_publish_queue_item(
        "github:owner/repo", "worker-a"
    ) is True

    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-b", "needs_human_review"
    ) is False
    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-b", "needs_generation"
    ) is False
    claimed = store.list_publish_queue()[0]
    assert claimed["status"] == "generating"
    assert claimed["claim_token"] == "worker-a"

    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-a", "needs_human_review"
    ) is True
    finalized = store.list_publish_queue()[0]
    assert finalized["status"] == "needs_human_review"
    assert finalized["claimed_at"] is None
    assert finalized["claim_token"] is None


def test_stale_worker_cannot_overwrite_new_owner(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="AI Screenshot Agent",
        column_name="AI discoveries",
        status="needs_generation",
        bundle_path="out/drafts/github-owner-repo.json",
    )
    assert store.claim_publish_queue_item(
        "github:owner/repo", "worker-a"
    ) is True
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE publish_queue
            SET claimed_at = '2000-01-01 00:00:00'
            WHERE dedupe_key = 'github:owner/repo'
            """
        )

    assert store.requeue_stale_generation_claims(lease_seconds=3600) == 1
    reclaimed = store.list_publish_queue()[0]
    assert reclaimed["claim_token"] is None
    assert store.claim_publish_queue_item(
        "github:owner/repo", "worker-b"
    ) is True

    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-a", "needs_human_review"
    ) is False
    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-a", "needs_generation"
    ) is False
    owned_by_b = store.list_publish_queue()[0]
    assert owned_by_b["status"] == "generating"
    assert owned_by_b["claim_token"] == "worker-b"

    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-b", "needs_human_review"
    ) is True
    finalized = store.list_publish_queue()[0]
    assert finalized["status"] == "needs_human_review"
    assert finalized["claim_token"] is None


@pytest.mark.parametrize("lease_seconds", [0, -1])
def test_store_rejects_nonpositive_generation_lease(
    tmp_path: Path, lease_seconds: int
):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()

    with pytest.raises(ValueError, match="lease_seconds"):
        store.requeue_stale_generation_claims(lease_seconds=lease_seconds)


def test_get_source_url_returns_url_for_known_item(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item(external_id="owner/repo")
    store.upsert_source_items([item])

    assert store.get_source_url(item.dedupe_key) == item.url
    assert store.get_source_url("missing") is None


def test_set_review_status_accepts_only_review_states(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        "github:owner/repo",
        "Repo",
        "开源项目淘金",
        "needs_human_review",
        str(tmp_path / "draft.json"),
    )

    store.set_review_status("github:owner/repo", "approved")
    assert store.list_publish_queue()[0]["status"] == "approved"

    with pytest.raises(ValueError, match="unsupported review status"):
        store.set_review_status("github:owner/repo", "generating")
