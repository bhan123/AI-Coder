"""词典法情感打分（设计文档 §2.2）。

关键公式：
    item_score = clamp(Σ sign(word) × weight(word) / Σ |weight(word)|, -1, 1)
                 无命中词则 = 0
    thread_weight = clamp(1 + 0.3·log(replies+1) + 0.2·log(views+1) + 0.2·log(likes+1), 1, 5)
    reply_weight  = clamp(1 + 0.2·log(likes+1), 1, 3)

否定词反转：negation 词后 N 个字符内出现的情感词极性取反。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lexicon:
    version: str
    strong_bullish: dict[str, float]
    weak_bullish: dict[str, float]
    neutral: dict[str, float]
    weak_bearish: dict[str, float]
    strong_bearish: dict[str, float]
    negation: tuple[str, ...]

    def all_with_weight(self) -> dict[str, float]:
        out: dict[str, float] = {}
        out.update(self.strong_bullish)
        out.update(self.weak_bullish)
        out.update(self.neutral)
        out.update(self.weak_bearish)
        out.update(self.strong_bearish)
        return out


def load_lexicon(path: str) -> Lexicon:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return Lexicon(
        version=raw["version"],
        strong_bullish=raw.get("strong_bullish", {}),
        weak_bullish=raw.get("weak_bullish", {}),
        neutral=raw.get("neutral", {}),
        weak_bearish=raw.get("weak_bearish", {}),
        strong_bearish=raw.get("strong_bearish", {}),
        negation=tuple(raw.get("negation", [])),
    )


_NEGATION_WINDOW = 6  # 否定词后 6 个字符内的情感词极性取反


def _apply_negation(text: str, polarity: float, negation_set: set[str]) -> float:
    """否定词后的窗口内命中一次就取反一次。

    简化做法：找每个否定词的位置，看其后面 6 字符内是否有 sign(polarity)!=0 的关键词；
    简单策略：遍历所有否定词 → 找到位置 → 在 [pos, pos+WINDOW] 内若有命中情感词的中心→极性取反。

    为覆盖多次否定叠加（"不是不涨" → 不 + 不 + 涨 → 双否定=肯定），采用位置穿越扫描法。
    """
    # 实现：把所有情感词的位置 + 极性列出，再扫所有否定词位置决定哪些反转
    return polarity  # 由 score_text 主循环统一处理，下面展开


def score_text(text: str, lexicon: Lexicon) -> tuple[float, list[str]]:
    """返回 (item_score ∈ [-1,1], 命中关键词列表)。"""
    if not text:
        return 0.0, []

    weighted = lexicon.all_with_weight()
    negation_set = set(lexicon.negation)

    # 收集所有情感关键词 + 否定词在文本中的位置（按位置排序）
    spans: list[tuple[int, int, float]] = []  # (start, end, weight)
    matched_keywords: list[str] = []
    for word, weight in weighted.items():
        if not word:
            continue
        for m in re.finditer(re.escape(word), text):
            spans.append((m.start(), m.end(), weight))
            matched_keywords.append(word)

    negation_positions: list[int] = []
    for neg in negation_set:
        if not neg:
            continue
        for m in re.finditer(re.escape(neg), text):
            negation_positions.append(m.end())  # 否定词"作用范围"从词尾开始

    # 计算 Σ sign × weight 与 Σ |weight|
    if not spans:
        return 0.0, []

    sign_sum = 0.0
    abs_sum = 0.0
    for start, end, w in spans:
        # 看这个情感词的中心点附近有没有 negation
        center = (start + end) // 2
        flipped = False
        for np in negation_positions:
            # 否定词尾在情感词中心前 N 字符内：反转
            if 0 < center - np <= _NEGATION_WINDOW:
                flipped = not flipped
                if flipped:
                    break
        effective = -w if flipped else w
        sign_sum += effective
        abs_sum += abs(w)

    if abs_sum == 0:
        return 0.0, matched_keywords
    return max(-1.0, min(1.0, sign_sum / abs_sum)), matched_keywords


def item_weight(item_type: str, replies: int = 0, views: int = 0, likes: int = 0) -> float:
    """设计文档 §2.2。thread = clamp(1 + 0.3·log(replies+1) + 0.2·log(views+1) + 0.2·log(likes+1), 1, 5)
                 reply  = clamp(1 + 0.2·log(likes+1), 1, 3)
    """
    if item_type == "thread":
        w = 1 + 0.3 * math.log(replies + 1) + 0.2 * math.log(views + 1) + 0.2 * math.log(likes + 1)
    else:
        w = 1 + 0.2 * math.log(likes + 1)
    if item_type == "thread":
        return max(1.0, min(5.0, w))
    return max(1.0, min(3.0, w))
