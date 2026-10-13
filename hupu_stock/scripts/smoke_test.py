"""冒烟测试：单次拉 /stock 第一页，确认 HTML 能抓、能解析、选择器命中。

设计文档 §11 验收点 1、9 的部署前自检：
1. 爬虫能在不报错的前提下抓回 HTML
2. 选择器命中至少 1 条候选帖子
3. SQLite 表已创建且可写入

用法：
    python -m scripts.smoke_test
    python -m scripts.smoke_test --board stock --dump-html /tmp/hupu_stock.html
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from crawler.hupu_crawler import HupuCrawler, DEFAULT_HEADERS, board_page_url
from storage.connection import session, DEFAULT_DB_PATH
from storage.persist import list_crawled_thread_ids


def _parse_thread_list(html: str) -> int:
    """复刻爬虫 _parse_thread_list 的命中数，用于冒烟统计。"""
    soup = BeautifulSoup(html, "lxml")
    count = 0
    seen: set[str] = set()
    import re as _re
    for link in soup.select("a[href*='.html']"):
        href = link.get("href", "")
        m = _re.search(r"/(\d+)(?:-\d+)?\.html", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        text = link.get_text(strip=True)
        if not text or text in {"下一页", "上一页", "末页"} or _re.fullmatch(r"\d+", text):
            continue
        seen.add(tid)
        count += 1
    return count


def _diagnose(html: str) -> dict:
    """列出 HTML 里看到的唯一 class 名高频 Top 20、链接模式、a 标签样式。"""
    soup = BeautifulSoup(html, "lxml")
    from collections import Counter
    classes = Counter()
    for el in soup.select("[class]"):
        for cls in el.get("class", []):
            classes[cls] += 1
    # 链接样本：抽 8 个含 .html 的 a
    samples = []
    for a in soup.select("a[href*='.html']")[:8]:
        samples.append({
            "text": a.get_text(strip=True)[:60],
            "href": a.get("href", "")[:80],
            "parent_class": (a.parent.get("class") if a.parent else None),
        })
    return {
        "top_classes": classes.most_common(20),
        "link_samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冒烟测试：抓 /stock 第一页")
    parser.add_argument("--board", default="stock")
    parser.add_argument("--dump-html", default=None, help="把原始 HTML 写到本地以便调试选择器")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("smoke_test")

    log.info("=" * 60)
    log.info("smoke_test start board=%s db=%s", args.board, DEFAULT_DB_PATH)
    log.info("=" * 60)

    crawler = HupuCrawler(
        rate_limiter=type("Fast", (), {"wait": lambda self: time.sleep(0.5)})(),
        max_retries=1,
    )

    url = board_page_url(args.board)
    log.info("[1/4] GET %s", url)
    html = crawler._get(url)
    if not html:
        log.error("无法获取板块首页 HTML（403/超时/反爬？检查 User-Agent 与 IP）")
        return 2

    log.info("[2/4] HTML 长度=%d 字节", len(html))

    if args.dump_html:
        Path(args.dump_html).write_text(html, encoding="utf-8")
        log.info("已 dump 到 %s", args.dump_html)

    soup = BeautifulSoup(html, "lxml")
    list_match = _parse_thread_list(html)
    log.info("[3/4] 板块列表候选命中数 = %d", list_match)
    diag = _diagnose(html)
    log.info("页面 Top class:")
    for cls, n in diag["top_classes"][:15]:
        log.info("    %-40s × %d", cls, n)
    log.info("链接样本（前 8 个 .html）：")
    for s in diag["link_samples"]:
        log.info("    href=%-60s parent=%-30s text=%s",
                 s["href"], s["parent_class"], s["text"])
    if list_match == 0:
        log.warning(
            "未命中任何候选："
            "如果上面的链接样本看起来是正常帖子（不是翻页数字），"
            "说明 _parse_thread_list 的过滤条件太严；"
            "否则说明 /stock 页面结构已变，需调整 src/crawler/hupu_crawler.py"
        )

    log.info("[4/4] SQLite 表初始化 …")
    with session() as conn:
        ids = list_crawled_thread_ids(conn)
    log.info("数据库里已有 %d 条历史 thread_id（首次运行应为 0）", len(ids))

    log.info("smoke_test OK")
    return 0 if list_match > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
