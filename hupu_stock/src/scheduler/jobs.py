"""APScheduler 定时任务。

设计文档 §6：
- 每个交易日 15:30 拉 akshare 板块行情
- 09:00 / 12:00 / 18:00 / 21:00 跑爬虫
- 每天 21:00 跑主分析流水线
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from crawler.hupu_crawler import HupuCrawler, ThreadListItem
from business_time import business_now
from storage.connection import DEFAULT_DB_PATH, session
from storage.persist import persist_batch

logger = logging.getLogger(__name__)


def crawl_job(
    board: str = "stock",
    board_pages: int = 5,
    since_hours: int = 6,
    max_thread_reply_pages: int | None = 5,
    db_path: str | None = None,
) -> dict:
    """单次抓取任务入口。

    返回统计 dict 供调度器 / 调用方记录。可被 APScheduler 当成函数直接调用，
    也可被脚本 / 测试直接调用。
    """
    crawler = HupuCrawler(max_thread_reply_pages=max_thread_reply_pages)
    new_t = 0
    new_r = 0
    skipped = 0
    with session(db_path or DEFAULT_DB_PATH) as conn:
        def persist_fetched_thread(thread, replies) -> None:
            nonlocal new_t, new_r, skipped
            written_threads, written_replies, skipped_threads = persist_batch(
                conn, [thread], replies,
            )
            new_t += written_threads
            new_r += written_replies
            skipped += skipped_threads

        crawler.crawl_incremental(
            board=board,
            board_pages=board_pages,
            since_hours=since_hours,
            on_thread_fetched=persist_fetched_thread,
        )
    stats = {
        "new_threads": new_t,
        "replies": new_r,
        "skipped_threads": skipped,
    }
    logger.info("爬虫 job 完成：%s", stats)
    return stats


def _backfill_job_key(board: str, cutoff: datetime) -> str:
    """Stable key lets an interrupted fixed-window run resume safely."""
    return f"{board}:{cutoff.date().isoformat()}"


def _crawl_backfill_candidates(
    conn,
    candidates,
    *,
    crawler: HupuCrawler,
    board: str,
    job_key: str,
    stats: dict,
) -> None:
    """逐页持久化候选帖；调用方可先传未完成检查点，再传列表新发现的候选。"""
    for item in candidates:
        checkpoint = conn.execute(
            """
            SELECT status, last_completed_page
            FROM backfill_thread_progress
            WHERE job_key = ? AND thread_id = ?
            """,
            (job_key, item.thread_id),
        ).fetchone()
        if checkpoint is not None and checkpoint["status"] == "completed":
            stats["reused_completed_threads"] += 1
            continue

        conn.execute(
            """
            INSERT INTO backfill_thread_progress
                (job_key, thread_id, listed_activity_time, status, last_completed_page, completed_at, last_error)
            VALUES (?, ?, ?, 'running', 0, NULL, NULL)
            ON CONFLICT(job_key, thread_id) DO UPDATE SET
                listed_activity_time = excluded.listed_activity_time,
                status = 'running', completed_at = NULL, last_error = NULL
            """,
            (job_key, item.thread_id, item.post_time),
        )
        conn.commit()
        try:
            last_completed_page = int(checkpoint["last_completed_page"]) if checkpoint else 0
            start_page = max(1, last_completed_page + 1)
            stored_thread = conn.execute(
                "SELECT title FROM threads WHERE thread_id = ?", (item.thread_id,)
            ).fetchone()
            thread_title = stored_thread["title"] if stored_thread is not None else ""

            page = start_page
            while True:
                thread, replies = crawler.fetch_thread_page(
                    item.thread_id,
                    board=board,
                    page=page,
                    listed_post_time=item.post_time,
                    thread_title=thread_title,
                )
                # 续页没有主帖正文/互动数据，不能用它覆盖第一页已保存的主帖。
                threads_to_persist = [thread] if page == 1 else []
                written_threads, written_replies, _ = persist_batch(conn, threads_to_persist, replies)
                conn.execute(
                    """
                    UPDATE backfill_thread_progress
                    SET last_completed_page = ?, status = 'running', last_error = NULL
                    WHERE job_key = ? AND thread_id = ?
                    """,
                    (page, job_key, item.thread_id),
                )
                conn.commit()
                stats["new_threads"] += written_threads
                stats["replies"] += written_replies
                stats["pages_persisted"] += 1
                logger.info(
                    "历史回填线程 %s：已持久化第 %d 页（%d 条回复）",
                    item.thread_id, page, written_replies,
                )
                if not replies:
                    break
                thread_title = thread.title or thread_title
                page += 1

            conn.execute(
                """
                UPDATE backfill_thread_progress
                SET status = 'completed', completed_at = ?, last_error = NULL
                WHERE job_key = ? AND thread_id = ?
                """,
                (business_now().isoformat(timespec="seconds"), job_key, item.thread_id),
            )
            conn.commit()
            stats["completed_threads"] += 1
        except Exception as exc:
            conn.execute(
                """
                UPDATE backfill_thread_progress
                SET status = 'failed', last_error = ?
                WHERE job_key = ? AND thread_id = ?
                """,
                (str(exc)[:1000], job_key, item.thread_id),
            )
            conn.commit()
            stats["failed_threads"] += 1
            logger.warning("历史回填帖子 %s 失败：%s", item.thread_id, exc)


def crawl_backfill_job(
    *,
    board: str = "stock",
    days: int = 60,
    board_pages: int = 200,
    max_thread_reply_pages: int | None = None,
    db_path: str | None = None,
    cutoff: datetime | None = None,
) -> dict:
    """回填最近 ``days`` 天内有过更新的帖子及其全部可见回复。

    列表页按最后活动时间扫描至 cutoff；详情页每页落库并更新页级检查点，进程中断后
    使用相同的 days/cutoff 再执行时从最后成功页的下一页恢复。默认 ``None`` 表示不截断回复页。
    """
    if days <= 0:
        raise ValueError("days 必须为正整数")
    if board_pages <= 0:
        raise ValueError("board_pages 必须为正整数")

    cutoff = cutoff or (business_now() - timedelta(days=days))
    job_key = _backfill_job_key(board, cutoff)
    crawler = HupuCrawler(max_thread_reply_pages=max_thread_reply_pages)
    db_target = db_path or DEFAULT_DB_PATH
    # 先完成 schema migration；列表扫描可能耗时数分钟，不能让恢复检查点延后才可用。
    with session(db_target):
        pass
    stats = {
        "job_key": job_key,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "candidates": 0,
        "completed_threads": 0,
        "reused_completed_threads": 0,
        "failed_threads": 0,
        "new_threads": 0,
        "replies": 0,
        "pages_persisted": 0,
        "oldest_listed_activity": None,
        "cutoff_reached": False,
        "list_pages_scanned": 0,
    }

    with session(db_target) as conn:
        pending_rows = conn.execute(
            """
            SELECT thread_id, listed_activity_time
            FROM backfill_thread_progress
            WHERE job_key = ? AND status != 'completed'
            ORDER BY rowid
            """,
            (job_key,),
        ).fetchall()
        # 恢复详情页只需要 id 与活动时间；其余字段沿用空值。
        pending = [
            ThreadListItem(row["thread_id"], "", "", "", row["listed_activity_time"] or "", 0, "")
            for row in pending_rows
        ]
        if pending:
            logger.info("优先恢复 %d 个未完成历史帖子", len(pending))
            _crawl_backfill_candidates(
                conn, pending, crawler=crawler, board=board, job_key=job_key, stats=stats,
            )

    candidates = crawler.list_board(
        board=board,
        max_pages=board_pages,
        stop_when_older_than=cutoff,
    )
    # 置顶帖或翻页交界可能重复，保留第一次（最新）出现的条目。
    unique_candidates = {item.thread_id: item for item in candidates}
    stats["candidates"] = len(unique_candidates)
    stats["list_pages_scanned"] = crawler.last_list_board_pages
    stats["cutoff_reached"] = crawler.last_list_board_cutoff_reached
    listed_times: list[datetime] = []
    for item in unique_candidates.values():
        try:
            listed_times.append(datetime.fromisoformat(item.post_time))
        except ValueError:
            logger.warning("无法解析列表活动时间，忽略 cutoff 校验：%s", item.post_time)
    if listed_times:
        oldest = min(listed_times)
        stats["oldest_listed_activity"] = oldest.isoformat(timespec="seconds")

    with session(db_target) as conn:
        _crawl_backfill_candidates(
            conn,
            unique_candidates.values(),
            crawler=crawler,
            board=board,
            job_key=job_key,
            stats=stats,
        )

    logger.info("历史回填抓取完成：%s", stats)
    return stats


def daily_analysis_job() -> dict:
    """21:00 主任务：情感打分 → 板块匹配 → 指标 → 状态判定 → 写 daily_metrics + daily_pipeline_stats。

    包装 analysis.pipeline.run_daily_pipeline；流水线是 daily_pipeline_stats 的唯一写入方。
    """
    from analysis.pipeline import run_daily_pipeline
    return run_daily_pipeline()


def configure_scheduler(
    boards: tuple[str, ...] = ("stock",),
    cron_hours: tuple[int, ...] = (9, 12, 18, 21),
) -> BackgroundScheduler:
    """注册定时任务。

    默认 cron：
      - 每个交易日（周一到周五）15:30 拉 akshare 板块行情
      - 每天 9/12/18/21:10 抓虎扑
      - 每天 21:30 跑主分析流水线
    """
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 板块行情（每个交易日盘后）
    scheduler.add_job(
        sector_prices_job,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="sector_prices",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_seconds=1800,
    )

    # 虎扑爬虫（每天 4 轮）
    for board in boards:
        for hour in cron_hours:
            scheduler.add_job(
                crawl_job,
                CronTrigger(hour=hour, minute=10),
                kwargs={"board": board},
                id=f"crawl_{board}_{hour}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_seconds=600,
            )

    # 主分析流水线
    scheduler.add_job(
        daily_analysis_job,
        CronTrigger(hour=21, minute=30),
        id="daily_analysis",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_seconds=1800,
    )
    return scheduler


def sector_prices_job() -> dict:
    """每个交易日 15:30 拉所有板块（来自 config/boards.json）的实时行情。"""
    from market.akshare_loader import refresh_all_known_boards
    try:
        boards = json.loads(Path("config/boards.json").read_text(encoding="utf-8"))
        names = list(boards.get("boards", {}).keys())
    except Exception as exc:
        logger.warning("读 boards.json 失败：%s", exc)
        names = ["半导体", "白酒", "新能源", "银行", "人工智能"]

    with session() as conn:
        stats = refresh_all_known_boards(conn, names, sleep_between=1.2)
    logger.info("sector_prices_job 完成：%s", stats)
    return stats
