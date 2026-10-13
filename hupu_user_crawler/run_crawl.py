"""CLI 入口：抓取虎扑指定用户的主贴。

用法：
    python run_crawl.py                          # 默认：抓 /stock 前 50 页
    python run_crawl.py --max-pages 3            # 烟雾测试
    python run_crawl.py --until-date 2026-01-01  # 抓取 2026-01-01 之后的所有主贴
    python run_crawl.py --uid 19134213076193     # 指定用户（默认就是这个）
    python run_crawl.py --output my_data.jsonl   # 指定输出文件
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from config import DEFAULT_MAX_PAGES, HUPU_COOKIE, TARGET_BOARD, TARGET_USER_ID
from crawler import HupuUserCrawler, crawl_user_posts


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="抓取虎扑指定用户的主贴")
    parser.add_argument("--uid", default=TARGET_USER_ID, help="目标用户数字 ID")
    parser.add_argument("--board", default=TARGET_BOARD, help="板块短名")
    parser.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES,
        help=f"最多扫多少页（默认 {DEFAULT_MAX_PAGES}，安全上限防失控）",
    )
    parser.add_argument(
        "--until-date", type=str, default=None,
        help="日期截断 YYYY-MM-DD：一页所有帖子都早于该日期时停止。如 2025-01-01",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="JSONL 输出路径（默认 data/hupu_<uid>.jsonl）",
    )
    parser.add_argument(
        "--cookie", type=str, default=None,
        help="登录 cookie 字符串（用于抓 my.hupu.com）。优先于环境变量 HUPU_COOKIE",
    )
    args = parser.parse_args()

    until_date = None
    if args.until_date:
        until_date = datetime.strptime(args.until_date, "%Y-%m-%d")

    output = args.output or Path("data") / f"hupu_{args.uid}.jsonl"
    cookie = args.cookie or HUPU_COOKIE
    crawler = HupuUserCrawler(cookie=cookie)

    print(f"目标用户: {args.uid}")
    print(f"目标板块: /{args.board}")
    print(f"输出文件: {output}")
    print(f"翻页上限: {args.max_pages} 页（安全上限）")
    if until_date:
        print(f"日期截断: 抓取 {until_date.date().isoformat()} 之后的帖子")
    print("-" * 60)

    matched, written = crawl_user_posts(
        crawler,
        target_uid=args.uid,
        output_path=output,
        board=args.board,
        max_pages=args.max_pages,
        until_date=until_date,
    )

    print("-" * 60)
    print(f"完成：发现 {matched} 条匹配，新增 {written} 条 → {output}")
    if written == 0 and matched == 0:
        print("提示：未匹配到任何帖子，可能原因：")
        print("  - 已抓完（再次运行只会跳过已有记录）")
        print("  - 目标 uid 不在该板块活跃")
        print("  - 日期截断过早")
        print("  - 网络/HTTP 限流失败（看日志）")
    else:
        print("再次运行会自动跳过已抓取记录，可放心中断/重跑。")


if __name__ == "__main__":
    main()
