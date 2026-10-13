"""抓取源平台补充内容（README、讨论、文章正文等）用于增强证据包。

所有抓取函数超时 15 秒，失败不抛异常（返回 None），不阻塞主流水线。
"""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

from engine.sources.base import fetch_json, fetch_text


def _truncate(text: str, max_chars: int = 2000) -> str:
    """截断文本，尽量在句子边界处断开。"""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ("。", "\n\n", "\n", ". ", "."):
        last = truncated.rfind(sep)
        if last > max_chars // 2:
            return truncated[: last + len(sep)]
    return truncated + "…"


def fetch_github_readme(owner: str, repo: str) -> str | None:
    """获取 GitHub 仓库 README 内容（前 2000 字符）。"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        data = fetch_json(
            url,
            headers={
                "User-Agent": "ai-content-loop/0.1",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=15,
        )
        content = data.get("content", "")
        if content:
            import base64

            decoded = base64.b64decode(content).decode("utf-8", errors="replace")
            return _truncate(decoded, 2000)
        return None
    except Exception:
        return None


def fetch_hn_story_comments(story_id: str) -> str | None:
    """获取 Hacker News 帖子的前几条热评。"""
    try:
        story = fetch_json(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
            timeout=15,
        )
        kids = story.get("kids", [])[:10]
        if not kids:
            return None

        comments = []
        for kid_id in kids[:5]:
            try:
                kid = fetch_json(
                    f"https://hacker-news.firebaseio.com/v0/item/{kid_id}.json",
                    timeout=10,
                )
                text = (kid.get("text") or "").strip()
                if text and len(text) > 50:
                    comments.append(_truncate(text, 500))
            except Exception:
                continue

        return "\n\n---\n\n".join(comments) if comments else None
    except Exception:
        return None


def fetch_hf_model_card(model_id: str) -> str | None:
    """获取 HuggingFace 模型卡片的描述信息。"""
    try:
        data = fetch_json(
            f"https://huggingface.co/api/models/{model_id}",
            timeout=15,
        )
        parts = []
        card_data = data.get("cardData", {})
        if isinstance(card_data, dict):
            desc = card_data.get("description")
            if desc:
                parts.append(f"描述: {desc}")
        pipeline_tag = data.get("pipeline_tag", "")
        if pipeline_tag:
            parts.append(f"任务类型: {pipeline_tag}")
        tags = data.get("tags", [])
        if tags:
            parts.append(f"标签: {', '.join(str(t) for t in tags[:10])}")
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def fetch_webpage_text(url: str) -> str | None:
    """通用网页文本抓取（用于 RSS 等场景）。简单提取 HTML 中的可见文本。"""
    try:
        html = fetch_text(url, timeout=15)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return _truncate(text, 1500) if len(text) > 100 else None
    except Exception:
        return None


def enrich_source_content(source: str, external_id: str, url: str) -> str | None:
    """根据来源类型，获取补充内容。"""
    if source == "github":
        parts = external_id.split("/")
        if len(parts) == 2:
            return fetch_github_readme(parts[0], parts[1])
        return None

    if source == "hackernews":
        return fetch_hn_story_comments(external_id)

    if source == "modelscope":
        return None  # ModelScope model page scraping not yet implemented

    if source == "huggingface":
        return fetch_hf_model_card(external_id)

    if source.startswith("official_rss"):
        return fetch_webpage_text(url)

    return None
