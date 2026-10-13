"""每日分析流水线（设计文档 §6 21:00 主任务）。

做的事：
  1. 把最近 N 天抓到的 thread/reply 文本打板块标签 + 情感打分 → 写入 item_analysis
  2. 按 (board, date) 聚合到 daily_metrics
  3. 按过去 20 个交易日 effective_item_count 算 Top N，标记 is_top_board

注意事项：
  - 单条文本可能命中多个板块，必须用 match_weight 归一化后参与聚合
  - 历史分位依赖 120 日窗口；冷启动阶段使用原始值并在 confidence 上标注
  - akshare 价格接入前 PriceExtension 给定 50（中性）
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import pstdev

from analysis.board_matcher import BoardConfig, BoardExtras, load_boards, load_extras, match_board
from business_time import business_date, business_now
from analysis.metrics import (
    compute_consensus_score,
    compute_coverage_score,
    compute_crowding_score,
    compute_extreme_sent,
    compute_heat_momentum,
    compute_hot_raw,
    compute_hot_score,
    compute_price_extension,
    sent_raw_to_score,
)
from analysis.sentiment import Lexicon, item_weight, load_lexicon, score_text
from analysis.state_classifier import classify_state, compute_confidence
from storage.connection import DEFAULT_DB_PATH, session

logger = logging.getLogger(__name__)

TOP_N = 20
MIN_20D_ITEMS_FOR_TOPN = 100
HISTORY_DAYS_DEFAULT = 7


def _daily_window(conn: sqlite3.Connection, days: int = HISTORY_DAYS_DEFAULT) -> tuple[str, str]:
    """最近 N 天（按 post_time / reply_time）作为分析窗口。"""
    end = business_now()
    start = end - timedelta(days=days)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def fetch_recent_items(
    conn: sqlite3.Connection,
    days: int = HISTORY_DAYS_DEFAULT,
    window: tuple[str, str] | None = None,
):
    """返回窗口内待分析文本；回复同时携带其主帖语境。"""
    start, end = window or _daily_window(conn, days)
    rows = conn.execute(
        """
        SELECT thread_id AS id, 'thread' AS type, title || '\n' || COALESCE(content,'') AS text,
               replies, views, likes, post_time,
               NULL AS parent_thread_id, NULL AS parent_context
        FROM threads WHERE post_time >= ? AND post_time < ?
        UNION ALL
        SELECT r.reply_id AS id, 'reply' AS type, r.content AS text,
               0 AS replies, 0 AS views, r.likes, r.reply_time AS post_time,
               r.thread_id AS parent_thread_id,
               COALESCE(t.title, '') || '\n' || COALESCE(t.content, '') AS parent_context
        FROM replies r
        LEFT JOIN threads t ON t.thread_id = r.thread_id
        WHERE r.reply_time >= ? AND r.reply_time < ?
        """,
        (start, end, start, end),
    ).fetchall()
    return rows


def analyze_items(
    rows,
    boards: dict[str, BoardConfig],
    extras: BoardExtras,
    lexicon: Lexicon,
    boards_version: str,
    *,
    event_only_weights: bool = False,
) -> list[dict]:
    """对一批 item 做 (board, sentiment) 计算，返回可插入 item_analysis 的字典列表。

    每条 item 在每个命中板上各插一行（含归一化 match_weight + sentiment_score + 命中词）。
    无任何板块命中 → 板 = "其他"。
    boards_version 必须传 boards.json 顶层 version 字段（不是板名）。
    """
    analyses: list[dict] = []
    analyzed_at = business_now().isoformat(timespec="seconds")
    for r in rows:
        text = (r["text"] or "").strip()
        if not text:
            continue
        item_id = r["id"]
        item_type = r["type"]
        item_score, matched_kws = score_text(text, lexicon)
        iw = 1.0 if event_only_weights else item_weight(
            item_type,
            replies=int(r["replies"] or 0),
            views=int(r["views"] or 0),
            likes=int(r["likes"] or 0),
        )
        board_hits = match_board(text, boards, extras)
        # 大多数回复是省略主语的短句。主帖已命中具体行业时，优先继承该语境，
        # 避免把“明天继续涨”这类有效讨论错误沉到“其他”。
        if item_type == "reply" and not [hit for hit in board_hits if hit[0] != "其他"]:
            parent_context = r["parent_context"] if "parent_context" in r.keys() else ""
            if parent_context:
                parent_hits = match_board(parent_context, boards, extras)
                sector_parent_hits = [hit for hit in parent_hits if hit[0] != "其他"]
                if sector_parent_hits:
                    board_hits = sector_parent_hits
        for board, is_primary, weight, kws in board_hits:
            analyses.append({
                "item_id": f"{item_id}",
                "item_type": item_type,
                "board": board,
                "is_primary": 1 if is_primary else 0,
                "match_weight": weight,
                "sentiment_score": item_score,
                "matched_keywords": json.dumps(list(set(kws)), ensure_ascii=False),
                "lexicon_version": lexicon.version,
                "board_dict_version": boards_version,  # 设计 §4.1 字段语义：词典版本号（不是板名）
                "analyzed_at": analyzed_at,
                "_item_weight": iw,
            })
    return analyses


def persist_item_analysis(conn: sqlite3.Connection, analyses: list[dict]) -> int:
    """批量写入 item_analysis 表。"""
    if not analyses:
        return 0
    cur = conn.cursor()
    # 同一条内容重新分析后，旧的多板块关联（尤其是“其他”）必须移除，
    # 否则历史聚合会同时保留旧标签与新标签。
    item_keys = {(a["item_id"], a["item_type"]) for a in analyses}
    cur.executemany(
        "DELETE FROM item_analysis WHERE item_id = ? AND item_type = ?",
        item_keys,
    )
    for a in analyses:
        cur.execute(
            """
            INSERT OR REPLACE INTO item_analysis
                (item_id, item_type, board, is_primary, match_weight,
                 sentiment_score, matched_keywords, lexicon_version, board_dict_version, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                a["item_id"], a["item_type"], a["board"], a["is_primary"], a["match_weight"],
                a["sentiment_score"], a["matched_keywords"],
                a["lexicon_version"], a["board_dict_version"], a["analyzed_at"],
            ),
        )
    conn.commit()
    return len(analyses)


