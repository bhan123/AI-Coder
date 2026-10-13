"""Run-audit and freshness-health regression tests."""
from __future__ import annotations

from datetime import datetime

import pytest

from analysis.pipeline import run_daily_pipeline
from api.db import fetch_health_status
from crawler.hupu_crawler import Thread
from storage.connection import session
from storage.persist import persist_batch


def test_successful_pipeline_records_terminal_audit_row(tmp_path) -> None:
    db_path = tmp_path / "audit.db"
    post_time = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    thread = Thread(
        thread_id="audit-thread",
        title="半导体上涨",
        content="半导体今天表现强势",
        replies=0,
        likes=0,
        views=1,
        author_hash="audit-author",
        post_time=post_time,
        crawl_time=post_time,
        url="https://example.test/audit-thread",
        board="stock",
    )
    with session(db_path) as conn:
        persist_batch(conn, [thread], [])

    stats = run_daily_pipeline(db_path=str(db_path))

    with session(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, started_at, finished_at, analyzed_items, matched_items,
                   unmatched_items, top_board_count, error_summary
            FROM pipeline_runs
            """
        ).fetchone()

    assert row is not None
    assert row["status"] == "success"
    assert row["started_at"] is not None
    assert row["finished_at"] is not None
    assert row["analyzed_items"] == stats["analyzed"]
    assert row["matched_items"] == stats["matched_items"]
    assert row["unmatched_items"] == stats["unmatched_items"]
    assert row["top_board_count"] == stats["top_n_boards"]
    assert row["error_summary"] is None


def test_failed_pipeline_marks_its_running_audit_row_and_reraises(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "failed-audit.db"
    expected_run_id = "failure-audit-run"
    error_message = "x" * 1001

    def fail_loading_boards(_path: str) -> list[object]:
        raise RuntimeError(error_message)

    monkeypatch.setattr("analysis.pipeline.uuid.uuid4", lambda: expected_run_id)
    monkeypatch.setattr("analysis.pipeline.load_boards", fail_loading_boards)

    with pytest.raises(RuntimeError, match=error_message):
        run_daily_pipeline(db_path=str(db_path))

    with session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, status, finished_at, error_summary
            FROM pipeline_runs
            WHERE run_id = ?
            """,
            (expected_run_id,),
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "failed"
    assert row["finished_at"] is not None
    assert row["error_summary"] == error_message[:1000]


def test_health_status_uses_fixed_freshness_thresholds(tmp_path) -> None:
    db_path = tmp_path / "health.db"
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO threads (thread_id, title, content, post_time, crawl_time)
            VALUES ('thread-1', 'title', 'content', '2026-01-15 06:00:00', '2026-01-15 06:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO replies (reply_id, thread_id, content, reply_time, crawl_time)
            VALUES ('reply-1', 'thread-1', 'reply', '2026-01-15 08:00:00', '2026-01-15 08:00:00')
            """
        )
        conn.execute(
            "INSERT INTO sector_prices (board, date, close) VALUES ('半导体', '2026-01-12', 1.0)"
        )
        conn.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, finished_at, status)
            VALUES ('run-success', '2026-01-15T08:30:00', '2026-01-15T09:00:00', 'success')
            """
        )
        conn.commit()

    now = datetime(2026, 1, 15, 12, 0, 0)
    fresh = fetch_health_status(db_path=str(db_path), now=now)

    assert fresh["status"] == "ok"
    assert fresh["sources"]["forum"] == {
        "latest": "2026-01-15 08:00:00", "age_hours": 4.0, "fresh": True,
    }
    assert fresh["sources"]["analysis"] == {
        "latest": "2026-01-15T09:00:00", "age_hours": 3.0, "fresh": True,
    }
    assert fresh["sources"]["price"] == {
        "latest": "2026-01-12", "age_hours": 84.0, "fresh": True,
    }

    stale = fetch_health_status(
        db_path=str(db_path), now=datetime(2026, 1, 16, 17, 0, 0),
    )

    assert stale["status"] == "degraded"
    assert stale["sources"]["forum"]["fresh"] is False
    assert stale["sources"]["analysis"]["fresh"] is False
    assert stale["sources"]["price"]["fresh"] is False
