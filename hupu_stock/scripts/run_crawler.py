"""手动跑爬虫（设计文档 §6）。

用法：
    python -m scripts.run_crawler                    # 默认 /stock 板块，5 页范围
    python -m scripts.run_crawler --board stock --pages 3 --since-hours 12
"""
from __future__ import annotations

import argparse
import logging
import sys

from scheduler.jobs import crawl_job


def main() -> int:
    parser = argparse.ArgumentParser(description="手动跑虎扑板块爬虫")
    parser.add_argument("--board", default="stock", help="虎扑板块 short path，默认 stock")
    parser.add_argument("--pages", type=int, default=5, help="板块列表页数，默认 5")
    parser.add_argument("--since-hours", type=int, default=6, help="只抓该小时数内的新帖")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stats = crawl_job(
        board=args.board,
        board_pages=args.pages,
        since_hours=args.since_hours,
    )
    print(f"[run_crawler] {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
