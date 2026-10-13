"""回复上下文继承、历史窗口与可重复聚合的回归测试。"""
from __future__ import annotations

from datetime import date, timedelta

from analysis.board_matcher import load_boards, load_extras
from analysis.pipeline import analyze_items, fetch_recent_items, run_daily_pipeline
from analysis.sentiment import load_lexicon
from crawler.hupu_crawler import Reply, Thread
from storage.connection import session
from storage.persist import persist_batch


def _thread(thread_id: str, post_time: str, *, title: str = "半导体景气回升") -> Thread:
    return Thread(
        thread_id=thread_id,
        title=title,
        content="行业基本面正在改善。",
        replies=1,
        likes=0,
        views=0,
        author_hash=f"author-{thread_id}",
        post_time=post_time,
        crawl_time=post_time,
        url=f"https://bbs.hupu.com/{thread_id}.html",
        board="stock",
    )


def _reply(thread_id: str, reply_id: str, reply_time: str, content: str = "明天继续涨") -> Reply:
    return Reply(
        reply_id=reply_id,
        thread_id=thread_id,
        content=content,
        likes=0,
        author_hash=f"reply-author-{reply_id}",
        reply_time=reply_time,
        crawl_time=reply_time,
        floor=1,
    )


def test_generic_reply_inherits_its_parent_thread_board(tmp_path) -> None:
    db_path = str(tmp_path / "context.db")
    with session(db_path) as conn:
        persist_batch(
            conn,
            [_thread("t1", "2026-07-20T09:00:00")],
            [_reply("t1", "r1", "2026-07-20T09:10:00")],
        )
        rows = fetch_recent_items(
            conn,
            window=("2026-07-20T00:00:00", "2026-07-21T00:00:00"),
        )

    analyses = analyze_items(
        rows,
        load_boards("config/boards.json"),
        load_extras("config/boards_extra.json"),
        load_lexicon("config/sentiment_lexicon.json"),
        "test-v1",
    )

    reply_boards = {a["board"] for a in analyses if a["item_id"] == "r1"}
    assert reply_boards == {"半导体"}


def test_fetch_recent_items_honours_both_window_boundaries(tmp_path) -> None:
    db_path = str(tmp_path / "window.db")
    with session(db_path) as conn:
        persist_batch(
            conn,
            [
                _thread("before", "2026-07-19T23:59:59"),
                _thread("inside", "2026-07-20T09:00:00"),
                _thread("after", "2026-07-21T00:00:00"),
            ],
            [],
        )
        rows = fetch_recent_items(
            conn,
            window=("2026-07-20T00:00:00", "2026-07-21T00:00:00"),
        )

    assert {(r["id"], r["type"]) for r in rows} == {("inside", "thread")}


def test_backfill_window_rebuilds_history_in_chronological_order(tmp_path) -> None:
    db_path = str(tmp_path / "backfill.db")
    start_day = date(2026, 6, 1)
    days = 21
    threads = []
    replies = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        day_iso = day.isoformat()
        thread_id = f"t-{day_iso}"
        threads.append(_thread(thread_id, f"{day_iso}T09:00:00"))
        replies.append(_reply(thread_id, f"r-{day_iso}", f"{day_iso}T09:10:00"))

    with session(db_path) as conn:
        persist_batch(conn, threads, replies)

    run_daily_pipeline(
        db_path=db_path,
        window=(f"{start_day.isoformat()}T00:00:00", "2026-06-22T00:00:00"),
        historical_mode=True,
    )

    with session(db_path) as conn:
        rows = conn.execute(
            "SELECT date, history_days FROM daily_metrics WHERE board = '半导体' ORDER BY date"
        ).fetchall()

    assert len(rows) == days
    assert [row["history_days"] for row in rows] == list(range(1, days + 1))


def test_existing_thread_refreshes_mutable_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "refresh.db")
    original = _thread("t1", "2026-07-20T09:00:00")
    refreshed = _thread("t1", "2026-07-20T09:00:00")
    refreshed.replies = 42
    refreshed.likes = 9
    refreshed.views = 1234

    with session(db_path) as conn:
        persist_batch(conn, [original], [])
        new_threads, _, existing_threads = persist_batch(conn, [refreshed], [])
        stored = conn.execute(
            "SELECT replies, likes, views FROM threads WHERE thread_id = 't1'"
        ).fetchone()

    assert new_threads == 0
    assert existing_threads == 1
    assert tuple(stored) == (42, 9, 1234)
