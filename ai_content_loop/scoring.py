from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_content_loop.models import CandidateScore, SourceItem


# ---------------------------------------------------------------------------
# 中文关键词库（用于预筛）
# ---------------------------------------------------------------------------

EASY_WORDS_CN = {
    "工具", "demo", "演示", "app", "应用", "平台",
    "一键", "自动", "免费", "开源", "在线",
    "小白", "新手", "普通人", "零基础",
}

EASY_WORDS_EN = {"tool", "demo", "app", "workflow", "assistant", "bot", "generator", "automation"}

FUN_WORDS_CN = {
    "有趣", "好玩", "神器", "创意", "生成",
    "聊天", "对话", "游戏", "视频", "图片",
    "声音", "音乐", "动画", "表情", "头像",
}

FUN_WORDS_EN = {
    "fun", "interesting", "creative", "image", "video",
    "voice", "agent", "game", "chat", "screenshot", "generate",
}

USEFUL_WORDS_CN = {
    "提效", "效率", "省时", "自动化", "降本",
    "副业", "赚钱", "变现", "获客", "内容",
    "写作", "办公", "营销", "学习", "翻译",
    "总结", "整理", "搜索", "分析",
}

USEFUL_WORDS_EN = {
    "automate", "save", "summarize", "write", "customer",
    "content", "sales", "work", "productivity",
}

DEMO_WORDS_CN = {
    "截图", "演示", "demo", "案例", "示例",
    "教程", "上手", "体验", "试用",
}

DEMO_WORDS_EN = {"demo", "screenshot", "space", "example", "preview", "ui", "app", "generate"}

CLICKBAIT_WORDS_CN = {"震惊", "疯了", "炸裂", "颠覆", "彻底改变", "革命性", "人人都能"}


# ---------------------------------------------------------------------------
# 来源可信度分层
# ---------------------------------------------------------------------------

SOURCE_CREDIBILITY: dict[str, int] = {
    "arxiv": 10,
    "github": 8,
    "hackernews": 7,
    "producthunt": 6,
    "modelscope": 7,
}


def _source_credibility(source: str) -> int:
    if source.startswith("official_rss"):
        return 8
    return SOURCE_CREDIBILITY.get(source, 5)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _bounded(value: int, low: int = 1, high: int = 10) -> int:
    return max(low, min(high, value))


def _keyword_score(text: str, words_cn: set[str], words_en: set[str], base: int) -> int:
    """中英文关键词混合匹配。"""
    lowered = text.lower()
    hits_cn = sum(1 for word in words_cn if word in text)
    hits_en = sum(1 for word in words_en if word in lowered)
    return _bounded(base + hits_cn + hits_en)


def _recency_decay(published_at: str) -> float:
    """时效衰减：7 天内 1.0，7-14 天 0.7，超 14 天 0.5。"""
    if not published_at:
        return 1.0
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_days = (datetime.now(UTC) - published).days
    except (ValueError, TypeError):
        return 1.0
    if age_days <= 7:
        return 1.0
    if age_days <= 14:
        return 0.7
    return 0.5


def _normalize_heat(source: str, raw: dict) -> int:
    """按来源归一化热度分数（对数尺度）。"""
    if source == "github":
        stars = int(raw.get("stars") or 0)
        if stars >= 5000:
            return 10
        if stars >= 1000:
            return 9
        if stars >= 500:
            return 8
        if stars >= 100:
            return 6
        if stars >= 50:
            return 4
        return 2

    if source == "hackernews":
        score = int(raw.get("score") or 0)
        if score >= 500:
            return 10
        if score >= 200:
            return 9
        if score >= 100:
            return 7
        if score >= 50:
            return 5
        if score >= 20:
            return 3
        return 1

    if source == "producthunt":
        votes = int(raw.get("votes") or 0)
        if votes >= 1000:
            return 10
        if votes >= 500:
            return 8
        if votes >= 200:
            return 6
        if votes >= 100:
            return 4
        if votes >= 50:
            return 3
        return 1

    if source == "modelscope":
        downloads = int(raw.get("downloads") or 0)
        stars = int(raw.get("stars") or 0)
        combined = downloads + stars * 100
        if combined >= 500_000:
            return 10
        if combined >= 100_000:
            return 9
        if combined >= 50_000:
            return 8
        if combined >= 10_000:
            return 6
        if combined >= 5_000:
            return 4
        if combined >= 1_000:
            return 2
        return 1

    if source.startswith("official_rss"):
        return 7

    return 5


def _clickbait_penalty(title: str) -> int:
    """标题党惩罚：每命中一个标题党词汇扣 2 分，最多扣 6 分。"""
    hits = sum(1 for word in CLICKBAIT_WORDS_CN if word in title)
    return min(6, hits * 2)


# ---------------------------------------------------------------------------
# 预筛打分（改进版）
# ---------------------------------------------------------------------------