def _sector_prices_at(conn: sqlite3.Connection, board: str, ref_date: str) -> dict | None:
    """返回 (board, date) 对应的 sector_prices 行；没有就 None。"""
    return conn.execute(
        """
        SELECT pct_change_10d, up_extension_10d, down_extension_10d
        FROM sector_prices
        WHERE board = ? AND date = ?
        """,
        (board, ref_date),
    ).fetchone()


def _sector_history_for_board(conn: sqlite3.Connection, board: str, before_date: str, limit: int = 120) -> list[float]:
    """返回某 board 在指定日期之前的最近 N 个 **pct_change_10d** 值（升序时间序列）。

    用途：PriceExtension（设计 §2.3 要求基于价格序列分位）。
    """
    rows = conn.execute(
        """
        SELECT pct_change_10d FROM sector_prices
        WHERE board = ? AND date < ? AND pct_change_10d IS NOT NULL
        ORDER BY date DESC LIMIT ?
        """,
        (board, before_date, limit),
    ).fetchall()
    return [r["pct_change_10d"] for r in rows][::-1]


def _hot_raw_history_for_board(conn: sqlite3.Connection, board: str, before_date: str, limit: int = 120) -> list[float]:
    """返回某 board 在指定日期之前的最近 N 个 **hot_raw** 值（升序时间序列）。

    用途：HotScore（设计 §2.1 — 拿同板块过往 HotRaw 做百分位，不是价格序列）。
    """
    rows = conn.execute(
        """
        SELECT hot_raw FROM daily_metrics
        WHERE board = ? AND date < ? AND hot_raw IS NOT NULL
        ORDER BY date DESC LIMIT ?
        """,
        (board, before_date, limit),
    ).fetchall()
    return [r["hot_raw"] for r in rows][::-1]


def _sector_hot_raw_avg(conn: sqlite3.Connection, board: str, before_date: str, days: int = 20) -> float:
    """某 board 在 before_date 之前 N 日的 hot_raw 均值（HeatMomentum 用）。"""
    rows = conn.execute(
        """
        SELECT hot_raw FROM daily_metrics
        WHERE board = ? AND date < ? AND hot_raw IS NOT NULL
        ORDER BY date DESC LIMIT ?
        """,
        (board, before_date, days),
    ).fetchall()
    vals = [r["hot_raw"] for r in rows]
    return sum(vals) / len(vals) if vals else 0.0


