"""探测个人主页结构：抓一次 https://my.hupu.com/{uid}，保存 HTML 到本地用于分析。

不做任何写入、不持久化 cookie，只是为了看清楚：
1. 这个用户是否真的能看到所有帖子
2. 页面是分页、滚动、还是单页全量
3. 帖子元素的选择器是什么
4. 帖子 URL 格式（能不能直接复用现有 fetch_main_post）
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import HUPU_BASE, HUPU_COOKIE, TARGET_USER_ID
from crawler import HupuUserCrawler

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", default=TARGET_USER_ID)
    parser.add_argument("--cookie", default=None, help="覆盖 HUPU_COOKIE 环境变量")
    parser.add_argument("--out", type=Path, default=Path("data/probe_profile.html"))
    args = parser.parse_args()

    cookie = args.cookie or HUPU_COOKIE
    if not cookie:
        print("错误：未提供 cookie。设置环境变量 HUPU_COOKIE 或用 --cookie 传入。", file=sys.stderr)
        sys.exit(1)

    crawler = HupuUserCrawler(cookie=cookie)
    url = f"{HUPU_BASE}/my.hupu.com/{args.uid}"  # 实际是 my.hupu.com 不是 bbs.hupu.com
    # 修正：my.hupu.com 是另一域
    url = f"https://my.hupu.com/{args.uid}"
    print(f"抓取: {url}")

    html = crawler._get(url)
    if not html:
        print("失败：未拿到 HTML", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"✓ 已保存 {len(html)} 字节到 {args.out}")
    print()
    print("下一步：")
    print("  1) 用浏览器/编辑器打开这个 HTML")
    print("  2) 搜索 'stock' 看帖子的板块标识")
    print("  3) 搜索 'bbs.hupu.com' 看帖子链接格式")
    print("  4) 搜索 'nextPage' / 'loadMore' / 'page=' 看分页方式")
    print("  5) 把 HTML 结构截图/贴给我，告诉我你的发现")


if __name__ == "__main__":
    main()
