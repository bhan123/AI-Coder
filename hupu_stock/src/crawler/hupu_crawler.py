"""虎扑股票专区爬虫（真实实现）。

虎扑结构（2026-07 实测）：
- 板块列表：https://bbs.hupu.com/{board}，传统分页 ?page=N，每页 ~50 帖
- 帖子详情：https://bbs.hupu.com/{tid}.html（首页）/{tid}-{n}.html（续页）
- 回复随主帖 SSR 一起渲染，每页 ~20 条，无 AJAX 端点
- 高热度帖子可至 500+ 页（设计文档要求保守限速，因此按 max_pages 截断）
- 默认 User-Agent + Referer 即可，无需登录
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Callable, Iterable

import requests
from bs4 import BeautifulSoup

from crawler.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

HUPU_BASE = "https://bbs.hupu.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://bbs.hupu.com/",
}


def board_page_url(board: str, page: int = 1) -> str:
    """Return the current Hupu board-list URL for a one-based page number."""
    return f"{HUPU_BASE}/{board}" if page == 1 else f"{HUPU_BASE}/{board}-{page}"


@dataclass
class Thread:
    thread_id: str
    title: str
    content: str
    replies: int
    likes: int
    views: int
    author_hash: str
    post_time: str
    crawl_time: str
    url: str
    board: str = "stock"


@dataclass
class Reply:
    reply_id: str
    thread_id: str
    content: str
    likes: int
    author_hash: str
    reply_time: str
    crawl_time: str
    floor: int = 0


@dataclass
class ThreadListItem:
    thread_id: str
    title: str
    author: str
    author_hash: str
    post_time: str
    reply_count: int
    url: str


def _hash_user(uid: str | None) -> str:
    """作者 ID → 不可逆哈希（设计文档 §9.4 合规要求）。"""
    if not uid:
        return ""
    return sha256(uid.encode("utf-8")).hexdigest()[:16]


def _author_hash_from_text(name: str) -> str:
    return _hash_user(name)


def _parse_int(text: str | None) -> int:
    if not text:
        return 0
    m = re.search(r"\d+", text.replace(",", ""))
    return int(m.group()) if m else 0


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _normalize_time(text: str | None) -> str:
    """把 '07-09 19:42'、'2026-07-09 19:42:15' 等混合格式统一到 ISO。"""
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


class HupuCrawler:
    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        max_thread_reply_pages: int | None = 5,
        session: requests.Session | None = None,
    ) -> None:
        self._limiter = rate_limiter or RateLimiter(min_interval=3.0, max_interval=5.0)
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_thread_reply_pages = max_thread_reply_pages
        self.last_list_board_cutoff_reached = False
        self.last_list_board_pages = 0
        self._session = session or requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    # ---------- 通用 GET ----------

    def _get(self, url: str) -> str | None:
        """带限速 + 重试的 GET。失败返回 None（不让爬虫中断）。"""
        for attempt in range(1, self._max_retries + 1):
            try:
                self._limiter.wait()
                resp = self._session.get(url, timeout=self._timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
                if resp.status_code == 403:
                    logger.warning("GET %s → 403（疑似被限流），延长等待", url)
                    import time
                    time.sleep(60)
            except requests.RequestException as exc:
                logger.warning("GET %s attempt %d/%d 失败：%s",
                               url, attempt, self._max_retries, exc)
        return None

    # ---------- 板块列表 ----------

    def list_board(
        self,
        board: str = "stock",
        max_pages: int = 20,
        stop_when_older_than: datetime | None = None,
    ) -> list[ThreadListItem]:
        """拉取 /{board} 最近 N 页帖子列表。stop_when_older_than 用于按时间截断。

        现代 Hupu URL 模式（2026-07 实测）：
            第 1 页：/{board}
            第 N 页 (N>=2)：/{board}-{N}    或    /{board}?page=N
        """
        results: list[ThreadListItem] = []
        self.last_list_board_cutoff_reached = False
        self.last_list_board_pages = 0
        for page in range(1, max_pages + 1):
            url = board_page_url(board, page)
            html = self._get(url)
            if not html:
                logger.warning("板块页 %s 第 %d 页抓取失败，跳过", board, page)
                break
            items = self._parse_thread_list(html, board)
            if not items:
                break
            results.extend(items)
            self.last_list_board_pages = page
            if stop_when_older_than and items:
                try:
                    # 仅当整页都早于 cutoff 才停止，置顶旧帖不能让扫描过早结束。
                    page_times = [datetime.fromisoformat(item.post_time) for item in items]
                    if page_times and max(page_times) < stop_when_older_than:
                        self.last_list_board_cutoff_reached = True
                        break
                except ValueError:
                    pass
        return results

    def _parse_thread_list(self, html: str, board: str) -> list[ThreadListItem]:
        """解析 /{board} 的 SSR 列表。

        现代 Hupu (Next.js, 2026-07 实测) 结构：
            <li class="bbs-sl-web-post-body">
              <div class="bbs-sl-web-post-layout">
                <div class="post-title"><a class="p-title" href="/<tid>.html">…</a></div>
                <div class="post-datum">2 / 828  </div>  ← 回复/浏览
                <div class="post-auth"><a href="https://my.hupu.com/<uid>">…</a></div>
                <div class="post-time">07-10 09:55</div>
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
            raw_time = time_el.get_text(strip=True) if time_el else ""
            post_time = _normalize_time(raw_time)

            datum_text = li.select_one(".post-datum").get_text(strip=True) if li.select_one(".post-datum") else "0 / 0"
            parts = re.findall(r"\d+", datum_text)
            reply_count = int(parts[0]) if len(parts) >= 1 else 0
            view_count = int(parts[1]) if len(parts) >= 2 else 0

            items.append(ThreadListItem(
                thread_id=tid,
                title=link.get_text(strip=True),
                author=author,
                author_hash=_hash_user(uid) if uid else _author_hash_from_text(author),
                post_time=post_time,
                reply_count=reply_count,
                url=f"{HUPU_BASE}{href}" if href.startswith("/") else href,
            ))
        return items

    # ---------- 单帖 + 回复 ----------

    def fetch_thread(
        self,
        thread_id: str,
        board: str = "stock",
        listed_post_time: str = "",
    ) -> tuple[Thread, list[Reply]]:
        """抓取单帖回复。

        ``max_thread_reply_pages=None`` 时翻到站点返回空页为止；增量任务仍使用
        有界默认值，避免单个超长讨论拖慢日常抓取。

        第 1 页：必须抓到主帖（标题、正文），同时拿到首批回复。
        第 2+ 页：仅追加回复；如果该页 0 回复就停止翻页（高互动帖子可能 page 2 即不存在）。
        """
        thread, replies = self.fetch_thread_page(
            thread_id, board=board, page=1, listed_post_time=listed_post_time,
        )
        page = 2
        while self._max_thread_reply_pages is None or page <= max(1, self._max_thread_reply_pages):
            try:
                _, page_replies = self.fetch_thread_page(
                    thread_id, board=board, page=page, thread_title=thread.title,
                )
            except Exception as exc:
                logger.warning("帖子 %s 第 %d 页解析失败：%s", thread_id, page, exc)
                break
            if not page_replies:
                logger.info("帖子 %s 第 %d 页无回复，停止翻页", thread_id, page)
                break
            replies.extend(page_replies)
            page += 1
        return thread, replies

    def fetch_thread_page(
        self,
        thread_id: str,
        *,
        board: str = "stock",
        page: int = 1,
        listed_post_time: str = "",
        thread_title: str = "",
    ) -> tuple[Thread, list[Reply]]:
        """抓取单帖的一页，供可恢复回填逐页持久化使用。"""
        if page < 1:
            raise ValueError("page 必须从 1 开始")
        url = (
            f"{HUPU_BASE}/{thread_id}.html"
            if page == 1
            else f"{HUPU_BASE}/{thread_id}-{page}.html"
        )
        html = self._get(url)
        if not html:
            raise RuntimeError(f"无法抓取帖子 {thread_id} 第 {page} 页")
        return self._parse_thread_page(
            html,
            thread_id,
            board,
            page=page,
            thread_title=thread_title,
            listed_post_time=listed_post_time if page == 1 else "",
        )

    def _parse_thread_page(
        self,
        html: str,
        thread_id: str,
        board: str,
        page: int,
        thread_title: str = "",
        listed_post_time: str = "",
    ) -> tuple[Thread, list[Reply]]:
        """解析 /<tid>[-n].html 详情页（现代 Hupu Next.js，2026-07 实测）。

        现代 Hupu 结构：
        - 第 1 页：<h1>title</h1> + 主帖 (.bbs-thread-comp .thread-content-detail) + 回复
        - 第 2 页及之后：仅回复，可能不再含 <h1> 和顶层 .bbs-thread-comp
        - 高亮回复 meta: "12625 回复 / 50 亮 759587 浏览"（仅大帖子可见）
        """
        soup = BeautifulSoup(html, "lxml")

        # ---- 标题（第 1 页才有）----
        title_el = soup.select_one("h1")
        title = (title_el.get_text(strip=True) if title_el else "") or thread_title

        # ---- 顶部 meta（大帖子页才有："X 回复 / Y 亮 Z 浏览"）----
        meta_match = re.search(
            r"(\d[\d,]*)\s*回复\s*/\s*(\d+)\s*亮\s*([\d,]+)\s*浏览",
            soup.get_text(" ", strip=True),
        )
        meta_replies = int(meta_match.group(1).replace(",", "")) if meta_match else 0
        meta_likes = int(meta_match.group(2)) if meta_match else 0
        meta_views = int(meta_match.group(3).replace(",", "")) if meta_match else 0

        # ---- 主帖（仅第 1 页有）----
        main_post = soup.select_one(".bbs-thread-comp")
        body_el = main_post.select_one(".thread-content-detail") if main_post else None
        content = body_el.get_text("\n", strip=True) if body_el else ""

        # 主帖作者可能在主帖之外（顶部独立卡片），先试几个回退选择器
        main_author_a = soup.select_one(
            ".post-auth a, .post-user-name, .user-base-info a[href*='my.hupu.com']"
        )
        main_uid = ""
        main_author_name = ""
        if main_author_a:
            main_author_name = main_author_a.get_text(strip=True)
            href_a = main_author_a.get("href", "")
            uid_m = re.search(r"my\.hupu\.com/(\d+)", href_a)
            main_uid = uid_m.group(1) if uid_m else ""

        # 主帖时间位于主帖卡片的作者头部；限定该范围以免回复时间抢占。
        # 现代 Hupu 的 CSS Modules 类名会带构建后缀。
        main_post_card = (
            main_post.find_parent(
                "div", class_=re.compile(r"post-content_bbs-post-content__")
            )
            if main_post
            else None
        )
        main_time_el = main_post_card.select_one(
            ".post-time, .post-info .post-time, "
            "[class*='post-user_post-user-comp-info-top-time']"
        ) if main_post_card else None
        detail_post_time = _normalize_time(main_time_el.get_text(strip=True)) if main_time_el else ""
        post_time = detail_post_time or listed_post_time

        crawl_time = _now_iso()
        thread = Thread(
            thread_id=thread_id,
            title=title,
            content=content,
            replies=meta_replies,
            likes=meta_likes,
            views=meta_views,
            author_hash=_hash_user(main_uid) if main_uid else _author_hash_from_text(main_author_name),
            post_time=post_time,
            crawl_time=crawl_time,
            url=f"{HUPU_BASE}/{thread_id}.html",
            board=board,
        )

        # ---- 回复（第 1+ 页都有，但 page 2+ 可能为 0）----
        replies: list[Reply] = []
        for li in soup.select(".post-reply-list-container"):
            r_author_a = li.select_one(".post-reply-list-user-info-top-name")
            r_author = r_author_a.get_text(strip=True) if r_author_a else ""
            r_uid = ""
            if r_author_a:
                uid_m = re.search(r"my\.hupu\.com/(\d+)", r_author_a.get("href", ""))
                r_uid = uid_m.group(1) if uid_m else ""

            r_time_el = li.select_one(".post-reply-list-user-info-top-time")
            r_time = (r_time_el.get_text(strip=True) if r_time_el else "") or ""

            r_floor_el = li.select_one(".position")
            floor = _parse_int(r_floor_el.get_text() if r_floor_el else "0")

            r_like_text = ""
            for todo in li.select(".todo-list.light .todo-list-text, .todo-list"):
                txt = todo.get_text(" ", strip=True)
                if "亮了" in txt:
                    r_like_text = txt
                    break
            r_likes = _parse_int(r_like_text)

            r_body_el = li.select_one(".thread-content-detail")
            r_content = r_body_el.get_text("\n", strip=True) if r_body_el else ""

            rid_anchor = li.select_one("[id]") or li
            rid_raw = rid_anchor.get("id") or f"{thread_id}-{floor}"
            rid = f"{thread_id}:{rid_raw}"

            replies.append(Reply(
                reply_id=rid,
                thread_id=thread_id,
                content=r_content,
                likes=r_likes,
                author_hash=_hash_user(r_uid) if r_uid else _author_hash_from_text(r_author),
                reply_time=r_time,
                crawl_time=crawl_time,
                floor=floor,
            ))
        return thread, replies

    # ---------- 增量入口 ----------

    def crawl_incremental(
        self,
        board: str = "stock",
        board_pages: int = 5,
        since_hours: int = 6,
        on_thread_fetched: Callable[[Thread, list[Reply]], None] | None = None,
    ) -> tuple[list[Thread], list[Reply]]:
        """板块列表前 N 页 → 单帖详情（受 max_pages 限制）→ 返回本次抓到的主帖 + 回复。
        已经存在于 db 的帖子会被 skip（由持久化层判断）。"""
        from datetime import datetime, timedelta
        stop = datetime.now() - timedelta(hours=since_hours)
        items = self.list_board(
            board=board,
            max_pages=board_pages,
            stop_when_older_than=stop,
        )
        logger.info("发现 %d 个候选帖子（板块 %s）", len(items), board)

        all_threads: list[Thread] = []
        all_replies: list[Reply] = []
        for it in items:
            try:
                thread, replies = self.fetch_thread(
                    it.thread_id, board=board, listed_post_time=it.post_time,
                )
            except Exception as exc:
                logger.warning("帖子 %s 抓取失败：%s", it.thread_id, exc)
                continue
            if on_thread_fetched is not None:
                on_thread_fetched(thread, replies)
            all_threads.append(thread)
            all_replies.extend(replies)
        return all_threads, all_replies
