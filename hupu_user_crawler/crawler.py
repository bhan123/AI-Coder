"""虎扑单用户主贴爬虫。

按 uid 抓取指定用户在某个板块的所有主贴（标题 + 正文），输出 JSONL。

设计要点：
- 通过遍历板块分页过滤作者 uid，无需登录（个人主页才需要登录）
- 复用 hupu-sector-crowding 已验证的 Next.js SSR 选择器（2026-07 实测）
- 断点续传：JSONL 增量写入；重启会自动跳过已抓 thread_id
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from config import (
    DEFAULT_USER_AGENT,
    HUPU_BASE,
    HUPU_COOKIE,
    HTTP_TIMEOUT_SECONDS,
    MAX_INTERVAL_SECONDS,
    MAX_RETRIES,
    MIN_INTERVAL_SECONDS,
    TARGET_BOARD,
    TARGET_USER_ID,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://bbs.hupu.com/",
}


# ---------- 数据类 ----------


@dataclass
class ThreadListItem:
    """板块列表页的一条记录。"""

    thread_id: str
    title: str
    author: str
    author_uid: str
    post_time: str
    reply_count: int
    url: str


@dataclass
class MainPost:
    """单个主贴（标题 + 正文 + 元数据）。"""

    thread_id: str
    title: str
    content: str
    author: str
    author_uid: str
    post_time: str
    url: str
    fetched_at: str


# ---------- 解析工具 ----------


def _board_page_url(board: str, page: int) -> str:
    """虎扑板块分页 URL：第 1 页 /{board}，第 N 页 /{board}-{N}（2026-07 实测）。"""
    return f"{HUPU_BASE}/{board}" if page == 1 else f"{HUPU_BASE}/{board}-{page}"


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """把 'name=value; name2=value2' 解析成 dict。空段忽略。"""
    cookies: dict[str, str] = {}
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                cookies[k] = v
    return cookies


def _normalize_time(text: str | None) -> str:
    """'07-09 19:42' / '2026-07-09 19:42:15' 等混合时间 → ISO 字符串。"""
    if not text:
        return ""
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        dt = datetime.strptime(text, "%m-%d %H:%M")
        return dt.replace(year=datetime.now().year).isoformat(timespec="seconds")
    except ValueError:
        return text


def parse_thread_list(html: str) -> list[ThreadListItem]:
    """解析 /{board} 的 SSR 列表。

    Hupu Next.js (2026-07 实测) 结构：
        <li class="bbs-sl-web-post-body">
          <div class="bbs-sl-web-post-layout">
            <div class="post-title"><a class="p-title" href="/<tid>.html">…</a></div>
            <div class="post-datum">32 / 1234  </div>
            <div class="post-auth"><a href="https://my.hupu.com/<uid>">…</a></div>
            <div class="post-time">08-05 17:17</div>
          </div>
        </li>
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[ThreadListItem] = []
    for li in soup.select("li.bbs-sl-web-post-body"):
        link = li.select_one("a.p-title")
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"/(\d+)(?:-\d+)?\.html", href)
        if not m:
            continue
        tid = m.group(1)

        author_a = li.select_one(".post-auth a")
        author = author_a.get_text(strip=True) if author_a else ""
        uid = ""
        if author_a:
            href_a = author_a.get("href", "")
            uid_m = re.search(r"my\.hupu\.com/(\d+)", href_a)
            uid = uid_m.group(1) if uid_m else ""

        time_el = li.select_one(".post-time")
        post_time = _normalize_time(time_el.get_text(strip=True)) if time_el else ""

        datum_el = li.select_one(".post-datum")
        datum_text = datum_el.get_text(strip=True) if datum_el else "0 / 0"
        parts = re.findall(r"\d+", datum_text)
        reply_count = int(parts[0]) if parts else 0

        items.append(
            ThreadListItem(
                thread_id=tid,
                title=link.get_text(strip=True),
                author=author,
                author_uid=uid,
                post_time=post_time,
                reply_count=reply_count,
                url=f"{HUPU_BASE}{href}" if href.startswith("/") else href,
            )
        )
    return items


