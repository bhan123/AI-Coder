"""SQLite 持久化层。

设计文档 §4.1 表结构。所有 upsert 用 INSERT OR REPLACE，
主键/唯一键冲突时整行替换为最新一次 crawl_time 的版本。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from crawler.hupu_crawler import Reply, Thread


def upsert_thread(conn: sqlite3.Connection, thread: Thread) -> None:
    """替换式写入主帖。已存在则整行替换为新 crawl_time 版本。"""
    conn.execute(
        """
        INSERT OR REPLACE INTO threads
            (thread_id, title, content, replies, likes, views,
             author_hash, post_time, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread.thread_id,
            thread.title,
            thread.content,
            thread.replies,
            thread.likes,
            thread.views,
            thread.author_hash,
            thread.post_time,
            thread.crawl_time,
        ),
    )


def upsert_reply(conn: sqlite3.Connection, reply: Reply) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO replies
            (reply_id, thread_id, content, likes,
             author_hash, reply_time, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reply.reply_id,
            reply.thread_id,
            reply.content,
            reply.likes,
            reply.author_hash,
            reply.reply_time,
            reply.crawl_time,
        ),
    )


def list_crawled_thread_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT thread_id FROM threads").fetchall()
    return {r["thread_id"] for r in rows}


def persist_batch(
    conn: sqlite3.Connection,
    threads: Iterable[Thread],
    replies: Iterable[Reply],
) -> tuple[int, int, int]:
    """写入一批抓取结果，返回 (新主帖数, 回复数, 已存在主帖数)。

    已存在主帖仍会 upsert，确保回复数、亮数、浏览数等会随增量抓取刷新。
    """
    existing = list_crawled_thread_ids(conn)
    new_threads = 0
    skipped = 0
    thread_buffer: list[Thread] = []
    for t in threads:
        if t.thread_id in existing:
            skipped += 1
        else:
            new_threads += 1
        thread_buffer.append(t)

    replies_buffer = list(replies)
    cur = conn.cursor()
    try:
        for t in thread_buffer:
            upsert_thread(conn, t)
        for r in replies_buffer:
            upsert_reply(conn, r)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return new_threads, len(replies_buffer), skipped
