from __future__ import annotations

from datetime import datetime

from crawler.hupu_crawler import HUPU_BASE, HupuCrawler, Reply, Thread, ThreadListItem, board_page_url
from crawler.rate_limiter import RateLimiter
from scheduler.jobs import crawl_backfill_job
from storage.connection import session
from storage.schema import init_db


def test_board_page_url_uses_extensionless_first_page() -> None:
    assert board_page_url("stock", 1) == f"{HUPU_BASE}/stock"


def test_board_page_url_uses_hyphenated_following_pages() -> None:
    assert board_page_url("stock", 2) == f"{HUPU_BASE}/stock-2"


def test_incremental_crawl_notifies_each_fetched_thread(monkeypatch) -> None:
    crawler = HupuCrawler(rate_limiter=RateLimiter(min_interval=0, max_interval=0))
    item = ThreadListItem("1", "title", "author", "hash", "2026-07-13T10:00:00", 0, "url")
    thread = Thread("1", "title", "body", 0, 0, 0, "hash", item.post_time, item.post_time, "url")
    monkeypatch.setattr(crawler, "list_board", lambda **_: [item])
    monkeypatch.setattr(crawler, "fetch_thread", lambda *_, **__: (thread, []))

    persisted: list[str] = []
    crawler.crawl_incremental(on_thread_fetched=lambda fetched, _: persisted.append(fetched.thread_id))

    assert persisted == ["1"]


def test_unbounded_reply_mode_stops_only_at_first_empty_page(monkeypatch) -> None:
    crawler = HupuCrawler(rate_limiter=RateLimiter(min_interval=0, max_interval=0), max_thread_reply_pages=None)
    first = Thread("1", "title", "body", 0, 0, 0, "hash", "2026-07-13T10:00:00", "2026-07-13T10:00:00", "url")
    requested: list[str] = []

    def fake_get(url: str) -> str:
        requested.append(url)
        return url

    def fake_parse(html: str, *_args, page: int, **_kwargs):
        if page == 1:
            return first, []
        if page <= 3:
            return first, [Reply(f"r{page}", "1", "回复", 0, "hash", "2026-07-13T10:00:00", "2026-07-13T10:00:00")]
        return first, []

    monkeypatch.setattr(crawler, "_get", fake_get)
    monkeypatch.setattr(crawler, "_parse_thread_page", fake_parse)
    _, replies = crawler.fetch_thread("1")

    assert [reply.reply_id for reply in replies] == ["r2", "r3"]
    assert requested[-1].endswith("1-4.html")


def test_backfill_resumes_from_last_persisted_reply_page(tmp_path, monkeypatch) -> None:
    item = ThreadListItem("1", "半导体", "author", "hash", "2026-07-13T10:00:00", 0, "url")
    thread = Thread("1", "半导体", "body", 0, 0, 0, "hash", item.post_time, item.post_time, "url")
    calls: list[int] = []
    fail_on_page_two = True

    monkeypatch.setattr(HupuCrawler, "list_board", lambda *_args, **_kwargs: [item])

    def fake_fetch_page(self, thread_id: str, *, page: int, **_kwargs):
        nonlocal fail_on_page_two
        calls.append(page)
        if page == 2 and fail_on_page_two:
            fail_on_page_two = False
            raise RuntimeError("temporary page failure")
        if page == 1:
            return thread, [Reply("r1", "1", "第一页", 0, "a", item.post_time, item.post_time)]
        if page == 2:
            return thread, [Reply("r2", "1", "第二页", 0, "b", item.post_time, item.post_time)]
        return thread, []

    monkeypatch.setattr(HupuCrawler, "fetch_thread_page", fake_fetch_page)
    cutoff = datetime(2026, 7, 1, 0, 0, 0)
    db_path = str(tmp_path / "backfill.db")

    first = crawl_backfill_job(db_path=db_path, cutoff=cutoff, days=60)
    second = crawl_backfill_job(db_path=db_path, cutoff=cutoff, days=60)

    with session(db_path) as conn:
        progress = conn.execute(
            "SELECT status, last_completed_page FROM backfill_thread_progress"
        ).fetchone()
        reply_count = conn.execute("SELECT count(*) FROM replies").fetchone()[0]

    assert calls == [1, 2, 2, 3]
    assert first["failed_threads"] == 1
    assert second["completed_threads"] == 1
    assert progress["status"] == "completed"
    assert progress["last_completed_page"] == 3
    assert reply_count == 2
    assert second["cutoff_reached"] is False


def test_existing_backfill_progress_table_is_migrated_with_page_checkpoint(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy-progress.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE backfill_thread_progress (
            job_key TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            listed_activity_time TIMESTAMP,
            status TEXT NOT NULL,
            completed_at TIMESTAMP,
            last_error TEXT,
            PRIMARY KEY (job_key, thread_id)
        )
        """
    )
    init_db(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(backfill_thread_progress)")}
    conn.close()

    assert "last_completed_page" in columns
