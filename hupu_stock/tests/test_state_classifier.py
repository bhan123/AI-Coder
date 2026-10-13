"""状态判定测试。

设计文档 §3 状态表。
"""
from __future__ import annotations

import pytest

from analysis.state_classifier import classify_state, compute_confidence

pytestmark = pytest.mark.skip(reason="stub: 待 state_classifier 实现")


def test_confidence_thresholds() -> None:
    assert compute_confidence(0) == "冷启动"
    assert compute_confidence(19) == "冷启动"
    assert compute_confidence(20) == "低置信"
    assert compute_confidence(59) == "低置信"
    assert compute_confidence(60) == "中置信"
    assert compute_confidence(119) == "中置信"
    assert compute_confidence(120) == "正式"
    assert compute_confidence(500) == "正式"


def test_euphoric_crowding_state() -> None:
    # TODO: Hot>90, Sent>75, Crowding>80 → "亢奋拥挤"
    ...


def test_panic_crowding_state() -> None:
    # TODO: Hot>85, Sent<25, Crowding>70 → "恐慌拥挤"
    ...


def test_new_heat_state() -> None:
    # TODO: Hot 70-90, HeatMomentum>1.5, Sent 55-70, Crowding<60, PriceExt<60 → "新热启动"
    ...


def test_noise_state() -> None:
    # TODO: Hot>70 且 abs(Sent-50)<10 → "噪音争吵"
    ...


def test_long_tail_forced_to_insufficient() -> None:
    # TODO: is_top_board=False 时永远返回 "样本不足"
    ...