def parse_main_post(html: str, thread_id: str, listed_post_time: str = "") -> MainPost | None:
    """解析 /<tid>.html 详情页，仅提取主贴（标题 + 正文）。

    第 1 页结构（Next.js，2026-08 实测）：
        <div class="post-content_bbs-post-content__<hash>">      ← 主贴外层 wrapper（含作者+内容）
            <div class="post-user_post-user-comp__...">         ← 用户信息
                <a class="..." href="https://my.hupu.com/<uid>">作者名</a>
                <div class="post-time">...</div>
            </div>
            <div class="post-content_main-post-info__<hash>">   ← 主贴内容卡片
                <div class="bbs-thread-comp">
                    <div class="thread-content-detail">主贴正文</div>
                </div>
            </div>
        </div>
        <!-- 之后是每条回复，结构是 .post-reply-list-wrapper，不复用上面的 class -->

    注意：必须把作者/时间查找限定在外层 post-content_bbs-post-content__ 内，
    否则会取到某条回复者的 uid（回复区域内的链接不在这个 class 下，但仍可能被
    全局 select_one 命中）。
    """
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    # 主贴 wrapper（用户信息 + 内容卡片都在这）
    # 类名带构建后缀（post-content_bbs-post-content__<hash>），用属性子串匹配
    main_post_card = soup.select_one("[class*='post-content_bbs-post-content__']")
    main_post = main_post_card.select_one(".bbs-thread-comp") if main_post_card else None
    body_el = main_post.select_one(".thread-content-detail") if main_post else None
    content = body_el.get_text("\n", strip=True) if body_el else ""

    if not title and not content:
        return None

    # 在主贴卡片内找作者链接。可能有多个（头像 img 链接 + 名字链接），
    # 优先选有可见文字的（名字链接）
    main_uid = ""
    main_author_name = ""
    if main_post_card is not None:
        candidate_links = main_post_card.select("a[href*='my.hupu.com']")
        for link in candidate_links:
            text = link.get_text(strip=True)
            if text:  # 优先用有可见文字的链接（名字）
                main_author_name = text
                href_a = link.get("href", "")
                uid_m = re.search(r"my\.hupu\.com/(\d+)", href_a)
                main_uid = uid_m.group(1) if uid_m else ""
                break
        # 退化：拿不到名字但有链接就用第一个
        if not main_uid and candidate_links:
            href_a = candidate_links[0].get("href", "")
            uid_m = re.search(r"my\.hupu\.com/(\d+)", href_a)
            main_uid = uid_m.group(1) if uid_m else ""

    # 时间同样在主贴卡片内
    main_time_el = main_post_card.select_one(".post-time") if main_post_card is not None else None
    detail_post_time = _normalize_time(main_time_el.get_text(strip=True)) if main_time_el else ""
    post_time = detail_post_time or listed_post_time

    return MainPost(
        thread_id=thread_id,
        title=title,
        content=content,
        author=main_author_name,
        author_uid=main_uid,
        post_time=post_time,
        url=f"{HUPU_BASE}/{thread_id}.html",
        fetched_at=datetime.now().isoformat(timespec="seconds"),
    )


# ---------- 爬虫主类 ----------


class HupuUserCrawler:
    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_SECONDS,
        max_interval: float = MAX_INTERVAL_SECONDS,
        max_retries: int = MAX_RETRIES,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        cookie: str = HUPU_COOKIE,
        session: requests.Session | None = None,
    ) -> None:
        self._min = min_interval
        self._max = max_interval
        self._max_retries = max_retries
        self._timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        # 注入登录 cookie（如果提供），用于访问 my.hupu.com 等登录后页面
        if cookie:
            self._session.cookies.update(_parse_cookie_string(cookie))
            self._session.headers["Cookie"] = cookie
            logger.info("已注入登录 cookie（%d 个键）", len(_parse_cookie_string(cookie)))

    def _get(self, url: str) -> str | None:
        """带限速 + 重试的 GET。失败返回 None。"""
        for attempt in range(1, self._max_retries + 1):
            try:
                time.sleep(random.uniform(self._min, self._max))
                resp = self._session.get(url, timeout=self._timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
                if resp.status_code == 403:
                    logger.warning("GET %s → 403，限流，sleep 60s", url)
                    time.sleep(60)
            except requests.RequestException as exc:
                logger.warning("GET %s 第 %d 次失败：%s", url, attempt, exc)
        return None

    def list_board_page(self, board: str, page: int) -> list[ThreadListItem]:
        url = _board_page_url(board, page)
        html = self._get(url)
        if not html:
            return []
        return parse_thread_list(html)

    def fetch_main_post(self, thread_id: str, listed_post_time: str = "") -> MainPost | None:
        url = f"{HUPU_BASE}/{thread_id}.html"
        html = self._get(url)
        if not html:
            return None
        return parse_main_post(html, thread_id, listed_post_time)


# ---------- 写入 / 续传 ----------


def load_existing_tids(jsonl_path: Path) -> set[str]:
    """读已有 JSONL，返回已写入的 thread_id 集合（用于续传去重）。"""
    if not jsonl_path.exists():
        return set()
    tids: set[str] = set()
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                tid = obj.get("thread_id")
                if tid:
                    tids.add(tid)
            except json.JSONDecodeError:
                continue
    return tids


def append_post(jsonl_path: Path, post: MainPost) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(post), ensure_ascii=False) + "\n")


# ---------- 主入口 ----------


