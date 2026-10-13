"""FastAPI 路由的 DB 查询层。

返回值都是可 JSON 序列化的 dict / list；不做任何 transformation 之外的包装。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from business_time import business_now
from storage.connection import DEFAULT_DB_PATH, session


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def fetch_latest_snapshot_date(db_path: str | None = None) -> str | None:
    """Return the newest complete dashboard snapshot date known to SQLite."""
    with session(db_path or DEFAULT_DB_PATH) as conn:
        row = conn.execute("SELECT MAX(date) AS date FROM daily_metrics").fetchone()
    return row["date"] if row else None


def fetch_today_all(
    db_path: str | None = None,
    *,
    as_of_date: str | None = None,
) -> list[dict]:
    """Return one coherent daily snapshot instead of mixing per-board dates."""
    with session(db_path or DEFAULT_DB_PATH) as conn:
        snapshot_date = as_of_date
        if snapshot_date is None:
            snapshot_date = conn.execute(
                "SELECT MAX(date) AS date FROM daily_metrics"
            ).fetchone()["date"]
        if snapshot_date is None:
            return []
        rows = conn.execute(
            """
            SELECT * FROM daily_metrics
            WHERE date = ?
            ORDER BY crowding_score DESC NULLS LAST, board
            """,
            (snapshot_date,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def fetch_board_latest(
    name: str,
    db_path: str | None = None,
    *,
    as_of_date: str | None = None,
) -> dict | None:
    """单板块最新一条 daily_metrics + 当日 Top 10 高热度帖子（来自 threads 表）。

    帖子按当天的 post_count / likes 估热度的近似：直接拿当天的帖子按 views desc 取 10 条。
    """
    with session(db_path or DEFAULT_DB_PATH) as conn:
        if as_of_date is None:
            row = conn.execute(
                """
                SELECT * FROM daily_metrics WHERE board = ?
                ORDER BY date DESC LIMIT 1
                """,
                (name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM daily_metrics WHERE board = ? AND date = ?",
                (name, as_of_date),
            ).fetchone()
        if not row:
            return None
        out = _row_to_dict(row)
        # 当日高热帖必须命中当前板块；threads 本身没有 board 字段。
        today_posts = conn.execute(
            """
            SELECT t.thread_id, t.title, t.replies, t.likes, t.views,
                   t.author_hash, t.post_time, t.content
            FROM threads t
            WHERE date(t.post_time) = ?
              AND EXISTS (
                  SELECT 1 FROM item_analysis a
                  WHERE a.item_id = t.thread_id
                    AND a.item_type = 'thread'
                    AND a.board = ?
              )
            ORDER BY t.views DESC, t.likes DESC
            LIMIT 10
            """,
            (out["date"], name),
        ).fetchall()
        out["top_posts"] = [_row_to_dict(r) for r in today_posts]
        return out


def fetch_board_history(name: str, days: int = 30, db_path: str | None = None) -> list[dict]:
    """单板块最近 N 日 daily_metrics。"""
    with session(db_path or DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_metrics
            WHERE board = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (name, days),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def fetch_global_stats(
    db_path: str | None = None,
    *,
    as_of_date: str | None = None,
) -> dict:
    """Return global stats using the same snapshot date as the board list."""
    with session(db_path or DEFAULT_DB_PATH) as conn:
        snapshot_date = as_of_date
        if snapshot_date is None:
            snapshot_date = conn.execute(
                "SELECT MAX(date) AS date FROM daily_metrics"
            ).fetchone()["date"]
        today_count = conn.execute(
            "SELECT COUNT(*) AS n FROM daily_metrics WHERE date = ?",
            (snapshot_date,),
        ).fetchone()["n"]
        top_state = conn.execute(
            """
            SELECT state, COUNT(*) AS n FROM daily_metrics
            WHERE date = ?
            GROUP BY state ORDER BY n DESC, state LIMIT 1
            """,
            (snapshot_date,),
        ).fetchone()
        crawl_count = conn.execute(
            "SELECT COUNT(*) AS n FROM threads"
        ).fetchone()["n"]
        quality_row = conn.execute(
            """
            SELECT unmatched_rate, computed_at FROM daily_pipeline_stats
            ORDER BY date DESC LIMIT 1
            """
        ).fetchone()
    return {
        "as_of_date": snapshot_date,
        "today_boards": today_count,
        "dominant_state": top_state["state"] if top_state else None,
        "all_crawled_threads": crawl_count,
        "unmatched_rate": quality_row["unmatched_rate"] if quality_row else 0.0,
        "quality_computed_at": quality_row["computed_at"] if quality_row else None,
    }


def _parse_health_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _health_source(latest: str | None, now: datetime, threshold_hours: float) -> dict:
    latest_at = _parse_health_timestamp(latest)
    if latest_at is None:
        return {"latest": latest, "age_hours": None, "fresh": False}
    age_hours = max(0.0, (now - latest_at).total_seconds() / 3600)
    return {
        "latest": latest,
        "age_hours": round(age_hours, 3),
        "fresh": age_hours <= threshold_hours,
    }


def fetch_health_status(db_path: str | None = None, now: datetime | None = None) -> dict:
    """Return source freshness for forum data, pipeline analysis, and prices."""
    checked_at = now or business_now()
    with session(db_path or DEFAULT_DB_PATH) as conn:
        thread_latest = conn.execute("SELECT MAX(post_time) AS latest FROM threads").fetchone()["latest"]
        reply_latest = conn.execute("SELECT MAX(reply_time) AS latest FROM replies").fetchone()["latest"]
        price_latest = conn.execute("SELECT MAX(date) AS latest FROM sector_prices").fetchone()["latest"]
        analysis_latest = conn.execute(
            """
            SELECT finished_at AS latest FROM pipeline_runs
            WHERE status = 'success'
            ORDER BY finished_at DESC
            LIMIT 1
            """
        ).fetchone()

    forum_latest = max((value for value in (thread_latest, reply_latest) if value), default=None)
    sources = {
        "forum": _health_source(forum_latest, checked_at, threshold_hours=8),
        "analysis": _health_source(
            analysis_latest["latest"] if analysis_latest else None,
            checked_at,
            threshold_hours=30,
        ),
        "price": _health_source(price_latest, checked_at, threshold_hours=96),
    }
    return {
        "status": "ok" if all(source["fresh"] for source in sources.values()) else "degraded",
        "sources": sources,
    }