def aggregate_daily_metrics(
    conn: sqlite3.Connection,
    boards: dict[str, BoardConfig],
    analyses: list[dict],
    *,
    event_only_interactions: bool = False,
) -> set[str]:
    """把 analyses 按 (board, date) 聚合写 daily_metrics。

    date 取 item 对应原文的日期（thread.post_time / reply.reply_time），从 item_id 关联查。
    """
    if not analyses:
        return set()

    # 取所有 item_id 对应的原始日期（threads.post_time / replies.reply_time）
    item_dates: dict[tuple[str, str], str] = {}  # (item_id, item_type) -> date YYYY-MM-DD
    for r in conn.execute("SELECT thread_id AS id, post_time FROM threads").fetchall():
        item_dates[(r["id"], "thread")] = _date_only(r["post_time"])
    for r in conn.execute("SELECT reply_id AS id, reply_time FROM replies").fetchall():
        item_dates[(r["id"], "reply")] = _date_only(r["reply_time"])

    # 按 (board, date) 聚合
    by_key: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "post_count": 0, "reply_count": 0,
        "_weighted_sent_sum": 0.0,
        "_weight_sum": 0.0,
        "_item_scores": [],
        "_effective": 0.0,
        "_authors": set(),
        "_views_or_likes": 0,
    })

    # 关联原表的 author_hash + 互动字段
    meta_cache: dict[tuple[str, str], dict] = {}
    for r in conn.execute(
        "SELECT thread_id AS id, 'thread' AS type, author_hash, replies, views, likes FROM threads"
    ).fetchall():
        meta_cache[(r["id"], "thread")] = {
            "author_hash": r["author_hash"], "replies": r["replies"] or 0,
            "views": r["views"] or 0, "likes": r["likes"] or 0,
        }
    for r in conn.execute(
        "SELECT reply_id AS id, 'reply' AS type, author_hash, likes FROM replies"
    ).fetchall():
        meta_cache[(r["id"], "reply")] = {
            "author_hash": r["author_hash"], "replies": 0,
            "views": 0, "likes": r["likes"] or 0,
        }

    for a in analyses:
        key = (a["item_id"], a["item_type"])
        date_str = item_dates.get(key, "")
        if not date_str:
            continue
        board = a["board"]
        m = meta_cache.get(key, {})
        author_hash = m.get("author_hash") or ""
        iw = a["_item_weight"]
        mw = a["match_weight"]
        cell = by_key[(board, date_str)]
        if a["item_type"] == "thread":
            cell["post_count"] += 1
            cell["_views_or_likes"] += (m.get("views", 0) or 0) + (m.get("likes", 0) or 0)
        else:
            cell["reply_count"] += 1
            cell["_views_or_likes"] += (m.get("likes", 0) or 0)
        cell["_weight_sum"] += iw * mw
        cell["_weighted_sent_sum"] += a["sentiment_score"] * iw * mw
        cell["_item_scores"].append(a["sentiment_score"])
        cell["_effective"] += mw
        if author_hash:
            cell["_authors"].add(author_hash)

    cur = conn.cursor()
    metric_version = "backfill-event-v1" if event_only_interactions else "v1-2026-07-10"
    lexicon_v = analyses[0]["lexicon_version"]
    dict_v = analyses[0]["board_dict_version"]

    # 历史指标依赖当天之前的序列，必须按日期顺序重建。
    for (board, date_str), cell in sorted(by_key.items(), key=lambda entry: (entry[0][1], entry[0][0])):
        if cell["_weight_sum"] == 0:
            sent_raw = 0.0
            item_sent_std = 0.0
        else:
            sent_raw = cell["_weighted_sent_sum"] / cell["_weight_sum"]
            item_sent_std = pstdev(cell["_item_scores"]) if len(cell["_item_scores"]) >= 2 else 0.0

        unique_authors = len(cell["_authors"])
        effective = cell["_effective"]
        post_count = cell["post_count"]
        reply_count = cell["reply_count"]
        views_or_likes = cell["_views_or_likes"]

        hot_raw = compute_hot_raw(
            post_count,
            reply_count,
            unique_authors,
            0 if event_only_interactions else views_or_likes,
        )

        # HotScore 取该板块过往 HotRaw 做百分位（设计 §2.1）—— 用 daily_metrics.hot_raw 而非价格序列
        hot_history = _hot_raw_history_for_board(conn, board, date_str)
        hot_score = compute_hot_score(hot_raw, hot_history)

        sent_score = sent_raw_to_score(sent_raw)
        extreme_sent = compute_extreme_sent(sent_score)
        consensus_score = compute_consensus_score(item_sent_std)

        # PriceExtension 仍取价格序列分位（设计 §2.3）
        sp = _sector_prices_at(conn, board, date_str)
        if sp is not None and sp["pct_change_10d"] is not None:
            pct10 = sp["pct_change_10d"]
            if sp["up_extension_10d"] is not None:
                price_extension = (
                    sp["up_extension_10d"] if sent_score >= 50 else sp["down_extension_10d"]
                )
            else:
                price_extension = compute_price_extension(
                    pct10, _sector_history_for_board(conn, board, date_str), sent_score,
                )
        else:
            price_extension = 50.0

        crowding_score = compute_crowding_score(hot_score, extreme_sent, consensus_score, price_extension)
        heat_momentum = compute_heat_momentum(hot_raw, _sector_hot_raw_avg(conn, board, date_str))
        coverage_score = compute_coverage_score(effective, unique_authors)

        # history_days 只统计目标日及之前的数据，重复跑同一天必须保持幂等。
        history_days = conn.execute(
            """
            SELECT COUNT(DISTINCT date) FROM daily_metrics
            WHERE board = ? AND date < ?
            """,
            (board, date_str),
        ).fetchone()[0] + 1
        confidence = compute_confidence(history_days)
        # 初版写入时 is_top_board 仍是 False，state 用占位逻辑（classify_state 看到 is_top_board=False
        # 会返回"样本不足"）；Top N 标记完后由 reclassify_with_top_n 重算 state/confidence。
        state = classify_state(
            hot_score=hot_score,
            sent_score=sent_score,
            crowding_score=crowding_score,
            heat_momentum=heat_momentum,
            price_extension=price_extension,
            is_top_board=False,
            coverage_score=coverage_score,
            history_days=history_days,
            effective_item_count=effective,
            unique_authors=unique_authors,
        )

        cur.execute(
            """
            INSERT OR REPLACE INTO daily_metrics
                (board, date, history_days, confidence, post_count, reply_count,
                 effective_item_count, unique_authors, hot_raw, hot_score, sent_score,
                 item_sent_std, consensus_score, heat_momentum, coverage_score,
                 price_extension, crowding_score, state, metric_version, lexicon_version,
                 board_dict_version, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (board, date_str, history_days, confidence, post_count, reply_count,
             round(effective, 2), unique_authors,
             round(hot_raw, 4), round(hot_score, 2), round(sent_score, 2),
             round(item_sent_std, 4), round(consensus_score, 2),
             round(heat_momentum, 3), round(coverage_score, 2),
             round(price_extension, 2), round(crowding_score, 2),
             state, metric_version, lexicon_v, dict_v,
              business_now().isoformat(timespec="seconds")),
        )
    conn.commit()
    return {date_str for _, date_str in by_key}


def _trading_dates_as_of(
    conn: sqlite3.Connection, as_of_date: str, count: int = 20,
) -> list[str]:
    """Return the latest date slots for Top-N as of ``as_of_date``.

    行情数据可用时使用真实交易日；行情补数尚未完成时，退化为论坛已有的观测日。
    Top-N 是论坛样本覆盖度门槛，不能因可选的价格源缺失而永久失效。
    """
    rows = conn.execute(
        """
        SELECT DISTINCT date FROM sector_prices
        WHERE date <= ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (as_of_date, count),
    ).fetchall()
    dates = [row["date"] for row in reversed(rows)]
    if len(dates) >= count:
        return dates
    fallback_rows = conn.execute(
        """
        SELECT DISTINCT date FROM daily_metrics
        WHERE date <= ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (as_of_date, count),
    ).fetchall()
    return [row["date"] for row in reversed(fallback_rows)]


def mark_top_n_boards(
    conn: sqlite3.Connection,
    top_n: int = TOP_N,
    *,
    metric_dates: list[str] | set[str] | None = None,
) -> int:
    """Mark Top-N boards independently for each requested metric date."""
    if metric_dates is None:
        dates = [
            row["date"]
            for row in conn.execute("SELECT DISTINCT date FROM daily_metrics ORDER BY date")
        ]
    else:
        dates = sorted(set(metric_dates))

    marked = 0
    for as_of_date in dates:
        conn.execute("UPDATE daily_metrics SET is_top_board = 0 WHERE date = ?", (as_of_date,))
        window = _trading_dates_as_of(conn, as_of_date)
        if len(window) < 20:
            continue

        date_slots = ",".join("?" * len(window))
        rows = conn.execute(
            f"""
            SELECT board, SUM(effective_item_count) AS effective_items
            FROM daily_metrics
            WHERE date IN ({date_slots})
            GROUP BY board
            HAVING effective_items >= ?
            ORDER BY effective_items DESC, board ASC
            LIMIT ?
            """,
            [*window, MIN_20D_ITEMS_FOR_TOPN, top_n],
        ).fetchall()
        top_boards = [row["board"] for row in rows]
        if not top_boards:
            continue

        board_slots = ",".join("?" * len(top_boards))
        conn.execute(
            f"""
            UPDATE daily_metrics SET is_top_board = 1
            WHERE date = ? AND board IN ({board_slots})
            """,
            [as_of_date, *top_boards],
        )
        marked += len(top_boards)
    conn.commit()
    return marked


def reclassify_with_top_n(
    conn: sqlite3.Connection, metric_dates: list[str] | set[str] | None = None,
) -> int:
    """在 mark_top_n_boards 之后跑：按当前 daily_metrics 的 is_top_board 重算 state/confidence。

    关键设计：aggregate_daily_metrics 写入时 is_top_board=False，所以首版 state 永远是"样本不足"。
    这步负责让真 Top N 板的状态机有正确的 is_top_board 输入。
    """
    cur = conn.cursor()
    query = """
        SELECT board, date, hot_score, sent_score, crowding_score,
               heat_momentum, price_extension, coverage_score,
               history_days, effective_item_count, unique_authors, is_top_board
        FROM daily_metrics
    """
    if metric_dates is None:
        rows = cur.execute(query).fetchall()
    else:
        dates = sorted(set(metric_dates))
        if not dates:
            return 0
        date_slots = ",".join("?" * len(dates))
        rows = cur.execute(f"{query} WHERE date IN ({date_slots})", dates).fetchall()
    n = 0
    for r in rows:
        new_state = classify_state(
            hot_score=r["hot_score"],
            sent_score=r["sent_score"],
            crowding_score=r["crowding_score"],
            heat_momentum=r["heat_momentum"],
            price_extension=r["price_extension"],
            is_top_board=bool(r["is_top_board"]),
            coverage_score=r["coverage_score"],
            history_days=r["history_days"],
            effective_item_count=r["effective_item_count"],
            unique_authors=r["unique_authors"],
        )
        new_confidence = compute_confidence(r["history_days"])
        cur.execute(
            """
            UPDATE daily_metrics
            SET state = ?, confidence = ?
            WHERE board = ? AND date = ?
            """,
            (new_state, new_confidence, r["board"], r["date"]),
        )
        n += 1
    conn.commit()
    return n


def write_pipeline_stats(
    conn: sqlite3.Connection,
    *,
    analyzed: int,
    matched: int,
    unmatched: int,
    top_n_boards: int,
    crawled_threads: int,
    crawled_replies: int,
    stats_date: str | None = None,
) -> None:
    """写入 daily_pipeline_stats（设计 §4.1）。

    设计要求：保证至少 1 行；analyzed=0 时 unmatched_rate 也 = 0 而不是 NULL。
    """
    unmatched_rate = (unmatched / analyzed) if analyzed > 0 else 0.0
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO daily_pipeline_stats
            (date, crawled_threads, crawled_replies, analyzed_items,
             matched_items, unmatched_items, unmatched_rate,
             top_board_count, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stats_date or business_date(),
            crawled_threads, crawled_replies, analyzed, matched, unmatched,
            unmatched_rate, top_n_boards,
            business_now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def _insert_running_pipeline_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    started_at: str,
    input_start: str,
    input_end: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_runs (run_id, started_at, status, input_start, input_end)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (run_id, started_at, input_start, input_end),
    )
    conn.commit()


def _finish_pipeline_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    stats: dict,
) -> None:
    conn.execute(
        """
        UPDATE pipeline_runs
        SET finished_at = ?, status = 'success',
            latest_thread_time = (SELECT MAX(post_time) FROM threads),
            latest_reply_time = (SELECT MAX(reply_time) FROM replies),
            latest_price_date = (SELECT MAX(date) FROM sector_prices),
            analyzed_items = ?, matched_items = ?, unmatched_items = ?, top_board_count = ?,
            error_summary = NULL
        WHERE run_id = ?
        """,
        (
            business_now().isoformat(timespec="seconds"),
            stats["analyzed"],
            stats["matched_items"],
            stats["unmatched_items"],
            stats["top_n_boards"],
            run_id,
        ),
    )
    conn.commit()


def _fail_pipeline_run(conn: sqlite3.Connection, *, run_id: str, exc: Exception) -> None:
    error_summary = str(exc)[:1000]
    conn.execute(
        """
        UPDATE pipeline_runs
        SET finished_at = ?, status = 'failed', error_summary = ?
        WHERE run_id = ?
        """,
        (business_now().isoformat(timespec="seconds"), error_summary, run_id),
    )
    conn.commit()


def run_daily_pipeline(
    db_path: str | None = None,
    *,
    window: tuple[str, str] | None = None,
    historical_mode: bool = False,
) -> dict:
    """一次性跑完：
      1. 取最近 N 天 items → analyze → 写 item_analysis
      2. 聚合到 daily_metrics（初版 state="样本不足"，等 Top N 标记完再重算）
      3. 标 Top N
      4. **重算 state/confidence**（关键步骤：让 Top N 板进入可行动状态机候选）
      5. 写 daily_pipeline_stats
    """
    stats: dict = {
        "analyzed": 0, "aggregated_rows": 0, "top_n_boards": 0,
        "reclassified_rows": 0,
        "matched_items": 0, "unmatched_items": 0,
    }

    run_id = str(uuid.uuid4())
    with session(db_path or DEFAULT_DB_PATH) as conn:
        input_start, input_end = window or _daily_window(conn)
        _insert_running_pipeline_run(
            conn,
            run_id=run_id,
            started_at=business_now().isoformat(timespec="seconds"),
            input_start=input_start,
            input_end=input_end,
        )
        try:
            if historical_mode:
                # 回填以事件发生日为准；先清掉目标窗口的旧聚合，确保重复执行幂等。
                conn.execute(
                    "DELETE FROM daily_metrics WHERE date >= ? AND date < ?",
                    (_date_only(input_start), _date_only(input_end)),
                )
                conn.commit()
            boards_path = "config/boards.json"
            boards_raw = json.loads(Path(boards_path).read_text(encoding="utf-8"))
            boards_version = boards_raw.get("version", "unknown")
            boards = load_boards(boards_path)
            extras = load_extras("config/boards_extra.json")
            lexicon = load_lexicon("config/sentiment_lexicon.json")

            rows = fetch_recent_items(conn, window=(input_start, input_end))
            analyses = analyze_items(
                rows,
                boards,
                extras,
                lexicon,
                boards_version,
                event_only_weights=historical_mode,
            )
            stats["analyzed"] = persist_item_analysis(conn, analyses)
            stats["matched_items"] = sum(1 for a in analyses if a["board"] != "其他")
            stats["unmatched_items"] = stats["analyzed"] - stats["matched_items"]
            metric_dates = aggregate_daily_metrics(
                conn,
                boards,
                analyses,
                event_only_interactions=historical_mode,
            )
            stats["aggregated_rows"] = len(metric_dates)
            stats["top_n_boards"] = mark_top_n_boards(conn, metric_dates=metric_dates)
            stats["reclassified_rows"] = reclassify_with_top_n(conn, metric_dates=metric_dates)

            # 全局统计：抓了多少条帖子 + 回复 + 状态机 + Top N
            crawled_threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
            crawled_replies = conn.execute("SELECT COUNT(*) FROM replies").fetchone()[0]
            if not historical_mode:
                write_pipeline_stats(
                    conn,
                    analyzed=stats["analyzed"],
                    matched=stats["matched_items"],
                    unmatched=stats["unmatched_items"],
                    top_n_boards=stats["top_n_boards"],
                    crawled_threads=crawled_threads,
                    crawled_replies=crawled_replies,
                )
            _finish_pipeline_run(conn, run_id=run_id, stats=stats)
        except Exception as exc:
            _fail_pipeline_run(conn, run_id=run_id, exc=exc)
            raise

    logger.info("daily pipeline: %s", stats)
    return stats


def _date_only(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + (0 if "%H" not in fmt else 0)], fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10]
