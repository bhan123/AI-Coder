"""回填最近一段时间有更新的虎扑帖子、回复与板块历史指标。

示例（默认抓全量回复；可随时中断，用相同参数重跑即可恢复）：
    python -m scripts.backfill_history --days 60 --pages 200 --analyze
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

from analysis.pipeline import run_daily_pipeline
from business_time import business_now
from scheduler.jobs import crawl_backfill_job


def _reply_pages(value: str) -> int | None:
    if value.lower() == "all":
        return None
    pages = int(value)
    if pages <= 0:
        raise argparse.ArgumentTypeError("reply-pages 必须是正整数或 all")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description="回填虎扑历史帖子与回复（支持中断恢复）")
    parser.add_argument("--board", default="stock", help="虎扑板块 short path，默认 stock")
    parser.add_argument("--days", type=int, default=60, help="按最后活动时间回溯天数，默认 60")
    parser.add_argument("--pages", type=int, default=200, help="最多扫描的板块列表页数，默认 200")
    parser.add_argument(
        "--reply-pages",
        type=_reply_pages,
        default=None,
        help="每个帖子的回复页上限；all 表示翻至空页（默认 all）",
    )
    parser.add_argument("--db-path", help="SQLite 路径；默认读取 HUPU_DB_PATH / data/hupu.db")
    parser.add_argument("--analyze", action="store_true", help="抓取完整后立即重算历史指标")
    parser.add_argument("--allow-partial", action="store_true", help="即使列表页未扫到 cutoff 也允许重算（不建议）")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    if args.days <= 0 or args.pages <= 0:
        parser.error("days 和 pages 必须是正整数")
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cutoff = business_now() - timedelta(days=args.days)
    crawl_stats = crawl_backfill_job(
        board=args.board,
        days=args.days,
        board_pages=args.pages,
        max_thread_reply_pages=args.reply_pages,
        db_path=args.db_path,
        cutoff=cutoff,
    )
    print(f"[backfill crawl] {crawl_stats}")
    if crawl_stats["failed_threads"]:
        print("存在抓取失败线程；请直接以相同参数重跑以恢复，尚未重算历史指标。", file=sys.stderr)
        return 2
    if not crawl_stats["cutoff_reached"] and not args.allow_partial:
        print("列表页尚未扫描到 cutoff；请提高 --pages 后重跑，尚未重算历史指标。", file=sys.stderr)
        return 2
    if not args.analyze:
        return 0

    analysis_stats = run_daily_pipeline(
        db_path=args.db_path,
        window=(cutoff.isoformat(timespec="seconds"), (business_now() + timedelta(seconds=1)).isoformat(timespec="seconds")),
        historical_mode=True,
    )
    print(f"[backfill analysis] {analysis_stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
