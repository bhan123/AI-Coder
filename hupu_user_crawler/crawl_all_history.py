"""基于 /pcmapi/pc/space/v1/getThreadList 的分页抓取。

API endpoint: https://bbs.hupu.com/pcmapi/pc/space/v1/getThreadList
参数:
  euid:   用户 UID
  page:   页码，从 1 开始（默认 pageSize=10）

每次返回 10 条主贴。响应: {code, msg, data: [post, ...]}
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import HUPU_COOKIE, TARGET_USER_ID
from crawler import append_post, load_existing_tids, parse_main_post
from profile_parser import ProfilePost, filter_stock

logger = logging.getLogger(__name__)

API_URL = "https://bbs.hupu.com/pcmapi/pc/space/v1/getThreadList"
PAGE_SIZE = 10


def fetch_page(
    session: requests.Session, euid: str, page: int
) -> list[dict[str, Any]]:
    """拉一页（10 条）原始帖子数据。失败返回 []。"""
    try:
        r = session.get(
            API_URL,
            params={"euid": euid, "page": page},
            timeout=15,
        )
        if r.status_code != 200:
            logger.warning("page=%d HTTP %d", page, r.status_code)
            return []
        data = r.json()
        if data.get("code") != 1:
            logger.warning("page=%d code=%s msg=%s", page, data.get("code"), data.get("msg"))
            return []
        return data.get("data", [])
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.warning("page=%d 失败：%s", page, e)
        return []


def item_to_profile_post(item: dict[str, Any]) -> ProfilePost | None:
    """把 API 返回的 item 转成 ProfilePost（复用 profile_parser）。"""
    tid = str(item.get("tid", "")).strip()
    title = (item.get("title") or "").strip()
    fid = item.get("fid")
    create_ts = item.get("create_time")
    if not tid or not title or fid is None or create_ts is None:
        return None

    return ProfilePost(
        tid=tid,
        title=title,
        fid=int(fid),
        create_time=datetime.fromtimestamp(int(create_ts)),
        summary=(item.get("summary") or "").strip(),
        replies=int(item.get("replies", 0)),
        visits=int(item.get("visits", 0)),
        nickname=(item.get("nickname") or "").strip(),
        puid=int(item.get("puid", 0)),
        url=f"https://bbs.hupu.com/{tid}.html",
    )


def crawl_all_history(
    session: requests.Session,
    euid: str,
    output_path: Path,
    fetch_detail: bool = True,
    only_fid: int = 161,
    until_date: datetime | None = None,
    max_pages: int = 1000,
    min_interval: float = 3.0,
    max_interval: float = 5.0,
) -> tuple[int, int, int]:
    """分页拉所有主贴，过滤 stock 板块，写 JSONL。

    Parameters
    ----------
    session : requests.Session
        已注入 cookie 的 session。
    euid : str
        目标用户 UID。
    output_path : Path
        输出 JSONL。
    fetch_detail : bool
        是否拉详情页拿完整正文。False 则只用 API 返回的 summary。
    only_fid : int
        板块 ID 过滤（161 = stock）。
    until_date : datetime | None
        日期截断：拉到此日期为止。None 表示不限制。
    max_pages : int
        安全上限。

    Returns
    -------
    (matched, written, last_page)
    """
    seen = load_existing_tids(output_path)
    logger.info("续传：已存在 %d 条 thread_id", len(seen))

    matched_total = 0
    written_total = 0
    last_page = 0

    for page in range(1, max_pages + 1):
        items = fetch_page(session, euid, page)
        if not items:
            logger.info("page=%d 无内容，停止", page)
            break
        last_page = page

        posts = [p for p in (item_to_profile_post(it) for it in items) if p is not None]
        stock_posts = [p for p in posts if p.fid == only_fid]
        matched_total += len(stock_posts)

        if posts:
            oldest = min(p.create_time for p in posts)
            newest = max(p.create_time for p in posts)
            logger.info(
                "page=%d 共 %d 条, stock %d 条, %s → %s",
                page, len(posts), len(stock_posts),
                oldest.strftime("%Y-%m-%d"),
                newest.strftime("%Y-%m-%d"),
            )

        # 日期截断：整页都早于 until_date 就停
        if until_date and posts:
            if max(p.create_time for p in posts) < until_date:
                logger.info("page=%d 全部早于 %s，停止", page, until_date.date())
                break

        for pp in stock_posts:
            if pp.tid in seen:
                continue

            if not fetch_detail:
                from crawler import MainPost
                from dataclasses import asdict
                stub = MainPost(
                    thread_id=pp.tid,
                    title=pp.title,
                    content=pp.summary,
                    author=pp.nickname,
                    author_uid=euid,
                    post_time=pp.create_time.isoformat(timespec="seconds"),
                    url=pp.url,
                    fetched_at=datetime.now().isoformat(timespec="seconds"),
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with output_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(stub), ensure_ascii=False) + "\n")
                seen.add(pp.tid)
                written_total += 1
                logger.info("  ✓ (summary) %s  %s", pp.tid, pp.title[:50])
                continue

            html = session.get(pp.url, timeout=15).text
            post = parse_main_post(
                html, pp.tid, listed_post_time=pp.create_time.isoformat(timespec="seconds")
            )
            if post is None:
                logger.warning("  ✗ tid=%s 解析失败", pp.tid)
                continue
            if post.author_uid and post.author_uid != euid:
                logger.warning("  ✗ tid=%s 作者 uid 不匹配", pp.tid)
                continue
            append_post(output_path, post)
            seen.add(pp.tid)
            written_total += 1
            logger.info("  ✓ %s  %s（%d 字）", pp.tid, pp.title[:50], len(post.content))

        # 限速：API 调用间隔（详情页之间也需要）
        time.sleep(2)  # API 调用后稍微等下
        if page < max_pages and fetch_detail:
            # 详情页限速
            time.sleep(random.uniform(min_interval, max_interval))

    logger.info(
        "完成：%d 页, 共发现 %d 条 stock 帖子, 新增写入 %d 条 → %s",
        last_page, matched_total, written_total, output_path,
    )
    return matched_total, written_total, last_page


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="分页抓取虎扑用户全部 stock 主贴（API 版）")
    parser.add_argument("--uid", default=TARGET_USER_ID)
    parser.add_argument("--cookie", default=None)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--until-date", default=None,
                        help="YYYY-MM-DD，只抓该日期之后的帖子")
    parser.add_argument("--max-pages", type=int, default=200,
                        help="安全上限页数（每页 10 条）")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    cookie = args.cookie or HUPU_COOKIE
    if not cookie:
        print("错误：需要 cookie。设置 HUPU_COOKIE 或 --cookie", file=sys.stderr)
        sys.exit(1)

    output = args.output or Path("data") / f"hupu_{args.uid}_full.jsonl"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": f"https://my.hupu.com/{args.uid}",
    })
    for pair in cookie.split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            session.cookies.set(k.strip(), v.strip(), domain=".hupu.com")

    until_date = None
    if args.until_date:
        until_date = datetime.strptime(args.until_date, "%Y-%m-%d")

    matched, written, last_page = crawl_all_history(
        session,
        euid=args.uid,
        output_path=output,
        fetch_detail=not args.summary_only,
        until_date=until_date,
        max_pages=args.max_pages,
    )
    print(f"\n完成：{last_page} 页, 发现 {matched} 条 stock, 新增 {written} 条 → {output}")


if __name__ == "__main__":
    main()
