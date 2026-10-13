"""解析逻辑的最小单元测试。

无需联网，跑 < 1 秒。
"""
from pathlib import Path

from crawler import parse_main_post, parse_thread_list


SAMPLE_LIST_HTML = """<html><head><meta charset="utf-8"></head><body>
<ul>
  <li class="bbs-sl-web-post-body">
    <div class="bbs-sl-web-post-layout">
      <div class="post-title"><a class="p-title" href="/641580705.html">0805复盘：继续修复</a></div>
      <div class="post-datum">32 / 1234</div>
      <div class="post-auth"><a href="https://my.hupu.com/19134213076193">巴萨主教练弗里克</a></div>
      <div class="post-time">08-05 17:17</div>
    </div>
  </li>
  <li class="bbs-sl-web-post-body">
    <div class="bbs-sl-web-post-layout">
      <div class="post-title"><a class="p-title" href="/641580706.html">别人的帖子</a></div>
      <div class="post-datum">5 / 100</div>
      <div class="post-auth"><a href="https://my.hupu.com/999999">其他用户</a></div>
      <div class="post-time">08-05 17:18</div>
    </div>
  </li>
</ul>
</body></html>
"""


def test_parse_thread_list_extracts_both_items() -> None:
    items = parse_thread_list(SAMPLE_LIST_HTML)
    assert len(items) == 2, f"应解析出 2 条，实际 {len(items)}"

    target, other = items
    assert target.thread_id == "641580705"
    assert target.title == "0805复盘：继续修复"
    assert target.author_uid == "19134213076193"
    assert target.author == "巴萨主教练弗里克"
    assert target.reply_count == 32
    assert target.url == "https://bbs.hupu.com/641580705.html"

    assert other.thread_id == "641580706"
    assert other.author_uid == "999999"


def test_filter_target_user_by_uid() -> None:
    """验证按 uid 过滤能正确挑出目标用户。"""
    items = parse_thread_list(SAMPLE_LIST_HTML)
    target_uid = "19134213076193"
    matched = [it for it in items if it.author_uid == target_uid]
    assert len(matched) == 1
    assert matched[0].thread_id == "641580705"


SAMPLE_DETAIL_HTML = """<html><head><meta charset="utf-8"></head><body>
<h1>0805复盘：继续修复</h1>
<div class="post-content_bbs-post-content__abc">
  <div class="post-user_post-user-comp__xyz">
    <a class="post-user-name" href="https://my.hupu.com/19134213076193">巴萨主教练弗里克</a>
    <div class="post-time">2026-08-05 17:17</div>
  </div>
  <div class="post-content_main-post-info__qwe">
    <div class="bbs-thread-comp">
      <div class="thread-content-detail">
        今天半导体修复为主，AI 调整。

        板块：光模块、PCB。
        个股：沪电股份 +5%，中际旭创 +3%。
        明日策略：等量企稳。
      </div>
    </div>
  </div>
</div>
<!-- 下方是一条回复，主贴解析不应取到它 -->
<div class="reply-list-wrapper">
  <div class="bbs-thread-comp">
    <div class="thread-content-detail">这是一条回复，不应被提取</div>
  </div>
  <a class="post-user-name" href="https://my.hupu.com/999999">路人甲</a>
  <div class="post-time">2026-08-05 17:30</div>
</div>
</body></html>
"""


def test_parse_main_post_extracts_title_and_content() -> None:
    post = parse_main_post(SAMPLE_DETAIL_HTML, "641580705")
    assert post is not None
    assert post.thread_id == "641580705"
    assert post.title == "0805复盘：继续修复"
    assert "半导体修复为主" in post.content
    assert "明日策略" in post.content
    # 必须取到主贴作者，不能误取回复者
    assert post.author_uid == "19134213076193"
    assert post.author == "巴萨主教练弗里克"
    assert post.post_time.startswith("2026-08-05T17:17")
    assert post.url == "https://bbs.hupu.com/641580705.html"


