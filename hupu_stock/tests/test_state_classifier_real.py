"""置信度分级 + 状态判定。"""
from __future__ import annotations

from analysis.state_classifier import classify_state, compute_confidence


def test_confidence_thresholds() -> None:
    assert compute_confidence(0) == "冷启动"
    assert compute_confidence(19) == "冷启动"
    assert compute_confidence(20) == "低置信"
    assert compute_confidence(59) == "低置信"
    assert compute_confidence(60) == "中置信"
    assert compute_confidence(119) == "中置信"
    assert compute_confidence(120) == "正式"
    assert compute_confidence(5000) == "正式"


def test_long_tail_forced_insufficient() -> None:
    s = classify_state(
        hot_score=100, sent_score=80, crowding_score=90, heat_momentum=2.0,
        price_extension=80, is_top_board=False, coverage_score=80,
        history_days=200, effective_item_count=50, unique_authors=20,
    )
    assert s == "样本不足"


def test_euphoric_state() -> None:
    s = classify_state(
        hot_score=92, sent_score=80, crowding_score=85, heat_momentum=1.2,
        price_extension=80, is_top_board=True, coverage_score=80,
        history_days=200, effective_item_count=50, unique_authors=20,
    )
    assert s == "亢奋拥挤"


def test_panic_state() -> None:
    s = classify_state(
        hot_score=88, sent_score=20, crowding_score=75, heat_momentum=1.2,
        price_extension=80, is_top_board=True, coverage_score=80,
        history_days=200, effective_item_count=50, unique_authors=20,
    )
    assert s == "恐慌拥挤"


def test_noise_state() -> None:
    s = classify_state(
        hot_score=80, sent_score=50, crowding_score=50, heat_momentum=1.2,
        price_extension=50, is_top_board=True, coverage_score=80,
        history_days=200, effective_item_count=50, unique_authors=20,
    )
    # abs(50-50)=0 < 10, hot>70 → 噪音争吵
    assert s == "噪音争吵"
