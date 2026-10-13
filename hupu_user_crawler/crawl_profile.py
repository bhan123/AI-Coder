"""基于个人主页的抓取入口。

从 https://my.hupu.com/{uid} 的 pageData JSON 里直接拿到该用户的所有 stock 帖子列表，
然后对每条调用现有 fetch_main_post 抓全正文。

相比 /stock 板块分页抓取，优势：
- 一次请求就拿到所有帖子（30 条），无需遍历翻页
- 不受板块分页深度限制
- 能抓到很久之前的旧帖

依赖：需要 cookie。设置 HUPU_COOKIE 环境变量或 --cookie 参数。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import HUPU_COOKIE, TARGET_USER_ID
from crawler import (
    HupuUserCrawler,
    append_post,
    load_existing_tids,
    parse_main_post,
)
from profile_parser import ProfilePost, filter_stock, parse_profile_page

logger = logging.getLogger(__name__)


def fetch_profile_posts(
    crawler: HupuUserCrawler, uid: str
) -> list[ProfilePost]:
    """抓个人主页 HTML，解析 pageData，过滤 stock 板块。"""
    url = f"https://my.hupu.com/{uid}"
    html = crawler._get(url)
    if not html:
        logger.error("个人主页 %s 抓取失败", url)
        return []

    posts, has_more = parse_profile_page(html)
    if has_more:
        logger.warning("pageData.nextPage=true，可能还有更多帖子未抓到（当前实现不支持分页）")

    stock_posts = filter_stock(posts)
    logger.info(
        "个人主页 %s: 共 %d 条帖子，其中 stock (fid=161) %d 条",
        url, len(posts), len(stock_posts),
    )
    return stock_posts


def crawl_profile_to_jsonl(
    crawler: HupuUserCrawler,
    uid: str,
    output_path: Path,
    only_fid: int = 161,
    fetch_full: bool = True,
) -> tuple[int, int]:
    """从个人主页抓所有 stock 帖子主贴，写入 JSONL。

    Parameters
    ----------
    crawler : HupuUserCrawler
        已注入 cookie 的爬虫实例。
    uid : str
        目标用户 uid（my.hupu.com URL 里的数字部分）。
    output_path : Path
        输出 JSONL 文件。已存在的 thread_id 自动跳过（断点续传）。
    only_fid : int
        板块 ID 过滤。默认 161（股票区）。
    fetch_full : bool
        是否拉每条帖子的详情页拿全文。True: 慢但有完整正文；False: 快但只有 summary 预览。

    Returns
    -------
    (matched_total, written_total)
    """
    seen = load_existing_tids(output_path)
    logger.info("续传：已存在 %d 条 thread_id，将跳过", len(seen))

    profile_posts = fetch_profile_posts(crawler, uid)
    # 仅保留目标板块
    target_posts = [p for p in profile_posts if p.fid == only_fid]
    logger.info("目标板块 (fid=%d) 共 %d 条", only_fid, len(target_posts))

    matched_total = len(target_posts)
    written_total = 0

    for pp in target_posts:
        if pp.tid in seen:
            logger.debug("跳过已存在 tid=%s", pp.tid)
            continue

        if not fetch_full:
            # 直接用 summary 写入（不抓详情页，速度快 ~10s）
            from crawler import MainPost
            from dataclasses import asdict
            output_path.parent.mkdir(parents=True, exist_ok=True)
            stub = MainPost(
                thread_id=pp.tid,
                title=pp.title,
                content=pp.summary,
                author=pp.nickname,
                author_uid=uid,
                post_time=pp.create_time.isoformat(timespec="seconds"),
                url=pp.url,
                fetched_at=datetime.now().isoformat(timespec="seconds"),
            )
            with output_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(stub), ensure_ascii=False) + "\n")
            seen.add(pp.tid)
            written_total += 1
            logger.info("✓ (summary) %s  %s", pp.tid, pp.title[:50])
            continue

        # 拉详情页拿全文
        html = crawler._get(pp.url)
        if not html:
            logger.warning("tid=%s 详情页抓取失败", pp.tid)
            continue
        post = parse_main_post(html, pp.tid, listed_post_time=pp.create_time.isoformat(timespec="seconds"))
        if post is None:
            logger.warning("tid=%s 解析失败", pp.tid)
            continue
        # 二次校验：作者 uid 必须匹配
        if post.author_uid and post.author_uid != uid:
            logger.warning("tid=%s 作者 uid 不匹配（%s != %s），跳过", pp.tid, post.author_uid, uid)
            continue
        append_post(output_path, post)
        seen.add(pp.tid)
        written_total += 1
        logger.info("✓ %s  %s（%d 字）", pp.tid, post.title[:50], len(post.content))

    logger.info(
        "完成：%d 条目标板块帖子，新增写入 %d 条 → %s",
        matched_total, written_total, output_path,
    )
    return matched_total, written_total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="从个人主页抓取虎扑用户的所有 stock 板块主贴")
    parser.add_argument("--uid", default=TARGET_USER_ID)
    parser.add_argument("--cookie", default=None, help="登录 cookie（默认从 HUPU_COOKIE 环境变量读取）")
    parser.add_argument("--summary-only", action="store_true",
                        help="只用 pageData 的 summary 字段写入（不抓详情页），速度极快但内容不完整")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    cookie = args.cookie or HUPU_COOKIE
    if not cookie:
        print("错误：需要 cookie。设置 HUPU_COOKIE 环境变量或用 --cookie 传入。", file=sys.stderr)
        sys.exit(1)

    output = args.output or Path("data") / f"hupu_{args.uid}_profile.jsonl"
    crawler = HupuUserCrawler(cookie=cookie)

    matched, written = crawl_profile_to_jsonl(
        crawler,
        uid=args.uid,
        output_path=output,
        fetch_full=not args.summary_only,
    )
    print(f"\n完成：发现 {matched} 条 stock 帖子，新增 {written} 条 → {output}")


if __name__ == "__main__":
    main()