def test_parse_main_post_ignores_reply_authors() -> None:
    """当页面上有回复时，主贴解析必须只取主贴作者，不能误取回复者。"""
    post = parse_main_post(SAMPLE_DETAIL_HTML, "641580705")
    assert post is not None
    # 回复里有个 uid=999999 的路人甲
    assert "999999" not in post.author_uid
    assert "路人甲" not in post.author
    # 内容也不能混入回复
    assert "这是一条回复" not in post.content


def test_parse_main_post_returns_none_for_empty() -> None:
    assert parse_main_post("<html><body></body></html>", "123") is None


# ---------- crawl_user_posts 日期截断逻辑 ----------

from datetime import datetime
from unittest.mock import MagicMock

from crawler import MainPost, ThreadListItem, crawl_user_posts


def _mock_crawler_with_pages(pages: list[list[ThreadListItem]]) -> MagicMock:
    """Mock 一个 HupuUserCrawler，让 list_board_page 依次返回 pages 里的页面。

    超出 pages 范围的请求返回 []（模拟真实爬虫"页空了"的情形）。
    """
    c = MagicMock()
    page_iter = iter(pages)

    def list_board_page_side_effect(*args, **kwargs):
        try:
            return next(page_iter)
        except StopIteration:
            return []

    c.list_board_page.side_effect = list_board_page_side_effect
    c.fetch_main_post.side_effect = lambda tid, listed_post_time="": MainPost(
        thread_id=tid,
        title=f"title-{tid}",
        content="body",
        author="巴萨主教练弗里克",
        author_uid="19134213076193",
        post_time=listed_post_time or "2026-08-05T00:00:00",
        url=f"https://bbs.hupu.com/{tid}.html",
        fetched_at="2026-08-05T00:00:00",
    )
    return c


def _make_tmp_path(name: str) -> Path:
    """避免 Windows 下 tmp_path fixture 的权限问题，直接在项目 data/ 下建文件。"""
    from pathlib import Path as _P
    d = _P(__file__).parent.parent / "data" / "_test_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def test_crawl_stops_when_all_posts_older_than_until_date() -> None:
    """所有帖子都早于 until_date 时应停止翻页（不再统计本页匹配数）。"""
    target_uid = "19134213076193"
    # 第 1 页：50 条帖子全部 2026-07-20 < 截止 2026-08-01 → 应立即停止
    pages = [
        [
            ThreadListItem(
                thread_id=str(100 + i),
                title=f"old-{i}",
                author="any", author_uid=target_uid if i == 0 else "other",
                post_time="2026-07-20T10:00:00",
                reply_count=0, url=f"https://bbs.hupu.com/{100+i}.html",
            )
            for i in range(50)
        ],
    ]
    crawler = _mock_crawler_with_pages(pages)
    out = _make_tmp_path("test_cutoff_stop.jsonl")
    if out.exists():
        out.unlink()

    matched, written = crawl_user_posts(
        crawler, target_uid=target_uid, output_path=out,
        max_pages=10, empty_page_limit=10,
        until_date=datetime(2026, 8, 1),
    )

    assert crawler.list_board_page.call_count == 1  # 只取了第 1 页就停了
    assert matched == 0  # 截止触发时不统计本页匹配（设计意图：加速跳出）
    assert written == 0


def test_crawl_continues_when_some_posts_newer_than_until_date() -> None:
    """只要页面里还有晚于 until_date 的帖子就继续翻页。"""
    target_uid = "19134213076193"
    pages = [
        # 第 1 页：含 2026-08-05 的新帖子（> 截止 2026-08-01），继续
        [
            ThreadListItem(
                thread_id=str(100 + i),
                title=f"newer-{i}",
                author="any", author_uid=target_uid if i == 0 else "other",
                post_time="2026-08-05T10:00:00" if i == 0 else "2026-08-03T10:00:00",
                reply_count=0, url=f"https://bbs.hupu.com/{100+i}.html",
            )
            for i in range(50)
        ],
        # 第 2 页：全部 2026-07-15 < 2026-08-01 → 停止
        [
            ThreadListItem(
                thread_id=str(200 + i),
                title=f"old-{i}",
                author="any", author_uid="other",
                post_time="2026-07-15T10:00:00",
                reply_count=0, url=f"https://bbs.hupu.com/{200+i}.html",
            )
            for i in range(50)
        ],
    ]
    crawler = _mock_crawler_with_pages(pages)
    out = _make_tmp_path("test_cutoff_continue.jsonl")
    if out.exists():
        out.unlink()

    matched, written = crawl_user_posts(
        crawler, target_uid=target_uid, output_path=out,
        max_pages=10, empty_page_limit=10,
        until_date=datetime(2026, 8, 1),
    )

    assert crawler.list_board_page.call_count == 2
    assert matched == 1
    assert written == 1


