"""端到端 pipeline 测试。

构造多板多日 sample 数据 + 真 THS 价格，验证：
  - HotScore 用 daily_metrics.hot_raw 做分位（不是价格序列）
  - board_dict_version = boards.json 的 version 字段（不是板名）
  - Top N 标记后 state 字段被重算（不是统一"样本不足"）
  - daily_pipeline_stats 至少 1 行
  - matched_items / unmatched_items 计数正确

注意：run_daily_pipeline 的 fetch_recent_items 只看最近 7 天帖子，所以为了让 Top N 激活
（需要 sum(effective_item_count) >= 100 / 板），我们直接预填过去 18 天的 daily_metrics 历史。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from analysis.pipeline import run_daily_pipeline
from crawler.hupu_crawler import Reply, Thread
from market.akshare_loader import (
    compute_pct_changes,
    compute_price_extensions,
    upsert_sector_prices,
)
from storage.connection import session
from storage.persist import persist_batch


def _seed_today_items(db_path: str) -> None:
    """插入今天 + 昨天两天的帖子（fetch_recent_items 看 7 天，但精简到 2 天演示 Top N 不依赖）"""
    from datetime import date, timedelta
    today = date.today()
    boards = ["半导体", "白酒", "新能源"]
    threads: list[Thread] = []
    replies: list[Reply] = []
    for day_offset in range(2):  # 今天 + 昨天
        date_str = (today - timedelta(days=day_offset)).isoformat()
        for board in boards:
            for i in range(20):  # ≥10 条 → 跨过 effective_item_count 阈值
                tid = f"{date_str}-{board}-{i}"
                if board == "半导体":
                    content = f"今天{board}起飞，中芯国际涨停！主力拉升梭哈了！"
                elif board == "白酒":
                    content = f"今天{board}崩盘，茅台五粮液全跌停。麻了，套牢。"
                else:
                    content = f"今天{board}爆发，比亚迪涨停，宁王起飞！"
                threads.append(Thread(
                    thread_id=tid, title=f"{board}帖子 {date_str} #{i}",
                    content=content, replies=20, likes=30, views=500,
                    author_hash=f"h_{i}",
                    post_time=f"{date_str} 09:30:00",
                    crawl_time=f"{date_str} 10:00:00",
                    url=f"https://bbs.hupu.com/{tid}.html",
                    board="stock",
                ))
                replies.append(Reply(
                    reply_id=f"{tid}-r1", thread_id=tid,
                    content="+1", likes=5, author_hash=f"h_{i}",
                    reply_time=f"{date_str} 09:40:00",
                    crawl_time=f"{date_str} 10:00:00", floor=1,
                ))

    with session(db_path) as conn:
        persist_batch(conn, threads, replies)


def _seed_history_daily_metrics(db_path: str, days: int = 25) -> None:
    """直接灌过去 N 天 daily_metrics，跳过 fetch_recent_items 的 7 天窗口。

    每板每天 effective_item_count = 5（≥10 阈值） + 5 unique authors（≥5 阈值）。
    hot_raw 每天递增（构造历史 percentile 序列）。
    """
    from datetime import date, timedelta
    today = date.today()
    boards = ["半导体", "白酒", "新能源"]
    rows = []
    for day_offset in range(days):
        d = (today - timedelta(days=day_offset + 1)).isoformat()  # 不覆盖今天
        for b in boards:
            hot_raw = 1.5 + day_offset * 0.1
            rows.append((
                b, d, days, "中置信", 5, 30, 5.0, 5,
                hot_raw, 50.0, 60.0, 0.2, 60.0, 1.0, 30.0, 50.0,
                55.0, "无强信号", "v1", "manual-2026-07-10", "ths-2026-07-10",
                "2026-07-13T01:00:00",
            ))
    with session(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO daily_metrics
                (board, date, history_days, confidence, post_count, reply_count,
                 effective_item_count, unique_authors, hot_raw, hot_score, sent_score,
                 item_sent_std, consensus_score, heat_momentum, coverage_score,
                 price_extension, crowding_score, state, metric_version, lexicon_version,
                 board_dict_version, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()


def _seed_sector_prices(db_path: str) -> None:
    import pandas as pd
    from datetime import date, timedelta
    today = date.today()
    boards = ["半导体", "白酒", "新能源"]
    for board in boards:
        rows = []
        for day_offset in range(60):
            d = (today - timedelta(days=day_offset)).isoformat()
            rows.append({"date": d, "close": 100.0 + day_offset * 0.5 + (hash(board) % 7 - 3) * 0.1})
        df = pd.DataFrame(rows)
        df = compute_pct_changes(df)
        with session(db_path) as conn:
            upsert_sector_prices(conn, board, df)
    with session(db_path) as conn:
        compute_price_extensions(conn)


def test_end_to_end_pipeline() -> None:
    tmpdir = tempfile.mkdtemp(prefix="hupu_e2e_")
    db_path = os.path.join(tmpdir, "e2e.db")
    try:
        _seed_history_daily_metrics(db_path, days=25)
        _seed_sector_prices(db_path)
        _seed_today_items(db_path)

        stats = run_daily_pipeline(db_path=db_path)
        assert stats["analyzed"] > 0, stats
        assert stats["aggregated_rows"] > 0, stats
        assert stats["matched_items"] + stats["unmatched_items"] == stats["analyzed"]

        with session(db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT board_dict_version FROM item_analysis"
            ).fetchall()
            versions = {r["board_dict_version"] for r in rows}
            assert versions <= {"ths-2026-07-10", "manual-2026-07-10"}, (
                f"unexpected board_dict_version(s): {versions}"
            )

            top_count = conn.execute(
                "SELECT COUNT(DISTINCT board) FROM daily_metrics WHERE is_top_board = 1"
            ).fetchone()[0]
            assert top_count > 0, "no Top N boards; check MIN_20D_ITEMS_FOR_TOPN"

            top_states = conn.execute(
                "SELECT DISTINCT state FROM daily_metrics WHERE is_top_board = 1"
            ).fetchall()
            state_set = {r["state"] for r in top_states}
            # 至少有一个 Top N 板进入非"样本不足"状态（证明 reclassify 真的跑了且 is_top_board 已生效）
            non_insufficient = state_set - {"样本不足"}
            assert non_insufficient, (
                f"所有 Top N 板都是样本不足；reclassify 没跑。states={state_set}"
            )

            stat_rows = conn.execute("SELECT * FROM daily_pipeline_stats").fetchall()
            assert len(stat_rows) >= 1
            row = stat_rows[0]
            assert row["crawled_threads"] > 0
            assert row["crawled_replies"] > 0
            assert 0.0 <= row["unmatched_rate"] <= 1.0

            hot_scores = conn.execute(
                "SELECT DISTINCT hot_score FROM daily_metrics ORDER BY hot_score"
            ).fetchall()
            distinct_hot = {r["hot_score"] for r in hot_scores}
            # HotScore 应该用 daily_metrics.hot_raw 做分位；历史预填 hot_raw 都是 1.5~3.9 线性递增
            # 所以分位会变化（不全 50）
            assert len(distinct_hot) > 1, (
                f"hot_score 全相等；HotRaw 历史没起作用。distinct={distinct_hot}"
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)