def score_item(item: SourceItem) -> CandidateScore:
    """改进版关键词打分 —— 作为预筛器。"""
    text = f"{item.title} {item.summary}"
    published_at = item.published_at if item.published_at else ""

    base_novelty = 7 if published_at else 5
    novelty = _bounded(round(base_novelty * _recency_decay(published_at)))

    clarity = _keyword_score(text, EASY_WORDS_CN, EASY_WORDS_EN, 5)
    fun = _keyword_score(text, FUN_WORDS_CN, FUN_WORDS_EN, 4)
    usefulness = _keyword_score(text, USEFUL_WORDS_CN, USEFUL_WORDS_EN, 5)
    demo = _keyword_score(text, DEMO_WORDS_CN, DEMO_WORDS_EN, 4)
    heat = _normalize_heat(item.source, item.raw if isinstance(item.raw, dict) else {})
    credibility = _source_credibility(item.source)
    penalty = _clickbait_penalty(item.title)

    total = (
        novelty * 0.20
        + clarity * 0.20
        + fun * 0.20
        + usefulness * 0.20
        + demo * 0.10
        + heat * 0.05
        + credibility * 0.05
    ) * 10 - penalty

    total = max(1.0, round(total, 2))

    reason = (
        f"novelty={novelty}, clarity={clarity}, fun={fun}, usefulness={usefulness}, "
        f"demo={demo}, heat={heat}, credibility={credibility}, penalty={penalty}"
    )
    return CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=novelty,
        clarity=clarity,
        fun=fun,
        usefulness=usefulness,
        demo=demo,
        heat=heat,
        credibility=credibility,
        total=total,
        reason=reason,
    )


def score_items(items: list[SourceItem]) -> list[CandidateScore]:
    """预筛：关键词打分 + 排序。"""
    return sorted(
        (score_item(item) for item in items),
        key=lambda s: s.total,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# LLM 精选层
# ---------------------------------------------------------------------------

def _parse_llm_scores(raw_output: str) -> list[dict[str, Any]]:
    """解析 Hermes 输出的 JSON 数组。容错处理。"""
    decoder = json.JSONDecoder()
    for idx, start_char in enumerate(raw_output):
        if start_char not in "[{":
            continue
        try:
            result, _ = decoder.raw_decode(raw_output, idx)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                for key in ("results", "candidates", "scores"):
                    nested = result.get(key)
                    if isinstance(nested, list):
                        return nested
                return [result]
        except json.JSONDecodeError:
            continue
    raise ValueError("无法从 Hermes 输出中解析 JSON 评分结果")


def llm_score_items(
    candidates: list[dict[str, Any]],
    *,
    hermes_command: str,
    prompt_path: str | Path,
    timeout_seconds: int = 300,
) -> list[dict[str, Any]] | None:
    """调用 Hermes 对预筛后的候选进行精选打分。

    返回 Hermes 评分结果列表，按 total_score 降序。调用失败返回空列表。
    """
    prompt_path = Path(prompt_path)
    scoring_prompt = prompt_path.read_text(encoding="utf-8")

    slim_candidates = []
    for c in candidates:
        raw_slim = {}
        if isinstance(c.get("raw"), dict):
            for k in ("stars", "likes", "downloads", "votes", "score", "comments"):
                if k in c["raw"]:
                    raw_slim[k] = c["raw"][k]

        slim_candidates.append({
            "dedupe_key": c.get("dedupe_key", ""),
            "source": c.get("source", ""),
            "title": c.get("title", ""),
            "summary": c.get("summary", ""),
            "url": c.get("url", ""),
            "keyword_score": c.get("total", 0),
            "keyword_reason": c.get("reason", ""),
            "raw_metrics": raw_slim,
        })

    prompt = "\n".join([
        scoring_prompt.rstrip(),
        "",
        "以下是预筛后的候选项目列表（已按关键词初筛排序，分数仅供参考）：",
        json.dumps(slim_candidates, ensure_ascii=False, indent=2),
        "",
        "请对每个候选按评分维度打分，返回 JSON 数组，按 total_score 降序。",
        "只输出 JSON 数组，不要有任何解释。",
    ])

    argv = [hermes_command, "chat", "-Q", "-t", "none", "-q", prompt]

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[scoring] LLM scoring: Hermes timed out after {timeout_seconds}s",
            file=sys.stderr,
        )
        return None
    except (OSError, UnicodeError) as error:
        print(
            f"[scoring] LLM scoring: Hermes launch failed ({type(error).__name__})",
            file=sys.stderr,
        )
        return None

    if completed.returncode != 0:
        print(
            f"[scoring] LLM scoring: Hermes exited with code {completed.returncode}",
            file=sys.stderr,
        )
        return None

    try:
        scores = _parse_llm_scores(completed.stdout)
    except ValueError:
        print(
            "[scoring] LLM scoring: Hermes output could not be parsed as JSON",
            file=sys.stderr,
        )
        return None

    valid_scores = [
        s for s in scores
        if (
            isinstance(s, dict)
            and s.get("dedupe_key")
            and s.get("recommended") is True
        )
    ]
    valid_scores.sort(key=lambda s: s.get("total_score", 0), reverse=True)
    if valid_scores:
        print(
            f"[scoring] LLM scoring: {len(valid_scores)} candidates scored by Hermes",
            file=sys.stderr,
        )
    else:
        print(
            "[scoring] LLM scoring: Hermes returned no recommended candidates",
            file=sys.stderr,
        )
    return valid_scores
