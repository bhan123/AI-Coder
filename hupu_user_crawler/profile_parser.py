"""解析个人主页 HTML，提取 pageData JSON。

个人主页结构（2026-08 实测）：
    HTML 内嵌一段 SSR JSON：
        "pageData": [{"fid":161,"create_time":...,"title":...,"tid":...,"puid":...,"summary":"...",...}, ...]
        "nextPage": false   ← 没有下一页，全量
        "tabKey": "1"

    fid=161 是虎扑股票区板块 ID。
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

STOCK_FORUM_ID = 161  # 虎扑股票区 /stock


@dataclass
class ProfilePost:
    """从个人主页 pageData 提取的帖子元数据。"""

    tid: str
    title: str
    fid: int
    create_time: datetime.datetime
    summary: str  # 内容预览（~150 字）
    replies: int
    visits: int
    nickname: str
    puid: int  # 作者内部 ID
    url: str


def _find_matching_bracket(s: str, open_pos: int, open_ch: str = "[", close_ch: str = "]") -> int:
    """从 open_pos 开始，找到匹配的 close_ch 的位置（不含）。处理字符串转义。"""
    depth = 0
    in_string = False
    escape = False
    quote = None
    for i in range(open_pos, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if in_string:
            if c == quote:
                in_string = False
            continue
        if c in ('"', "'"):
            in_string = True
            quote = c
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_profile_page(html: str) -> tuple[list[ProfilePost], bool]:
    """解析个人主页 HTML，返回 (该用户的帖子列表, 是否还有下一页)。"""
    idx = html.find("pageData")
    if idx < 0:
        logger.warning("HTML 中未找到 pageData 字段")
        return [], False

    arr_start = html.find("[", idx)
    if arr_start < 0:
        return [], False

    arr_end = _find_matching_bracket(html, arr_start)
    if arr_end < 0:
        logger.warning("pageData 数组未闭合")
        return [], False

    arr_str = html[arr_start:arr_end + 1]
    try:
        data = json.loads(arr_str)
    except json.JSONDecodeError as e:
        logger.warning("pageData JSON 解析失败: %s", e)
        return [], False

    next_page_match = re.search(r'"nextPage"\s*:\s*(true|false)', html)
    has_more = next_page_match.group(1) == "true" if next_page_match else False

    posts: list[ProfilePost] = []
    for item in data:
        try:
            post = _item_to_post(item)
            if post is not None:
                posts.append(post)
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("跳过一条 pageData: %s", e)
            continue

    logger.info("pageData 解析: %d 条帖子, nextPage=%s", len(posts), has_more)
    return posts, has_more


def _item_to_post(item: dict[str, Any]) -> ProfilePost | None:
    """把 pageData 中的一条 item 转成 ProfilePost。"""
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
        create_time=datetime.datetime.fromtimestamp(int(create_ts)),
        summary=(item.get("summary") or "").strip(),
        replies=int(item.get("replies", 0)),
        visits=int(item.get("visits", 0)),
        nickname=(item.get("nickname") or "").strip(),
        puid=int(item.get("puid", 0)),
        url=f"https://bbs.hupu.com/{tid}.html",
    )


def filter_stock(posts: list[ProfilePost]) -> list[ProfilePost]:
    """只保留 stock 板块（fid=161）的帖子。"""
    return [p for p in posts if p.fid == STOCK_FORUM_ID]