def test_crawl_skips_already_seen_thread_ids() -> None:
    """续传：已存在的 thread_id 应被跳过，不重新抓详情页。"""
    target_uid = "19134213076193"
    out = _make_tmp_path("test_resume.jsonl")
    # 先写一条已存在记录
    out.write_text(
        '{"thread_id": "100", "title": "x", "content": "y", "author": "a", '
        '"author_uid": "19134213076193", "post_time": "2026-08-05T10:00:00", '
        '"url": "https://bbs.hupu.com/100.html", "fetched_at": "2026-08-05T10:00:00"}\n',
        encoding="utf-8",
    )

    pages = [[
        ThreadListItem(
            thread_id="100", title="already",
            author="a", author_uid=target_uid,
            post_time="2026-08-05T10:00:00",
            reply_count=0, url="https://bbs.hupu.com/100.html",
        ),
    ]]
    crawler = _mock_crawler_with_pages(pages)
    # 关键：匹配后 empty_pages=1，连续 3 页空后会自然停；给一个非常小的 empty_page_limit
    # 让我们用有限页数就能结束

    matched, written = crawl_user_posts(
        crawler, target_uid=target_uid, output_path=out,
        max_pages=2, empty_page_limit=1,  # 第 1 页后空页限制立刻触发
    )

    assert matched == 1
    assert written == 0  # 已存在，不重写
    assert crawler.fetch_main_post.call_count == 0  # 详情页都不抓


def test_crawl_continues_through_empty_pages_when_until_date_set() -> None:
    """关键 bug 回归测试：用户提供 until_date 后，不应再被空页限制过早停止。

    场景：用户每发 1 条帖子中间可能间隔 5-10 页空页（高流量板块的常态）。
    若 empty_page_limit=3，会在前几个用户帖子之间就过早停止，导致漏抓大量帖子。
    """
    target_uid = "19134213076193"
    # 模拟：每 5 页里有 1 个目标用户帖子（中间都是其他用户的帖子）
    pages = []
    for batch in range(5):  # 5 批 = 25 页
        batch_pages = []
        for p in range(5):
            page = []
            for i in range(50):
                # 第 1 页的第 1 条是目标用户的帖子
                is_target = (p == 0 and i == 0)
                page.append(ThreadListItem(
                    thread_id=f"{batch}000-{p}-{i}",
                    title=f"post-{batch}-{p}-{i}",
                    author="any",
                    author_uid=target_uid if is_target else "other",
                    # 时间线性递减，让前面的批次更新
                    post_time=f"2026-08-{5-batch:02d}T10:00:00",
                    reply_count=0,
                    url=f"https://bbs.hupu.com/{batch}-{p}-{i}.html",
                ))
            batch_pages.append(page)
        pages.extend(batch_pages)

    crawler = _mock_crawler_with_pages(pages)
    out = _make_tmp_path("test_sparse_posts.jsonl")
    if out.exists():
        out.unlink()

    matched, written = crawl_user_posts(
        crawler, target_uid=target_uid, output_path=out,
        max_pages=30, empty_page_limit=3,  # 默认 3，但有 until_date 会忽略
        until_date=datetime(2025, 8, 1),  # 提供 until_date
    )

    # 5 个批次，每批 1 个目标帖子 → 应匹配 5 个，写入 5 个
    assert matched == 5, f"应匹配 5 个，实际 {matched}"
    assert written == 5, f"应写入 5 个，实际 {written}"
    # 翻页应该走过所有页（不会被空页限制过早停）
    assert crawler.list_board_page.call_count >= 25