def crawl_user_posts(
    crawler: HupuUserCrawler,
    target_uid: str,
    output_path: Path,
    board: str = TARGET_BOARD,
    max_pages: int = 50,
    empty_page_limit: int = 3,
    until_date: datetime | None = None,
) -> tuple[int, int]:
    """遍历板块分页，按 uid 过滤并抓取每个匹配主贴。

    Parameters
    ----------
    crawler : HupuUserCrawler
    target_uid : str
        目标用户的虎扑数字 ID（从 my.hupu.com URL 提取）。
    output_path : Path
        JSONL 输出文件（增量写入，续传安全）。
    board : str
        板块短名，如 "stock"。
    max_pages : int
        最多扫多少页板块（每页 ~50 帖）。硬上限，防止失控。
    empty_page_limit : int
        连续多少页没有匹配帖子后提前停止，避免无意义翻页。
    until_date : datetime | None
        日期截断：当一页所有帖子的 post_time 都早于该日期时停止翻页。
        用于抓取指定日期范围内的所有历史主贴。

    Returns
    -------
    (matched_total, written_total) : tuple[int, int]
    """
    seen = load_existing_tids(output_path)
    logger.info("续传：已存在 %d 条 thread_id，将跳过", len(seen))
    if until_date:
        logger.info("日期截断：抓取到 %s 为止", until_date.date().isoformat())

    matched_total = 0
    written_total = 0
    # 日期截断模式下，空页限制应大幅放宽（用户每发 1 条帖子通常间隔 5-10 页）。
    # 当 until_date 给定时，empty_page_limit 不再作为停止条件（仅日志告警）。
    effective_empty_limit = empty_page_limit if until_date is None else 10**9
    empty_pages = 0

    for page in range(1, max_pages + 1):
        items = crawler.list_board_page(board, page)
        if not items:
            logger.info("第 %d 页无内容，停止翻页", page)
            break

        # 日期截断：整页都早于 until_date 就停
        if until_date:
            page_times: list[datetime] = []
            for it in items:
                if it.post_time:
                    try:
                        page_times.append(datetime.fromisoformat(it.post_time))
                    except ValueError:
                        continue
            if page_times and max(page_times) < until_date:
                logger.info(
                    "第 %d 页最晚帖子 %s 早于 %s，停止翻页",
                    page,
                    max(page_times).isoformat(timespec="seconds"),
                    until_date.isoformat(timespec="seconds"),
                )
                break

        matched = [it for it in items if it.author_uid == target_uid]
        matched_total += len(matched)
        logger.info("第 %d 页：%d 条匹配（%d 总）", page, len(matched), len(items))

        if not matched:
            empty_pages += 1
            if empty_pages >= effective_empty_limit:
                logger.info(
                    "连续 %d 页无匹配，可能已超出该用户活跃范围，停止",
                    effective_empty_limit,
                )
                break
        else:
            empty_pages = 0

        for it in matched:
            if it.thread_id in seen:
                logger.debug("跳过已存在 thread_id=%s", it.thread_id)
                continue
            post = crawler.fetch_main_post(it.thread_id, listed_post_time=it.post_time)
            if post is None:
                logger.warning("thread_id=%s 主贴抓取失败", it.thread_id)
                continue
            # 二次校验：详情页作者 uid 必须仍等于目标 uid
            if post.author_uid and post.author_uid != target_uid:
                logger.warning(
                    "thread_id=%s 作者 uid 不匹配（%s != %s），跳过",
                    it.thread_id, post.author_uid, target_uid,
                )
                continue
            append_post(output_path, post)
            seen.add(it.thread_id)
            written_total += 1
            logger.info(
                "✓ %s  %s（%d 字）",
                post.thread_id,
                post.title[:50],
                len(post.content),
            )

    logger.info(
        "完成：共发现 %d 条匹配，新增写入 %d 条 → %s",
        matched_total, written_total, output_path,
    )
    return matched_total, written_total


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    parser = argparse.ArgumentParser(description="抓取虎扑指定用户的主贴")
    parser.add_argument("--uid", default=TARGET_USER_ID, help="目标用户数字 ID")
    parser.add_argument("--board", default=TARGET_BOARD, help="板块短名")
    parser.add_argument("--max-pages", type=int, default=50, help="最多扫多少页（安全上限）")
    parser.add_argument(
        "--until-date",
        type=str,
        default=None,
        help="日期截断 YYYY-MM-DD：当一页所有帖子都早于该日期时停止。例如 2025-01-01 表示抓取 2025-01-01 之后的所有主贴",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL 输出路径（默认 data/hupu_<uid>.jsonl）",
    )
    parser.add_argument(
        "--cookie",
        type=str,
        default=None,
        help="登录 cookie 字符串（用于抓 my.hupu.com 等登录后页面）。优先于环境变量 HUPU_COOKIE",
    )
    args = parser.parse_args()

    until_date = None
    if args.until_date:
        until_date = datetime.strptime(args.until_date, "%Y-%m-%d")

    output = args.output or Path("data") / f"hupu_{args.uid}.jsonl"
    crawler = HupuUserCrawler(cookie=args.cookie or HUPU_COOKIE)
    matched, written = crawl_user_posts(
        crawler,
        target_uid=args.uid,
        output_path=output,
        board=args.board,
        max_pages=args.max_pages,
        until_date=until_date,
    )
    print(f"\n完成：发现 {matched} 条匹配，新增 {written} 条 → {output}")
