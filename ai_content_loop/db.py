from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from ai_content_loop.models import CandidateScore, SourceItem


EXCLUDE_QUEUED_SQL = """
WHERE NOT EXISTS (
    SELECT 1
    FROM publish_queue q
    WHERE q.dedupe_key = s.dedupe_key
)
"""


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
    claimed_at TEXT,
    claim_token TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_web_editions (
    dedupe_key TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL,
    exported_at TEXT NOT NULL,
    content_version TEXT NOT NULL,
    FOREIGN KEY(dedupe_key) REFERENCES publish_queue(dedupe_key)
);

CREATE TABLE IF NOT EXISTS wechat_draft_syncs (
    dedupe_key TEXT NOT NULL,
    content_version TEXT NOT NULL,
    media_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dedupe_key, content_version),
    FOREIGN KEY(dedupe_key) REFERENCES publish_queue(dedupe_key)
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
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(publish_queue)")
            }
            if "claimed_at" not in columns:
                conn.execute("ALTER TABLE publish_queue ADD COLUMN claimed_at TEXT")
            if "claim_token" not in columns:
                conn.execute("ALTER TABLE publish_queue ADD COLUMN claim_token TEXT")
            score_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(candidate_scores)")
            }
            if "llm_column" not in score_cols:
                conn.execute(
                    "ALTER TABLE candidate_scores ADD COLUMN llm_column TEXT NOT NULL DEFAULT ''"
                )
            if "llm_angle" not in score_cols:
                conn.execute(
                    "ALTER TABLE candidate_scores ADD COLUMN llm_angle TEXT NOT NULL DEFAULT ''"
                )

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

    def get_source_url(self, dedupe_key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT url FROM source_items WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        return None if row is None else str(row["url"])

    def upsert_scores(self, scores: list[CandidateScore]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO candidate_scores (
                    dedupe_key, novelty, clarity, fun, usefulness, demo,
                    heat, credibility, total, reason, llm_column, llm_angle
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    llm_column=excluded.llm_column,
                    llm_angle=excluded.llm_angle,
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
                        score.llm_column,
                        score.llm_angle,
                    )
                    for score in scores
                ],
            )

    def list_ranked_candidates(
        self, limit: int, exclude_queued: bool = False
    ) -> list[dict[str, Any]]:
        queue_filter = EXCLUDE_QUEUED_SQL if exclude_queued else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT s.dedupe_key, s.source, s.external_id, s.title, s.url, s.summary, s.raw_json,
                       c.total, c.reason, c.llm_column, c.llm_angle
                FROM source_items s
                JOIN candidate_scores c ON c.dedupe_key = s.dedupe_key
                {queue_filter}
                ORDER BY c.total DESC, s.fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "dedupe_key": row["dedupe_key"],
                "source": row["source"],
                "external_id": row["external_id"],
                "title": row["title"],
                "url": row["url"],
                "summary": row["summary"],
                "raw": json.loads(row["raw_json"]),
                "total": row["total"],
                "reason": row["reason"],
                "llm_column": row["llm_column"],
                "llm_angle": row["llm_angle"],
            }
            for row in rows
        ]

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

    def list_publish_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, title, column_name, status, bundle_path,
                       claimed_at, claim_token, created_at
                FROM publish_queue
                WHERE (? IS NULL OR status = ?)
                ORDER BY created_at DESC
                """,
                (status, status),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_publish_queue_status(self, dedupe_key: str, status: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE publish_queue
                SET status = ?,
                    claimed_at = CASE
                        WHEN ? = 'generating' THEN claimed_at
                        ELSE NULL
                    END,
                    claim_token = CASE
                        WHEN ? = 'generating' THEN claim_token
                        ELSE NULL
                    END
                WHERE dedupe_key = ?
                """,
                (status, status, status, dedupe_key),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown publish queue item: {dedupe_key}")

    def set_review_status(self, dedupe_key: str, status: str) -> None:
        allowed = {"needs_human_review", "approved", "revision_requested"}
        if status not in allowed:
            raise ValueError(f"unsupported review status: {status}")
        self.update_publish_queue_status(dedupe_key, status)

    def record_web_edition_export(
        self,
        dedupe_key: str,
        relative_path: str,
        exported_at: str,
        content_version: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_web_editions (
                    dedupe_key, relative_path, exported_at, content_version
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    relative_path=excluded.relative_path,
                    exported_at=excluded.exported_at,
                    content_version=excluded.content_version
                """,
                (dedupe_key, relative_path, exported_at, content_version),
            )

    def get_web_edition_export(
        self,
        dedupe_key: str,
    ) -> dict[str, str] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT relative_path, exported_at, content_version
                FROM review_web_editions
                WHERE dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchone()
        return None if row is None else dict(row)

    def record_wechat_draft_sync(
        self,
        dedupe_key: str,
        content_version: str,
        *,
        status: str,
        media_id: str | None,
        error: str | None,
    ) -> None:
        if status not in {"success", "error"}:
            raise ValueError("unsupported WeChat draft sync status")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO wechat_draft_syncs (
                    dedupe_key, content_version, media_id, status, error
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key, content_version) DO UPDATE SET
                    media_id=excluded.media_id,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=CURRENT_TIMESTAMP
                WHERE wechat_draft_syncs.status != 'success'
                """,
                (dedupe_key, content_version, media_id, status, error),
            )

    def get_wechat_draft_sync(
        self,
        dedupe_key: str,
        content_version: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT dedupe_key, content_version, media_id, status, error,
                       created_at, updated_at
                FROM wechat_draft_syncs
                WHERE dedupe_key = ? AND content_version = ?
                """,
                (dedupe_key, content_version),
            ).fetchone()
        return None if row is None else dict(row)

    def invalidate_web_edition_after_article_change(
        self,
        dedupe_key: str,
    ) -> None:
        """Atomically drop a stale export record and revoke prior approval."""

        with self.connect() as conn:
            conn.execute(
                "DELETE FROM review_web_editions WHERE dedupe_key = ?",
                (dedupe_key,),
            )
            conn.execute(
                """
                UPDATE publish_queue
                SET status = 'needs_human_review',
                    claimed_at = NULL,
                    claim_token = NULL
                WHERE dedupe_key = ? AND status = 'approved'
                """,
                (dedupe_key,),
            )

    def claim_publish_queue_item(self, dedupe_key: str, claim_token: str) -> bool:
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("claim_token must be a non-empty string")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE publish_queue
                SET status = 'generating',
                    claimed_at = CURRENT_TIMESTAMP,
                    claim_token = ?
                WHERE dedupe_key = ? AND status = 'needs_generation'
                """,
                (claim_token, dedupe_key),
            )
        return cursor.rowcount == 1

    def transition_claimed_publish_queue_item(
        self,
        dedupe_key: str,
        claim_token: str,
        status: str,
    ) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE publish_queue
                SET status = ?,
                    claimed_at = CASE
                        WHEN ? IN (
                            'needs_generation',
                            'needs_human_review',
                            'generation_failed'
                        ) THEN NULL
                        ELSE claimed_at
                    END,
                    claim_token = CASE
                        WHEN ? IN (
                            'needs_generation',
                            'needs_human_review',
                            'generation_failed'
                        ) THEN NULL
                        ELSE claim_token
                    END
                WHERE dedupe_key = ?
                  AND status = 'generating'
                  AND claim_token = ?
                """,
                (status, status, status, dedupe_key, claim_token),
            )
        return cursor.rowcount == 1

    def requeue_stale_generation_claims(self, lease_seconds: int = 3600) -> int:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than 0")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE publish_queue
                SET status = 'needs_generation',
                    claimed_at = NULL,
                    claim_token = NULL
                WHERE status = 'generating'
                  AND (
                      claimed_at IS NULL
                      OR claimed_at < datetime('now', ?)
                  )
                """,
                (f"-{lease_seconds} seconds",),
            )
        return cursor.rowcount
