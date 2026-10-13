"""基于真实抓取的虎扑 HTML 离线测试解析器。

fixtures/ 里的文件是真实抓下来的页面（2026-07）：
- stock_list.html        /stock 板块首页           50 条
- thread_small_p1.html   2 回复的小帖子第 1 页       主帖 + 2 回复
- thread_mega_p1.html    1.2 万回复的 mega 帖子第 1 页 主帖 "如题" + 70 回复
- thread_mega_p50.html   mega 帖子第 50 页           仅回复（无主帖）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from crawler.hupu_crawler import HupuCrawler
from crawler.rate_limiter import RateLimiter

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def crawler() -> HupuCrawler:
    return HupuCrawler(rate_limiter=RateLimiter(min_interval=0, max_interval=0))


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# -------- 列表 --------

def test_list_parses_50_threads(crawler: HupuCrawler) -> None:
    items = crawler._parse_thread_list(_read("stock_list.html"), "stock")
    assert len(items) == 50
    sample = items[0]
    assert sample.thread_id.isdigit()
    assert sample.reply_count >= 0
    assert sample.url.startswith("https://bbs.hupu.com/")


def test_list_extracts_post_time_iso(crawler: HupuCrawler) -> None:
    items = crawler._parse_thread_list(_read("stock_list.html"), "stock")
    iso_times = [it.post_time for it in items if "T" in it.post_time]
    assert len(iso_times) >= 40  # 至少 80% 是 ISO 格式


# -------- 主帖（page 1）--------

def test_small_thread_page_1(crawler: HupuCrawler) -> None:
    thread, replies = crawler._parse_thread_page(
        _read("thread_small_p1.html"), "640719734", "stock", page=1
    )
    assert thread.title == "7.10 早盘策略解析：华天科技，百合花，工业富联，拓维信息，东山精密，兴森科技，TCL科技"
    # 第一页有 meta: "2 回复 / 0 亮 843 浏览"
    assert thread.replies >= 1
    assert thread.views >= 1
    assert "华天科技" in thread.content
    # 主帖时间在 modern Hupu 小帖子里常常没有（只有翻页页才有）
    # 只要解析不会崩即可
    _ = thread.post_time
    assert thread.author_hash  # non-empty hash
    assert len(replies) == 2
    assert replies[0].floor == 1
    assert replies[0].content
    assert replies[0].reply_time.startswith("2026-")


def test_thread_page_prefers_css_module_detail_time_over_listed_post_time(
    crawler: HupuCrawler,
) -> None:
    listed_post_time = "2026-07-10T09:30:00"

    thread, _ = crawler._parse_thread_page(
        _read("thread_small_p1.html"),
        "640719734",
        "stock",
        page=1,
        listed_post_time=listed_post_time,
    )

    assert thread.post_time == "2026-07-10T08:02:15"


def test_thread_page_uses_op_time_when_reply_time_precedes_main_post(
    crawler: HupuCrawler,
) -> None:
    html_with_preceding_reply_time = (
        '<div class="post-reply-list-container">'
        '<span class="post-time">2025-01-01 00:00:00</span>'
        "</div>"
        + _read("thread_small_p1.html")
    )

    thread, _ = crawler._parse_thread_page(
        html_with_preceding_reply_time,
        "640719734",
        "stock",
        page=1,
        listed_post_time="2026-07-10T09:30:00",
    )

    assert thread.post_time == "2026-07-10T08:02:15"


def test_thread_page_uses_listed_post_time_when_detail_time_missing(
    crawler: HupuCrawler,
) -> None:
    listed_post_time = "2026-07-10T09:30:00"
    html_without_detail_time = _read("thread_small_p1.html").replace(
        '<span class="post-user_post-user-comp-info-top-time__k9K2U">'
        "2026-07-10 08:02:15</span>",
        "",
    )

    thread, _ = crawler._parse_thread_page(
        html_without_detail_time,
        "640719734",
        "stock",
        page=1,
        listed_post_time=listed_post_time,
    )

    assert thread.post_time == listed_post_time


def test_mega_thread_page_1_parses_meta_and_replies(crawler: HupuCrawler) -> None:
    thread, replies = crawler._parse_thread_page(
        _read("thread_mega_p1.html"), "640442830", "stock", page=1
    )
    assert "26年7月超短楼" in thread.title
    # 顶部 meta: "12625 回复 / 50 亮 759587 浏览"
    assert thread.replies >= 10000
    assert thread.views >= 100000
    assert thread.likes == 50
    assert len(replies) >= 50  # 第一页 ~70 条；只断言 50 保下限


# -------- 大帖子翻页（page 50，无主帖）--------

def test_mega_thread_page_50_only_replies(crawler: HupuCrawler) -> None:
    thread, replies = crawler._parse_thread_page(
        _read("thread_mega_p50.html"), "640442830", "stock", page=50,
        thread_title="26年7月超短楼",
    )
    # page 50 没有主帖正文，但 thread_title 由 caller 补齐
    assert thread.title == "26年7月超短楼"
    assert thread.content == ""  # page 2+ 不带主帖正文
    assert replies, "page 50 应至少有少量回复"
    # 楼层应在 900-1000 左右
    floors = [r.floor for r in replies]
    assert min(floors) >= 900 and max(floors) < 1100
