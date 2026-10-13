"""情感打分单元测试。"""
from __future__ import annotations

from analysis.sentiment import item_weight, load_lexicon, score_text


def _lex():
    return load_lexicon("config/sentiment_lexicon.json")


def test_no_keywords_returns_zero() -> None:
    score, hits = score_text("今天天气不错", _lex())
    assert score == 0.0
    assert hits == []


def test_strong_bullish_text_high_score() -> None:
    text = "主力拉升 起飞 涨停"
    score, _ = score_text(text, _lex())
    assert score > 0.5


def test_strong_bearish_text_low_score() -> None:
    text = "麻了 跌停 崩盘 套牢"
    score, _ = score_text(text, _lex())
    assert score < -0.5


def test_negation_reverses() -> None:
    pos_text = "今天涨势不错"
    neg_text = "今天不涨"
    pos_score, _ = score_text(pos_text, _lex())
    neg_score, _ = score_text(neg_text, _lex())
    # 不涨 / 不 + 涨 应当让情感走向偏负（涨词被反转）
    assert neg_score <= pos_score


def test_score_is_clamped() -> None:
    text = "起飞 起飞 起飞 满仓干 主力拉升 涨停" * 3
    s, _ = score_text(text, _lex())
    assert -1.0 <= s <= 1.0


def test_item_weight_thread_range() -> None:
    w_low = item_weight("thread", replies=0, views=0, likes=0)
    w_hi = item_weight("thread", replies=200, views=100_000, likes=500)
    assert 1.0 <= w_low <= 5.0
    assert 1.0 <= w_hi <= 5.0
    assert w_hi > w_low


def test_item_weight_reply_range() -> None:
    assert item_weight("reply", likes=0) == 1.0
    w_hi = item_weight("reply", likes=500)
    assert 1.0 <= w_hi <= 3.0
