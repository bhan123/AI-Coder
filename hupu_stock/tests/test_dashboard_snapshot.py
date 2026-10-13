"""Dashboard snapshot, board evidence and idempotency regressions."""
from __future__ import annotations

from analysis.pipeline import aggregate_daily_metrics, write_pipeline_stats
from api.db import (
    fetch_board_history,
    fetch_board_latest,
    fetch_global_stats,
    fetch_latest_snapshot_date,
    fetch_today_all,
)
from storage.connection import session


def _insert_metric(conn, board: str, date: str, crowding: float = 50.0) -> None:
    conn.execute(
        """
        INSERT INTO daily_metrics (
            board, date, crowding_score, state, metric_version,
            lexicon_version, board_dict_version
        ) VALUES (?, ?, ?, '样本不足', 'v1', 'lex-v1', 'board-v1')
        """,
        (board, date, crowding),
    )


def test_overview_uses_one_coherent_snapshot_date(tmp_path) -> None:
    db_path = tmp_path / "snapshot.db"
    with session(db_path) as conn:
        _insert_metric(conn, "半导体", "2026-07-20", 70)
        _insert_metric(conn, "白酒", "2026-07-20", 60)
        _insert_metric(conn, "半导体", "2026-07-21", 80)
        conn.commit()

    assert fetch_latest_snapshot_date(str(db_path)) == "2026-07-21"
    latest = fetch_today_all(str(db_path))
    assert [(row["board"], row["date"]) for row in latest] == [
        ("半导体", "2026-07-21"),
    ]
    previous = fetch_today_all(str(db_path), as_of_date="2026-07-20")
    assert {row["board"] for row in previous} == {"半导体", "白酒"}


def test_board_posts_are_filtered_by_analysis_board(tmp_path) -> None:
    db_path = tmp_path / "posts.db"
    with session(db_path) as conn:
        _insert_metric(conn, "半导体", "2026-07-21", 80)
        _insert_metric(conn, "白酒", "2026-07-21", 70)
        conn.executemany(
            """
            INSERT INTO threads (
                thread_id, title, content, views, post_time, crawl_time
            ) VALUES (?, ?, '', ?, '2026-07-21 10:00:00', '2026-07-21 10:05:00')
            """,
            [
                ("semiconductor-post", "芯片产业链更新", 100),
                ("liquor-post", "白酒渠道观察", 1000),
            ],
        )
        conn.executemany(
            """
            INSERT INTO item_analysis (
                item_id, item_type, board, is_primary, match_weight,
                sentiment_score, matched_keywords, lexicon_version,
                board_dict_version, analyzed_at
            ) VALUES (?, 'thread', ?, 1, 1.0, 0.2, '[]', 'lex-v1', 'board-v1',
                      '2026-07-21 11:00:00')
            """,
            [
                ("semiconductor-post", "半导体"),
                ("liquor-post", "白酒"),
            ],
        )
        conn.commit()

    result = fetch_board_latest("半导体", str(db_path))
    assert result is not None
    assert [post["thread_id"] for post in result["top_posts"]] == [
        "semiconductor-post",
    ]


def test_global_stats_use_current_totals_and_latest_quality_row(tmp_path) -> None:
    db_path = tmp_path / "stats.db"
    with session(db_path) as conn:
        _insert_metric(conn, "半导体", "2026-07-21")
        for index in range(3):
            conn.execute(
                """
                INSERT INTO threads (thread_id, title, post_time, crawl_time)
                VALUES (?, 'title', '2026-07-21 10:00:00', '2026-07-21 10:05:00')
                """,
                (f"thread-{index}",),
            )
        conn.executemany(
            """
            INSERT INTO daily_pipeline_stats (
                date, crawled_threads, unmatched_rate, computed_at
            ) VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-07-20", 10, 0.9, "2026-07-20 21:30:00"),
                ("2026-07-21", 20, 0.2, "2026-07-21 21:30:00"),
            ],
        )
        conn.commit()

    stats = fetch_global_stats(str(db_path), as_of_date="2026-07-21")
    assert stats["all_crawled_threads"] == 3
    assert stats["unmatched_rate"] == 0.2
    assert stats["as_of_date"] == "2026-07-21"


def test_history_returns_latest_data_days_not_utc_calendar_window(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    with session(db_path) as conn:
        for date in ("2025-01-01", "2025-02-01", "2025-03-01"):
            _insert_metric(conn, "半导体", date)
        conn.commit()

    rows = fetch_board_history("半导体", days=2, db_path=str(db_path))
    assert [row["date"] for row in rows] == ["2025-03-01", "2025-02-01"]


def test_aggregate_history_days_is_idempotent_for_same_date(tmp_path) -> None:
    db_path = tmp_path / "history-days.db"
    analysis = {
        "item_id": "thread-1",
        "item_type": "thread",
        "board": "半导体",
        "is_primary": 1,
        "match_weight": 1.0,
        "sentiment_score": 0.5,
        "lexicon_version": "lex-v1",
        "board_dict_version": "board-v1",
        "_item_weight": 1.0,
    }
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO threads (
                thread_id, title, content, replies, likes, views,
                author_hash, post_time, crawl_time
            ) VALUES (
                'thread-1', '半导体', '半导体', 1, 1, 10,
                'author-1', '2026-07-21 10:00:00', '2026-07-21 10:05:00'
            )
            """
        )
        aggregate_daily_metrics(conn, {}, [analysis])
        aggregate_daily_metrics(conn, {}, [analysis])
        row = conn.execute(
            "SELECT history_days FROM daily_metrics WHERE board = '半导体'"
        ).fetchone()

    assert row["history_days"] == 1


def test_pipeline_stats_accept_explicit_business_date(tmp_path) -> None:
    db_path = tmp_path / "pipeline-stats.db"
    with session(db_path) as conn:
        write_pipeline_stats(
            conn,
            analyzed=10,
            matched=8,
            unmatched=2,
            top_n_boards=3,
            crawled_threads=20,
            crawled_replies=30,
            stats_date="2026-07-22",
        )
        row = conn.execute("SELECT * FROM daily_pipeline_stats").fetchone()

    assert row["date"] == "2026-07-22"
    assert row["unmatched_rate"] == 0.2
