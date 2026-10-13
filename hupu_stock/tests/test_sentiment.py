"""词典法情感打分测试。

设计文档 §11 验收点 7：与人工评分 Spearman >= 0.5。
"""
from __future__ import annotations

import pytest

from analysis.sentiment import score_text

pytestmark = pytest.mark.skip(reason="stub: 待 score_text 实现")


def test_strong_bullish_keyword_high_score() -> None:
    # TODO: "主力拉升 + 起飞" → score > 0.7
    ...


def test_strong_bearish_keyword_low_score() -> None:
    # TODO: "跌停 + 套牢 + 崩盘" → score < -0.7
    ...


def test_negation_reverses_polarity() -> None:
    # TODO: "不涨" 中"涨"被反转 → 与"涨"反向
    ...


def test_no_keyword_match_returns_zero() -> None:
    # TODO: 无命中词时 score = 0
    ...
