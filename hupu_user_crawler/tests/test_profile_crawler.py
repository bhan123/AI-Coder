"""crawl_profile.py 的单元测试（用 mock 避免依赖真实 cookie/网络）。"""
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from crawl_profile import crawl_profile_to_jsonl
from profile_parser import ProfilePost


def _make_tmp_path(name: str) -> Path:
    """避免 Windows 下 tmp_path fixture 的权限问题。"""
    d = Path(__file__).parent.parent / "data" / "_test_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _make_mock_crawler(profile_html: str | None = None, detail_html_map: dict | None = None) -> MagicMock:
    """构造 mock crawler。profile_html: 个人主页响应；detail_html_map: tid → 详情页 HTML。"""
    c = MagicMock()

    def fake_get(url: str) -> str | None:
        if "my.hupu.com" in url and profile_html is not None:
            return profile_html
        if detail_html_map:
            for tid, html in detail_html_map.items():
                if f"/{tid}.html" in url:
                    return html
        return None

    c._get.side_effect = fake_get
    return c


SAMPLE_PROFILE_HTML = """
{"tabKey":"1","pageData":[
  {"tid":"100","title":"0701复盘：A","fid":161,"create_time":1720000000,"summary":"s1","puid":1,"replies":5,"visits":100,"nickname":"u"},
  {"tid":"101","title":"0702复盘：B","fid":161,"create_time":1720100000,"summary":"s2","puid":1,"replies":3,"visits":50,"nickname":"u"},
  {"tid":"200","title":"步行街帖子","fid":40,"create_time":1720200000,"summary":"x","puid":1,"replies":1,"visits":10,"nickname":"u"}
],"nextPage":false}
"""


def test_crawl_profile_filters_to_stock_only():
    """非 stock 板块的帖子（fid != 161）应被过滤掉。"""
    out = _make_tmp_path("test_profile_stock_only.jsonl")
    if out.exists():
        out.unlink()
    crawler = _make_mock_crawler(profile_html=SAMPLE_PROFILE_HTML)
    crawler._get.side_effect = lambda url: (
        SAMPLE_PROFILE_HTML if "my.hupu.com" in url
        else "<html><body></body></html>" if ".html" in url
        else None
    )

    matched, written = crawl_profile_to_jsonl(
        crawler, uid="999", output_path=out, fetch_full=False,
    )

    assert matched == 2  # 2 条 stock 帖子（tid 100, 101），跳过步行街
    assert written == 2


def test_crawl_profile_skips_existing_tids():
    """续传：已存在的 tid 不重抓。"""
    out = _make_tmp_path("test_profile_resume.jsonl")
    out.write_text(
        '{"thread_id":"100","title":"already","content":"x","author":"a","author_uid":"999","post_time":"2026-07-01T15:00:00","url":"u","fetched_at":"2026-07-01T15:00:00"}\n',
        encoding="utf-8",
    )

    crawler = _make_mock_crawler(profile_html=SAMPLE_PROFILE_HTML)
    matched, written = crawl_profile_to_jsonl(
        crawler, uid="999", output_path=out, fetch_full=False,
    )

    assert matched == 2
    assert written == 1  # tid=100 已存在，只新增 tid=101
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_crawl_profile_handles_failed_profile_fetch():
    """profile 页抓取失败时优雅返回，不抛异常。"""
    out = _make_tmp_path("test_profile_fail.jsonl")
    if out.exists():
        out.unlink()
    crawler = MagicMock()
    crawler._get.return_value = None

    matched, written = crawl_profile_to_jsonl(
        crawler, uid="999", output_path=out, fetch_full=False,
    )

    assert matched == 0
    assert written == 0
