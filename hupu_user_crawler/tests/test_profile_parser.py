"""profile_parser 的单元测试。

测试用的 HTML 是 2026-08 抓的真实 my.hupu.com/19134213076193 页面快照，
内嵌在 SAMPLE_PROFILE_HTML 常量里，不依赖外部文件。
"""
from profile_parser import filter_stock, parse_profile_page


# 真实抓取的 my.hupu.com/19134213076193 页面片段（含 30 条 stock 帖子的 pageData）
# 截取 pageData 数组及其上下文，用作 parser 的测试输入
SAMPLE_PROFILE_HTML = """
...,"nextPage":false,"env":"prod","tabKey":"1","pageData":[
{"fid":161,"create_time":1785999787,"lastpost_time":1786002533,"type":"mt","title":"0806复盘：反弹后的第一次分歧","tid":641625851,"visits":2408,"forum_name":"股票区","puid":16142549,"replies":8,"topic_name":"股票区","nickname":"巴萨主教练弗里克","topic_id":21,"summary":"【今日操作】1. 石头科技：106.2加仓；","lights":5},
{"fid":161,"create_time":1785914674,"lastpost_time":1786003402,"type":"mt","title":"0805复盘：继续修复","tid":641580705,"visits":24200,"forum_name":"股票区","puid":16142549,"replies":70,"topic_name":"股票区","nickname":"巴萨主教练弗里克","topic_id":21,"summary":"【今日操作】石头科技","lights":17},
{"fid":40,"create_time":1785000000,"lastpost_time":1785000001,"type":"mt","title":"步行街帖子","tid":999000,"visits":100,"forum_name":"步行街","puid":16142549,"replies":5,"topic_name":"步行街","nickname":"巴萨主教练弗里克","topic_id":5,"summary":"步行街内容","lights":0}
],"someOtherField":{...}
"""


def test_parse_profile_page_extracts_all_posts():
    posts, has_more = parse_profile_page(SAMPLE_PROFILE_HTML)
    assert len(posts) == 3, f"应解析 3 条帖子，实际 {len(posts)}"
    assert has_more is False, "nextPage=false 应被识别"


def test_filter_stock_only_returns_stock_board():
    posts, _ = parse_profile_page(SAMPLE_PROFILE_HTML)
    stock_posts = filter_stock(posts)
    assert len(stock_posts) == 2, "应只剩 2 条 stock 板块帖子（fid=161）"
    for p in stock_posts:
        assert p.fid == 161


def test_post_titles_have_correct_format():
    """每日复盘帖子的标题应该是 'MMDD复盘：xxx' 格式。"""
    posts, _ = parse_profile_page(SAMPLE_PROFILE_HTML)
    stock = filter_stock(posts)
    assert "复盘" in stock[0].title


def test_post_summary_is_present():
    """有 summary 字段的帖子应被正确提取。"""
    posts, _ = parse_profile_page(SAMPLE_PROFILE_HTML)
    stock = filter_stock(posts)
    # 第一条有完整 summary，第二条 summary 较短
    assert "【今日操作】" in stock[0].summary


def test_invalid_html_returns_empty():
    posts, has_more = parse_profile_page("<html><body>no pageData</body></html>")
    assert posts == []
    assert has_more is False


def test_parse_full_real_profile_structure():
    """端到端：构造一段完整的 pageData，验证 30 条全部解析。"""
    import json
    page_data = [
        {
            "fid": 161,
            "create_time": 1720000000 + i * 86400,
            "title": f"{6 if i < 10 else 7:02d}{15 + i if i < 16 else 1 + i - 16:02d}复盘：测试帖子{i}",
            "tid": str(640000000 + i),
            "puid": 16142549,
            "replies": 5,
            "visits": 1000,
            "nickname": "巴萨主教练弗里克",
            "summary": f"内容预览 {i}",
            "forum_name": "股票区",
            "topic_name": "股票区",
        }
        for i in range(30)
    ]
    html = json.dumps({
        "tabKey": "1",
        "nextPage": False,
        "pageData": page_data,
    })
    posts, has_more = parse_profile_page(html)
    assert len(posts) == 30
    assert has_more is False
